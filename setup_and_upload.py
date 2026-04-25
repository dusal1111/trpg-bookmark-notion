"""
setup_and_upload.py
classified_bookmarks.jsonl → 시스템별 Notion DB 생성 + 업로드

각 TRPG 시스템마다 별도 DB 생성:
    예) "CoC 시나리오 정리", "inSANe 시나리오 정리" ...

DB 스키마:
    시나리오 이름 / 배포 URL / 최소인원 / 최대인원 / 분위기(다중선택) /
    개요 / 원본 트위터 링크 / 이미지 / 저장일 / 트윗작성일 / 리트윗수

사용법:
    python setup_and_upload.py           (DB 생성 + 전체 업로드)
    python setup_and_upload.py --setup   (DB 생성만)
    python setup_and_upload.py --upload  (이미 DB 있으면 업로드만)
"""

import json, os, sys, time
from pathlib import Path
from datetime import datetime
from urllib import request as ureq
import urllib.error

_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

NOTION_TOKEN   = os.environ.get("NOTION_TOKEN", "")
PARENT_PAGE_ID = os.environ.get("NOTION_PARENT_PAGE_ID", "")

BASE_DIR        = Path(__file__).parent
CLASSIFIED_FILE = BASE_DIR / "classified_bookmarks.jsonl"
SYSTEMS_FILE    = BASE_DIR / "trpg_systems.json"
DB_IDS_FILE     = BASE_DIR / "notion_db_ids.json"
UPLOADED_FILE   = BASE_DIR / "uploaded_ids.json"

ONLY_SETUP  = "--setup"  in sys.argv
ONLY_UPLOAD = "--upload" in sys.argv

HEADERS = {
    "Authorization":  f"Bearer {NOTION_TOKEN}",
    "Content-Type":   "application/json",
    "Notion-Version": "2022-06-28",
}

MOOD_OPTIONS = [
    {"name": "공포",    "color": "red"},
    {"name": "일상",    "color": "green"},
    {"name": "미스터리", "color": "purple"},
    {"name": "액션",    "color": "orange"},
    {"name": "코미디",  "color": "yellow"},
    {"name": "감동",    "color": "blue"},
    {"name": "판타지",  "color": "pink"},
]


def api(method, path, body=None):
    url  = f"https://api.notion.com/v1/{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    retry_waits = [5, 15, 30]
    for attempt in range(4):
        req = ureq.Request(url, data=data, headers=HEADERS, method=method)
        try:
            with ureq.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:
                wait = retry_waits[attempt]
                print(f"\n  ⏳ Notion rate limit → {wait}초 후 재시도...")
                time.sleep(wait)
                continue
            err = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {e.code}: {err[:300]}")


def load_systems() -> list:
    with open(SYSTEMS_FILE, encoding="utf-8") as f:
        return json.load(f)["systems"]


def load_db_ids() -> dict:
    if DB_IDS_FILE.exists():
        return json.loads(DB_IDS_FILE.read_text(encoding="utf-8"))
    return {}


def save_db_ids(db_ids: dict):
    DB_IDS_FILE.write_text(
        json.dumps(db_ids, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── DB 생성 ────────────────────────────────────────────────────────────
def create_db(system: dict) -> str:
    print(f"  DB 생성 중: {system['db_title']} ...", end=" ", flush=True)
    body = {
        "parent": {"type": "page_id", "page_id": PARENT_PAGE_ID},
        "title": [{"type": "text", "text": {"content": system["db_title"]}}],
        "properties": {
            "시나리오 이름":   {"title": {}},
            "배포 URL":       {"url": {}},
            "최소인원":        {"number": {}},
            "최대인원":        {"number": {}},
            "분위기":          {"multi_select": {"options": MOOD_OPTIONS}},
            "개요":            {"rich_text": {}},
            "원본 트위터 링크": {"url": {}},
            "이미지":          {"url": {}},
            "저장일":          {"date": {}},
            "트윗작성일":      {"date": {}},
            "리트윗수":        {"number": {}},
        },
    }
    result = api("POST", "databases", body)
    db_id  = result["id"].replace("-", "")
    print(f"완료 ({db_id})")
    return db_id


def setup_all(systems: list) -> dict:
    db_ids  = load_db_ids()
    created = 0
    for s in systems:
        if s["id"] in db_ids:
            print(f"  기존 DB 재사용: {s['db_title']} ({db_ids[s['id']]})")
            continue
        db_id = create_db(s)
        db_ids[s["id"]] = db_id
        save_db_ids(db_ids)
        created += 1
        time.sleep(0.3)
    print(f"\nDB 생성: {created}개 / 재사용: {len(systems) - created}개")
    print()
    print("⚠️  업로드 전 확인: 각 DB가 있는 페이지에 Integration이 연결되어 있어야 합니다.")
    print("   페이지 우상단 '...' → '연결' → Integration 이름 선택")
    return db_ids


# ── 페이지 빌드 ────────────────────────────────────────────────────────
def _parse_tweet_date(posted: str) -> str | None:
    """트위터 날짜 문자열 → "YYYY-MM-DD". 실패 시 None."""
    try:
        return datetime.strptime(posted, "%a %b %d %H:%M:%S +0000 %Y").strftime("%Y-%m-%d")
    except Exception:
        return None


def make_page(bm: dict, db_id: str) -> dict:
    raw_name = (bm.get("scenarioName") or "").strip()
    if not raw_name:
        raw_name = (bm.get("text") or "")[:50].strip().replace("\n", " ")
    title = raw_name[:100] or f"Tweet {bm.get('id', '?')}"

    props: dict = {
        "시나리오 이름": {"title": [{"text": {"content": title}}]},
        "개요": {"rich_text": [{"text": {"content": (bm.get("overview") or bm.get("text") or "")[:2000]}}]},
    }

    if bm.get("url"):
        props["원본 트위터 링크"] = {"url": bm["url"]}

    if bm.get("distributionUrl"):
        props["배포 URL"] = {"url": bm["distributionUrl"]}

    min_p = bm.get("minPlayers")
    max_p = bm.get("maxPlayers")
    if min_p is not None:
        props["최소인원"] = {"number": int(min_p)}
    if max_p is not None:
        props["최대인원"] = {"number": int(max_p)}

    # 분위기 (multi_select)
    mood = bm.get("mood") or []
    if isinstance(mood, str):
        mood = [mood] if mood else []
    if mood:
        props["분위기"] = {"multi_select": [{"name": m} for m in mood]}

    # 이미지
    media = bm.get("media") or []
    if media and media[0]:
        props["이미지"] = {"url": media[0]}

    # 저장일
    synced = bm.get("syncedAt")
    if synced:
        props["저장일"] = {"date": {"start": synced[:10]}}

    # 트윗작성일
    tweet_date = _parse_tweet_date(bm.get("postedAt") or "")
    if tweet_date:
        props["트윗작성일"] = {"date": {"start": tweet_date}}

    # 리트윗수
    retweet = (bm.get("engagement") or {}).get("repostCount")
    if retweet is not None:
        props["리트윗수"] = {"number": retweet}

    page: dict = {"parent": {"database_id": db_id}, "properties": props}
    if media and media[0]:
        page["cover"] = {"type": "external", "external": {"url": media[0]}}
    return page


# ── 업로드 ─────────────────────────────────────────────────────────────
def load_uploaded() -> set:
    if UPLOADED_FILE.exists():
        return set(json.loads(UPLOADED_FILE.read_text(encoding="utf-8")))
    return set()


def save_uploaded(uploaded: set):
    UPLOADED_FILE.write_text(
        json.dumps(list(uploaded), ensure_ascii=False), encoding="utf-8"
    )


def upload(db_ids: dict):
    bookmarks: list = []
    with open(CLASSIFIED_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                bookmarks.append(json.loads(line.strip()))
            except Exception:
                pass

    uploaded  = load_uploaded()
    to_upload = [b for b in bookmarks if b.get("id") not in uploaded]
    print(f"업로드 대상: {len(to_upload)}개 (전체 {len(bookmarks)}개 중)")

    if not to_upload:
        print("업로드할 항목 없음.")
        return

    # 시스템별 개수 미리보기
    sys_count: dict[str, int] = {}
    ai_missing = sum(1 for b in to_upload if not b.get("aiEnriched"))
    for bm in to_upload:
        key = bm.get("systemLabel", "기타")
        sys_count[key] = sys_count.get(key, 0) + 1
    for label, cnt in sorted(sys_count.items(), key=lambda x: -x[1]):
        print(f"  {label:20s} {cnt:4d}개")

    if ai_missing:
        print(f"\n⚠️  AI 미추출 항목 {ai_missing}개 (시나리오 이름/인원/분위기/개요 비어있음)")
        print("   reclassify_ai.py 실행 후 업로드하면 정보가 채워집니다.\n")

    print(f"\n예상 시간: 약 {len(to_upload) * 0.35 / 60:.0f}분\n")

    success, fail = 0, 0
    start = time.time()

    for i, bm in enumerate(to_upload, 1):
        sys_id = bm.get("systemId", "other")
        db_id  = db_ids.get(sys_id) or db_ids.get("other")
        if not db_id:
            print(f"\n  [SKIP] DB 없음: systemId={sys_id}")
            fail += 1
            continue

        try:
            page = make_page(bm, db_id)
            api("POST", "pages", page)
            success += 1
            uploaded.add(bm["id"])
            if i % 50 == 0:
                save_uploaded(uploaded)
                elapsed = time.time() - start
                eta = (elapsed / i) * (len(to_upload) - i)
                print(f"  [{i}/{len(to_upload)}] 성공 {success} / 실패 {fail}  (남은 ~{eta/60:.1f}분)", end="\r")
        except Exception as e:
            fail += 1
            if fail <= 3:
                print(f"\n  [오류] {bm.get('id', '?')}: {e}")
            if fail >= 10 and success == 0:
                print("\n연속 오류 — 토큰 또는 DB 연결 확인 필요")
                break
        time.sleep(0.35)

    save_uploaded(uploaded)
    elapsed = time.time() - start
    print(f"\n\n완료: 성공 {success}개 / 실패 {fail}개  ({elapsed/60:.1f}분)")


# ── 메인 ─────────────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print("  트위터 북마크 → TRPG 시나리오 Notion 셋업 & 업로드")
    print("=" * 55 + "\n")

    if not NOTION_TOKEN:
        print("오류: NOTION_TOKEN이 설정되지 않았습니다.")
        print("setup.bat을 실행해서 토큰을 먼저 입력해주세요.")
        sys.exit(1)
    if not PARENT_PAGE_ID:
        print("오류: NOTION_PARENT_PAGE_ID가 설정되지 않았습니다.")
        print("setup.bat을 실행해서 Notion 페이지 ID를 먼저 입력해주세요.")
        sys.exit(1)

    systems = load_systems()

    if ONLY_UPLOAD:
        db_ids = load_db_ids()
        if not db_ids:
            print("오류: notion_db_ids.json 없음. --setup 먼저 실행하세요.")
            sys.exit(1)
        print("기존 DB 목록:")
        for sid, did in db_ids.items():
            print(f"  {sid}: {did}")
        print()
        upload(db_ids)
        return

    if ONLY_SETUP:
        setup_all(systems)
        return

    db_ids = setup_all(systems)
    print()
    upload(db_ids)


if __name__ == "__main__":
    main()
