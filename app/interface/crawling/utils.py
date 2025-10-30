"""
크롤러 공통 유틸리티 함수
"""

from urllib.parse import urlparse, urljoin
from typing import Optional


def extract_region_from_url(url: str) -> str:
    """
    URL에서 지역명 추출

    Args:
        url: URL 문자열

    Returns:
        지역명 (예: "강남구", "동작구") 또는 "unknown"
    """
    region_mapping = {
        "gangnam": "강남구",
        "gangdong": "강동구",
        "gangbuk": "강북구",
        "gangseo": "강서구",
        "guro": "구로구",
        "gwanak": "관악구",
        "dongjak": "동작구",
        "gwangjin": "광진구",
        "nowon": "노원구",
        "jongno": "종로구",
        "yongsan": "용산구",
        "junggu": "중구",
    }

    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    for key, value in region_mapping.items():
        if key in domain:
            return value

    # 매핑 실패 시 도메인 첫 부분 반환
    return domain.split(".")[0] if "." in domain else "unknown"


def get_base_url(url: str) -> str:
    """
    URL에서 base URL 추출 (scheme + netloc)

    Args:
        url: 전체 URL

    Returns:
        base URL (예: "https://example.com")

    Raises:
        ValueError: 유효하지 않은 URL인 경우
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"유효하지 않은 URL: {url}")

    return f"{parsed.scheme}://{parsed.netloc}"


def make_absolute_url(url: str, base_url: str) -> str:
    """
    상대 URL을 절대 URL로 변환

    Args:
        url: 상대 또는 절대 URL
        base_url: 기준이 되는 base URL

    Returns:
        절대 URL
    """
    # 이미 절대 URL이면 그대로 반환
    if url.startswith("http"):
        return url

    return urljoin(base_url, url)
