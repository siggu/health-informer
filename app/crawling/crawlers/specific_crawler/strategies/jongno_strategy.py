"""
종로구 메뉴 수집 전략
LNB 구조, depth1~2
"""

from .base_strategy import BaseMenuStrategy
from bs4 import BeautifulSoup
from typing import List, Dict
from urllib.parse import urljoin


class JongnoStrategy(BaseMenuStrategy):
    """종로구 전용 메뉴 수집 전략"""

    def collect_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """
        종로구 LNB 구조에서 링크 수집
        depth2가 있으면 depth2만, 없으면 depth1 수집
        """
        collected_links = []

        # Step 1: .lnb-wrap 찾기
        lnb_wrap = soup.select_one(".lnb-wrap")
        if not lnb_wrap:
            print("  [종로구] .lnb-wrap을 찾을 수 없습니다.")
            return []

        print("  [종로구] .lnb-wrap 발견")

        # Step 2: depth1 li 항목 순회
        depth1_items = lnb_wrap.select(".lnb-depth1 > li")
        for item in depth1_items:
            # depth2가 있는지 확인
            has_depth2 = item.select_one("ul.lnb-depth2") is not None

            if not has_depth2:
                # depth2가 없으면 depth1 링크 수집
                depth1_link = item.select_one("a.btn.btn-toggle")
                if depth1_link:
                    href = depth1_link.get("href", "")
                    if self._is_valid_href(href):
                        name = self._extract_text(depth1_link, from_span=True)
                        url = urljoin(base_url, href)
                        collected_links.append(self._make_link_dict(name, url, 1))

        # Step 3: depth2 링크 수집
        depth2_elements = lnb_wrap.select(".lnb-depth2 > li > a.btn")
        for element in depth2_elements:
            href = element.get("href", "")
            if self._is_valid_href(href):
                name = self._extract_text(element)
                url = urljoin(base_url, href)
                collected_links.append(self._make_link_dict(name, url, 2))

        print(
            f"  [종로구] 총 {len(collected_links)}개 링크 수집 "
            f"(depth1: {len([l for l in collected_links if l['depth_level'] == 1])}, "
            f"depth2: {len([l for l in collected_links if l['depth_level'] == 2])})"
        )

        return collected_links
