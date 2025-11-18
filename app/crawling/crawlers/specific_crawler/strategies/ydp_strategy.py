"""
영등포구 메뉴 수집 전략
side_menu 구조, depth1~3
"""

from .base_strategy import BaseMenuStrategy
from bs4 import BeautifulSoup
from typing import List, Dict
from urllib.parse import urljoin


class YDPStrategy(BaseMenuStrategy):
    """영등포구 전용 메뉴 수집 전략"""

    def collect_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """
        영등포구 사이드 메뉴에서 링크 수집
        depth1, depth2, depth3를 수집
        """
        collected_links = []

        # Step 1: .side_menu 찾기
        side_menu = soup.select_one(".side_menu")
        if not side_menu:
            print("  [영등포구] .side_menu를 찾을 수 없습니다.")
            return []

        print("  [영등포구] .side_menu 발견")

        # Step 2: depth1~3 링크 수집
        for depth_level, selector in [
            (1, ".depth1_list > .depth1_item > a.depth1_text"),
            (2, ".depth2_list > .depth2_item > a.depth2_text"),
            (3, ".depth3_list > .depth3_item > a.depth3_text"),
        ]:
            elements = side_menu.select(selector)
            for element in elements:
                href = element.get("href", "")
                if self._is_valid_href(href):
                    name = self._extract_text(element)
                    url = urljoin(base_url, href)
                    collected_links.append(
                        self._make_link_dict(name, url, depth_level)
                    )

        print(
            f"  [영등포구] 총 {len(collected_links)}개 링크 수집 "
            f"(depth1: {len([l for l in collected_links if l['depth_level'] == 1])}, "
            f"depth2: {len([l for l in collected_links if l['depth_level'] == 2])}, "
            f"depth3: {len([l for l in collected_links if l['depth_level'] == 3])})"
        )

        return collected_links
