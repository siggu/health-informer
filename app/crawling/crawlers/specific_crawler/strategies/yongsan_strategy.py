"""
용산구 메뉴 수집 전략
nav.lnb 구조, depth1~2
"""

from .base_strategy import BaseMenuStrategy
from bs4 import BeautifulSoup
from typing import List, Dict
from urllib.parse import urljoin


class YongsanStrategy(BaseMenuStrategy):
    """용산구 전용 메뉴 수집 전략"""

    def collect_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """
        용산구 nav.lnb에서 링크 수집
        depth1과 depth2를 수집
        """
        collected_links = []

        # Step 1: nav.lnb 찾기
        nav_lnb = soup.select_one("nav.lnb")
        if not nav_lnb:
            print("  [용산구] nav.lnb를 찾을 수 없습니다.")
            return []

        print("  [용산구] nav.lnb 발견")

        # Step 2: 모든 li 요소 순회
        all_li = nav_lnb.select("li")

        for li in all_li:
            # depth1: 직접 자식 a 태그만 찾기
            depth1_link = li.find("a", recursive=False)
            if depth1_link:
                href = depth1_link.get("href", "")
                if self._is_valid_href(href):
                    name = self._extract_text(depth1_link)
                    url = urljoin(base_url, href)
                    collected_links.append(self._make_link_dict(name, url, 1))

            # depth2: ul > li > a 구조
            ul = li.find("ul", recursive=False)
            if ul:
                depth2_li_list = ul.find_all("li", recursive=False)
                for depth2_li in depth2_li_list:
                    depth2_link = depth2_li.find("a", recursive=False)
                    if depth2_link:
                        href = depth2_link.get("href", "")
                        if self._is_valid_href(href):
                            name = self._extract_text(depth2_link)
                            url = urljoin(base_url, href)
                            collected_links.append(self._make_link_dict(name, url, 2))

        print(
            f"  [용산구] 총 {len(collected_links)}개 링크 수집 "
            f"(depth1: {len([l for l in collected_links if l['depth_level'] == 1])}, "
            f"depth2: {len([l for l in collected_links if l['depth_level'] == 2])})"
        )

        return collected_links
