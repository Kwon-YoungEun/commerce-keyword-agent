# -*- coding: utf-8 -*-
"""방송 회차 → 화제 상품 키워드 추출 엔진 (파이썬 표준 라이브러리만 사용).

자료를 모으는 곳 — 모두 API 키 없이 동작합니다.

  1) tvN 공식 회차 미리보기 본문   (server.py 가 회차를 맞춰 넘겨 줍니다)
  2) tvN 공식 클립 제목           (같은 회차 것만, '#유료광고포함' 이면 PPL)
  3) 구글 뉴스 RSS               (프로그램명으로 검색, 방송일 근처 기사 우대)
  4) Daum 검색광고 키워드         (광고주가 실제로 사는 커머스 키워드)
  5) 네이버 자동완성              (사람들이 실제로 치는 검색어 · 수요 검증)

고르는 방법
  공식 자료에서 따옴표·괄호로 강조된 말을 먼저 뽑고, 나머지는 조사를 뗀
  n-gram 으로 후보를 만듭니다. 그리고 **서로 다른 자료에서 같이 확인된
  키워드**에 크게 가산합니다(교차 검증). 한 곳에서만 나온 말은 뒤로 밀립니다.
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
        곶감 한과 약과 떡 떡볶이 만두 라면 국수 칼국수 밀키트 김치 깍두기 파김치 된장 고추장 간장
        쌈장 참기름 들기름 조청 꿀 홍삼 인삼 도라지 더덕 쌀 잡곡 현미 견과 땅콩 아몬드 호두 커피
        원두 차 녹차 보리차 진피차 과자 빵 잼 소스 육수 한우 삼겹살 수육 가브리살 닭갈비 통닭 치킨
        훈제 소시지 돈가스 규카츠 장어 과일 사과 배 감귤 한라봉 딸기 포도 샤인머스캣 수박 복숭아
        자두 매실 대추 밤 옥수수 감자 고구마 버섯 표고 나물 장아찌 액젓 선물세트 세트 즙 진액 환
        분말 티백 육포 어묵 두부 계란 우유 요거트 치즈 수프 크림수프 디저트 케이크 꼬치 족발 순대""".split(),
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
    "체험": """체험 족욕 스파 온천 캠핑장 펜션 숙소 호텔 맛집 식당 카페 시장 축제 투어 클래스
        공방 전시 공연 티켓""".split(),
}

PRODUCT_TERMS = {}
for _cat, _words in CATEGORY_TERMS.items():
    for _w in _words:
        PRODUCT_TERMS.setdefault(_w, _cat)

SPLITTABLE_TERMS = sorted([w for w in PRODUCT_TERMS if len(w) >= 2], key=len, reverse=True)

COMMERCE_CUES = set(
    """구매 구입 어디 어디서 어디껀지 어디꺼 가격 얼마 브랜드 제품 상품 협찬 착용 입은 신은 들었던
    사용한 판매 쇼핑 후기 추천 정보 링크 최저가 품절 완판 문의 ppl 나온 나왔던 인기 대란 주문
    직송 특산물 레시피 스타일 코디 룩 맛집 먹방 조업 수확 채취""".split()
)

STOPWORDS = set(
    """tvn 티비엔 방송 방영 예능 드라마 프로그램 시즌 회차 본방 재방 편성 편성표 시청률 시청자 시청
    출연 출연진 배우 가수 게스트 멤버 기자 뉴스 기사 사진 영상 제공 공개 예고 선공개 하이라이트
    화제 관심 오늘 어제 내일 이번 지난 최근 현재 당시 이날 사람 사람들 이야기 모습 순간 시간
    자신 우리 그녀 그들 대한 위해 통해 관련 진행 시작 공개된 나무위키 위키 블로그 카페 웹문서 유튜브
    인스타 인스타그램 네이버 다음 구글 쿠팡 검색 무료 배송 로켓배송 와우회원 리뷰 이벤트 할인 광고
    노출 입찰가 도움말 신청 바로가기 더보기 전체 선택 옵션 페이지 사이트 홈페이지 다시보기 지상파
    티빙 넷플릭스 웨이브 무엇 누구 언제 어떻게 정말 진짜 완전 너무 매우 아주 가장 함께 모두 각각
    등장 공식 최초 역대 이후 이전 동안 사이 결국 다시 계속 아직 벌써 심지어 특히 바로 직접 위치
    안내 서비스 총정리 편집 기획의도 목차 개요 내용 방법 이유 경우 문제 해결 확인 사용 이용 정보
    평균 최고 최저 기준 경신 기록 순위 목록 정리 소개 설명 참고 관계자 측은 밝혔다 전했다 말했다
    촬영지 촬영장 도전 원작 몇부작 등장인물 인물관계도 결말 스포 스포일러 줄거리 명대사 종합
    방영일 종영 첫방송 마지막회 최종회 시즌제 채널 실시간 스트리밍 자막 더빙 무료보기 사장 대표
    프로필 나이 학력 열애 결혼 소속사 팬미팅 논란 인정 종결 호불호 진화 완벽 만원 가지 부분
    재방송 본방송 몇시 시청방법 편성시간 모음 정리본 유료광고포함 유료광고 highlight shorts""".split()
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

# 공식 자료에서 강조된 말 — 따옴표·홑화살표·대괄호 안
EMPHASIS_RE = re.compile(
    r"[‘']([^’']{2,18})[’']"
    r"|[“\"]([^”\"]{2,18})[”\"]"
    r"|[<〈]([^>〉]{2,18})[>〉]"
    r"|\[([^\]]{2,18})\]"
)
# '재첩전&재첩국', '통닭X치즈' 처럼 묶인 것은 나눠 봅니다.
PAIR_SPLIT_RE = re.compile(r"\s*[&＆×xX]\s*")

# 자료 종류별 기본 점수 — 공식 자료를 가장 믿습니다.
KIND_WEIGHT = {
    "preview": 6.0,       # tvN 공식 회차 미리보기
    "clip": 5.0,          # tvN 공식 클립 제목(같은 회차)
    "ad": 4.0,            # 검색광고 키워드
    "news": 3.0,          # 구글 뉴스 제목
    "autocomplete": 2.5,  # 네이버 자동완성
    "web": 1.2,           # 그 밖의 웹문서
}
CROSS_BONUS = 7.0       # 서로 다른 자료에서 또 확인될 때마다
EMPHASIS_BONUS = 6.0    # 공식 자료에서 따옴표 등으로 강조된 말
PRODUCT_TAIL_BONUS = 6.0
PRODUCT_IN_BONUS = 3.0
PPL_BONUS = 3.0
NEWS_WINDOW_DAYS = 10   # 방송일에서 이만큼 떨어진 기사는 낮게 봅니다.


def short_title(title):
    """'언니네 산지직송3 - 네 식구 산지 라이프' 처럼 부제가 붙은 제목을 앞부분만 남깁니다."""
    out = re.split(r"\s+[-–—:]\s+", (title or "").strip())[0].strip()
    return out or (title or "").strip()


def norm_compact(text):
    return re.sub(r"\s+", "", text or "")


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


RSS_ITEM_RE = re.compile(r"<item>(.*?)</item>", re.S)
RSS_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
RSS_DATE_RE = re.compile(r"<pubDate>(.*?)</pubDate>", re.S)
RSS_LINK_RE = re.compile(r"<link>(.*?)</link>", re.S)


def search_google_news(query, limit=30):
    """구글 뉴스 RSS — 키 없이 안정적으로 한국어 기사 제목을 줍니다."""
    url = ("https://news.google.com/rss/search?q=%s&hl=ko&gl=KR&ceid=KR:ko"
           % urllib.parse.quote(query))
    body = _fetch(url, timeout=15)
    docs = []
    for chunk in RSS_ITEM_RE.findall(body)[:limit]:
        title = _strip_tags((RSS_TITLE_RE.search(chunk) or [None, ""])[1])
        if not title:
            continue
        # 제목 끝의 " - 언론사" 는 떼어 냅니다.
        title = re.sub(r"\s+-\s+[^-]{2,20}$", "", title).strip()
        raw_date = (RSS_DATE_RE.search(chunk) or [None, ""])[1].strip()
        ts = 0
        try:
            from email.utils import parsedate_to_datetime
            ts = int(parsedate_to_datetime(raw_date).timestamp())
        except Exception:
            ts = 0
        docs.append({
            "kind": "news", "source": "google-news", "title": title, "snippet": "",
            "url": _strip_tags((RSS_LINK_RE.search(chunk) or [None, ""])[1]),
            "query": query, "ts": ts,
        })
    return docs


def search_daum(query, limit=8):
    """Daum 통합검색 — 검색광고 키워드와 웹문서 제목."""
    body = _fetch("https://search.daum.net/search?w=tot&q=" + urllib.parse.quote(query))
    docs = []
    for kw in re.findall(r'<strong class="tit_item">(.*?)</strong>', body, re.S):
        text = _strip_tags(kw)
        if text and not any(t in STOPWORDS for t in TOKEN_RE.findall(text)):
            docs.append({"kind": "ad", "source": "daum-ad", "title": text,
                         "snippet": "", "url": "", "query": query, "ts": 0})
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
        if not title:
            continue
        docs.append({"kind": "web", "source": "daum", "title": title,
                     "snippet": _strip_tags(data.get("CONTENTS") or ""),
                     "url": data.get("DOCUMENT_URL") or "", "query": query, "ts": 0})
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
    text = re.sub(r"https?://\S+", " ", text or "")
    text = re.sub(r"[#＃]\S+", " ", text)          # 해시태그 제거
    text = re.sub(r"[^\w가-힣\s'\"‘’“”<>\[\]&×]", " ", text)   # 이모지 등 제거
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
    return len(tok) < 3


def categorize(phrase):
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


def extract_emphasis(lines):
    """공식 자료에서 따옴표·괄호로 강조된 말. 화제 상품이 여기 들어 있습니다."""
    found = []
    for line in lines:
        for groups in EMPHASIS_RE.findall(line or ""):
            for term in groups:
                term = (term or "").strip()
                if not term:
                    continue
                for piece in PAIR_SPLIT_RE.split(term):
                    piece = piece.strip(" '\"‘’“”")
                    if not piece or not HANGUL_RE.search(piece):
                        continue
                    toks = [strip_josa(t) for t in TOKEN_RE.findall(piece)]
                    toks = [t for t in toks if not is_bad_token(t)]
                    if toks:
                        found.append(" ".join(toks))
    return found


# ------------------------------------------------------------------ 수집


def build_queries(program):
    """뉴스·웹 검색어. 뉴스는 회차 번호를 쓰면 결과가 없어 프로그램명으로 찾습니다."""
    name = short_title(program.get("programName") or program.get("title") or "")
    episode = program.get("episode") or ""
    return {
        "news": [name],
        "web": [f"{name} {episode} 협찬 제품".strip(), f"{name} 나온 상품 구매"],
        "autocomplete": [name, name + " 협찬"],
    }


def collect_documents(program, official=None):
    """공식 자료 + 뉴스 + 검색광고 + 자동완성을 한데 모읍니다."""
    official = official or {}
    docs, errors = [], []

    for line in official.get("preview") or []:
        docs.append({"kind": "preview", "source": "tvn-preview", "title": line,
                     "snippet": "", "url": "", "query": "", "ts": 0})
    for title in official.get("clips") or []:
        docs.append({"kind": "clip", "source": "tvn-clip", "title": title,
                     "snippet": "", "url": "", "query": "", "ts": 0})

    queries = build_queries(program)
    for query in queries["news"]:
        try:
            docs.extend(search_google_news(query))
        except Exception as exc:
            errors.append("구글 뉴스 실패(%s): %s" % (query, exc))
    for query in queries["web"]:
        try:
            docs.extend(search_daum(query))
        except Exception as exc:
            errors.append("Daum 검색 실패(%s): %s" % (query, exc))
    for seed in queries["autocomplete"]:
        try:
            for phrase in naver_autocomplete(seed):
                docs.append({"kind": "autocomplete", "source": "naver-ac", "title": phrase,
                             "snippet": "", "url": "", "query": seed, "ts": 0})
        except Exception as exc:
            errors.append("네이버 자동완성 실패(%s): %s" % (seed, exc))
    return docs, errors


# ------------------------------------------------------------------ 추출기


def extract_keywords(program, docs, official=None, top_n=18):
    official = official or {}
    title = (program.get("title") or "").strip()
    name = short_title(program.get("programName") or title)
    title_tokens = {strip_josa(t) for t in TOKEN_RE.findall(title + " " + name)}
    air_ts = program.get("startTs") or 0

    scores = defaultdict(float)
    kinds = defaultdict(set)
    evidence = defaultdict(list)

    # 1) 공식 자료의 강조 표기 — 가장 신뢰도가 높습니다.
    official_lines = list(official.get("preview") or []) + list(official.get("clips") or [])
    emphasized = set()
    for phrase in extract_emphasis(official_lines):
        if phrase and phrase not in title_tokens:
            emphasized.add(phrase)
            scores[phrase] += KIND_WEIGHT["preview"] + EMPHASIS_BONUS
            kinds[phrase].add("preview")

    # 2) 문서별 n-gram
    for doc in docs:
        kind = doc.get("kind", "web")
        weight = KIND_WEIGHT.get(kind, 1.0)
        if kind == "news" and air_ts and doc.get("ts"):
            gap_days = abs(doc["ts"] - air_ts) / 86400.0
            if gap_days > NEWS_WINDOW_DAYS:
                weight *= 0.4          # 다른 회차 기사일 가능성이 큽니다.
        if kind == "clip" and official.get("ppl"):
            weight += PPL_BONUS

        text = (doc.get("title", "") + " " + doc.get("snippet", "")).strip()
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
                    if phrase == title or phrase == name:
                        continue
                    gain = weight * (1.0 + 0.25 * (n - 1))
                    if has_cue:
                        gain += 0.8
                    scores[phrase] += gain
                    kinds[phrase].add(kind)
                    if doc.get("title") and len(evidence[phrase]) < 3:
                        evidence[phrase].append({
                            "text": doc["title"][:120], "url": doc.get("url", ""),
                            "source": doc.get("source", ""),
                        })

    # 3) 검색광고에서 배운 (앞말 + 상품어)
    for doc in docs:
        if doc.get("kind") != "ad":
            continue
        parsed = split_commerce_keyword(doc.get("title", ""))
        if parsed:
            phrase = "%s %s" % parsed
            scores[phrase] = max(scores[phrase], KIND_WEIGHT["ad"] + 4.0)
            kinds[phrase].add("ad")

    # 4) 교차 검증 · 상품어 가산
    results = []
    for phrase, base in scores.items():
        toks = phrase.split()
        cat = categorize(phrase)
        score = base

        cross = len(kinds[phrase])
        score += CROSS_BONUS * (cross - 1)          # 여러 자료에서 확인될수록 크게 올림

        if cat:
            score += PRODUCT_TAIL_BONUS if ends_with_product(phrase) else PRODUCT_IN_BONUS
        if phrase in emphasized:
            cat = cat or "기타"
        if len(toks) == 1 and phrase in PRODUCT_TERMS:
            score *= 0.55                            # '모자' 처럼 너무 넓은 말
        if all(t in title_tokens for t in toks):
            score *= 0.3
        if len(toks) >= 2:
            score += 1.0
        # 공식 자료에도 없고 상품어도 아니고 한 곳에서만 나온 말은 버립니다.
        if cross <= 1 and not cat and not (kinds[phrase] & {"preview", "clip"}):
            continue
        results.append((phrase, score, cat, sorted(kinds[phrase])))

    results.sort(key=lambda x: -x[1])

    kept = []
    for phrase, score, cat, ks in results:
        if any(phrase in k and score <= s * 1.6 for k, s, _, _ in kept):
            continue
        kept.append((phrase, score, cat, ks))
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
            "shoppable": bool(cat and cat != "기타"),
            "kinds": ks,
            "crossChecked": len(ks) >= 2,
            "official": bool(set(ks) & {"preview", "clip"}),
            "sources": ks,
            "evidence": evidence.get(phrase, []),
            "demandChecked": False,
            "demand": [],
        }
        for phrase, score, cat, ks in kept
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


def analyze_program(program, verify=True, official=None):
    official = official or {}
    docs, errors = collect_documents(program, official)
    keywords = extract_keywords(program, docs, official)
    if verify:
        keywords = verify_demand(keywords)
    counts = defaultdict(int)
    for doc in docs:
        counts[doc.get("kind", "web")] += 1
    return {
        "keywords": keywords,
        "docCount": len(docs),
        "docCounts": dict(counts),
        "queries": build_queries(program)["news"] + build_queries(program)["web"],
        "errors": errors,
        "documents": [
            {k: d.get(k) for k in ("source", "kind", "title", "url")} for d in docs[:40]
        ],
    }
