"""
통합 구별 크롤러 설정 (Strategy Pattern 버전)

각 구별 메뉴 수집 전략 클래스를 지정하고, 간단한 메타데이터만 관리
"""

from typing import Dict, Any
from .strategies import (
    EPStrategy,
    GangdongStrategy,
    GwanakStrategy,
    DDMStrategy,
    JongnoStrategy,
    JungnangStrategy,
    JungguStrategy,
    SDStrategy,
    YDPStrategy,
    YongsanStrategy,
)


# =============================================================================
# 전역 블랙리스트 키워드
# 모든 구에서 공통으로 필터링할 키워드
# =============================================================================
GLOBAL_BLACKLIST_KEYWORDS = {
    # 방역 관련
    "방역",
    "소독",
    "방역소독",
    # 자료/문서 관련
    "자료실",
    "사진",
    # 동물/반려동물 관련
    "동물",
    # 자원/인력 관련
    "자원",
    # 안내/정보 관련
    "안내",
    # 조사/통계 관련
    "조사",
    "통계",
    "현황",
    # 교육 관련
    "교육",
    # 도시/환경 관련
    "건강도시",
    "안전도시",
    # 행정 관련
    "추진",
    "수상",
    "단속",
    "과태료",
    "법령",
    # 기타
    "해외여행",
    "자동심장충격기",
    "야간휴일 의료비청구",
    "영·유아 손상기록시스템",
}

MAX_WORKERS_DEFAULT = 4

# =============================================================================
# 구별 설정 (Strategy Pattern)
# =============================================================================
DISTRICT_CONFIGS: Dict[str, Dict[str, Any]] = {
    "은평구": {
        "strategy_class": EPStrategy,
        "filter_text": "사업안내",
        "output_dir": "app/crawling/output/은평구",
        "max_workers": MAX_WORKERS_DEFAULT,
        "depth_scores": {2: 5000, 3: 10000, 4: 20000},  # 구체성 점수
    },
    "강동구": {
        "strategy_class": GangdongStrategy,
        "filter_text": "보건사업",
        "output_dir": "app/crawling/output/강동구",
        "max_workers": MAX_WORKERS_DEFAULT,
        "depth_scores": {1: 5000, 2: 10000, 3: 20000},
    },
    "관악구": {
        "strategy_class": GwanakStrategy,
        "output_dir": "app/crawling/output/관악구",
        "max_workers": MAX_WORKERS_DEFAULT,
        "depth_scores": {1: 5000, 2: 10000},
    },
    "동대문구": {
        "strategy_class": DDMStrategy,
        "filter_text": "보건사업",
        "output_dir": "app/crawling/output/동대문구",
        "max_workers": MAX_WORKERS_DEFAULT,
        "depth_scores": {1: 5000, 2: 10000, 3: 20000},
    },
    "종로구": {
        "strategy_class": JongnoStrategy,
        "filter_text": None,
        "output_dir": "app/crawling/output/종로구",
        "max_workers": MAX_WORKERS_DEFAULT,
        "depth_scores": {1: 5000, 2: 10000},
    },
    "중랑구": {
        "strategy_class": JungnangStrategy,
        "filter_text": None,
        "output_dir": "app/crawling/output/중랑구",
        "max_workers": MAX_WORKERS_DEFAULT,
        "depth_scores": {1: 5000, 2: 10000, 3: 20000},
    },
    "성동구": {
        "strategy_class": SDStrategy,
        "filter_text": "보건사업",
        "output_dir": "app/crawling/output/성동구",
        "max_workers": MAX_WORKERS_DEFAULT,
        "depth_scores": {2: 5000, 3: 10000, 4: 20000},
    },
    "영등포구": {
        "strategy_class": YDPStrategy,
        "filter_text": None,
        "output_dir": "app/crawling/output/영등포구",
        "max_workers": MAX_WORKERS_DEFAULT,
        "depth_scores": {1: 1000, 2: 5000, 3: 10000},
    },
    "용산구": {
        "strategy_class": YongsanStrategy,
        "filter_text": None,
        "output_dir": "app/crawling/output/용산구",
        "max_workers": MAX_WORKERS_DEFAULT,
        "depth_scores": {1: 5000, 2: 10000},
    },
    "중구": {
        "strategy_class": JungguStrategy,
        "filter_text": None,
        "output_dir": "app/crawling/output/중구",
        "max_workers": MAX_WORKERS_DEFAULT,
        "depth_scores": {1: 5000},
    },
}


def get_config(district_name: str) -> Dict[str, Any]:
    """
    구 이름으로 설정 가져오기

    Args:
        district_name: 구 이름 (예: "은평구", "강동구")

    Returns:
        해당 구의 설정 딕셔너리

    Raises:
        KeyError: 설정에 없는 구 이름인 경우
    """
    if district_name not in DISTRICT_CONFIGS:
        available = ", ".join(DISTRICT_CONFIGS.keys())
        raise KeyError(
            f"'{district_name}'에 대한 설정이 없습니다. 사용 가능한 구: {available}"
        )

    return DISTRICT_CONFIGS[district_name]


def get_all_districts() -> list:
    """모든 구 이름 목록 반환"""
    return list(DISTRICT_CONFIGS.keys())
