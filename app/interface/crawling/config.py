"""
크롤러 설정 및 크롤링 규칙 정의
"""

# ========================================
# 크롤링 규칙 (CRAWL_RULES)
# ========================================
# 여러 보건소 사이트의 LNB 구조에 대응하는 규칙 목록
#
# 'name':         규칙의 이름 (로그에 표시됨)
# 'domain':       적용할 도메인 키워드
# 'single_page':  단일 페이지에서 모든 메뉴를 수집할지 여부
# 'filter_menu':  특정 메뉴만 필터링 (single_page=True일 때)
# 'menu_container': 메뉴 컨테이너 선택자 (single_page=True일 때)
# 'main_selector': 1단계 메인 메뉴 링크를 찾는 CSS 선택자
# 'sub_selector':  하위 메뉴 링크를 찾는 CSS 선택자

CRAWL_RULES = [
    {
        "name": "동작구 건강관리청 LNB",
        "domain": "dongjak",
        "main_selector": ".left-area .left-mdp1 > li > a",
        "sub_selector": [
            ".left-mdp1 > li.on > ul > li > a",
            ".tab-list li a",
        ],
    },
    {
        "name": "강남구보건소 LNB",
        "domain": "gangnam",
        "main_selector": ".left_menu_list > .oneDepth > a",
        "sub_selector": [
            ".oneDepth.active .twoDepth .oneDepth a",
            ".tabmenu ul li a",
        ],
    },
    {
        "name": "강동구 보건소 LNB",
        "domain": "gangdong",
        "single_page": True,
        "filter_menu": "보건사업",
        "menu_container": ".gnb",
        "main_selector": ".depth-02 > li > a",
        "sub_selector": "ul > li > a",
    },
    {
        "name": "강북구 보건소 LNB",
        "domain": "gangbuk",
        "main_selector": ".lnb nav > ul > li > a",
        "sub_selector": ".lnb nav > ul > li.on > ul > li > a",
    },
    {
        "name": "강서구 보건소 LNB",
        "domain": "gangseo",
        "single_page": True,
        "menu_container": ".lnb-wrap",
        "main_selector": ".lnb-menu > li > a",
        "sub_selector": "ul > li > a",
    },
    {
        "name": "관악구 보건소 LNB",
        "domain": "gwanak",
        "filter_menu": "사업안내",
        "main_selector": "#snav nav > .dep1 > li > a",
        "sub_selector": "#snav .dep1 > li.on .dep2 > li > a",
    },
    {
        "name": "광진구 보건소 LNB",
        "domain": "gwangjin",
        "main_selector": "nav.lnb > ul > li > a",
        "sub_selector": "nav.lnb > ul > li.on > div > ul > li > a",
    },
    {
        "name": "노원구 보건소 LNB",
        "domain": "nowon",
        "main_selector": ".sidebar-inner > ul > li > a",
        "sub_selector": ".sidebar-inner > ul > li.active > ul > li > a",
    },
    {
        "name": "종로구 보건소 LNB",
        "domain": "jongno",
        "single_page": True,
        "menu_container": ".lnb-wrap",
        "main_selector": ".lnb-depth1 > li > a.btn.btn-toggle",
        "sub_selector": ".lnb-depth2 > li > a.btn",
    },
    {
        "name": "용산구 보건소 LNB",
        "domain": "yongsan",
        "main_selector": "nav.lnb a",
        "sub_selector": "null",
    },
    {
        "name": "중구 보건소 LNB",
        "domain": "junggu",
        "main_selector": "div.lnb_area a[href!='#none']",
        "sub_selector": "null",
    },
]

# ========================================
# 탭 메뉴 선택자
# ========================================
# 페이지 내부의 탭 메뉴를 찾는 데 사용할 CSS 선택자 목록
TAB_SELECTORS = [
    ".tabmenu ul li a",  # 강남구 등
    ".tab-list li a",  # 동작구
    ".nw-tab-bx .nw-tab-ls > li > p > a",  # 추가 탭 패턴
]

# ========================================
# HTTP 설정
# ========================================
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
)
DEFAULT_TIMEOUT = 15  # 초
DEFAULT_DELAY = 1  # 요청 간 지연 시간 (초)
RATE_LIMIT_DELAY = 0.5  # Rate limiting 지연 시간 (초)

# ========================================
# 사이트별 특수 설정
# ========================================
# 특정 사이트에 필요한 쿠키, SSL 설정 등
SITE_SPECIFIC_CONFIGS = {
    "gangbuk": {
        "cookies": {
            "sabFingerPrint": "1920,1080,www.gangbuk.go.kr",
            "sabSignature": "f3m9iqAXBBmHE38diIuA0A==",
        },
        "verify_ssl": True,
    },
    "gangseo": {
        "verify_ssl": False,
        "disable_ssl_warnings": True,
    },
}

# ========================================
# 출력 설정
# ========================================
DEFAULT_OUTPUT_DIR = "crawling/output"

# ========================================
# e보건소 설정
# ========================================
EHEALTH_CATEGORIES = {
    "건강증진": {"bbsSeCd": "Z1", "menuId": "200035"},
    "질병관리": {"bbsSeCd": "Z2", "menuId": "200036"},
    "암관리": {"bbsSeCd": "Z3", "menuId": "200037"},
    "구강보건": {"bbsSeCd": "Z4", "menuId": "200038"},
    "정신보건": {"bbsSeCd": "Z5", "menuId": "200039"},
    "가족건강": {"bbsSeCd": "Z6", "menuId": "200040"},
    "한의약": {"bbsSeCd": "Z7", "menuId": "200041"},
    "방문건강관리": {"bbsSeCd": "Z8", "menuId": "200091"},
}

EHEALTH_BASE_URL = "https://www.e-health.go.kr"
EHEALTH_BBS_ID = "U00322"
