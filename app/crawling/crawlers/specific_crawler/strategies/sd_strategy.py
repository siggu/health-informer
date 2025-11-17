"""
성동구 메뉴 수집 전략
depth1~4 구조
"""

from .base_strategy import BaseMenuStrategy
from bs4 import BeautifulSoup
from typing import List, Dict
from urllib.parse import urljoin


class SDStrategy(BaseMenuStrategy):
    """성동구 전용 메뉴 수집 전략"""

    def collect_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """
        성동구 depth 구조에서 링크 수집
        "보건사업" 메뉴 아래의 depth2, depth3, depth4를 수집
        중복 URL은 crawler의 _deduplicate_by_specificity()에서 처리
        """
        collected_links = []

        # Step 1: .depth_list.depth1_list 찾기
        depth1_list = soup.select_one(".depth_list.depth1_list")
        if not depth1_list:
            print("  [성동구] .depth_list.depth1_list를 찾을 수 없습니다.")
            return []

        print("  [성동구] .depth_list.depth1_list 발견")

        # Step 2: "보건사업" 필터링
        container = depth1_list
        if self.filter_text:
            all_depth1_items = depth1_list.select(".depth1_item")
            for item in all_depth1_items:
                link = item.select_one("a.depth1_text")
                if link:
                    span = link.find("span")
                    if span and self.filter_text in span.get_text(strip=True):
                        print(f"  [성동구] '{self.filter_text}' 메뉴 발견")
                        container = item
                        break

        # Step 3: depth2~4 링크 수집
        for depth_level, selector in [
            (2, ".depth2_list > .depth2_item > a.depth2_text"),
            (3, ".depth3_list > .depth3_item > a.depth3_text"),
            (4, ".depth4_list > .depth4_item > a.depth4_text"),
        ]:
            elements = container.select(selector)
            for element in elements:
                href = element.get("href", "")
                if self._is_valid_href(href):
                    name = self._extract_text(element, from_span=True)
                    url = urljoin(base_url, href)
                    collected_links.append(
                        self._make_link_dict(name, url, depth_level)
                    )

        print(
            f"  [성동구] 총 {len(collected_links)}개 링크 수집 "
            f"(depth2: {len([l for l in collected_links if l['depth_level'] == 2])}, "
            f"depth3: {len([l for l in collected_links if l['depth_level'] == 3])}, "
            f"depth4: {len([l for l in collected_links if l['depth_level'] == 4])})"
        )

        return collected_links
