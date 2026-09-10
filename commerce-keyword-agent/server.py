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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
DATA_DIR = os.path.join(BASE_DIR, "data")
SCHEDULE_STORE = os.path.join(DATA_DIR, "schedule_store.json")
REGISTRATION_STORE = os.path.join(DATA_DIR, "registrations.json")

TVN_SCHEDULE_URL = "https://tvn.cjenm.com/ko/tvn-schedule/"
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
            "episodeName": epi_name,
            "episode": parse_episode(epi_name, raw_title),
            "subtitle": episode_subtitle(epi_name),
            "liveFlag": p.get("bdFgNm") or "",
            "grade": p.get("dlbrtGrdNm") or "",
        }
        days.setdefault(date, "")

    return {"days": days, "programs": programs}


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
        store.setdefault("days", {}).update(fetched["days"])
        store.setdefault("programs", {}).update(fetched["programs"])
        store["fetchedAt"] = int(time.time())
        _write_json(SCHEDULE_STORE, store)
        return store, True


# ------------------------------------------------------------------ 등록 키워드


def load_registrations():
    return _read_json(REGISTRATION_STORE, {"items": []})


def save_registration(item):
    with _store_lock:
        store = load_registrations()
        store["items"] = [x for x in store["items"] if x.get("id") != item.get("id")]
        store["items"].append(item)
        _write_json(REGISTRATION_STORE, store)
        return store


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
        return json.loads(self.rfile.read(length).decode("utf-8"))

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

            if path == "/api/registrations":
                return self._json({"ok": True, **load_registrations()})

            return self._error("없는 API 입니다: " + path, 404)
        except Exception as exc:
            return self._error(str(exc))

    # -- POST / DELETE ----------------------------------------------------
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/registrations":
                item = self._body_json()
                if not item.get("id"):
                    item["id"] = "reg_%d" % int(time.time() * 1000)
                item.setdefault("createdAt", int(time.time()))
                store = save_registration(item)
                return self._json({"ok": True, "item": item, **store})
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
