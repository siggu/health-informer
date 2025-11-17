"""
중구 메뉴 수집 전략
LNB 구조, depth1(카테고리) -> depth2(실제 링크)
"""

from .base_strategy import BaseMenuStrategy
from bs4 import BeautifulSoup
from typing import List, Dict
from urllib.parse import urljoin


class JungguStrategy(BaseMenuStrategy):
    """중구 전용 메뉴 수집 전략"""

    def collect_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """
        중구 LNB 구조에서 링크 수집
        - div.lnb_area 내부의 실제 링크만 수집
        - href="#none"인 카테고리 링크는 제외
        """
        collected_links = []

        # Step 1: lnb_area 찾기
        lnb_area = soup.select_one("div.lnb_area")
        if not lnb_area:
            print("  [중구] div.lnb_area를 찾을 수 없습니다.")
            return []

        print("  [중구] div.lnb_area 발견")

        # Step 2: 모든 링크 수집 (카테고리 링크 제외)
        # - depth_all 내부의 실제 링크 수집
        # - no_depth 클래스가 있는 단일 링크 수집
        all_links = lnb_area.select("ul li a[href]:not([href='#none'])")

        for link_element in all_links:
            href = link_element.get("href", "")
            if self._is_valid_href(href):
                name = self._extract_text(link_element)
                url = urljoin(base_url, href)
                collected_links.append(self._make_link_dict(name, url, 1))

        print(f"  [중구] 총 {len(collected_links)}개 링크 수집")

        return collected_links
