"""
관악구 메뉴 수집 전략
gnb 구조, "보건사업" 필터링
"""

from .base_strategy import BaseMenuStrategy
from bs4 import BeautifulSoup
from typing import List, Dict
from urllib.parse import urljoin


class GwanakStrategy(BaseMenuStrategy):
    """관악구 전용 메뉴 수집 전략"""

    def collect_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """
        관악구 gnb 구조에서 링크 수집
        "보건사업" 메뉴 아래의 depth1, depth2, depth3 수집
        """
        collected_links = []

        gnb = soup.select_one("#snav nav")
        if not gnb:
            print("  [관악구] #snav nav를 찾을 수 없습니다.")
            return []

        depth1_elements = gnb.select("a[href^='/site/health']")
        for element in depth1_elements:
            href = element.get("href", "")
            if self._is_valid_href(href):
                name = self._extract_text(element)
                url = urljoin(base_url, href)
                collected_links.append(self._make_link_dict(name, url, 1))

        print(
            f"  [관악구] 총 {len(collected_links)}개 링크 수집 "
            f"(depth1: {len([l for l in collected_links if l['depth_level'] == 1])}, "
            f"depth2: {len([l for l in collected_links if l['depth_level'] == 2])}, "
            f"depth3: {len([l for l in collected_links if l['depth_level'] == 3])})"
        )

        return collected_links
