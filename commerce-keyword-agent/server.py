# -*- coding: utf-8 -*-
"""AI 커머스광고 키워드 Agent — 로컬 개발 서버.

파이썬 표준 라이브러리만 사용합니다(설치 필요 없음).
실행:  python server.py   →  http://127.0.0.1:8765
"""

import calendar
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import keyword_engine

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
DATA_DIR = os.path.join(BASE_DIR, "data")
SCHEDULE_STORE = os.path.join(DATA_DIR, "schedule_store.json")
REGISTRATION_STORE = os.path.join(DATA_DIR, "registrations.json")
KEYWORD_CACHE = os.path.join(DATA_DIR, "keyword_cache.json")
CONFIG_STORE = os.path.join(DATA_DIR, "config.json")
PROGRAM_ID_STORE = os.path.join(DATA_DIR, "program_ids.json")
PROGRAM_CATALOG = os.path.join(DATA_DIR, "program_catalog.json")
PROGRAM_SEED = os.path.join(DATA_DIR, "tvn_programs.txt")
PROGRAM_SLUGS = os.path.join(DATA_DIR, "tvn_program_slugs.txt")
PREVIEW_CACHE = os.path.join(DATA_DIR, "preview_cache.json")
TVING_MAP = os.path.join(DATA_DIR, "tving_contents.txt")
TVING_CACHE = os.path.join(DATA_DIR, "tving_cache.json")
PROGRAM_NOTES = os.path.join(DATA_DIR, "program_notes.txt")
PROGRAM_GENRE_STORE = os.path.join(DATA_DIR, "program_genres.json")

TVN_SCHEDULE_URL = "https://tvn.cjenm.com/ko/tvn-schedule/"
TVN_PROGRAM_URL = "https://tvn.cjenm.com/ko/program/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
KST_OFFSET = 9 * 3600
SCHEDULE_TTL_SEC = 6 * 3600  # 6시간마다 tvN 편성표를 다시 읽습니다.

_store_lock = threading.Lock()


# ---------------------------------------------------------------- 저장소 유틸


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ------------------------------------------------------------ tvN 편성표 수집


def _http_get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read()
    charset = "utf-8"
    return raw.decode(charset, errors="replace")


TITLE_TAG_RE = re.compile(r"^\s*\[[^\]]{1,20}\]\s*")


def clean_title(name):
    """'[예능]유퀴즈온더블럭' 처럼 앞에 붙는 분류 태그를 떼어냅니다."""
    out = (name or "").strip()
    while True:
        stripped = TITLE_TAG_RE.sub("", out)
        if stripped == out:
            break
        out = stripped
    return out.strip()


DRAMA_TAGS = ("드라마", "월화", "화수", "수목", "목금", "금토", "토일", "일월")


def detect_genre(raw_title):
    """'[예능]유퀴즈…', '[토일] 포핸즈' 처럼 제목 앞에 붙는 태그로 장르를 봅니다."""
    tags = re.findall(r"\[([^\]]{1,20})\]", raw_title or "")
    joined = " ".join(tags)
    if "예능" in joined:
        return "예능"
    if any(t in joined for t in DRAMA_TAGS):
        return "드라마"
    return "기타"


SUBTITLE_SPLIT_RE = re.compile(r"\s+[-–—:]\s+")


def program_name_only(title):
    """'언니네 산지직송3 - 네 식구 산지 라이프' → '언니네 산지직송3' (시즌 숫자는 남김)."""
    return SUBTITLE_SPLIT_RE.split((title or "").strip())[0].strip() or (title or "").strip()


EPISODE_RE = re.compile(r"(\d+)\s*(회|화)")


def parse_episode(epi_name, fallback=""):
    text = epi_name or fallback or ""
    m = EPISODE_RE.search(text)
    return (m.group(1) + m.group(2)) if m else ""


def episode_subtitle(epi_name):
    """'유 퀴즈 온 더 블럭 359회ㅣ부제' 에서 부제만 떼어냅니다."""
    if not epi_name:
        return ""
    for sep in ("ㅣ", "|", "│"):
        if sep in epi_name:
            return epi_name.split(sep, 1)[1].strip()
    return ""


def day_start_ts(yyyymmdd):
    """방송일 기준 05:00(KST) 의 유닉스 시각."""
    y, m, d = int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8])
    return calendar.timegm((y, m, d, 5, 0, 0, 0, 0, 0)) - KST_OFFSET


def fetch_tvn_schedule():
    """tvN 편성표 페이지의 __NEXT_DATA__ 에서 주간 편성 데이터를 뽑습니다."""
    html = _http_get(TVN_SCHEDULE_URL)
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S
    )
    if not m:
        raise RuntimeError("tvN 편성표 페이지 구조가 바뀌었습니다(__NEXT_DATA__ 없음).")
    next_data = json.loads(m.group(1))
    fallback = next_data.get("props", {}).get("pageProps", {}).get("fallback", {}) or {}

    block = None
    for value in fallback.values():
        if isinstance(value, dict):
            data = value.get("data")
            if isinstance(data, dict) and "schePgmList" in data:
                block = data
                break
    if block is None:
        raise RuntimeError("tvN 편성표 페이지에서 편성 목록을 찾지 못했습니다.")

    days = {}
    for d in block.get("scheDtList") or []:
        days[d["scheDt"]] = d.get("scheWkday", "")

    programs = {}
    for p in block.get("schePgmList") or []:
        date = p.get("scheDt")
        if not date:
            continue
        start_ts = p.get("bdStrDtm") or 0
        end_ts = p.get("bdEndDtm") or 0
        base = day_start_ts(date)
        raw_title = p.get("pgmNm") or ""
        epi_name = p.get("pgmEpinoNm") or ""
        programs[p["scheId"]] = {
            "id": p["scheId"],
            "pgmId": p.get("pgmId") or "",
            "date": date,
            "channel": p.get("chnNm") or "tvN",
            "start": p.get("bdStrTtm") or "",
            "end": p.get("bdEndTtm") or "",
            "startTs": start_ts,
            "endTs": end_ts,
            "offsetMin": int(round((start_ts - base) / 60.0)),
            "durationMin": max(5, int(round((end_ts - start_ts) / 60.0))),
            "rawTitle": raw_title,
            "title": clean_title(raw_title),
            "programName": program_name_only(clean_title(raw_title)),
            "episodeName": epi_name,
            "episode": parse_episode(epi_name, raw_title),
            "subtitle": episode_subtitle(epi_name),
            "liveFlag": p.get("bdFgNm") or "",
            "grade": p.get("dlbrtGrdNm") or "",
        }
        days.setdefault(date, "")

    return {"days": days, "programs": programs}


# ------------------------------------------------------- tvN 프로그램 카탈로그
#
# tvN 프로그램 목록 페이지는 한 번에 24개만 내려줍니다(2페이지부터는 tvN 쪽
# API 가 404 라 더 받을 수 없습니다). 그래서 받을 수 있는 만큼을 로컬에 쌓아
# 두고, 편성표의 pgmId 로 장르와 정식 프로그램명을 찾습니다.


def _next_data(html_text):
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html_text, re.S
    )
    if not m:
        raise RuntimeError("페이지 구조가 바뀌었습니다(__NEXT_DATA__ 없음).")
    return json.loads(m.group(1))


def fetch_program_catalog():
    """프로그램 목록 페이지에서 {pgmId: {name, genre, subGenre}} 를 뽑습니다."""
    data = _next_data(_http_get(TVN_PROGRAM_URL))
    fallback = data.get("props", {}).get("pageProps", {}).get("fallback", {}) or {}
    out = {}
    for value in fallback.values():
        if not isinstance(value, dict):
            continue
        node = value.get("data")
        if not (isinstance(node, dict) and isinstance(node.get("dataInfo"), dict)):
            continue
        for item in node["dataInfo"].get("list") or []:
            pgm_id = item.get("pgmId")
            if not pgm_id:
                continue
            out[pgm_id] = {
                "name": (item.get("pgmNm") or "").strip(),
                "genre": (item.get("repGenreInfo") or "").strip(),
                "subGenre": (item.get("ptclrGenreInfo") or "").strip(),
                "channel": (item.get("repChnNm") or "").strip(),
                "slug": ((item.get("frontDetailUrlAddr") or "").rstrip("/").split("/")[-1]),
            }
    return out


def load_seed_catalog():
    """data/tvn_programs.txt (pgmId|이름|대표장르|세부장르) 를 읽습니다.

    tvN 목록 API 는 브라우저에서만 2페이지 이상을 내려주기 때문에,
    전체 목록을 한 번 받아 이 파일로 보관해 두고 기본값으로 씁니다.
    """
    out = {}
    try:
        with open(PROGRAM_SEED, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("|")
                if len(parts) < 3:
                    continue
                out[parts[0].strip()] = {
                    "name": parts[1].strip(),
                    "genre": parts[2].strip(),
                    "subGenre": parts[3].strip() if len(parts) > 3 else "",
                    "channel": "",
                }
    except OSError:
        pass
    return out


def load_program_catalog():
    store = _read_json(PROGRAM_CATALOG, {"fetchedAt": 0, "items": {}})
    merged = load_seed_catalog()
    merged.update(store.get("items", {}))   # 새로 받아 온 값이 우선입니다.
    store["items"] = merged
    return store


def refresh_program_catalog(force=False):
    """목록을 읽어 로컬 카탈로그에 누적합니다(tvN 이 노출을 바꾸면 조금씩 늘어납니다)."""
    store = load_program_catalog()
    fresh = (time.time() - store.get("fetchedAt", 0)) < SCHEDULE_TTL_SEC
    if fresh and not force and store.get("items"):
        return store
    try:
        fetched = fetch_program_catalog()
    except Exception:
        return store       # 실패해도 이미 쌓아 둔 카탈로그로 계속 씁니다.
    store.setdefault("items", {}).update(fetched)
    store["fetchedAt"] = int(time.time())
    _write_json(PROGRAM_CATALOG, store)
    return store


GENRE_CHOICES = ["드라마", "예능", "교양", "브랜디드", "영화", "스포츠", "기타"]


def load_program_genres():
    """사용자가 직접 지정한 장르 {프로그램명: 장르}."""
    return _read_json(PROGRAM_GENRE_STORE, {})


def save_program_genre(name, genre):
    name = (name or "").strip()
    genre = (genre or "").strip()
    with _store_lock:
        store = load_program_genres()
        if not name:
            return store
        if genre:
            store[name] = genre
        else:
            store.pop(name, None)
        _write_json(PROGRAM_GENRE_STORE, store)
        return store


BRANDED_TAGS = ("브랜디드", "건강IP")
VARIANT_SUFFIXES = ("특별판", "스페셜", "하이라이트", "스핀오프", "무삭제판", "확장판")
VARIANT_SPLIT_RE = re.compile(r"\s*[-–—:]\s+")


def tag_genre(raw_title):
    """제목 앞 말머리에서 읽을 수 있는 장르. 카탈로그에 없을 때만 씁니다."""
    tags = " ".join(re.findall(r"\[([^\]]{1,20})\]", raw_title or ""))
    if any(t in tags for t in BRANDED_TAGS):
        return "브랜디드"
    if "예능" in tags:
        return "예능"
    if any(t in tags for t in ("드라마", "월화", "화수", "수목", "목금", "금토", "토일", "일월")):
        return "드라마"
    return ""


def norm_name(name):
    """띄어쓰기·대소문자를 무시하고 이름을 비교하기 위한 형태."""
    return re.sub(r"\s+", "", (name or "")).lower()


def base_name_candidates(name):
    """'유 퀴즈 온 더 블럭 특별판', 'A - 부제' 처럼 붙은 변형에서 본 프로그램명 후보를 만듭니다."""
    out = []
    text = (name or "").strip()
    for _ in range(3):
        changed = False
        for suffix in VARIANT_SUFFIXES:
            if text.endswith(suffix) and len(text) > len(suffix) + 1:
                text = text[: -len(suffix)].strip()
                changed = True
        parts = VARIANT_SPLIT_RE.split(text, 1)
        if len(parts) == 2 and len(parts[0].strip()) >= 2:
            text = parts[0].strip()
            changed = True
        if not changed:
            break
        if text and text not in out:
            out.append(text)
    return out


def apply_catalog(store):
    """편성 목록에 카탈로그 장르를 붙이고, 특별판·파트를 본 프로그램으로 합칩니다."""
    catalog = load_program_catalog().get("items", {})
    programs = store.get("programs", {})

    # 1단계 — pgmId 로 정식 이름과 장르를 찾습니다.
    for p in programs.values():
        entry = catalog.get(p.get("pgmId") or "")
        p["catalogName"] = entry["name"] if entry else ""
        p["genre"] = (entry or {}).get("genre") or tag_genre(p.get("rawTitle", ""))
        p["subGenre"] = (entry or {}).get("subGenre") or ""
        # 카탈로그에 없으면 편성 제목을 그대로 둡니다. 잘라내는 건
        # 2단계에서 "같은 이름의 프로그램이 실제로 있을 때"만 합니다.
        p["programName"] = p["catalogName"] or p["title"]

    # 2단계 — 실제로 존재하는 프로그램명만 통합 대상으로 인정합니다.
    canonical = {}
    for p in programs.values():
        key = norm_name(p["programName"])
        if key and (key not in canonical or p["catalogName"]):
            canonical[key] = p["catalogName"] or p["programName"]
    for entry in catalog.values():
        canonical.setdefault(norm_name(entry["name"]), entry["name"])

    for p in programs.values():
        # 카탈로그에 자기 항목이 있으면 그 자체로 독립 프로그램입니다.
        # ('식스센스: B사이드' 를 '식스센스' 로 합치지 않기 위한 조건)
        if p["catalogName"]:
            continue
        for candidate in base_name_candidates(p["programName"]):
            key = norm_name(candidate)
            if key and key != norm_name(p["programName"]) and key in canonical:
                p["programName"] = canonical[key]
                break

    # 3단계 — 합쳐진 그룹 안에 장르를 아는 회차가 있으면 나눠 갖습니다.
    genre_by_name = {}
    for p in programs.values():
        if p["genre"]:
            genre_by_name.setdefault(norm_name(p["programName"]), (p["genre"], p["subGenre"]))
    for p in programs.values():
        if not p["genre"]:
            found = genre_by_name.get(norm_name(p["programName"]))
            if found:
                p["genre"], p["subGenre"] = found

    # 4단계 — 사용자가 직접 지정한 장르가 있으면 그 값을 씁니다.
    manual = load_program_genres()
    for p in programs.values():
        chosen = manual.get(p["programName"])
        p["genreManual"] = bool(chosen)
        if chosen:
            p["genre"] = chosen
            p["subGenre"] = ""
    return store


def load_schedule_store():
    return _read_json(SCHEDULE_STORE, {"fetchedAt": 0, "days": {}, "programs": {}})


def refresh_schedule(force=False):
    """tvN 에서 이번 주 편성표를 읽어 로컬 저장소에 누적 병합합니다."""
    with _store_lock:
        store = load_schedule_store()
        fresh_enough = (time.time() - store.get("fetchedAt", 0)) < SCHEDULE_TTL_SEC
        if fresh_enough and not force and store.get("programs"):
            return store, False

        fetched = fetch_tvn_schedule()

        # tvN 이 편성 시각을 고치면 같은 방송이 새 scheId 로 다시 내려옵니다.
        # 그대로 합치면 옛 편성이 남아 블록이 두 겹으로 겹쳐 보입니다.
        # 이번에 받아 온 날짜는 통째로 갈아끼우고, 그 밖의 날짜만 남깁니다.
        fetched_dates = set(fetched["days"]) | {
            p["date"] for p in fetched["programs"].values()
        }
        kept = {
            pid: p
            for pid, p in (store.get("programs") or {}).items()
            if p.get("date") not in fetched_dates
        }
        kept.update(fetched["programs"])
        store["programs"] = kept
        store.setdefault("days", {}).update(fetched["days"])
        store["fetchedAt"] = int(time.time())
        refresh_program_catalog(force=force)
        apply_catalog(store)
        _write_json(SCHEDULE_STORE, store)
        return store, True


# --------------------------------------------------------------------- 설정

DEFAULT_CONFIG = {
    # 팀에서 쓰는 링크 형태가 다르면 이 주소만 바꾸면 됩니다.
    "storeSearchUrl": "https://search.shopping.naver.com/ns/search?query={keyword}",
    # 키워드 등록 API 주소 — Postman 요청과 curl 명령을 만들 때 씁니다.
    "registerApiUrl": "",
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(_read_json(CONFIG_STORE, {}))
    return cfg


def save_config(patch):
    with _store_lock:
        cfg = load_config()
        for key in DEFAULT_CONFIG:
            if key in patch and patch[key] is not None:
                cfg[key] = str(patch[key]).strip()
        _write_json(CONFIG_STORE, cfg)
        return cfg


def public_config(cfg):
    return {"storeSearchUrl": cfg["storeSearchUrl"], "registerApiUrl": cfg["registerApiUrl"]}


# ------------------------------------------------------------------ 인증 키
#
# 인증 키는 config.json 과 따로 secrets.json 에 둡니다. 이 파일은 .gitignore
# 에 넣어 깃에 올라가지 않습니다. 한 번 커밋되면 기록에서 지우기 어렵습니다.
# 값 자체는 브라우저로 내려보내지 않고, 서버가 요청을 대신 보낼 때만 씁니다.

SECRETS_STORE = os.path.join(DATA_DIR, "secrets.json")


def load_secrets():
    data = _read_json(SECRETS_STORE, {})
    headers = data.get("authHeaders")
    return {"authHeaders": headers if isinstance(headers, list) else []}


def parse_header_lines(text):
    """'이름: 값' 을 한 줄에 하나씩. 값 안의 콜론은 그대로 둡니다."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition(":")
        if not sep:
            continue
        name, value = name.strip(), value.strip()
        if name and value:
            out.append({"name": name, "value": value})
    return out


def save_secrets(patch):
    """인증 헤더를 저장합니다. 입력이 비어 있으면 기존 값을 그대로 둡니다."""
    with _store_lock:
        data = load_secrets()
        if patch.get("clearAuthHeaders"):
            data["authHeaders"] = []
        else:
            parsed = parse_header_lines(patch.get("authHeadersText"))
            if parsed:
                data["authHeaders"] = parsed
        _write_json(SECRETS_STORE, data)
        return data


def mask_secret(value):
    """화면에는 끝 4자리만 보여 줍니다."""
    value = value or ""
    if not value:
        return ""
    if len(value) <= 4:
        return "•" * len(value)
    return "•" * 8 + value[-4:]


def public_secrets(data):
    """브라우저에는 값 대신 헤더 이름과 가린 문자열만 보냅니다."""
    return {
        "authHeaders": [{"name": h.get("name", ""),
                         "masked": mask_secret(h.get("value"))}
                        for h in data.get("authHeaders", [])],
    }


SEND_LOG = os.path.join(DATA_DIR, "send_log.json")


def send_registration(payload):
    """등록 API 로 대신 보냅니다.

    인증 키는 이 함수 안에서만 쓰이고 화면으로도, 기록으로도 나가지 않습니다.
    """
    body = payload.get("body")
    if not isinstance(body, dict):
        return {"ok": False, "error": "보낼 내용이 없습니다."}

    cfg = load_config()
    url = (cfg.get("registerApiUrl") or "").strip()
    if not url:
        return {"ok": False, "error": "등록 API 주소가 비어 있습니다. 설정에서 넣어 주세요."}
    if not url.lower().startswith("https://"):
        return {"ok": False, "error": "https 주소만 보낼 수 있습니다: " + url}

    secrets = load_secrets()
    headers = {"Content-Type": "application/json; charset=utf-8"}
    for item in secrets.get("authHeaders", []):
        name, value = (item.get("name") or "").strip(), (item.get("value") or "").strip()
        if name and value:
            headers[name] = value
    auth_names = [h for h in headers if h.lower() != "content-type"]

    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    started = time.time()
    try:
        req = urllib.request.Request(url, data=raw, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=20) as res:
            status, text = res.status, res.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        text = exc.read().decode("utf-8", "replace") if exc.fp else str(exc)
    except Exception as exc:
        return {"ok": False, "error": "보내지 못했습니다: %s" % exc}

    took = round(time.time() - started, 2)
    record = {
        "at": int(time.time()),
        "url": url,
        "status": status,
        "took": took,
        # 무엇을 보냈는지 알 수 있게 키워드만 남기고 키는 남기지 않습니다.
        "keyword": ((body.get("productInfo") or [{}])[0] or {}).get("productKeyword", ""),
        "programName": body.get("programName", ""),
        "requestId": body.get("requestId", ""),
    }
    with _store_lock:
        log = _read_json(SEND_LOG, {"items": []})
        log.setdefault("items", []).insert(0, record)
        log["items"] = log["items"][:200]
        _write_json(SEND_LOG, log)

    return {"ok": 200 <= status < 300, "status": status, "took": took,
            "response": text[:2000], "usedAuthHeaders": auth_names}


# ------------------------------------------------- tvN 공식 회차 미리보기
#
# tvN 프로그램 페이지(https://tvn.cjenm.com/ko/<slug>/)의 __NEXT_DATA__ 에는
# 공식 '회차 미리보기' 본문과 출연진이 들어 있습니다. 검색으로 추정하지 않고
# 이 값을 그대로 씁니다.

PREVIEW_TTL_SEC = 12 * 3600


def load_program_slugs():
    """{pgmId: slug}. 프로그램 상세 페이지 주소를 찾는 표입니다."""
    out = {}
    try:
        with open(PROGRAM_SLUGS, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "|" not in line:
                    continue
                pgm_id, slug = line.split("|", 1)
                if pgm_id.strip() and slug.strip():
                    out[pgm_id.strip()] = slug.strip()
    except OSError:
        pass
    # 카탈로그를 새로 받을 때 모인 주소도 함께 씁니다.
    for pgm_id, entry in load_program_catalog().get("items", {}).items():
        slug = (entry or {}).get("slug")
        if slug:
            out.setdefault(pgm_id, slug)
    return out


def resolve_slug(program, store):
    """이 회차의 상세 페이지 주소. 특별판·부제 회차는 본 프로그램 주소를 씁니다."""
    slugs = load_program_slugs()
    own = slugs.get(program.get("pgmId") or "")
    if own:
        return own
    name = program.get("programName")
    for other in (store.get("programs") or {}).values():
        if other.get("programName") == name:
            found = slugs.get(other.get("pgmId") or "")
            if found:
                return found
    return ""


EPISODE_NO_RE = re.compile(r"(\d+)\s*(?:회|화)")


def fetch_program_page(slug):
    """프로그램 페이지에서 출연진과 회차 미리보기 목록을 뽑습니다."""
    html_text = _http_get("https://tvn.cjenm.com/ko/%s/" % urllib.parse.quote(slug))
    data = _next_data(html_text)
    fallback = data.get("props", {}).get("pageProps", {}).get("fallback", {}) or {}

    cast, previews, clips, broadcast = [], [], [], ""
    for value in fallback.values():
        if not isinstance(value, dict):
            continue
        node = value.get("data")

        # 공식 클립 목록은 리스트로 옵니다. 제목에 그 회차에 나온 음식·물건이 적혀 있고
        # '#유료광고포함' 이 붙으면 PPL 이 들어간 클립입니다.
        if isinstance(node, list):
            for item in node:
                if not (isinstance(item, dict) and item.get("clipNm")):
                    continue
                title = str(item["clipNm"]).strip()
                clips.append({
                    "title": title,
                    "program": (item.get("pgmNm") or "").strip(),
                    "episode": (EPISODE_NO_RE.search(item.get("pgmNm") or "").group(1)
                                if EPISODE_NO_RE.search(item.get("pgmNm") or "") else ""),
                    "ppl": "유료광고" in title,
                    "thumb": (item.get("videoTnailImgPathAddr") or "").strip(),
                    "url": (item.get("clipFrontDetailUrlAddr")
                            or item.get("pgmFrontDetailUrlAddr") or "").strip(),
                })
            continue

        if not isinstance(node, dict):
            continue
        if not broadcast and isinstance(node.get("bdTm"), str):
            broadcast = node["bdTm"].strip()
        for person in node.get("simplePrsnInfoList") or []:
            name = (person or {}).get("prsnNm")
            if name and name not in cast:
                cast.append(name.strip())
        for item in node.get("previewInfoList") or []:
            text = (item or {}).get("prevewCnts") or ""
            title = (item or {}).get("prevewTit") or ""
            if not text.strip():
                continue
            previews.append({
                "title": title.strip(),
                "text": re.sub(r"\r\n|\r", "\n", text).strip(),
                "episode": (EPISODE_NO_RE.search(title).group(1)
                            if EPISODE_NO_RE.search(title) else ""),
            })
    return {"cast": cast, "previews": previews, "clips": clips,
            "broadcast": broadcast}


def load_program_page(slug, force=False):
    cache = _read_json(PREVIEW_CACHE, {})
    hit = cache.get(slug)
    if hit and not force and (time.time() - hit.get("fetchedAt", 0)) < PREVIEW_TTL_SEC:
        return hit
    try:
        fetched = fetch_program_page(slug)
    except Exception as exc:
        if hit:
            return hit
        return {"cast": [], "previews": [], "clips": [], "broadcast": "",
                "error": str(exc)}
    fetched["fetchedAt"] = int(time.time())
    with _store_lock:
        cache = _read_json(PREVIEW_CACHE, {})
        cache[slug] = fetched
        _write_json(PREVIEW_CACHE, cache)
    return fetched


# 마지막 문단은 대개 "9월 4일 금요일 저녁 8시 35분 …" 같은 방송 안내라 뺍니다.
SCHEDULE_HINT_RE = re.compile(
    r"\d+월\s*\d+일|\d+년\s*\d+월|본방\s*사수|채널\s*고정|시\s*방송|방송$|재방송"
)


def _preview_lines(text):
    return [ln.strip() for ln in (text or "").split("\n") if ln.strip()]


def _line_key(line):
    """비교용 — 공백과 흔한 기호를 지운 형태."""
    return re.sub(r"[\s~!?★☆♥♨.·…\"'\u2018\u2019\u201c\u201d]", "", line or "")


def repeated_lines(previews, min_share=0.5):
    """같은 프로그램의 여러 회차에 공통으로 나오는 줄 = 프로그램 소개 문구."""
    if len(previews) < 2:
        return set()
    counts = {}
    for item in previews:
        for key in {_line_key(ln) for ln in _preview_lines(item.get("text", ""))}:
            if key:
                counts[key] = counts.get(key, 0) + 1
    total = len(previews)
    return {
        key for key, hits in counts.items()
        if hits >= 2 and hits / total >= min_share
    }


def clean_preview_text(text, boiler=(), max_lines=3, width=72):
    """앞에서부터 3줄. 회차마다 반복되는 소개 문구와 방송 안내는 건너뜁니다.

    문장을 새로 쓰지 않고 원문 줄을 그대로 씁니다.
    """
    out, truncated = [], False
    for line in _preview_lines(text):
        key = _line_key(line)
        if key in boiler:
            continue
        if out and SCHEDULE_HINT_RE.search(line):
            continue
        if len(out) >= max_lines:
            truncated = True
            break
        if len(line) > width:
            line = line[: width - 1].rstrip() + "…"
        out.append(line)

    if truncated and out and not out[-1].endswith("…"):
        out[-1] = out[-1] + " …"
    return out


# ------------------------------------------------------------------ 티빙 보조
#
# tvN 프로그램 목록에 없는 프로그램(브랜디드·신설 등)은 tvN 페이지 자체가
# 없습니다. 그런 프로그램만 티빙 페이지에서 출연진과 소개를 가져옵니다.
# 표는 data/tving_contents.txt 에 "프로그램명|콘텐츠코드" 로 적습니다.


def load_tving_map():
    out = {}
    try:
        with open(TVING_MAP, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "|" not in line:
                    continue
                name, code = line.split("|", 1)
                if name.strip() and code.strip():
                    out[name.strip()] = code.strip()
    except OSError:
        pass
    return out


def fetch_tving_content(code):
    """티빙 콘텐츠 페이지에서 출연진과 줄거리를 뽑습니다."""
    data = _next_data(_http_get("https://www.tving.com/contents/%s" % urllib.parse.quote(code)))
    info = data.get("props", {}).get("pageProps", {}).get("contentInfo") or {}
    return {
        "title": (info.get("title") or "").strip(),
        "cast": [x.strip() for x in (info.get("actor") or []) if x and x.strip()],
        "synopsis": (info.get("synopsis") or "").strip(),
        "url": "https://www.tving.com/contents/%s" % code,
    }


def load_tving_content(code, force=False):
    cache = _read_json(TVING_CACHE, {})
    hit = cache.get(code)
    if hit and not force and (time.time() - hit.get("fetchedAt", 0)) < PREVIEW_TTL_SEC:
        return hit
    try:
        fetched = fetch_tving_content(code)
    except Exception as exc:
        return hit or {"cast": [], "synopsis": "", "error": str(exc)}
    fetched["fetchedAt"] = int(time.time())
    with _store_lock:
        cache = _read_json(TVING_CACHE, {})
        cache[code] = fetched
        _write_json(TVING_CACHE, cache)
    return fetched


def tving_summary(program):
    """tvN 자료가 없을 때 쓰는 예비 요약."""
    code = load_tving_map().get(program.get("programName") or "")
    if not code:
        return None
    info = load_tving_content(code)
    if not (info.get("cast") or info.get("synopsis")):
        return None
    synopsis = info.get("synopsis", "")
    # 소개가 프로그램 이름만 반복하는 경우는 내용으로 치지 않습니다.
    if norm_name(synopsis) == norm_name(program.get("programName") or ""):
        synopsis = ""
    return {
        "available": True,
        "source": "tving",
        "url": info.get("url", ""),
        "cast": info.get("cast", [])[:8],
        "preview": ({"title": "프로그램 소개",
                     "lines": clean_preview_text(synopsis)} if synopsis else None),
        "broadcast": "",
        "hasPreviews": False,
    }


def load_program_notes():
    """직접 적어 둔 프로그램 설명 {프로그램명: 설명}."""
    out = {}
    try:
        with open(PROGRAM_NOTES, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "|" not in line:
                    continue
                name, note = line.split("|", 1)
                if name.strip() and note.strip():
                    out[name.strip()] = note.strip()
    except OSError:
        pass
    return out


def note_summary(program):
    note = load_program_notes().get(program.get("programName") or "")
    if not note:
        return None
    return {
        "available": True,
        "source": "note",
        "url": "",
        "cast": [],
        "preview": {"title": "", "lines": clean_preview_text(note)},
        "broadcast": "",
        "hasPreviews": False,
    }


def build_program_summary(program, store):
    """tvN 공식 데이터 기반 방송 요약."""
    slug = resolve_slug(program, store)
    if not slug:
        fallback = tving_summary(program) or note_summary(program)
        if fallback:
            return fallback
        return {"available": False,
                "reason": "tvN·티빙 어디에도 이 프로그램 자료가 없습니다."}

    page = load_program_page(slug)
    episode_no = ""
    m = EPISODE_NO_RE.search(program.get("episode") or "")
    if m:
        episode_no = m.group(1)

    chosen = None
    for item in page.get("previews") or []:
        if episode_no and item.get("episode") == episode_no:
            chosen = item
            break
    if chosen is None and page.get("previews"):
        chosen = page["previews"][0]

    if not (page.get("cast") or chosen or page.get("broadcast")):
        fallback = tving_summary(program) or note_summary(program)
        if fallback:
            return fallback

    return {
        "available": bool(page.get("cast") or chosen or page.get("broadcast")),
        "source": "tvn",
        "slug": slug,
        "url": "https://tvn.cjenm.com/ko/%s/" % slug,
        "cast": (page.get("cast") or [])[:8],
        "broadcast": page.get("broadcast", ""),
        "hasPreviews": bool(page.get("previews")),
        # 회차가 일치할 때만 본문을 내보냅니다. 다른 회차 내용을 이 회차인 것처럼
        # 보여 주지 않기 위해서입니다.
        # 회차가 일치할 때만 본문을 내보냅니다. 다른 회차 내용을 이 회차인 것처럼
        # 보여 주지 않기 위해서입니다.
        "preview": (
            {"title": chosen["title"],
             "lines": clean_preview_text(chosen["text"],
                                         repeated_lines(page.get("previews") or []))}
            if chosen and episode_no and chosen.get("episode") == episode_no
            else None
        ),
        "latestPreviewTitle": (chosen or {}).get("title", "") if chosen else "",
        "error": page.get("error", ""),
    }


# ------------------------------------------------------------- 프로그램 ID 표


def load_program_ids():
    return _read_json(PROGRAM_ID_STORE, {})


def save_program_ids(mapping):
    """{프로그램명: programId} 를 병합 저장합니다."""
    with _store_lock:
        store = load_program_ids()
        for name, pid in (mapping or {}).items():
            name = (name or "").strip()
            pid = (pid or "").strip()
            if not name:
                continue
            if pid:
                store[name] = pid
            else:
                store.pop(name, None)
        _write_json(PROGRAM_ID_STORE, store)
        return store


# ------------------------------------------------- 네이버플러스스토어 미리보기
#
# 키워드를 판단할 재료(연관 검색어·근거 문서)와 실제 스토어 검색 링크를 제공합니다.


def store_search_url(cfg, keyword):
    template = cfg.get("storeSearchUrl") or DEFAULT_CONFIG["storeSearchUrl"]
    return template.replace("{keyword}", urllib.parse.quote(keyword))


def store_preview(keyword):
    cfg = load_config()
    related, error = [], ""
    try:
        related = keyword_engine.naver_autocomplete(keyword, limit=8)
    except Exception as exc:
        error = "연관 검색어를 못 읽었습니다: %s" % exc
    return {
        "searchUrl": store_search_url(cfg, keyword),
        "related": related,
        "warning": error,
    }


STORE_PRODUCT_TTL_SEC = 6 * 3600
_product_cache = {}


def store_products(keyword, limit=16):
    """미리보기 팝업에 그릴 상품 목록. 같은 키워드는 잠시 재사용합니다."""
    now = time.time()
    hit = _product_cache.get(keyword)
    if hit and now - hit["at"] < STORE_PRODUCT_TTL_SEC:
        return {"products": hit["products"], "cached": True, "warning": ""}

    try:
        products = keyword_engine.search_shopping(keyword, limit=limit)
    except Exception as exc:
        return {"products": [], "cached": False,
                "warning": "상품을 불러오지 못했습니다: %s" % exc}

    _product_cache[keyword] = {"at": now, "products": products}
    if len(_product_cache) > 200:                   # 오래된 것부터 버립니다
        for key in sorted(_product_cache, key=lambda k: _product_cache[k]["at"])[:50]:
            _product_cache.pop(key, None)
    return {"products": products, "cached": False, "warning": ""}


def collect_official_material(program, store):
    """이 회차의 공식 자료 — tvN 미리보기 본문과 공식 클립 제목.

    회차가 맞는 것만 씁니다. 다른 회차 내용이 섞이면 엉뚱한 상품이 올라옵니다.
    """
    out = {"preview": [], "clips": [], "cast": [], "ppl": False}
    slug = resolve_slug(program, store)
    if not slug:
        return out

    page = load_program_page(slug)
    out["cast"] = list(page.get("cast") or [])
    episode_no = ""
    m = EPISODE_NO_RE.search(program.get("episode") or "")
    if m:
        episode_no = m.group(1)
    if not episode_no:
        return out

    for item in page.get("previews") or []:
        if item.get("episode") == episode_no:
            out["preview"] = [ln for ln in (item.get("text") or "").split("\n") if ln.strip()]
            break
    for clip in page.get("clips") or []:
        if clip.get("episode") == episode_no:
            out["clips"].append({
                "title": clip.get("title", ""),
                "thumb": clip.get("thumb", ""),
                "url": clip.get("url", ""),
            })
            if clip.get("ppl"):
                out["ppl"] = True
    return out


# ------------------------------------------------------------- 키워드 분석 캐시

KEYWORD_TTL_SEC = 24 * 3600


def analyze_program_keywords(program, force=False):
    """회차별 키워드 분석 결과를 캐시와 함께 돌려줍니다."""
    cache = _read_json(KEYWORD_CACHE, {})
    hit = cache.get(program["id"])
    # 저장된 결과에 요약이 없으면(이전 버전) 다시 분석합니다.
    if (hit and not force and "summary" in hit
            and (time.time() - hit.get("analyzedAt", 0)) < KEYWORD_TTL_SEC):
        hit["cached"] = True
        return hit

    result = keyword_engine.analyze_program(
        {
            "title": program.get("title", ""),
            "programName": program.get("programName", "") or program.get("title", ""),
            "episode": program.get("episode", ""),
            "subtitle": program.get("subtitle", ""),
            "genre": program.get("genre", ""),
            # 방송일이 있어야 다른 회차 기사를 걸러낼 수 있습니다.
            "startTs": program.get("startTs", 0),
        },
        official=collect_official_material(program, load_schedule_store()),
    )
    result["analyzedAt"] = int(time.time())
    result["programId"] = program["id"]
    result["cached"] = False
    with _store_lock:
        cache = _read_json(KEYWORD_CACHE, {})
        cache[program["id"]] = result
        _write_json(KEYWORD_CACHE, cache)
    return result


# ------------------------------------------------------------------ 등록 키워드


def load_registrations():
    return _read_json(REGISTRATION_STORE, {"items": []})


def save_registration(item):
    """매뉴얼 키워드는 한 시점에 한 개만 유효합니다.

    이전 등록은 지우지 않고 남겨 둡니다. 회차마다 '그 방송 시각에 유효했던
    가장 최근 등록' 하나만 보이므로, 지난 편성에는 예전 키워드가 그대로 남습니다.
    """
    with _store_lock:
        store = load_registrations()
        name = item.get("programName")
        same = [x for x in store["items"] if name and x.get("programName") == name]
        previous = max(
            same, key=lambda x: (x.get("fromTs", 0), x.get("createdAt", 0)), default=None
        )
        store["items"] = [x for x in store["items"] if x.get("id") != item.get("id")]
        store["items"].append(item)
        _write_json(REGISTRATION_STORE, store)
        return store, previous


def delete_registration(reg_id):
    with _store_lock:
        store = load_registrations()
        store["items"] = [x for x in store["items"] if x.get("id") != reg_id]
        _write_json(REGISTRATION_STORE, store)
        return store


# --------------------------------------------------------------------- 라우팅

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "SKBKeywordAgent/0.1"

    def log_message(self, fmt, *args):  # 콘솔을 조용하게 유지합니다.
        sys.stderr.write("  %s\n" % (fmt % args))

    # -- 응답 헬퍼 -------------------------------------------------------
    def _send(self, code, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), CONTENT_TYPES[".json"])

    def _error(self, message, code=500):
        self._json({"ok": False, "error": message}, code)

    def _body_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype == "application/x-www-form-urlencoded":
            # 다른 사이트에서 폼 전송으로 넘겨줄 때 쓰는 경로입니다.
            form = urllib.parse.parse_qs(raw)
            return json.loads(form.get("payload", ["{}"])[0])
        return json.loads(raw)

    # -- GET -------------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            return self._serve_file("index.html")
        if path.startswith("/api/"):
            return self._api_get(path, query)
        return self._serve_file(path.lstrip("/"))

    def _serve_file(self, rel_path):
        safe = os.path.normpath(rel_path).replace("\\", "/")
        if safe.startswith("..") or safe.startswith("/"):
            return self._error("잘못된 경로입니다.", 400)
        full = os.path.join(WEB_DIR, safe)
        if not os.path.isfile(full):
            return self._send(404, "찾을 수 없는 파일입니다: " + safe, "text/plain; charset=utf-8")
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            data = f.read()
        self._send(200, data, CONTENT_TYPES.get(ext, "application/octet-stream"))

    def _api_get(self, path, query):
        try:
            if path == "/api/schedule":
                force = query.get("refresh", ["0"])[0] == "1"
                try:
                    store, refreshed = refresh_schedule(force=force)
                    warning = ""
                except Exception as exc:  # 네트워크 실패 시 저장된 편성표로 계속 진행
                    store = load_schedule_store()
                    refreshed = False
                    warning = "tvN 편성표를 새로 못 읽었습니다: %s" % exc
                    if not store.get("programs"):
                        return self._error(warning, 502)
                return self._json(
                    {
                        "ok": True,
                        "refreshed": refreshed,
                        "warning": warning,
                        "fetchedAt": store.get("fetchedAt", 0),
                        "days": store.get("days", {}),
                        "programs": list(store.get("programs", {}).values()),
                    }
                )

            if path == "/api/keywords":
                program_id = query.get("programId", [""])[0]
                store = load_schedule_store()
                program = store.get("programs", {}).get(program_id)
                if not program:
                    return self._error("편성 정보를 찾지 못했습니다: " + program_id, 404)
                force = query.get("refresh", ["0"])[0] == "1"
                result = analyze_program_keywords(program, force=force)
                return self._json({"ok": True, "program": program, **result})

            if path == "/api/store-preview":
                keyword = query.get("keyword", [""])[0].strip()
                if not keyword:
                    return self._error("키워드가 비어 있습니다.", 400)
                return self._json({"ok": True, "keyword": keyword, **store_preview(keyword)})

            if path == "/api/store-products":
                keyword = query.get("keyword", [""])[0].strip()
                if not keyword:
                    return self._error("키워드가 비어 있습니다.", 400)
                cfg = load_config()
                return self._json({"ok": True, "keyword": keyword,
                                   "searchUrl": store_search_url(cfg, keyword),
                                   **store_products(keyword)})

            if path == "/api/config":
                return self._json({"ok": True, **public_config(load_config()),
                                   **public_secrets(load_secrets())})

            if path == "/api/program-ids":
                return self._json({"ok": True, "map": load_program_ids()})

            if path == "/api/summary":
                program_id = query.get("programId", [""])[0]
                store = load_schedule_store()
                program = store.get("programs", {}).get(program_id)
                if not program:
                    return self._error("편성 정보를 찾지 못했습니다: " + program_id, 404)
                return self._json({"ok": True, **build_program_summary(program, store)})

            if path == "/api/program-genres":
                return self._json({"ok": True, "map": load_program_genres(),
                                   "choices": GENRE_CHOICES})

            if path == "/api/program-catalog":
                store = load_program_catalog()
                return self._json({"ok": True, "count": len(store.get("items", {})),
                                   "fetchedAt": store.get("fetchedAt", 0)})

            if path == "/api/registrations":
                return self._json({"ok": True, **load_registrations()})

            return self._error("없는 API 입니다: " + path, 404)
        except Exception as exc:
            return self._error(str(exc))

    # -- POST / DELETE ----------------------------------------------------
    def do_OPTIONS(self):
        """브라우저에서 카탈로그를 직접 넣을 때 필요한 예비 요청입니다."""
        self.send_response(204)
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _cors_headers(self):
        if self.path.startswith("/api/program-catalog"):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/config":
                body = self._body_json()
                cfg = save_config(body)
                secrets = save_secrets(body)
                return self._json({"ok": True, **public_config(cfg),
                                   **public_secrets(secrets)})

            if parsed.path == "/api/send-registration":
                return self._json(send_registration(self._body_json()))

            if parsed.path == "/api/program-catalog":
                body = self._body_json()
                items = body.get("items") or {}
                with _store_lock:
                    store = load_program_catalog()
                    store.setdefault("items", {}).update(items)
                    store["fetchedAt"] = int(time.time())
                    _write_json(PROGRAM_CATALOG, store)
                sched = load_schedule_store()
                if sched.get("programs"):
                    apply_catalog(sched)
                    _write_json(SCHEDULE_STORE, sched)
                return self._json({"ok": True, "added": len(items),
                                   "count": len(store.get("items", {}))})

            if parsed.path == "/api/program-genres":
                body = self._body_json()
                store = save_program_genre(body.get("name"), body.get("genre"))
                sched = load_schedule_store()
                if sched.get("programs"):
                    apply_catalog(sched)
                    _write_json(SCHEDULE_STORE, sched)
                return self._json({"ok": True, "map": store})

            if parsed.path == "/api/program-ids":
                body = self._body_json()
                mapping = body.get("map")
                if mapping is None and body.get("name"):
                    mapping = {body["name"]: body.get("id", "")}
                store = save_program_ids(mapping or {})
                return self._json({"ok": True, "map": store})

            if parsed.path == "/api/registrations":
                item = self._body_json()
                if not item.get("id"):
                    item["id"] = "reg_%d" % int(time.time() * 1000)
                item.setdefault("createdAt", int(time.time()))
                store, previous = save_registration(item)
                return self._json({
                    "ok": True, "item": item,
                    "previous": (previous or {}).get("keyword", ""),
                    **store,
                })
            return self._error("없는 API 입니다: " + parsed.path, 404)
        except Exception as exc:
            return self._error(str(exc))

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/api/registrations":
                reg_id = query.get("id", [""])[0]
                store = delete_registration(reg_id)
                return self._json({"ok": True, **store})
            return self._error("없는 API 입니다: " + parsed.path, 404)
        except Exception as exc:
            return self._error(str(exc))


def main():
    port = int(os.environ.get("PORT", "8765"))
    os.makedirs(DATA_DIR, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("AI 커머스광고 키워드 Agent")
    print("  → http://127.0.0.1:%d  (종료: Ctrl+C)" % port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료했습니다.")


if __name__ == "__main__":
    main()
