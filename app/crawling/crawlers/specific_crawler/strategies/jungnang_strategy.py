"""
중랑구 메뉴 수집 전략
sub-menu 구조, depth1~3
"""

from .base_strategy import BaseMenuStrategy
from bs4 import BeautifulSoup
from typing import List, Dict
from urllib.parse import urljoin


class JungnangStrategy(BaseMenuStrategy):
    """중랑구 전용 메뉴 수집 전략"""

    def collect_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """
        중랑구 sub-menu 구조에서 링크 수집
        depth1, depth2, depth3(sb-depth4)를 수집
        """
        collected_links = []

        # Step 1: ul.sub-menu 찾기
        sub_menu = soup.select_one("ul.sub-menu")
        if not sub_menu:
            print("  [중랑구] ul.sub-menu를 찾을 수 없습니다.")
            return []

        print("  [중랑구] ul.sub-menu 발견")

        # Step 2: depth1 링크 수집 (a.ym1)
        depth1_elements = sub_menu.select("li > a.ym1")
        for element in depth1_elements:
            href = element.get("href", "")
            if self._is_valid_href(href):
                name = self._extract_text(element)
                url = urljoin(base_url, href)
                collected_links.append(self._make_link_dict(name, url, 1))

        # Step 3: depth2 링크 수집
        depth2_elements = sub_menu.select("ul.sb-depth3 > li > a")
        for element in depth2_elements:
            href = element.get("href", "")
            if self._is_valid_href(href):
                name = self._extract_text(element)
                url = urljoin(base_url, href)
                collected_links.append(self._make_link_dict(name, url, 2))

        # Step 4: depth3 링크 수집 (ul.sb-depth4 > li > a)
        depth3_elements = sub_menu.select("ul.sb-depth4 > li > a")
        for element in depth3_elements:
            href = element.get("href", "")
            if self._is_valid_href(href):
                name = self._extract_text(element)
                url = urljoin(base_url, href)
                collected_links.append(self._make_link_dict(name, url, 3))

        print(
            f"  [중랑구] 총 {len(collected_links)}개 링크 수집 "
            f"(depth1: {len([l for l in collected_links if l['depth_level'] == 1])}, "
            f"depth2: {len([l for l in collected_links if l['depth_level'] == 2])}, "
            f"depth3: {len([l for l in collected_links if l['depth_level'] == 3])})"
        )

        return collected_links
