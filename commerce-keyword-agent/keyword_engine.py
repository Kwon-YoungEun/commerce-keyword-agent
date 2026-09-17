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
import math
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
        분말 티백 육포 어묵 두부 계란 우유 요거트 치즈 수프 크림수프 디저트 케이크 꼬치 족발 순대
        바지락 꼬막 가리비 소라 다슬기 우럭 광어 방어 대게 꽃게 갈치 고등어 삼치 명태 코다리 황태
        막국수 냉면 국밥 찌개 전골 구이 볶음 조림 튀김 탕수육 짬뽕 짜장 초밥 회 물회 매운탕
        약과 정과 유과 강정 젤리 아이스크림 마카롱 크로플 도넛 샌드위치 버거 피자 파스타""".split(),
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

# 교양·건강 프로그램에서 소개하는 성분·재료. 방송 뒤 이 이름으로 검색하고
# 사서 먹기 때문에 그 자체가 화제 상품입니다. '모자' 처럼 넓은 말이 아니라
# 이름 하나로 상품이 특정되므로, 단독으로 나와도 깎지 않습니다.
INGREDIENT_TERMS = """
    폴리코사놀 루테인 오메가 오메가3 프로바이오틱스 포스트바이오틱스 유산균 콜라겐 매스틱
    비타민 마그네슘 칼슘 아연 셀레늄 밀크씨슬 크릴오일 코엔자임 글루코사민 히알루론산
    아르기닌 타우린 아미노산 단백질 식이섬유 미네랄 항산화 폴리페놀 안토시아닌 레스베라트롤
    커큐민 카테킨 프로폴리스 보스웰리아 쏘팔메토 아스타잔틴 스피룰리나 클로렐라 모링가
    녹용 흑삼 아슈와간다 노니 아사이 구기자 복분자 아로니아
    파로 퀴노아 렌틸 렌틸콩 귀리 오트밀 치아씨드 아마씨 햄프씨드 병아리콩 통곡물 고대곡물
    효소 소화효소 낫토 케피어 콤부차 발효액 식초 비니거 올리브유 아보카도오일 들깨 참깨
    베리 블루베리 아사이베리 크랜베리 라즈베리 하스카프베리 빌베리 c3g 안토시아닌
    양파 배추 우엉 마늘 생강 강황 양배추 브로콜리 케일 시금치 토마토 당근 호박 연근 도토리
    주꾸미 성게 멍게 해삼 골뱅이 다슬기 미더덕 톳 파래 매생이 감태 함초
    차돌박이 우설 도가니 곱창 막창 등심 목살 항정살 갈매기살
    유자 유자차 모과 오미자 도라지청 배즙 흑마늘 개똥쑥 산양삼 침향
""".split()

PRODUCT_TERMS = {}
for _cat, _words in CATEGORY_TERMS.items():
    for _w in _words:
        PRODUCT_TERMS.setdefault(_w, _cat)
for _w in INGREDIENT_TERMS:
    PRODUCT_TERMS.setdefault(_w, "식품")

INGREDIENT_SET = set(INGREDIENT_TERMS)

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
    재방송 본방송 몇시 시청방법 편성시간 모음 정리본 유료광고포함 유료광고 highlight shorts
    있는 없는 하는 되는 같은 나오는 들어간 품은 감싸 하시 거예요 이런 저런 그런 지금 여기 거기
    지구급 극강 화려한 시끌벅적 유쾌한 부드러움 감칠맛 맛으 향긋한 폭발 매콤새콤
    무조건 필수 전용 저녁 아침 점심 새벽 인분 겉바속촉 오픈 역대급 최애 강추 대박 실화
    퍼포먼스 답변들 찐친 찐맛 개꿀 꿀조합 레전드 소문 정체 비법 공개된
    셰프 요리사 사장님 게스트 멤버 출연자 진행자 심사위원 패널 제작진 스태프
    맛집 식당 공방 법정 현장 스튜디오 특집 예고편 비하인드 메이킹 풀버전 미방분
    리액션 티저 쇼츠 클립 편집본 몰아보기 명장면 짤방
    with and the for of vs zip ep feat part full sub eng ver open new best
    official mix live special edition""".split()
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
    "youtube": 4.5,       # 유튜브 검색 결과 제목(회차로 검색, 조회수로 가중)
    "ad": 4.0,            # 검색광고 키워드
    "news": 3.0,          # 구글 뉴스 제목
    "autocomplete": 2.5,  # 네이버 자동완성
    "web": 1.2,           # 그 밖의 웹문서
}
CROSS_BONUS = 7.0       # 서로 다른 자료에서 또 확인될 때마다
EMPHASIS_BONUS = 14.0   # 공식 자료에서 따옴표 등으로 강조된 말 = 사실상 정답
PRODUCT_TAIL_BONUS = 8.0
PRODUCT_IN_BONUS = 5.0
NON_PRODUCT_PENALTY = 0.22   # 상품으로 볼 수 없는 말은 크게 낮춥니다.
PPL_BONUS = 3.0
NEWS_WINDOW_DAYS = 10   # 방송일에서 이만큼 떨어진 기사는 낮게 봅니다.


def short_title(title):
    """'언니네 산지직송3 - 네 식구 산지 라이프' 처럼 부제가 붙은 제목을 앞부분만 남깁니다."""
    out = re.split(r"\s+[-–—:]\s+", (title or "").strip())[0].strip()
    return out or (title or "").strip()


def norm_compact(text):
    return re.sub(r"\s+", "", text or "")


MATCH_KEY_RE = re.compile(r"[^가-힣0-9a-zA-Z]")


def match_key(text):
    """제목·채널 비교용 — 공백과 기호를 모두 지웁니다."""
    return MATCH_KEY_RE.sub("", text or "").lower()


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


VIEW_COUNT_RE = re.compile(r"([\d,]+)")


def _parse_views(text):
    """'조회수 79,226회' → 79226"""
    m = VIEW_COUNT_RE.search(text or "")
    if not m:
        return 0
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return 0


def view_weight(views):
    """조회수가 많을수록 화제도가 높다고 봅니다(로그로 완만하게)."""
    if views <= 0:
        return 1.0
    return 1.0 + min(0.8, math.log10(views) / 6.0)


# tvN 은 영상 제목에 'EP.6' 을 꼬박 답니다. '6화 예고', '7회' 표기도 함께 봅니다.
EPISODE_MARK_RE = re.compile(r"ep\s*\.?\s*(\d{1,4})|(\d{1,4})\s*[회화]", re.I)
PUBLISHED_RE = re.compile(r"(\d+)\s*(초|분|시간|일|주|개월|년)")
PUBLISHED_UNIT_DAYS = {"초": 0, "분": 0, "시간": 0, "일": 1, "주": 7, "개월": 30, "년": 365}


def episode_numbers(text):
    """제목에 적힌 회차 번호를 모두 뽑습니다."""
    found = set()
    for a, b in EPISODE_MARK_RE.findall(text or ""):
        num = a or b
        if num:
            found.add(int(num))
    return found


def published_days_ago(text):
    """'10일 전', '2주 전', '8개월 전' → 며칠 전인지. 못 읽으면 None."""
    m = PUBLISHED_RE.search(text or "")
    if not m:
        return None
    return int(m.group(1)) * PUBLISHED_UNIT_DAYS.get(m.group(2), 0)


def in_age_window(age, min_days, max_days, strict):
    """방송 무렵에 올라온 영상인지. strict 면 시점을 모르는 영상은 버립니다."""
    if age is None:
        return not strict
    if max_days is not None and age > max_days:
        return False
    if min_days is not None and age < min_days:
        return False
    return True


def search_youtube(query, program_keys=(), limit=12, episode_no=None,
                   min_age_days=None, max_age_days=None):
    """유튜브 검색 — 키 없이 검색 페이지의 ytInitialData 를 읽습니다.

    program_keys 에 프로그램명(띄어쓰기 제거)을 넘기면, 제목이나 채널에 그 말이
    들어간 영상만 남깁니다. 검색 결과에는 무관한 프로그램이 섞여 들어옵니다.

    검색어에 회차를 넣어도 유튜브는 다른 회차를 함께 돌려줍니다. 그래서
    episode_no 를 넘기면 제목의 회차 표기로 한 번 더 거르고, 표기가 없는 영상은
    방송 무렵(min_age_days ~ max_age_days)에 올라온 것만 남깁니다. 이 회차보다
    나중에 올라온 영상은 대개 다음 회차 것이라 아래쪽 경계도 함께 봅니다.
    """
    url = ("https://www.youtube.com/results?search_query=%s&hl=ko&gl=KR"
           % urllib.parse.quote(query))
    body = _fetch(url, timeout=20)
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", body, re.S)
    if not m:
        return []
    data = json.loads(m.group(1))

    found = []

    def walk(node):
        if len(found) >= limit * 3:
            return
        if isinstance(node, dict):
            vr = node.get("videoRenderer")
            if isinstance(vr, dict):
                runs = (vr.get("title") or {}).get("runs") or []
                title = "".join(r.get("text", "") for r in runs).strip()
                if title:
                    thumbs = ((vr.get("thumbnail") or {}).get("thumbnails") or [])
                    found.append({
                        "title": title,
                        "channel": (((vr.get("ownerText") or {}).get("runs") or [{}])[0]
                                    .get("text", "")),
                        "views": _parse_views(
                            (vr.get("viewCountText") or {}).get("simpleText", "")),
                        "published": (vr.get("publishedTimeText") or {}).get("simpleText", ""),
                        "videoId": vr.get("videoId", ""),
                        # 검색 결과에 붙어 오는 서명 주소는 다른 곳에서 열리지 않아
                        # 영상 번호로 만든 고정 주소를 씁니다.
                        "thumb": ("https://i.ytimg.com/vi/%s/mqdefault.jpg" % vr["videoId"]
                                  if vr.get("videoId")
                                  else (thumbs[-1]["url"] if thumbs else "")),
                    })
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)

    docs = []
    for item in found:
        haystack = match_key(item["title"] + " " + item["channel"])
        if program_keys and not any(k and k in haystack for k in program_keys):
            continue                      # 무관한 프로그램 영상은 버립니다.

        age = published_days_ago(item["published"])
        title_eps = episode_numbers(item["title"])
        if title_eps and episode_no:
            if episode_no not in title_eps:
                continue                  # 다른 회차 영상입니다.
        elif not in_age_window(age, min_age_days, max_age_days, strict=bool(episode_no)):
            continue                      # 회차 표기가 없으면 올라온 시점으로 봅니다.

        docs.append({
            "kind": "youtube", "source": "youtube", "title": item["title"],
            "snippet": "", "url": "https://www.youtube.com/watch?v=" + item["videoId"],
            "query": query, "ts": 0,
            "views": item["views"], "thumb": item["thumb"],
            "channel": item["channel"], "published": item["published"],
        })
        if len(docs) >= limit:
            break
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


# ------------------------------------------------------- 네이버 쇼핑 상품 조회
#
# 플러스스토어(search.shopping.naver.com)는 페이지도 내부 API 도 막혀 있어서
# (405 / 418) 통합검색 쇼핑탭을 대신 읽습니다. 같은 네이버 쇼핑 상품이지만
# 정렬은 플러스스토어 화면과 다를 수 있습니다.

MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile Safari/604.1")
CARD_START_RE = re.compile(r'\{"cardType"')
MARK_TAG_RE = re.compile(r"</?mark>")


def _slice_json_object(text, start):
    """text[start] 의 '{' 와 짝이 맞는 '}' 까지 잘라 냅니다."""
    depth, in_str, esc = 0, False, False
    for i in range(start, min(len(text), start + 300000)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def search_shopping(keyword, limit=16):
    """검색어로 네이버 쇼핑 상품을 가져옵니다."""
    url = ("https://m.search.naver.com/search.naver?where=m_shop&query="
           + urllib.parse.quote(keyword))
    body = _fetch(url, headers={"User-Agent": MOBILE_UA,
                                "Accept-Language": "ko-KR,ko;q=0.9"}, timeout=20)

    products, seen = [], set()
    for match in CARD_START_RE.finditer(body):
        raw = _slice_json_object(body, match.start())
        if not raw:
            continue
        try:
            # 화면 코드라 값이 undefined 로 비어 있는 자리가 있습니다.
            card = json.loads(raw.replace(":undefined", ":null"))
        except Exception:
            continue

        name = MARK_TAG_RE.sub("", card.get("productName") or "").strip()
        if not name:
            continue
        key = norm_compact(name)
        if key in seen:
            continue
        seen.add(key)

        images = card.get("images") or []
        image = (images[0].get("imageUrl") if images else "") or card.get("imageUrl") or ""
        products.append({
            "name": name,
            "price": card.get("discountedSalePrice") or card.get("salePrice") or 0,
            "mall": (card.get("mallName") or "").strip(),
            "image": image,
            "reviewCount": card.get("totalReviewCount") or 0,
            "reviewScore": card.get("averageReviewScore") or 0,
            "mallCount": card.get("mallCount") or 0,
            "isAd": card.get("sourceType") == "AD",
            "url": ((card.get("productClickUrl") or {}).get("mobileUrl")
                    or (card.get("productClickUrl") or {}).get("pcUrl") or ""),
        })
        if len(products) >= limit:
            break
    return products


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
    # 영어는 제목마다 대소문자가 달라서 소문자로도 맞춰 봅니다.
    if tok in STOPWORDS or tok.lower() in STOPWORDS or tok.isdigit():
        return True
    if HANGUL_RE.search(tok):
        return len(tok) < 2
    return len(tok) < 3


def categorize(phrase):
    """상품어 사전과 맞춰 봅니다.

    '재첩전', '가브리살수육', '재첩크림수프' 처럼 상품어가 말 안쪽에 섞여 있는
    경우가 많아, 두 글자 이상 상품어는 포함 여부까지 봅니다.
    """
    tokens = phrase.split()
    for token in tokens:
        cat = PRODUCT_TERMS.get(token)
        if cat:
            return cat
    for token in tokens:
        for word in SPLITTABLE_TERMS:
            if len(token) > len(word) and token.endswith(word):
                return PRODUCT_TERMS[word]
    # 글자 한가운데 우연히 들어간 말은 보지 않습니다. 한국어 합성어는 앞뒤로
    # 붙지 가운데에 끼지 않습니다. '하스카프베리' 가 '스카프' 때문에 패션으로,
    # '레드와인비니거' 가 '비니' 때문에 패션으로 잡히던 문제입니다.
    for token in tokens:
        if len(token) < 3:
            continue
        for word in SPLITTABLE_TERMS:
            if len(word) >= 2 and token.startswith(word):
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


# '함께한 끝이라면', '만든 짬뽕' 처럼 꾸밈말로 시작하는 조각을 걸러냅니다.
MODIFIER_HEAD_RE = re.compile(r"^.{1,3}(한|든|는|운|린|던|워|해|인|은)$")


# '끝이라면' 의 '라면', '갔더라고' 처럼 어미가 상품어로 잡히는 경우를 막습니다.
SENTENCE_TAIL_RE = re.compile(r"(이라면|이라고|라니까|더라고|던데요|거든요|잖아요|네요|군요)$")


def looks_like_fragment(tokens):
    """'만든 크림수프', '끓인 정아표 수프' 처럼 꾸밈말로 시작하는 토막인지.

    상품어 자체가 그렇게 끝나는 경우('곤약', '수박'은 아니지만 만일을 대비)는
    빼고 봅니다.
    """
    if not tokens:
        return False
    head = tokens[0]
    if head in PRODUCT_TERMS:
        return False
    return bool(MODIFIER_HEAD_RE.match(head))


# 따옴표 안이라도 대사·감탄사는 상품이 아닙니다.
SPEECH_TAIL_RE = re.compile(r"(요|다|야|죠|네|까|군|잖아|는데|던데|았어|었어|해요|예요|이에요)$")
SPEECH_NOISE_RE = re.compile(r"[ㄱ-ㅎㅏ-ㅣ]|(.)\1{2,}")


def looks_like_speech(text):
    """'미쿡 왔어요 제니카예요', '으아아아아악' 같은 대사·감탄사인지."""
    compact = norm_compact(text)
    if not compact:
        return True
    if SPEECH_NOISE_RE.search(compact):
        return True
    last = text.split()[-1] if text.split() else ""
    return bool(SPEECH_TAIL_RE.search(last))


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
                    if looks_like_speech(piece):
                        continue
                    toks = [strip_josa(t) for t in TOKEN_RE.findall(piece)]
                    toks = [t for t in toks if not is_bad_token(t)]
                    if toks and len(toks) <= 3:
                        found.append(" ".join(toks))
    return found


# ------------------------------------------------------------------ 수집


def episode_number(episode):
    """'7회' → 7. 회차를 모르면 None."""
    m = re.search(r"(\d{1,4})", episode or "")
    return int(m.group(1)) if m else None


# 장르마다 화제 상품의 성격이 달라서 검색어도 달라야 합니다.
#
#   예능 — 먹거리·체험이 미리보기에 그대로 나옵니다.
#   드라마 — 상품이 PPL(의상·소품)이고 블로그에 정리돼 있습니다.
#            '나온 상품 구매' 로는 0건, '소품 협찬' 으로는 4/6 이 걸렸습니다.
#   교양 — 방송에서 소개한 식품·성분입니다. '방송 식품' 이 가장 잘 맞습니다.
GENRE_QUERIES = {
    "드라마": ["{name} 소품 협찬", "{name} 착용 의상", "{name} 협찬 제품"],
    "교양": ["{name} 방송 식품", "{name} 소개 제품"],
}
DRAMA_LIKE = ("드라마", "브랜디드")
DOCUMENTARY_LIKE = ("교양", "시사", "다큐", "정보")


def genre_bucket(genre):
    text = genre or ""
    if any(word in text for word in DRAMA_LIKE):
        return "드라마"
    if any(word in text for word in DOCUMENTARY_LIKE):
        return "교양"
    return ""


def build_queries(program, official=None):
    """소스마다, 장르마다 잘 맞는 검색어가 다릅니다.

    뉴스   — 회차 번호를 쓰면 결과가 0건이라 프로그램명으로 찾고 방송일로 거릅니다.
    유튜브 — 회차별 클립이 올라와서 '프로그램명 + 회차' 가 가장 정확합니다.
    검색광고·웹문서 — 장르에 맞는 말을 붙여야 관련 글이 걸립니다.
    """
    official = official or {}
    name = short_title(program.get("programName") or program.get("title") or "")
    episode = (program.get("episode") or "").strip()
    cast = [c for c in (official.get("cast") or []) if c][:1]

    news = [name]
    if cast:
        news.append(f"{name} {cast[0]}")

    episode_no = episode_number(episode)
    youtube = []
    if episode:
        youtube.append(f"{name} {episode}")
    if episode_no:
        youtube.append(f"{name} EP.{episode_no}")   # tvN 공식 채널 표기
    else:
        youtube.append(f"{name} 하이라이트")

    autocomplete = [name, name + " 협찬"]
    if episode:
        autocomplete.append(f"{name} {episode}")

    bucket = genre_bucket(program.get("genre"))
    ad = [q.format(name=name) for q in
          GENRE_QUERIES.get(bucket, ["{name} 협찬 제품", "{name} 나온 상품 구매"])]
    # 교양은 회차별로 정리한 글이 있어 회차를 붙이면 잘 걸립니다.
    if bucket == "교양" and episode:
        ad.append(f"{name} {episode}")

    return {
        "news": news,
        "youtube": youtube,
        "ad": ad,
        "autocomplete": autocomplete,
    }


def collect_documents(program, official=None):
    """공식 자료 + 뉴스 + 검색광고 + 자동완성을 한데 모읍니다."""
    official = official or {}
    docs, errors = [], []

    for line in official.get("preview") or []:
        docs.append({"kind": "preview", "source": "tvn-preview", "title": line,
                     "snippet": "", "url": "", "query": "", "ts": 0})
    for clip in official.get("clips") or []:
        if isinstance(clip, str):
            clip = {"title": clip}
        docs.append({"kind": "clip", "source": "tvn-clip", "title": clip.get("title", ""),
                     "snippet": "", "url": clip.get("url", ""), "query": "", "ts": 0,
                     "thumb": clip.get("thumb", "")})

    name = short_title(program.get("programName") or program.get("title") or "")
    # 시즌 번호까지 그대로 맞춥니다. 번호를 떼면 시즌1의 같은 회차 영상
    # ('언니네산지직송 EP.7')이 함께 걸립니다.
    program_keys = {k for k in {match_key(name)} if len(k) >= 3}

    # 이 회차 방송일을 기준으로, 그 무렵에 올라온 영상만 봅니다.
    episode_no = episode_number(program.get("episode"))
    air_ts = program.get("startTs") or 0
    if air_ts:
        days_since_air = max(0.0, (time.time() - air_ts) / 86400.0)
        max_age_days = days_since_air + 6      # 예고 영상은 방송 며칠 전에 올라옵니다
        min_age_days = max(0.0, days_since_air - 5)   # 더 최근 것은 다음 회차입니다
    else:
        max_age_days, min_age_days = 45, None  # 방송일을 모르면 넉넉하게 봅니다

    queries = build_queries(program, official)
    for query in queries["news"]:
        try:
            docs.extend(search_google_news(query))
        except Exception as exc:
            errors.append("구글 뉴스 실패(%s): %s" % (query, exc))
    for query in queries["youtube"]:
        try:
            docs.extend(search_youtube(query, program_keys,
                                       episode_no=episode_no,
                                       min_age_days=min_age_days,
                                       max_age_days=max_age_days))
        except Exception as exc:
            errors.append("유튜브 검색 실패(%s): %s" % (query, exc))
    # 웹문서는 검색어만 보고 아무 글이나 걸려 옵니다. 실제로 '슈퍼푸드의 힘
    # 나온 상품 구매' 로는 6건 모두 무관한 글(코스트코 수분크림 등)이었습니다.
    # 유튜브처럼 프로그램 이름이 들어간 글만 남깁니다. 웹문서는 시즌 번호를
    # 빼고 쓰는 경우가 많아 번호를 뗀 이름도 함께 봅니다.
    web_keys = {k for k in (match_key(name), match_key(re.sub(r"\d+$", "", name)))
                if len(k) >= 3}
    for query in queries["ad"]:
        try:
            for doc in search_daum(query):
                if doc.get("kind") == "web":
                    haystack = match_key(doc.get("title", "") + " " + doc.get("snippet", ""))
                    if not any(k in haystack for k in web_keys):
                        continue
                docs.append(doc)
        except Exception as exc:
            errors.append("Daum 검색 실패(%s): %s" % (query, exc))
    for seed in queries["autocomplete"]:
        try:
            for phrase in naver_autocomplete(seed):
                docs.append({"kind": "autocomplete", "source": "naver-ac", "title": phrase,
                             "snippet": "", "url": "", "query": seed, "ts": 0})
        except Exception as exc:
            errors.append("네이버 자동완성 실패(%s): %s" % (seed, exc))
    # 검색어가 겹쳐 같은 영상이 두 번 오고, 가로 영상과 쇼츠가 같은 제목으로
    # 따로 올라오기도 합니다. 둘 다 한 번만 셉니다.
    seen, unique = set(), []
    for doc in docs:
        if doc.get("kind") == "youtube":
            key = doc.get("url") or ""
            title_key = match_key(doc.get("title", ""))
            if key in seen or (title_key and title_key in seen):
                continue
            seen.add(key)
            seen.add(title_key)
        unique.append(doc)
    return unique, errors


# ------------------------------------------------------------------ 추출기


def extract_keywords(program, docs, official=None, top_n=18):
    official = official or {}
    title = (program.get("title") or "").strip()
    name = short_title(program.get("programName") or title)
    title_tokens = {strip_josa(t) for t in TOKEN_RE.findall(title + " " + name)}
    # 시청자들이 쓰는 프로그램 줄임말(놀라운 토요일 → 놀토)도 상품이 아닙니다.
    name_parts = [t for t in re.split(r"\s+", re.sub(r"[^가-힣0-9a-zA-Z ]", " ", name)) if t]
    if len(name_parts) >= 2:
        abbrev = "".join(part[0] for part in name_parts)
        if len(abbrev) >= 2:
            title_tokens.add(abbrev)
    air_ts = program.get("startTs") or 0
    # 출연진 이름은 그 자체로는 살 수 없는 말이라 단독으로는 빼고,
    # '염정아 모자' 처럼 상품어와 붙은 것만 남깁니다.
    cast_names = {c.strip() for c in (official.get("cast") or []) if c and c.strip()}
    bucket = genre_bucket(program.get("genre"))

    scores = defaultdict(float)
    kinds = defaultdict(set)
    evidence = defaultdict(list)
    doc_hits = defaultdict(set)      # 몇 건의 문서에서 나왔는지

    # 1) 공식 자료의 강조 표기 — 가장 신뢰도가 높습니다.
    official_lines = list(official.get("preview") or []) + [
        (c.get("title") if isinstance(c, dict) else c) or ""
        for c in (official.get("clips") or [])
    ]
    emphasized = set()
    for phrase in extract_emphasis(official_lines):
        if phrase and phrase not in title_tokens:
            emphasized.add(phrase)
            scores[phrase] += KIND_WEIGHT["preview"] + EMPHASIS_BONUS
            kinds[phrase].add("preview")

    # 2) 문서별 n-gram
    for doc_no, doc in enumerate(docs):
        kind = doc.get("kind", "web")
        weight = KIND_WEIGHT.get(kind, 1.0)
        if kind == "news":
            if air_ts and doc.get("ts"):
                gap_days = abs(doc["ts"] - air_ts) / 86400.0
                if gap_days > NEWS_WINDOW_DAYS:
                    weight *= 0.4      # 다른 회차 기사일 가능성이 큽니다.
            # 교양 뉴스는 편성·출연·행사 소식뿐이라 상품이 거의 없습니다.
            # 실제로 수집한 30건 모두 프로그램 홍보 기사였습니다.
            if bucket == "교양":
                weight *= 0.35
        if kind == "clip" and official.get("ppl"):
            weight += PPL_BONUS
        if kind == "youtube":
            weight *= view_weight(doc.get("views", 0))   # 많이 본 영상일수록 화제

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
                    # 길이로 가산하지 않습니다. 가산하면 미리보기 문장에서
                    # '언니네 조업에 한계란 없다' 같은 줄이 통째로 잘려
                    # '언니네 조업 한계란' 이 '한계란' 을 밀어냅니다.
                    gain = weight
                    if has_cue:
                        gain += 0.8
                    scores[phrase] += gain
                    kinds[phrase].add(kind)
                    doc_hits[phrase].add(doc_no)
                    if doc.get("title") and len(evidence[phrase]) < 2:
                        evidence[phrase].append({
                            "text": doc["title"][:90], "url": doc.get("url", ""),
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
            if ends_with_product(phrase):
                score += PRODUCT_TAIL_BONUS
            elif len(toks) >= 3:
                continue          # '통닭 변신 무죄' 같은 문장 토막은 버립니다.
            else:
                score = score * 0.6 + PRODUCT_IN_BONUS
        # 교양에서는 성분 이름 하나로 상품이 특정되므로 깎지 않습니다. 깎으면
        # '콜라겐' 보다 '촬영 콜라겐' 이 위로 올라옵니다. 예능에서는 마늘·양파
        # 같은 흔한 재료가 주인공을 밀어내서 그대로 둡니다.
        if len(toks) == 1 and phrase in INGREDIENT_SET and bucket == "교양":
            score += 1.5          # '촬영 콜라겐' 보다 '콜라겐' 이 위로 오게
        elif len(toks) == 1 and phrase in PRODUCT_TERMS:
            score *= 0.55                            # '모자' 처럼 너무 넓은 말
        if all(t in title_tokens for t in toks):
            if not cat:
                continue                             # 프로그램명·줄임말 그 자체
            score *= 0.3
        # 어절 수로도 가산하지 않습니다. 같은 이유로 긴 조각이 이깁니다.

        # 출연진 이름만 있는 말, 대사로 보이는 말은 제외합니다.
        if toks and all(t in cast_names for t in toks):
            continue
        if looks_like_speech(phrase):
            continue
        # '만든 크림수프' 처럼 꾸밈말로 시작하는 말은 어디서 나왔든 상품명이 아닙니다.
        if looks_like_fragment(toks) or SENTENCE_TAIL_RE.search(phrase):
            continue
        # 검색 제목은 해시태그·감탄사가 섞여 긴 조각이 잘 생깁니다.
        # 공식 자료(미리보기·클립)에서 나온 게 아니면 두 어절까지만 인정합니다.
        official_seen = bool(kinds[phrase] & {"preview", "clip"})
        if not official_seen:
            if len(toks) >= 3:
                continue
            # 영상 제목 하나에만 스쳐 나온 말은 화제 상품으로 보기 어렵습니다.
            if kinds[phrase] == {"youtube"} and len(doc_hits[phrase]) < 2:
                continue
        if any(t in cast_names for t in toks) and cat:
            score += 4.0                             # '염정아 모자' 같은 조합은 우대

        # 상품으로 볼 수 없는 말은 크게 낮춥니다(사람·장소·일반어).
        if not cat:
            if phrase in emphasized:
                score *= 0.7
            else:
                score *= NON_PRODUCT_PENALTY

        # 공식 자료에도 없고 상품어도 아니고 한 곳에서만 나온 말은 버립니다.
        if cross <= 1 and not cat and not (kinds[phrase] & {"preview", "clip"}):
            continue
        results.append((phrase, score, cat, sorted(kinds[phrase])))

    # 상품으로 볼 수 있는 것을 먼저, 그 밖의 말은 뒤에 조금만 둡니다.
    results.sort(key=lambda x: (0 if x[2] else 1, -x[1]))

    kept, others, seen_keys = [], 0, set()
    for phrase, score, cat, ks in results:
        key = match_key(phrase)
        if key in seen_keys:          # 띄어쓰기만 다른 같은 말
            continue
        # 이미 뽑은 키워드를 감싸기만 한 긴 조각은 버립니다.
        # ('통닭' 을 뽑았으면 '맛으 수원 통닭' 은 문장 토막으로 봅니다)
        if any(phrase in k and score <= s * 1.6 for k, s, _, _ in kept):
            continue
        if any(k in phrase and score <= s for k, s, _, _ in kept):
            continue
        if not cat:
            # 상품어 사전에 없는 말은 한 자리만 둡니다. 어절 수 가산을 없앤
            # 뒤로 출연자 이름 같은 단독 고유명사가 그 자리를 차지합니다.
            if others >= 1:
                continue
            others += 1
        kept.append((phrase, score, cat, ks))
        seen_keys.add(key)
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
    gallery = []
    for doc in docs:
        if doc.get("thumb") and doc.get("kind") in ("clip", "youtube"):
            gallery.append({
                "title": doc.get("title", ""),
                "thumb": doc.get("thumb", ""),
                "url": doc.get("url", ""),
                "views": doc.get("views", 0),
                "published": doc.get("published", ""),
                "source": doc.get("kind"),
            })
    gallery.sort(key=lambda g: -(g.get("views") or 0))

    return {
        "keywords": keywords,
        "docCount": len(docs),
        "docCounts": dict(counts),
        "queries": build_queries(program, official),
        "gallery": gallery[:9],
        "errors": errors,
    }
