# -*- coding: utf-8 -*-
"""방송 회차 → 화제 상품 키워드 추출 엔진 (파이썬 표준 라이브러리만 사용).

수집처 (모두 API 키 없이 동작)
  1) DuckDuckGo 웹검색 — 기사·커뮤니티 글의 제목과 요약
  2) Daum 통합검색  — 검색광고 키워드( 광고주가 실제로 사는 커머스 키워드 )와 웹문서
  3) 네이버 자동완성 — 사람들이 실제로 치는 검색어

추출 방식
  형태소 분석기 없이 처리합니다. 조사를 떼고 n-gram 후보를 만든 뒤,
  상품어 사전 / 커머스 신호어 / 출처 신뢰도로 점수를 매깁니다.
  인물·브랜드 이름은 추측하지 않고, 검색광고 키워드( 예: '노윤서모자' )를
  상품어로 쪼개서 배웁니다.
"""

import html
import json
import re
import time
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
        액젓 선물세트 세트 즙 진액 환 분말 티백 육포 어묵 두부 계란 우유 요거트 치즈 젓갈세트""".split(),
    "패션": """원피스 니트 가디건 코트 자켓 재킷 점퍼 패딩 셔츠 블라우스 티셔츠 맨투맨 후드 팬츠
        바지 청바지 데님 슬랙스 스커트 치마 가방 백팩 크로스백 토트백 숄더백 에코백 신발 운동화
        스니커즈 부츠 샌들 슬리퍼 로퍼 구두 모자 버킷햇 캡모자 볼캡 비니 목걸이 귀걸이 반지 팔찌
        시계 선글라스 안경 스카프 머플러 장갑 벨트 지갑 양말 잠옷 수영복 등산복 레깅스 조끼 셋업
        주얼리 액세서리 집업 트레이닝복""".split(),
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

# 붙여 쓴 키워드를 쪼갤 때 쓰는 상품어 — 긴 것부터 맞춰 봅니다.
SPLITTABLE_TERMS = sorted([w for w in PRODUCT_TERMS if len(w) >= 2], key=len, reverse=True)

COMMERCE_CUES = set(
    """구매 구입 어디 어디서 어디껀지 어디꺼 가격 얼마 브랜드 제품 상품 협찬 착용 입은 신은 들었던
    사용한 판매 쇼핑 후기 추천 정보 링크 최저가 품절 완판 문의 ppl 나온 나왔던 인기 대란 주문
    직송 특산물 레시피 스타일 코디 룩""".split()
)

STOPWORDS = set(
    """tvn 티비엔 방송 방영 예능 드라마 프로그램 시즌 회차 본방 재방 편성 편성표 시청률 시청자 시청
    출연 출연진 배우 가수 게스트 멤버 기자 뉴스 기사 사진 영상 제공 공개 예고 선공개 하이라이트
    화제 관심 오늘 어제 내일 이번 지난 다음 최근 현재 당시 이날 사람 사람들 이야기 모습 순간 시간
    자신 우리 그녀 그들 대한 위해 통해 관련 진행 시작 공개된 나무위키 위키 블로그 카페 웹문서 유튜브
    인스타 인스타그램 네이버 다음 구글 쿠팡 검색 무료 배송 로켓배송 와우회원 리뷰 이벤트 할인 광고
    노출 입찰가 도움말 신청 바로가기 더보기 전체 선택 옵션 페이지 사이트 홈페이지 다시보기 지상파
    티빙 넷플릭스 웨이브 무엇 누구 언제 어떻게 정말 진짜 완전 너무 매우 아주 가장 함께 모두 각각
    등장 공식 최초 역대 이후 이전 동안 사이 결국 다시 계속 아직 벌써 심지어 특히 바로 직접 위치
    안내 서비스 총정리 편집 기획의도 목차 개요 내용 방법 이유 경우 문제 해결 확인 사용 이용 정보
    평균 최고 최저 기준 경신 기록 순위 목록 정리 소개 설명 참고 관계자 측은 밝혔다 전했다 말했다
    촬영지 촬영장 도전 원작 몇부작 등장인물 인물관계도 결말 스포 스포일러 줄거리 명대사
    방영일 종영 첫방송 마지막회 최종회 시즌제 채널 실시간 스트리밍 자막 더빙 무료보기 사장 대표
    프로필 나이 학력 열애 결혼 소속사 팬미팅 논란 인정 종결 호불호 진화 완벽 만원 가지 부분
    재방송 본방송 몇시 시청방법 편성시간 다시보기 무료 총정리 모음 정리본""".split()
)

JOSA = [
    "으로부터", "에서부터", "이라는", "라는", "이라고", "라고", "에게서", "한테서", "으로서", "으로써",
    "까지", "부터", "에게", "한테", "보다", "처럼", "이랑", "으로", "에서", "에는", "에도", "이나",
    "라도", "든지", "이며", "이고", "와의", "과의", "마다", "조차", "밖에", "의", "가", "이", "은",
    "는", "을", "를", "에", "도", "만", "와", "과", "로", "랑", "께",
]

TOKEN_RE = re.compile(r"[가-힣]+|[A-Za-z][A-Za-z0-9']*|\d+")
HANGUL_RE = re.compile(r"[가-힣]")
SPLIT_RE = re.compile(r"[.!?\n·ㆍ|ㅣ,\[\]()<>“”\"']+")

SOURCE_WEIGHT = {"ad": 4.0, "autocomplete": 3.0, "title": 2.0, "snippet": 1.0}


def short_title(title):
    """'언니네 산지직송3 - 네 식구 산지 라이프' 처럼 부제가 붙은 제목을 앞부분만 남깁니다."""
    out = re.split(r"\s+[-–—:]\s+", (title or "").strip())[0].strip()
    out = re.sub(r"\s*\d+$", "", out).strip()
    return out or (title or "").strip()


# ------------------------------------------------------------------ 수집기


def _fetch(url, headers=None, data=None, timeout=TIMEOUT):
    hdr = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9", "Accept": "*/*"}
    hdr.update(headers or {})
    body = urllib.parse.urlencode(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read().decode("utf-8", errors="replace")


def _strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _parse_ddg(body, query, limit):
    titles = re.findall(r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', body, re.S)
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', body, re.S)
    docs = []
    for idx, (link, raw_title) in enumerate(titles[:limit]):
        title = _strip_tags(raw_title)
        if not title:
            continue
        docs.append(
            {"source": "duckduckgo", "kind": "web", "title": title,
             "snippet": _strip_tags(snippets[idx]) if idx < len(snippets) else "",
             "url": html.unescape(link), "query": query}
        )
    return docs


def search_ddg(query, limit=12):
    """DuckDuckGo(HTML판) 웹검색. GET 이 비면 폼 전송(POST)으로 한 번 더 시도합니다."""
    url = "https://html.duckduckgo.com/html/?q=%s&kl=kr-kr" % urllib.parse.quote(query)
    docs = _parse_ddg(_fetch(url), query, limit)
    if not docs:
        time.sleep(0.6)
        docs = _parse_ddg(
            _fetch("https://html.duckduckgo.com/html/",
                   headers={"Content-Type": "application/x-www-form-urlencoded",
                            "Referer": "https://html.duckduckgo.com/"},
                   data={"q": query, "kl": "kr-kr"}),
            query, limit,
        )
    return docs


def search_daum(query, limit=10):
    """Daum 통합검색 — 검색광고 키워드와 웹문서를 함께 가져옵니다."""
    body = _fetch("https://search.daum.net/search?w=tot&q=" + urllib.parse.quote(query))
    docs = []
    for kw in re.findall(r'<strong class="tit_item">(.*?)</strong>', body, re.S):
        text = _strip_tags(kw)
        if text and not any(t in STOPWORDS for t in TOKEN_RE.findall(text)):
            docs.append({"source": "daum-ad", "kind": "ad", "title": text,
                         "snippet": "", "url": "", "query": query})
    count = 0
    for blob in re.findall(
        r'<script slot="data" type="application/json">(.*?)</script>', body, re.S
    ):
        try:
            node = json.loads(blob)
        except ValueError:
            continue
        data = node.get("data") or {}
        title = _strip_tags(data.get("TITLE") or "")
        desc = _strip_tags(data.get("CONTENTS") or "")
        if not title:
            continue
        docs.append({"source": "daum", "kind": "web", "title": title, "snippet": desc,
                     "url": data.get("DOCUMENT_URL") or "", "query": query})
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
    data = json.loads(_fetch(url, headers={"Referer": "https://search.naver.com/"}))
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
    out = []
    for sent in SPLIT_RE.split(text):
        toks = [strip_josa(t.lower() if t.isascii() else t) for t in TOKEN_RE.findall(sent)]
        toks = [t for t in toks if t]
        if toks:
            out.append(toks)
    return out


def is_bad_token(tok):
    if tok in STOPWORDS or tok.isdigit():
        return True
    if HANGUL_RE.search(tok):
        return len(tok) < 2
    return len(tok) < 3  # 영문 두 글자 이하는 버립니다.


def categorize(phrase):
    """어절 단위로 상품어 사전과 맞춥니다. '김선영' 이 '김(식품)' 으로 잡히지 않게 합니다."""
    tokens = phrase.split()
    for token in tokens:
        cat = PRODUCT_TERMS.get(token)
        if cat:
            return cat
    for token in tokens:
        for word in SPLITTABLE_TERMS:
            if len(token) > len(word) and token.endswith(word):
                return PRODUCT_TERMS[word]
    return ""


def ends_with_product(phrase):
    last = phrase.split()[-1]
    if last in PRODUCT_TERMS:
        return True
    return any(len(last) > len(w) and last.endswith(w) for w in SPLITTABLE_TERMS)


def split_commerce_keyword(text):
    """'노윤서모자' 처럼 붙여 쓴 광고 키워드를 (앞말, 상품어) 로 쪼갭니다."""
    compact = text.replace(" ", "")
    if not HANGUL_RE.search(compact) or len(compact) > 14:
        return None
    for word in SPLITTABLE_TERMS:
        if compact.endswith(word):
            head = compact[: -len(word)]
            if 2 <= len(head) <= 6 and HANGUL_RE.match(head) and head not in STOPWORDS:
                return head, word
    return None


# ------------------------------------------------------------------ 추출기


def build_queries(program):
    title = (program.get("title") or "").strip()
    episode = program.get("episode") or ""
    subtitle = program.get("subtitle") or ""
    genre = program.get("genre") or ""
    base = short_title(title)

    queries = []
    if episode:
        queries.append("%s %s 협찬 제품" % (title, episode))
    if genre == "드라마":
        queries.append("%s 의상 협찬 어디" % base)
        queries.append("%s 착용 가방 주얼리" % base)
    else:
        queries.append("%s 협찬 제품 어디" % base)
        queries.append("%s 나온 상품 구매" % base)
    if subtitle:
        queries.append("%s %s" % (base, subtitle[:30]))

    seen, out = set(), []
    for q in queries:
        q = re.sub(r"\s+", " ", q).strip()
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out[:4]


def collect_documents(program):
    """검색처를 돌며 문서를 모읍니다. 한 곳이 실패해도 나머지는 계속합니다."""
    docs, errors = [], []
    for query in build_queries(program):
        for fn, name in ((search_ddg, "DuckDuckGo"), (search_daum, "Daum")):
            try:
                docs.extend(fn(query))
            except Exception as exc:
                errors.append("%s 검색 실패(%s): %s" % (name, query, exc))

    title = (program.get("title") or "").strip()
    base = short_title(title)
    for seed in [title, base + " 협찬", base + " 제품"]:
        try:
            for phrase in naver_autocomplete(seed):
                docs.append({"source": "naver-ac", "kind": "autocomplete", "title": phrase,
                             "snippet": "", "url": "", "query": seed})
        except Exception as exc:
            errors.append("네이버 자동완성 실패(%s): %s" % (seed, exc))
    return docs, errors


def learn_entities(docs):
    """광고·자동완성 키워드를 상품어로 쪼개어 인물·브랜드 이름을 배웁니다."""
    entities = defaultdict(float)
    pairs = defaultdict(float)
    for doc in docs:
        if doc.get("kind") not in ("ad", "autocomplete"):
            continue
        text = doc.get("title", "")
        weight = 2.0 if doc.get("kind") == "ad" else 1.0
        parsed = split_commerce_keyword(text)
        if parsed:
            head, product = parsed
            entities[head] += weight
            pairs[(head, product)] += weight
            continue
        toks = [strip_josa(t) for t in TOKEN_RE.findall(text)]
        for i, tok in enumerate(toks[:-1]):
            nxt = toks[i + 1]
            if (nxt in PRODUCT_TERMS and len(tok) >= 2 and tok not in STOPWORDS
                    and tok not in PRODUCT_TERMS and HANGUL_RE.match(tok)):
                entities[tok] += weight * 0.7
                pairs[(tok, nxt)] += weight * 0.7
    return entities, pairs


def extract_keywords(program, docs, top_n=18):
    title = (program.get("title") or "").strip()
    base = short_title(title)
    title_tokens = {strip_josa(t) for t in TOKEN_RE.findall(title)}

    scores = defaultdict(float)
    evidence = defaultdict(list)
    sources = defaultdict(set)

    entities, learned_pairs = learn_entities(docs)
    anchor_tokens = title_tokens | set(entities)

    for doc in docs:
        kind = doc.get("kind")
        doc_text = (doc.get("title", "") + " " + doc.get("snippet", "")).strip()
        doc_tokens = {strip_josa(t) for t in TOKEN_RE.findall(doc_text)}
        related = bool(anchor_tokens & doc_tokens)

        fields = [("title", doc.get("title", ""))]
        if doc.get("snippet"):
            fields.append(("snippet", doc["snippet"]))

        for field, text in fields:
            if kind == "ad":
                weight = SOURCE_WEIGHT["ad"] if related else 0.6
            elif kind == "autocomplete":
                weight = SOURCE_WEIGHT["autocomplete"]
            else:
                weight = SOURCE_WEIGHT[field] * (1.0 if related else 0.4)

            for toks in tokenize(text):
                has_cue = any(t in COMMERCE_CUES for t in toks)
                for n in (1, 2, 3):
                    for i in range(len(toks) - n + 1):
                        gram = toks[i : i + n]
                        if any(is_bad_token(t) for t in gram):
                            continue
                        phrase = " ".join(gram)
                        if not (2 <= len(phrase) <= 24) or not HANGUL_RE.search(phrase):
                            continue
                        if phrase == title or phrase == base:
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

    # 배운 (앞말 + 상품어) 짝을 띄어쓴 형태의 키워드로 만들어 둡니다.
    for (head, product), hits in learned_pairs.items():
        phrase = "%s %s" % (head, product)
        scores[phrase] = max(scores.get(phrase, 0.0), 8.0 + 3.0 * hits)
        sources[phrase].add("광고키워드")

    # 프로그램 이름 + 상품어 조합 — 방송 연계 검색에 실제로 쓰이는 형태입니다.
    top_products = sorted(
        ((p, s) for p, s in scores.items() if p in PRODUCT_TERMS), key=lambda x: -x[1]
    )[:4]
    for product, pscore in top_products:
        phrase = "%s %s" % (base, product)
        scores[phrase] = max(scores.get(phrase, 0.0), pscore * 0.8 + 4.0)
        sources[phrase].add("조합")

    results = []
    for phrase, score in scores.items():
        toks = phrase.split()
        cat = categorize(phrase)
        if cat:
            score += 6.0 if ends_with_product(phrase) else 3.0
        if len(toks) == 1 and phrase in PRODUCT_TERMS:
            score *= 0.45   # '모자' 처럼 너무 넓은 말은 낮춥니다.
        if all(t in title_tokens for t in toks):
            score *= 0.3
        if len(toks) >= 2:
            score += 1.0
        results.append((phrase, score, cat))

    results.sort(key=lambda x: -x[1])

    kept = []
    for phrase, score, cat in results:
        if any(phrase in k and score <= s * 1.6 for k, s, _ in kept):
            continue
        kept.append((phrase, score, cat))
        if len(kept) >= top_n:
            break

    if not kept:
        return []
    max_score = kept[0][1] or 1.0
    return [
        {
            "keyword": phrase,
            "score": round(score, 2),
            "confidence": round(min(100, score / max_score * 100)),
            "category": cat or "기타",
            "shoppable": bool(cat),
            "sources": sorted(s for s in sources[phrase] if s),
            "evidence": evidence.get(phrase, []),
            "demandChecked": False,
            "demand": [],
        }
        for phrase, score, cat in kept
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
    top = keywords[0]["score"] if keywords else 1.0
    for item in keywords:
        item["confidence"] = round(min(100, item["score"] / (top or 1.0) * 100))
    return keywords


# ------------------------------------------------------------------ 방송 요약
#
# 요약은 지어내지 않습니다. tvN 이 준 회차 부제와, 검색 결과에 실제로 있는
# 문장/이름만 씁니다. 근거가 없으면 그 줄은 비워 둡니다.

CAST_RUN_RE = re.compile(r"(?:[가-힣]{2,4}\s*[·ㆍ]\s*){1,6}[가-힣]{2,4}")

# '염정아 가방', '강유석 패션' 처럼 사람 이름 뒤에 착장·소지품 말이 붙는 자리
WEAR_WORDS = (
    "패션|의상|스타일|착용|코디|룩|가방|모자|버킷햇|바지|팬츠|반바지|신발|운동화|재킷|자켓|"
    "티셔츠|셔츠|원피스|니트|가디건|목걸이|귀걸이|반지|시계|선글라스|스카프|양말|지갑"
)
CAST_WEAR_RE = re.compile(r"([가-힣]{2,4})\s*(?:의\s*)?(?:" + WEAR_WORDS + r")")
CAST_ROLE_RE = re.compile(
    r"(?:배우|가수|모델|방송인|개그맨|코미디언|셰프|게스트)\s*([가-힣]{2,4})"
    r"|([가-힣]{2,4})\s*(?:출연|합류|등장)"
)
SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def norm_compact(text):
    return re.sub(r"\s+", "", text or "")


def _cast_candidate(name):
    return (
        name
        and 2 <= len(name) <= 4
        and name not in STOPWORDS
        and name not in PRODUCT_TERMS
        and not TITLE_NOISE_RE.search(name)
    )


TITLE_NOISE_RE = re.compile(r"^(제작|공식|영상|사진|정보|추천|리뷰|후기|가격|구매|최신|이번|지난)$")


def extract_cast(program, docs, limit=6):
    """검색 결과 제목에서 사람 이름을 모읍니다.

    '염정아 가방', '강유석 패션' 처럼 착장 이야기에 붙은 이름과,
    '배우 OOO' / 'OOO 출연' 자리, 그리고 이름이 나열된 자리만 인정합니다.
    프로그램 이름에 들어 있는 말은 제외합니다.
    """
    title_tokens = set(TOKEN_RE.findall(program.get("title", "")))
    counts = defaultdict(int)

    for doc in docs:
        text = (doc.get("title", "") + " " + doc.get("snippet", ""))
        for name in CAST_WEAR_RE.findall(text):
            if _cast_candidate(name) and name not in title_tokens:
                counts[name] += 2
        for group in CAST_ROLE_RE.findall(text):
            for name in group:
                if _cast_candidate(name) and name not in title_tokens:
                    counts[name] += 2
        for run in CAST_RUN_RE.findall(text):
            names = [x.strip() for x in re.split(r"[·ㆍ]", run) if x.strip()]
            if len(names) < 2:
                continue
            good = [n for n in names if _cast_candidate(n) and n not in title_tokens]
            if len(good) >= 2:          # 이름 나열로 보일 때만 인정합니다.
                for name in good:
                    counts[name] += 2

    ordered = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return [name for name, hits in ordered if hits >= 2][:limit]


def extract_story(program, docs, limit=2):
    """검색 결과에 실제로 있는 문장/제목을 그대로 한두 줄 가져옵니다."""
    base = norm_compact(short_title(program.get("title", "")))
    episode = norm_compact(program.get("episode", ""))
    picked, seen = [], set()

    for doc in docs:
        if doc.get("kind") != "web":
            continue
        candidates = []
        for sent in SENT_SPLIT_RE.split(doc.get("snippet", "") or ""):
            sent = re.sub(r"\s+", " ", sent).strip(" -·|")
            if 20 <= len(sent) <= 120:
                candidates.append((sent, 1))          # 요약문이 있으면 우선
        title = re.sub(r"\s+", " ", doc.get("title", "")).strip()
        if 12 <= len(title) <= 120:
            candidates.append((title, 0))

        for text, is_snippet in candidates:
            key = norm_compact(text)[:16]
            if key in seen:
                continue
            flat = norm_compact(text)
            score = is_snippet * 4
            if base and base in flat:
                score += 3
            if episode and episode in flat:
                score += 2
            picked.append({"text": text, "url": doc.get("url", ""), "score": score})
            seen.add(key)

    picked.sort(key=lambda x: -x["score"])
    return [{"text": p["text"], "url": p["url"]} for p in picked[:limit] if p["score"] > 0]


def build_summary(program, docs):
    return {
        "episodeTitle": program.get("subtitle", "") or "",
        "cast": extract_cast(program, docs),
        "story": extract_story(program, docs),
    }


def analyze_program(program, verify=True):
    docs, errors = collect_documents(program)
    keywords = extract_keywords(program, docs)
    if verify:
        keywords = verify_demand(keywords)
    return {
        "keywords": keywords,
        "summary": build_summary(program, docs),
        "docCount": len(docs),
        "queries": build_queries(program),
        "errors": errors,
        "documents": [
            {k: d.get(k) for k in ("source", "kind", "title", "url")} for d in docs[:40]
        ],
    }
