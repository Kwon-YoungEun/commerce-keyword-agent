# -*- coding: utf-8 -*-
"""방송 회차 → 화제 상품 키워드 추출 엔진 (표준 라이브러리만 사용).

수집처
  1) DuckDuckGo 웹검색 (키 없이) — 기사·커뮤니티 글 제목/요약
  2) Daum 통합검색 (키 없이) — 검색광고 키워드( 실제 커머스 수요 신호 )
  3) 네이버 자동완성 (키 없이) — 사람들이 실제로 치는 검색어
추출
  형태소 분석기 없이, 조사 제거 + n-gram + 상품어 사전 + 커머스 신호어로 점수를 냅니다.
"""

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
TIMEOUT = 12

# ---------------------------------------------------------------- 사전 정의

CATEGORY_TERMS = {
    "식품": """재첩 굴 전복 새우 낙지 문어 오징어 조개 홍합 멸치 김 미역 다시마 젓갈 명란 창란
        곶감 한과 약과 떡 만두 라면 국수 칼국수 밀키트 김치 깍두기 된장 고추장 간장 쌈장 참기름
        들기름 조청 꿀 홍삼 인삼 도라지 더덕 쌀 잡곡 현미 견과 땅콩 아몬드 호두 커피 원두 차 녹차
        보리차 과자 빵 잼 소스 육수 한우 삼겹살 닭갈비 훈제 소시지 과일 사과 배 감귤 한라봉 딸기
        포도 샤인머스캣 수박 복숭아 자두 매실 대추 밤 옥수수 감자 고구마 버섯 표고 나물 장아찌
        젓 액젓 선물세트 세트 즙 진액 환 분말 티백 육포 어묵 만두피 두부 계란 우유 요거트 치즈""".split(),
    "패션": """원피스 니트 가디건 코트 자켓 재킷 점퍼 패딩 셔츠 블라우스 티셔츠 맨투맨 후드 팬츠
        바지 청바지 데님 슬랙스 스커트 치마 가방 백팩 크로스백 토트백 숄더백 에코백 신발 운동화
        스니커즈 부츠 샌들 슬리퍼 로퍼 구두 모자 버킷햇 캡모자 볼캡 비니 목걸이 귀걸이 반지 팔찌
        시계 선글라스 안경 스카프 머플러 장갑 벨트 지갑 양말 잠옷 수영복 등산복 레깅스 조끼 셋업
        원단 주얼리 액세서리""".split(),
    "뷰티": """립스틱 립밤 틴트 쿠션 파운데이션 컨실러 아이섀도 마스카라 아이라이너 블러셔 향수
        크림 로션 세럼 앰플 토너 에센스 마스크팩 클렌저 클렌징 샴푸 린스 트리트먼트 헤어오일
        선크림 자외선차단제 네일 바디로션 핸드크림 미스트""".split(),
    "리빙": """텀블러 컵 머그 물병 보온병 냄비 프라이팬 웍 솥 도마 칼 그릇 접시 수저 젓가락 트레이
        에어프라이어 밥솥 믹서기 블렌더 정수기 청소기 세탁기 건조기 이불 베개 매트 매트리스 러그
        커튼 조명 스탠드 의자 테이블 책상 선반 수납 바구니 화분 방향제 디퓨저 캔들 텐트 캠핑 침낭
        아이스박스 그릴 버너 랜턴 돗자리 우산 가습기 선풍기 히터 전기장판 빨래건조대 수세미 행주""".split(),
    "디지털": """노트북 태블릿 이어폰 헤드폰 스피커 카메라 마우스 키보드 충전기 보조배터리 케이블
        스마트워치 공기청정기 프로젝터 모니터 마이크 짐벌 드론""".split(),
}

PRODUCT_TERMS = {}
for _cat, _words in CATEGORY_TERMS.items():
    for _w in _words:
        PRODUCT_TERMS.setdefault(_w, _cat)

COMMERCE_CUES = set(
    """구매 구입 어디 어디서 어디껀지 가격 얼마 브랜드 제품 상품 협찬 착용 입은 신은 들었던 사용한
    판매 쇼핑 후기 추천 정보 링크 최저가 품절 완판 문의 ppl 나온 나왔던 화제 인기 대란 주문 배송
    직송 특산물 맛집 레시피""".split()
)

STOPWORDS = set(
    """tvn 티비엔 방송 방영 예능 드라마 프로그램 시즌 회차 본방 재방 편성 편성표 시청률 시청자 시청
    출연 출연진 배우 가수 mc 게스트 멤버 기자 뉴스 기사 사진 영상 제공 공개 예고 선공개 하이라이트
    화제 관심 오늘 어제 내일 이번 지난 다음 최근 현재 당시 이날 사람 사람들 이야기 모습 순간 시간
    자신 우리 그녀 그들 대한 위해 통해 관련 진행 시작 공개된 나무위키 위키 블로그 카페 웹문서 유튜브
    인스타 인스타그램 네이버 다음 구글 쿠팡 검색 무료 배송 로켓배송 와우회원 리뷰 이벤트 할인 광고
    노출 기준 입찰가 도움말 신청 바로가기 더보기 전체 선택 옵션 페이지 사이트 홈페이지 다시보기
    티빙 넷플릭스 웨이브 무엇 누구 언제 어떻게 정말 진짜 완전 너무 매우 아주 가장 함께 모두 각각
    등장 공식 최초 역대 이후 이전 동안 사이 결국 다시 계속 아직 벌써 심지어 특히 바로 직접
    안내 서비스 신청 총정리 편집 기획의도 목차 개요 내용 방법 이유 경우 문제 해결 확인 사용 이용
    평균 최고 최저 기준 경신 기록 순위 목록 정리 소개 설명 참고 관계자 측은 밝혔다 전했다 말했다""".split()
)

JOSA = [
    "으로부터", "에서부터", "이라는", "라는", "이라고", "라고", "에게서", "한테서", "으로서", "으로써",
    "까지", "부터", "에게", "한테", "보다", "처럼", "이랑", "으로", "에서", "에는", "에도", "이나",
    "라도", "든지", "이며", "이고", "와의", "과의", "마다", "조차", "밖에", "의", "가", "이", "은",
    "는", "을", "를", "에", "도", "만", "와", "과", "로", "랑", "께",
]

TOKEN_RE = re.compile(r"[가-힣]+|[A-Za-z][A-Za-z0-9']*|\d+")
HANGUL_RE = re.compile(r"[가-힣]")

SOURCE_WEIGHT = {"ad": 4.0, "autocomplete": 3.0, "title": 2.0, "snippet": 1.0}


# ------------------------------------------------------------------ 수집기


def _fetch(url, headers=None, timeout=TIMEOUT):
    hdr = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9", "Accept": "*/*"}
    hdr.update(headers or {})
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read().decode("utf-8", errors="replace")


def _strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def search_ddg(query, limit=12):
    """DuckDuckGo(HTML판) 웹검색 — 한국어 결과가 안정적으로 나옵니다."""
    url = "https://html.duckduckgo.com/html/?q=%s&kl=kr-kr" % urllib.parse.quote(query)
    body = _fetch(url)
    titles = re.findall(r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', body, re.S)
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', body, re.S)
    docs = []
    for idx, (link, raw_title) in enumerate(titles[:limit]):
        title = _strip_tags(raw_title)
        if not title:
            continue
        snippet = _strip_tags(snippets[idx]) if idx < len(snippets) else ""
        docs.append(
            {"source": "duckduckgo", "kind": "web", "title": title, "snippet": snippet,
             "url": html.unescape(link), "query": query}
        )
    return docs


def search_daum(query, limit=10):
    """Daum 통합검색 — 검색광고 키워드( 커머스 수요 신호 )와 웹문서를 함께 가져옵니다."""
    url = "https://search.daum.net/search?w=tot&q=" + urllib.parse.quote(query)
    body = _fetch(url)
    docs = []
    for kw in re.findall(r'<strong class="tit_item">(.*?)</strong>', body, re.S):
        text = _strip_tags(kw)
        if text:
            docs.append(
                {"source": "daum-ad", "kind": "ad", "title": text, "snippet": "",
                 "url": "", "query": query}
            )
    # 웹문서 결과는 <script slot="data"> 안의 JSON 에 들어 있습니다.
    count = 0
    for blob in re.findall(r'<script slot="data" type="application/json">(.*?)</script>', body, re.S):
        try:
            node = json.loads(blob)
        except ValueError:
            continue
        data = node.get("data") or {}
        title = _strip_tags(data.get("TITLE") or "")
        desc = _strip_tags(data.get("CONTENTS") or data.get("DESCRIPTION") or "")
        if not title or desc == "웹문서":
            desc = "" if desc == "웹문서" else desc
        if title:
            docs.append(
                {"source": "daum", "kind": "web", "title": title, "snippet": desc,
                 "url": data.get("DOCUMENT_URL") or "", "query": query}
            )
            count += 1
        if count >= limit:
            break
    return docs


def naver_autocomplete(seed, limit=10):
    """네이버 자동완성 — 사람들이 실제로 검색하는 문구."""
    url = (
        "https://ac.search.naver.com/nx/ac?q=%s&st=100&r_format=json&r_enc=UTF-8"
        "&r_unicode=0&t_koreng=1&ans=2" % urllib.parse.quote(seed)
    )
    raw = _fetch(url, headers={"Referer": "https://search.naver.com/"})
    data = json.loads(raw)
    out = []
    for group in data.get("items", []) or []:
        for row in group:
            if row and row[0]:
                out.append(row[0])
    return out[:limit]


# ------------------------------------------------------------------ 전처리


def strip_josa(token):
    if not HANGUL_RE.search(token) or len(token) < 3:
        return token
    for j in JOSA:
        if token.endswith(j) and len(token) - len(j) >= 2:
            return token[: -len(j)]
    return token


def tokenize(text):
    """문장 단위로 나눈 뒤 토큰 목록을 돌려줍니다."""
    text = re.sub(r"https?://\S+", " ", text or "")
    sentences = re.split(r"[.!?\n·|ㅣ,\[\]()<>“”\"']+", text)
    out = []
    for sent in sentences:
        toks = [strip_josa(t.lower() if t.isascii() else t) for t in TOKEN_RE.findall(sent)]
        toks = [t for t in toks if t]
        if toks:
            out.append(toks)
    return out


def is_bad_token(tok):
    if tok in STOPWORDS:
        return True
    if tok.isdigit():
        return True
    if HANGUL_RE.search(tok):
        return len(tok) < 2
    return len(tok) < 3  # 영문 두 글자 이하는 버립니다.


def categorize(phrase):
    for word, cat in PRODUCT_TERMS.items():
        if phrase.endswith(word) or (" " + word) in (" " + phrase):
            return cat
    return ""


# ------------------------------------------------------------------ 추출기


def build_queries(program):
    title = program.get("title") or ""
    episode = program.get("episode") or ""
    subtitle = program.get("subtitle") or ""
    base = re.sub(r"\s*\d+$", "", title).strip() or title

    queries = []
    if episode:
        queries.append("%s %s 협찬 제품" % (title, episode))
        queries.append("%s %s 나온 상품" % (title, episode))
    queries.append("%s 협찬 어디" % base)
    queries.append("%s 화제 상품 구매" % base)
    if subtitle:
        queries.append("%s %s" % (base, subtitle[:30]))
    # 중복 제거(순서 유지)
    seen, out = set(), []
    for q in queries:
        q = re.sub(r"\s+", " ", q).strip()
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out[:4]


def collect_documents(program, log=None):
    """검색처를 돌며 문서를 모읍니다. 한 곳이 실패해도 나머지는 계속합니다."""
    docs, errors = [], []
    for query in build_queries(program):
        for fn, name in ((search_ddg, "DuckDuckGo"), (search_daum, "Daum")):
            try:
                docs.extend(fn(query))
            except Exception as exc:
                errors.append("%s 검색 실패(%s): %s" % (name, query, exc))

    title = program.get("title") or ""
    base = re.sub(r"\s*\d+$", "", title).strip() or title
    for seed in [title, base + " 협찬", base + " 제품"]:
        try:
            for phrase in naver_autocomplete(seed):
                docs.append(
                    {"source": "naver-ac", "kind": "autocomplete", "title": phrase,
                     "snippet": "", "url": "", "query": seed}
                )
        except Exception as exc:
            errors.append("네이버 자동완성 실패(%s): %s" % (seed, exc))
    return docs, errors


def extract_keywords(program, docs, top_n=18):
    title = program.get("title") or ""
    title_tokens = set(TOKEN_RE.findall(title))
    scores = defaultdict(float)
    evidence = defaultdict(list)
    sources = defaultdict(set)

    for doc in docs:
        kind = doc.get("kind")
        fields = [("title", doc.get("title", ""))]
        if doc.get("snippet"):
            fields.append(("snippet", doc["snippet"]))

        for field, text in fields:
            weight = SOURCE_WEIGHT["ad"] if kind == "ad" else (
                SOURCE_WEIGHT["autocomplete"] if kind == "autocomplete"
                else SOURCE_WEIGHT[field]
            )
            for toks in tokenize(text):
                has_cue = any(t in COMMERCE_CUES for t in toks)
                for n in (1, 2, 3):
                    for i in range(len(toks) - n + 1):
                        gram = toks[i : i + n]
                        if any(is_bad_token(t) for t in gram):
                            continue
                        phrase = " ".join(gram)
                        if len(phrase) < 2 or len(phrase) > 24:
                            continue
                        if not HANGUL_RE.search(phrase):
                            continue  # 영문만 있는 후보는 잡음이 많아 제외합니다.
                        if phrase in title.lower() or phrase == title:
                            continue
                        gain = weight * (1.0 + 0.25 * (n - 1))
                        if has_cue:
                            gain += 0.8
                        scores[phrase] += gain
                        sources[phrase].add(doc.get("source", ""))
                        if doc.get("title") and len(evidence[phrase]) < 3:
                            evidence[phrase].append(
                                {"text": doc["title"][:120], "url": doc.get("url", ""),
                                 "source": doc.get("source", "")}
                            )

    # 상품어 사전 가산점 + 프로그램 이름만 반복되는 후보 감점
    results = []
    for phrase, score in scores.items():
        cat = categorize(phrase)
        if cat:
            score += 6.0
        toks = phrase.split()
        if all(t in title_tokens for t in toks):
            score *= 0.35
        if len(toks) >= 2:
            score += 1.0
        results.append((phrase, score, cat))

    results.sort(key=lambda x: -x[1])

    # 부분 문자열 중복 정리 — 더 구체적인(긴) 표현을 남깁니다.
    kept = []
    for phrase, score, cat in results:
        redundant = False
        for kphrase, kscore, _ in kept:
            if phrase in kphrase and score <= kscore * 1.6:
                redundant = True
                break
        if not redundant:
            kept.append((phrase, score, cat))
        if len(kept) >= top_n * 2:
            break

    top = kept[:top_n]
    if not top:
        return []
    max_score = top[0][1] or 1.0
    return [
        {
            "keyword": phrase,
            "score": round(score, 2),
            "confidence": round(min(100, score / max_score * 100)),
            "category": cat or "기타",
            "shoppable": bool(cat),
            "sources": sorted(sources[phrase]),
            "evidence": evidence[phrase],
            "demandChecked": False,
            "demand": [],
        }
        for phrase, score, cat in top
    ]


def verify_demand(keywords, limit=8):
    """상위 키워드를 네이버 자동완성으로 검증해 '실제 검색 수요'를 표시합니다."""
    for item in keywords[:limit]:
        try:
            suggestions = naver_autocomplete(item["keyword"], limit=6)
        except Exception:
            continue
        item["demandChecked"] = True
        item["demand"] = suggestions
        if suggestions:
            item["score"] = round(item["score"] + 2.0, 2)
    keywords.sort(key=lambda k: -k["score"])
    return keywords


def analyze_program(program, verify=True):
    docs, errors = collect_documents(program)
    keywords = extract_keywords(program, docs)
    if verify:
        keywords = verify_demand(keywords)
    return {
        "keywords": keywords,
        "docCount": len(docs),
        "queries": build_queries(program),
        "errors": errors,
        "documents": [
            {k: d.get(k) for k in ("source", "kind", "title", "url")}
            for d in docs[:40]
        ],
    }
