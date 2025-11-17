"""
기본 메뉴 수집 전략 추상 클래스
"""

from abc import ABC, abstractmethod
from bs4 import BeautifulSoup
from typing import List, Dict
from urllib.parse import urljoin


class BaseMenuStrategy(ABC):
    """
    구별 메뉴 수집 전략 기본 클래스

    각 구는 이 클래스를 상속하여 자신만의 메뉴 수집 로직을 구현합니다.
    """

    def __init__(self, filter_text: str = None):
        """
        Args:
            filter_text: 필터링할 메뉴 텍스트 (예: "사업안내", "보건사업")
        """
        self.filter_text = filter_text

    @abstractmethod
    def collect_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """
        메뉴에서 링크 수집

        Args:
            soup: BeautifulSoup 객체
            base_url: 기본 URL

        Returns:
            수집된 링크 목록 [{"name": "...", "url": "...", "depth_level": 1}, ...]
        """
        pass

    def _extract_text(self, element, from_span: bool = False) -> str:
        """엘리먼트에서 텍스트 추출"""
        if from_span:
            span = element.find("span")
            return span.get_text(strip=True) if span else element.get_text(strip=True)
        return element.get_text(strip=True)

    def _is_valid_href(self, href: str) -> bool:
        """유효한 href인지 확인"""
        return href and href not in ["#", "#none", ""]

    def _make_link_dict(self, name: str, url: str, depth_level: int) -> Dict:
        """링크 딕셔너리 생성"""
        return {
            "name": name,
            "url": url,
            "depth_level": depth_level
        }
