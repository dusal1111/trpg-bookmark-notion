"""
classify_bookmarks.py
bookmarks.jsonl → TRPG 시스템별 분류 → classified_bookmarks.jsonl

시나리오 이름 / 인원 / 분위기 / 개요는 AI가 채움 (reclassify_ai.py 실행 필요).
이 스크립트는 키워드 기반 시스템 분류 + 배포 URL 추출만 담당.

사용법:
    python classify_bookmarks.py
    python classify_bookmarks.py --reset   (이미 분류된 것도 재분류)
"""

import json, os, sys
from pathlib import Path

BASE_DIR       = Path(__file__).parent
BOOKMARKS_FILE = BASE_DIR / "bookmarks.jsonl"
SYSTEMS_FILE   = BASE_DIR / "trpg_systems.json"
OUTPUT_FILE    = BASE_DIR / "classified_bookmarks.jsonl"
UPLOADED_FILE  = BASE_DIR / "uploaded_ids.json"

_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

RESET = "--reset" in sys.argv


def load_uploaded_ids() -> set:
    if not UPLOADED_FILE.exists():
        return set()
    try:
        data = json.loads(UPLOADED_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(str(x) for x in data)
    except Exception:
        pass
    return set()


def load_systems() -> list:
    with open(SYSTEMS_FILE, encoding="utf-8") as f:
        return json.load(f)["systems"]


def classify_system(text: str, systems: list) -> tuple[str, str]:
    """키워드 매칭으로 (systemId, systemLabel) 반환."""
    text_lower = text.lower()
    other = None
    for s in systems:
        if s["id"] == "other":
            other = s
            continue
        for kw in s.get("keywords", []):
            if kw.lower() in text_lower:
                return s["id"], s["label"]
    fallback = other or systems[-1]
    return fallback["id"], fallback["label"]


def main():
    print("=" * 50)
    print("  TRPG 북마크 분류기")
    print("=" * 50)

    systems = load_systems()
    print(f"시스템 {len(systems)}개 로드: {[s['label'] for s in systems]}\n")

    already_done: set = set()
    uploaded_ids = load_uploaded_ids()
    if OUTPUT_FILE.exists() and not RESET:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    already_done.add(json.loads(line)["id"])
                except Exception:
                    pass
        print(f"기존 분류 완료: {len(already_done)}개 (스킵됨)\n")
    if uploaded_ids and not RESET:
        already_done.update(uploaded_ids)
        print(f"Notion 업로드 완료: {len(uploaded_ids)}개 (스킵됨)\n")

    if not BOOKMARKS_FILE.exists():
        print(f"오류: {BOOKMARKS_FILE} 없음")
        print("bookmark_sync.py 먼저 실행하세요.")
        sys.exit(1)

    bookmarks = []
    with open(BOOKMARKS_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                bookmarks.append(json.loads(line.strip()))
            except Exception:
                pass

    print(f"전체 북마크: {len(bookmarks)}개")
    to_process = [b for b in bookmarks if b.get("id") not in already_done]
    print(f"분류 대상: {len(to_process)}개\n")

    if not to_process:
        if not RESET:
            print("새로 분류할 북마크 없음.")
            print("재분류 하려면: python classify_bookmarks.py --reset")
            return
        print("(--reset: 전체 재분류 시작)")
        to_process = bookmarks
        already_done.clear()

    stat: dict[str, int] = {}
    results = []

    for i, bm in enumerate(to_process, 1):
        text  = (bm.get("text") or "") + " " + (bm.get("authorHandle") or "")
        links = bm.get("links") or []

        sys_id, sys_label = classify_system(text, systems)

        bm_out = dict(bm)
        bm_out["systemId"]        = sys_id
        bm_out["systemLabel"]     = sys_label
        bm_out["distributionUrl"] = links[0] if links else None
        # AI(reclassify_ai.py)가 채울 필드 초기값
        bm_out["scenarioName"]    = ""
        bm_out["minPlayers"]      = None
        bm_out["maxPlayers"]      = None
        bm_out["mood"]            = []
        bm_out["overview"]        = ""
        bm_out["aiEnriched"]      = False

        results.append(bm_out)
        stat[sys_label] = stat.get(sys_label, 0) + 1

        if i % 100 == 0:
            print(f"  {i}/{len(to_process)} 처리 중...")

    mode = "w" if RESET else "a"
    with open(OUTPUT_FILE, mode, encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n분류 완료: {len(results)}개 → {OUTPUT_FILE.name}\n")
    print("시스템별 통계:")
    for label, cnt in sorted(stat.items(), key=lambda x: -x[1]):
        bar = "█" * min(cnt // 5, 40)
        print(f"  {label:20s} {cnt:4d}개  {bar}")
    print("\n※ 시나리오 이름/인원/분위기/개요는 AI 추출 필요:")
    print("  python reclassify_ai.py")


if __name__ == "__main__":
    main()
