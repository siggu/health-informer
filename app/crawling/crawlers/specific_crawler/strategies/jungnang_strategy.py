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

        구조:
        - ul.sb-depth3 > li > a (직접 페이지 링크, a.ym2가 아닌 것)
        - ul.sb-depth3 > li > a.ym2 (중간 카테고리, 제외)
            └─ ul.sb-depth4 > li > a (최종 페이지, 수집 대상)
        """
        collected_links = []

        # 디버그: 가능한 메뉴 컨테이너 확인
        print("  [중랑구 DEBUG] 페이지에서 찾은 메뉴 관련 요소들:")
        for selector in ["ul.sub-menu", ".sub-left", ".gnb", "#gnb", "nav.lnb", ".lnb"]:
            found = soup.select_one(selector)
            print(f"    - {selector}: {'발견' if found else '없음'}")

        # Step 1: ul.sub-menu 찾기
        sub_menu = soup.select_one("ul.sub-menu")
        if not sub_menu:
            # 대안: .sub-left 안의 ul.sub-menu 시도
            sub_left = soup.select_one(".sub-left")
            if sub_left:
                sub_menu = sub_left.select_one("ul.sub-menu")

            if not sub_menu:
                print("  [중랑구] ul.sub-menu를 찾을 수 없습니다.")
                return []

        print("  [중랑구] ul.sub-menu 발견")

        # Step 2: ul.sb-depth3의 li 중에서 하위 ul.sb-depth4를 가지지 않는 것만 수집
        # 예: "임신 사전건강관리 지원", "식중독 예방" 등
        depth3_items = sub_menu.select("ul.sb-depth3 > li")
        print(f"  [중랑구] ul.sb-depth3에서 {len(depth3_items)}개 li 항목 발견")

        for li_element in depth3_items:
            # 하위에 ul.sb-depth4가 있는지 확인
            has_depth4 = li_element.select_one("ul.sb-depth4") is not None

            # 직접 자식 a 태그 찾기 (첫 번째 a 태그)
            link_element = li_element.find("a", recursive=False)
            if link_element:
                name = self._extract_text(link_element)

                if has_depth4:
                    # 하위 메뉴가 있으면 중간 카테고리이므로 건너뛰기
                    print(f"    [중랑구] 중간 카테고리 건너뜀: {name}")
                    continue

                href = link_element.get("href", "")
                if self._is_valid_href(href):
                    url = urljoin(base_url, href)
                    collected_links.append(self._make_link_dict(name, url, 2))
                    print(f"    [중랑구] depth3 직접 링크 수집: {name}")

        # Step 3: ul.sb-depth4의 모든 링크 수집 (최종 페이지)
        # 예: "걷기프로그램", "신체활동프로그램", "비만관리 프로그램" 등
        depth4_links = sub_menu.select("ul.sb-depth4 > li > a")
        for element in depth4_links:
            href = element.get("href", "")
            if self._is_valid_href(href):
                name = self._extract_text(element)
                url = urljoin(base_url, href)
                collected_links.append(self._make_link_dict(name, url, 3))

        print(
            f"  [중랑구] 총 {len(collected_links)}개 링크 수집 "
            f"(depth3 직접: {len([l for l in collected_links if l['depth_level'] == 2])}, "
            f"depth4: {len([l for l in collected_links if l['depth_level'] == 3])})"
        )

        return collected_links
