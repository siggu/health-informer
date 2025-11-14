"""
동대문구 메뉴 수집 전략

구조:
- .side_menu > nav.menu
- .depth2_list > .depth2_item > a.depth2_text (depth2 - 수집 대상)
- .depth3_list > .depth3_item > a.depth3_text (depth3 - 수집 대상)

중복 처리: depth_level 점수로 자동 처리 (depth3 > depth2)
"""

from .base_strategy import BaseMenuStrategy
from bs4 import BeautifulSoup
from typing import List, Dict
from urllib.parse import urljoin


class DDMStrategy(BaseMenuStrategy):
    """동대문구 전용 메뉴 수집 전략"""

    def collect_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """
        동대문구 side_menu 구조에서 링크 수집
        depth2, depth3 수집
        """
        collected_links = []

        # .side_menu nav.menu 컨테이너 찾기
        side_menu = soup.select_one(".side_menu nav.menu")
        if not side_menu:
            print("  [동대문구] .side_menu nav.menu를 찾을 수 없습니다.")
            return []

        print("  [동대문구] .side_menu nav.menu 컨테이너 발견")

        # Step 1: depth2~3 링크 수집
        for depth_level, selector in [
            (2, ".depth2_list > .depth2_item > a.depth2_text[href]"),
            (3, ".depth3_list > .depth3_item > a.depth3_text[href]"),
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
            f"  [동대문구] 총 {len(collected_links)}개 링크 수집 "
            f"(depth2: {len([l for l in collected_links if l['depth_level'] == 2])}, "
            f"depth3: {len([l for l in collected_links if l['depth_level'] == 3])})"
        )

        return collected_links
