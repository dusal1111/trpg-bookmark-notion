"""
reclassify_ai.py
classified_bookmarks.jsonl 의 모든 항목에 대해 AI로 필드 추출

추출 필드:
    scenarioName / minPlayers / maxPlayers / mood(복수) / overview

"기타" 시스템 항목은 올바른 시스템 ID도 함께 판별.

지원 API (둘 중 하나만 있으면 됨, 둘 다 있으면 OpenAI 우선):
    - OpenAI:  .env에 OPENAI_API_KEY=sk-...       모델: gpt-4.1-mini
    - Gemini:  .env에 GEMINI_API_KEY=AIza...       모델: gemini-2.5-flash

사용법:
    python reclassify_ai.py
    python reclassify_ai.py --reset    (이미 추출된 것도 재추출)
    python reclassify_ai.py --dry-run  (실제 저장 없이 결과만 확인)
"""

import json, os, re, sys, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib import request as ureq
import urllib.error

BASE_DIR        = Path(__file__).parent
CLASSIFIED_FILE = BASE_DIR / "classified_bookmarks.jsonl"
SYSTEMS_FILE    = BASE_DIR / "trpg_systems.json"
PROGRESS_FILE   = BASE_DIR / ".ai_enrich_progress.json"
UPLOADED_FILE   = BASE_DIR / "uploaded_ids.json"

_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
VERTEX_PROJECT_ID = os.environ.get("VERTEX_PROJECT_ID", "")
VERTEX_REGION     = os.environ.get("VERTEX_REGION", "global")

OPENAI_MODEL = "gpt-4.1-mini"
GEMINI_MODEL = "gemini-3-flash-preview"

# 우선순위: OpenAI > Vertex AI > Gemini AI Studio
if OPENAI_API_KEY:
    AI_PROVIDER = "openai"
    BATCH_SIZE  = 10
    SLEEP_SEC   = 1
    WORKERS     = 1
elif VERTEX_PROJECT_ID:
    AI_PROVIDER = "vertex"
    BATCH_SIZE  = 3
    SLEEP_SEC   = 0
    WORKERS     = 3   # 병렬 요청 수
elif GEMINI_API_KEY:
    AI_PROVIDER = "gemini"
    BATCH_SIZE  = 5
    SLEEP_SEC   = 4
    WORKERS     = 1
else:
    AI_PROVIDER = None
    BATCH_SIZE  = 10
    SLEEP_SEC   = 1
    WORKERS     = 1

DRY_RUN = "--dry-run" in sys.argv
RESET   = "--reset"   in sys.argv


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

# Gemini AI Studio 전용 응답 스키마
_GEMINI_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "scenarioName": {"type": "string"},
            "minPlayers":   {"type": "integer", "nullable": True},
            "maxPlayers":   {"type": "integer", "nullable": True},
            "mood":         {"type": "array", "items": {"type": "string"}},
            "overview":     {"type": "string"},
            "systemId":     {"type": "string", "nullable": True},
        },
        "required": ["scenarioName", "mood", "overview"],
    },
}


def load_systems() -> dict[str, str]:
    with open(SYSTEMS_FILE, encoding="utf-8") as f:
        return {s["id"]: s["label"] for s in json.load(f)["systems"]}


def build_prompt(batch: list, sys_map: dict[str, str]) -> str:
    valid_sys = ", ".join(f'"{sid}"' for sid in sys_map if sid != "other")
    valid_sys += ", null"
    lines = []
    for i, bm in enumerate(batch, 1):
        sys_label = bm.get("systemLabel", "기타")
        text = (bm.get("text") or "").replace("\n", " ")[:300]
        lines.append(f"[{i}] [{sys_label}] {text}")
    tweet_block = "\n".join(lines)
    return f"""다음 TRPG 시나리오 트윗들을 분석해서 JSON 배열로 정보를 추출해줘.
코드블록(```) 없이 JSON 배열만 반환해. 설명 금지.

추출할 필드:
- scenarioName (string): 트윗에 명시된 시나리오 제목. 없으면 "".
- minPlayers (int|null): 최소 PL 인원 (KPC 제외). 타이만/솔로=1. 불명확하면 null.
- maxPlayers (int|null): 최대 PL 인원 (KPC 제외). 타이만/솔로=1. 불명확하면 null.
- mood (array): 시나리오 분위기 태그. 해당하는 것 모두, 없으면 [].
  "공포" "일상" "미스터리" "액션" "코미디" "감동" "판타지" 등을 참고하되,
  시나리오에 더 잘 맞는 표현이 있으면 자유롭게 추가 가능 (한국어 2~6자 권장).
- overview (string): 시나리오 1~2문장 한국어 요약. TRPG 시나리오가 아니면 "".
- systemId (string|null): 시스템이 [기타]인 항목만 올바른 ID 제공. 나머지는 null.
  허용값: {valid_sys}

트윗:
{tweet_block}

응답 형식 (트윗과 동일한 순서/개수):
[{{"scenarioName":"...","minPlayers":1,"maxPlayers":4,"mood":["공포"],"overview":"...","systemId":null}}, ...]"""


# ── HTTP 헬퍼 ────────────────────────────────────────────────────────────
def _http_post(url: str, payload_dict: dict, headers: dict) -> dict:
    payload = json.dumps(payload_dict).encode("utf-8")
    retry_waits = [15, 30, 60]
    last_err = None
    for attempt in range(4):
        try:
            req = ureq.Request(url, data=payload, headers=headers, method="POST")
            with ureq.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 503) and attempt < 3:
                body = e.read().decode("utf-8", errors="ignore")
                if "quota" in body or "billing" in body or "insufficient_quota" in body:
                    print(f"\n  ❌ API 크레딧 소진 또는 결제 문제입니다.")
                    raise RuntimeError("quota_exceeded") from e
                wait = retry_waits[attempt]
                print(f"\n  ⏳ HTTP {e.code} → {wait}초 후 재시도 ({attempt+1}/3)...")
                time.sleep(wait)
                continue
            raise
    raise last_err


# ── AI 호출 ──────────────────────────────────────────────────────────────
def call_openai(prompt: str) -> str:
    result = _http_post(
        "https://api.openai.com/v1/chat/completions",
        {
            "model": OPENAI_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 2048,
        },
        {"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"},
    )
    return result["choices"][0]["message"]["content"].strip()


def call_gemini(prompt: str) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    result = _http_post(
        url,
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json",
                "responseSchema": _GEMINI_SCHEMA,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        },
        {"Content-Type": "application/json"},
    )
    candidate = result.get("candidates", [{}])[0]
    parts = candidate.get("content", {}).get("parts", [])
    for p in parts:
        if "text" in p and not p.get("thought", False):
            return p["text"].strip()
    raise ValueError(f"응답 비어있음. finishReason={candidate.get('finishReason')}")


def call_vertex(prompt: str) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError("google-genai 미설치. pip install google-genai")
    client = genai.Client(vertexai=True, project=VERTEX_PROJECT_ID, location=VERTEX_REGION)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=8192,
            response_mime_type="application/json",
            response_schema=_GEMINI_SCHEMA,  # BATCH_SIZE=1이므로 1-item array, 잘림 없음
        ),
    )
    text = response.text
    if not text:
        try:
            reason = response.candidates[0].finish_reason
        except (IndexError, AttributeError):
            reason = "unknown"
        raise ValueError(f"Vertex 응답 비어있음. finish_reason={reason}")
    return text.strip()


def call_ai(prompt: str) -> str:
    if AI_PROVIDER == "openai":
        return call_openai(prompt)
    elif AI_PROVIDER == "vertex":
        return call_vertex(prompt)
    elif AI_PROVIDER == "gemini":
        return call_gemini(prompt)
    raise ValueError("API 키 없음")


# ── JSON 파싱 ────────────────────────────────────────────────────────────
def _repair_json(s: str) -> str:
    """문자열 내 이스케이프 누락 + 객체 간 쉼표 누락 수정."""
    result = []
    in_string = False
    escape_next = False
    for ch in s:
        if escape_next:
            result.append(ch); escape_next = False
        elif ch == "\\":
            result.append(ch); escape_next = True
        elif ch == '"':
            in_string = not in_string; result.append(ch)
        elif in_string and ch == "\n":
            result.append("\\n")
        elif in_string and ch == "\r":
            result.append("\\r")
        elif in_string and ch == "\t":
            result.append("\\t")
        else:
            result.append(ch)
    s = "".join(result)
    s = re.sub(r"\}\s*\{", "}, {", s)
    return s


def parse_response(text: str, batch_size: int) -> list[dict]:
    start = text.find("[")
    end   = text.rfind("]") + 1
    if start == -1 or end <= start:
        raise ValueError(f"JSON 배열 없음. 응답: {text[:200]}")
    json_str = text[start:end]
    try:
        items = json.loads(json_str)
    except json.JSONDecodeError:
        try:
            items = json.loads(_repair_json(json_str))
        except json.JSONDecodeError as e2:
            col = e2.colno - 1
            print(f"⚠️ JSON 파싱 실패 ({e2})")
            print(f"   문제 위치 주변: {repr(json_str[max(0,col-20):col+20])}")
            raise RuntimeError("retry_json")
    if len(items) != batch_size:
        raise ValueError(f"응답 수 불일치: {len(items)} != {batch_size}")
    return items


# ── 결과 적용 ────────────────────────────────────────────────────────────
def apply_result(bm: dict, result: dict, sys_map: dict[str, str]) -> dict:
    out = dict(bm)
    out["scenarioName"] = str(result.get("scenarioName") or "")
    min_p = result.get("minPlayers")
    max_p = result.get("maxPlayers")
    out["minPlayers"] = int(min_p) if min_p is not None else None
    out["maxPlayers"] = int(max_p) if max_p is not None else None
    raw_mood = result.get("mood") or []
    out["mood"] = [str(m).strip() for m in raw_mood if m and str(m).strip()]
    out["overview"] = str(result.get("overview") or "")
    if bm.get("systemId") == "other":
        new_sys = result.get("systemId")
        if new_sys and new_sys in sys_map and new_sys != "other":
            out["systemId"]    = new_sys
            out["systemLabel"] = sys_map[new_sys]
    out["aiEnriched"] = True
    return out


# ── 단일 배치 처리 (재시도 포함) ─────────────────────────────────────────
def process_batch(batch: list, sys_map: dict[str, str]) -> dict[str, dict]:
    """배치 처리 → {bm_id: result_dict}. 실패 시 예외."""
    raw   = call_ai(build_prompt(batch, sys_map))
    items = parse_response(raw, len(batch))
    return {bm["id"]: item for bm, item in zip(batch, items)}


# ── 메인 ─────────────────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print("  AI 필드 추출 (시나리오 이름 / 인원 / 분위기 / 개요)")
    print("=" * 55)

    if not AI_PROVIDER:
        print("\n⚠️  AI API 키가 없습니다.")
        print("  OPENAI_API_KEY / GEMINI_API_KEY / VERTEX_PROJECT_ID 중 하나를 .env에 추가하세요.")
        sys.exit(1)

    if AI_PROVIDER == "vertex":
        import importlib.util
        if importlib.util.find_spec("google.genai") is None:
            print("\n❌ google-genai 미설치: pip install google-genai")
            sys.exit(1)
        provider_label = f"Vertex AI ({GEMINI_MODEL}, {VERTEX_PROJECT_ID}, {VERTEX_REGION}, workers={WORKERS})"
    elif AI_PROVIDER == "openai":
        provider_label = f"OpenAI ({OPENAI_MODEL})"
    else:
        provider_label = f"Gemini AI Studio ({GEMINI_MODEL})"
    print(f"  사용 API: {provider_label}\n")

    sys_map = load_systems()

    all_bookmarks: list[dict] = []
    with open(CLASSIFIED_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                all_bookmarks.append(json.loads(line.strip()))
            except Exception:
                pass

    uploaded_ids = load_uploaded_ids()

    if RESET:
        targets = all_bookmarks
        print(f"(--reset: 전체 {len(targets)}개 재추출)\n")
    else:
        targets = [
            b for b in all_bookmarks
            if not b.get("aiEnriched") and str(b.get("id")) not in uploaded_ids
        ]
        print(f"전체: {len(all_bookmarks)}개 / 미추출: {len(targets)}개\n")
        if uploaded_ids:
            print(f"Notion 업로드 완료: {len(uploaded_ids)}개 제외\n")

    if not targets:
        print("추출할 항목 없음. 재추출: python reclassify_ai.py --reset")
        return

    if DRY_RUN:
        print("[DRY-RUN 모드: 저장 안 함]\n")

    progress: dict[str, dict] = {}
    if PROGRESS_FILE.exists() and not DRY_RUN and not RESET:
        try:
            progress = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
            skip = sum(1 for b in targets if b["id"] in progress)
            if skip:
                print(f"  이전 진행분 {skip}개 로드됨 → 이어서 진행\n")
        except Exception:
            pass

    # 처리할 배치 목록
    pending_batches = [
        targets[i : i + BATCH_SIZE]
        for i in range(0, len(targets), BATCH_SIZE)
        if not all(b["id"] in progress for b in targets[i : i + BATCH_SIZE])
    ]

    total_items = len(targets)
    done_count  = sum(1 for b in targets if b["id"] in progress)
    errors      = 0
    progress_lock = threading.Lock()
    quota_hit   = threading.Event()

    def save_progress():
        if not DRY_RUN:
            PROGRESS_FILE.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")

    print(f"  배치 {len(pending_batches)}개 × {BATCH_SIZE}항목, 병렬 {WORKERS}개\n")

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(process_batch, batch, sys_map): batch for batch in pending_batches}
        for future in as_completed(futures):
            if quota_hit.is_set():
                future.cancel()
                continue
            try:
                result_map = future.result()
                with progress_lock:
                    progress.update(result_map)
                    done_count += len(result_map)
                    print(f"  [{done_count}/{total_items}] 추출 완료...", end="\r")
                    save_progress()
            except RuntimeError as e:
                if str(e) == "quota_exceeded":
                    quota_hit.set()
                    print("\n  ❌ 크레딧 소진 → 중단")
                elif str(e) == "retry_json":
                    print(f"\n  ⏭ JSON 파싱 실패 → 스킵 (다음 실행 때 재처리)")
                    errors += 1
                else:
                    print(f"\n  [오류] {e}")
                    errors += 1
            except Exception as e:
                print(f"\n  [오류] {e}")
                errors += 1

    print(f"\n\nAI 추출 완료: {len(progress)}개 / 오류: {errors}배치")

    if DRY_RUN:
        print("\n[DRY-RUN] 저장 건너뜀.")
        if progress:
            sample = next(iter(progress.values()))
            print(f"\n샘플 결과: {json.dumps(sample, ensure_ascii=False, indent=2)}")
        return

    id_to_bm = {b["id"]: b for b in all_bookmarks}
    for bm_id, result in progress.items():
        if bm_id in id_to_bm:
            id_to_bm[bm_id] = apply_result(id_to_bm[bm_id], result, sys_map)

    updated = [id_to_bm.get(b["id"], b) for b in all_bookmarks]

    with open(CLASSIFIED_FILE, "w", encoding="utf-8") as f:
        for bm in updated:
            f.write(json.dumps(bm, ensure_ascii=False) + "\n")

    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()

    enriched = sum(1 for b in updated if b.get("aiEnriched"))
    print(f"저장 완료: {enriched}개 AI 추출됨 → {CLASSIFIED_FILE.name}")

    stat: dict[str, int] = {}
    for bm in updated:
        lbl = bm.get("systemLabel", "기타")
        stat[lbl] = stat.get(lbl, 0) + 1
    print("\n최종 시스템별 통계:")
    for label, cnt in sorted(stat.items(), key=lambda x: -x[1]):
        bar = "█" * min(cnt // 5, 40)
        print(f"  {label:20s} {cnt:4d}개  {bar}")


if __name__ == "__main__":
    main()
