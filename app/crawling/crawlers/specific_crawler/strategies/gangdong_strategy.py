"""
강동구 메뉴 수집 전략
gnb 구조, "보건사업" 필터링
"""

from .base_strategy import BaseMenuStrategy
from bs4 import BeautifulSoup
from typing import List, Dict
from urllib.parse import urljoin


class GangdongStrategy(BaseMenuStrategy):
    """강동구 전용 메뉴 수집 전략"""

    def collect_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """
        강동구 gnb 구조에서 링크 수집
        "보건사업" 메뉴 아래의 depth1, depth2, depth3 수집
        """
        collected_links = []

        # Step 1: ul.gnb 찾기
        gnb = soup.select_one("ul.gnb")
        if not gnb:
            print("  [강동구] ul.gnb를 찾을 수 없습니다.")
            return []

        # Step 2: "보건사업" 필터링
        container = gnb
        if self.filter_text:
            all_menu_items = gnb.select("li")
            for li in all_menu_items:
                link = li.select_one("a.gnb-category")
                if link and self.filter_text in link.get_text(strip=True):
                    print(
                        f"  [강동구] '{self.filter_text}' 메뉴 발견, 해당 섹션만 수집"
                    )
                    container = li
                    break

        # Step 3: depth1 링크 수집
        depth1_elements = container.select("li > a.gnb-category")
        for element in depth1_elements:
            href = element.get("href", "")
            if self._is_valid_href(href):
                name = self._extract_text(element)
                url = urljoin(base_url, href)
                collected_links.append(self._make_link_dict(name, url, 1))

        # Step 4: depth2 링크 수집
        depth2_elements = container.select("ul.depth-02 > li > a")
        for element in depth2_elements:
            href = element.get("href", "")
            if self._is_valid_href(href):
                name = self._extract_text(element)
                url = urljoin(base_url, href)
                collected_links.append(self._make_link_dict(name, url, 2))

        # Step 5: depth3 링크 수집
        depth3_elements = container.select("ul.depth-03 > li > a")
        for element in depth3_elements:
            href = element.get("href", "")
            if self._is_valid_href(href):
                name = self._extract_text(element)
                url = urljoin(base_url, href)
                collected_links.append(self._make_link_dict(name, url, 3))

        print(
            f"  [강동구] 총 {len(collected_links)}개 링크 수집 "
            f"(depth1: {len([l for l in collected_links if l['depth_level'] == 1])}, "
            f"depth2: {len([l for l in collected_links if l['depth_level'] == 2])}, "
            f"depth3: {len([l for l in collected_links if l['depth_level'] == 3])})"
        )

        return collected_links
