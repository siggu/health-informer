"""
양천구 보건소 전용 크롤러
복잡한 3단계 구조 처리:
1. subnav-dep2에서 링크 수집
2. 각 링크의 내부 탭(.content-tab) 수집
3. 게시판 페이지의 "더보기" 링크 수집
"""

import time
import re
from urllib.parse import urlparse

from ..district_crawler import DistrictCrawler
from bs4 import BeautifulSoup
from typing import List, Dict, Set
from ...utils import extract_link_from_element, normalize_url
from ... import config


class YangcheonCrawler(DistrictCrawler):
    """양천구 보건소 전용 크롤러"""

    def __init__(self, start_url: str, output_dir: str = None, max_workers: int = 3):
        # output_dir 기본값 설정
        if output_dir is None:
            output_dir = "app/crawling/output/양천구"

        super().__init__(
            output_dir=output_dir, region="양천구", max_workers=max_workers
        )

        self.start_url = start_url
        self.filter_keyword = "보건사업"

        # 양천구 전용 블랙리스트 키워드
        # 제목에 이 키워드가 포함되면 제외
        self.blacklist_keywords = {
            "교육",
            "건강도시",
            "조사",
            "방역",
            "동물",
        }

    def _collect_dep2_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """
        subnav-dep2에서 링크 수집

        Returns:
            수집된 링크 목록
        """
        collected_links = []
        seen_urls = set()

        # subnav-dep1 확인 (보건사업 필터링)
        subnav_dep1 = soup.select_one(".subnav-dep1")
        if subnav_dep1:
            selected_menu = subnav_dep1.select_one(".subnav-selected")
            if selected_menu:
                menu_text = selected_menu.get_text(strip=True)
                if self.filter_keyword not in menu_text:
                    print(
                        f"  [SKIP] subnav-dep1이 '{self.filter_keyword}'가 아님: {menu_text}"
                    )
                    return []
                print(f"  [OK] subnav-dep1 필터 통과: {menu_text}")

        # subnav-dep2 링크 수집
        subnav_dep2 = soup.select_one(".subnav-dep2")
        if not subnav_dep2:
            print("  경고: .subnav-dep2를 찾을 수 없습니다.")
            return []

        # 모든 링크 수집 (빈 링크 제외)
        dep2_links = subnav_dep2.select("ul li a[href]")

        for link_element in dep2_links:
            href = link_element.get("href", "")
            if href and href not in ["#", "#none", ""]:
                link_info = extract_link_from_element(link_element, base_url, seen_urls)
                if link_info:
                    normalized_url = normalize_url(link_info["url"])
                    if normalized_url not in seen_urls:
                        seen_urls.add(normalized_url)
                        collected_links.append(link_info)

        print(f"  [OK] subnav-dep2에서 {len(collected_links)}개 링크 수집")
        return collected_links

    def _collect_content_tabs(
        self, url: str, base_url: str, seen_urls: Set[str]
    ) -> List[Dict]:
        """
        페이지 내부의 content-tab 링크 수집

        Returns:
            탭 링크 목록
        """
        tab_links = []

        soup = self.fetch_page(url)
        if not soup:
            return []

        # content-tab 찾기
        content_tab = soup.select_one(".content-tab")
        if not content_tab:
            return []

        # 탭 링크 수집
        tab_elements = content_tab.select("ul li a[href]")
        for tab_element in tab_elements:
            href = tab_element.get("href", "")
            if href and href not in ["#", "#none", ""]:
                link_info = extract_link_from_element(tab_element, base_url, seen_urls)
                if link_info:
                    normalized_url = normalize_url(link_info["url"])
                    if normalized_url not in seen_urls:
                        seen_urls.add(normalized_url)
                        tab_links.append(link_info)

        if tab_links:
            print(f"    → content-tab에서 {len(tab_links)}개 탭 발견")

        return tab_links

    def _collect_board_items(
        self, url: str, base_url: str, seen_urls: Set[str]
    ) -> List[Dict]:
        """
        게시판 페이지의 "더보기" 링크 수집
        onclick="doBbsFView('715','295695','16010100')" 형식 파싱

        Returns:
            게시판 항목 링크 목록
        """
        board_links = []

        soup = self.fetch_page(url)
        if not soup:
            return []

        # post-box 찾기
        post_boxes = soup.select(".post-box")
        if not post_boxes:
            return []

        # base_url에서 도메인만 추출 (https://www.yangcheon.go.kr)
        parsed = urlparse(base_url)
        domain = f"{parsed.scheme}://{parsed.netloc}"

        for post_box in post_boxes:
            # 제목 추출
            title_element = post_box.select_one(".post-subject strong")
            if not title_element:
                continue

            title = title_element.get_text(strip=True)

            # "더보기" 버튼의 onclick 파싱
            more_button = post_box.select_one("a.btn-card-more")
            if not more_button:
                continue

            onclick = more_button.get("onclick", "")
            # doBbsFView('715','295695','16010100') 형식 파싱
            match = re.search(r"doBbsFView\('(\d+)','(\d+)','(\d+)'\)", onclick)
            if not match:
                continue

            cb_idx = match.group(1)
            bc_idx = match.group(2)

            # View URL 생성 (도메인만 사용)
            view_url = (
                f"{domain}/site/health/ex/bbs/View.do?cbIdx={cb_idx}&bcIdx={bc_idx}"
            )
            normalized_url = normalize_url(view_url)

            if normalized_url not in seen_urls:
                seen_urls.add(normalized_url)
                board_links.append({"name": title, "url": view_url})

        if board_links:
            print(f"    → 게시판에서 {len(board_links)}개 항목 발견")

        return board_links

    def _apply_blacklist_filter(self, links: List[Dict]) -> List[Dict]:
        """
        양천구 전용 블랙리스트 키워드 필터 적용

        Returns:
            필터링된 링크 목록
        """
        filtered_links = []
        excluded_count = 0

        for link in links:
            name = link["name"]
            should_exclude = False

            # 블랙리스트 키워드 체크
            for keyword in self.blacklist_keywords:
                if keyword in name:
                    print(f"    ✗ 블랙리스트 제외: '{name}' (키워드: '{keyword}')")
                    excluded_count += 1
                    should_exclude = True
                    break

            if not should_exclude:
                filtered_links.append(link)

        if excluded_count > 0:
            print(f"\n  [필터링 결과] {excluded_count}개 링크 제외됨")

        return filtered_links

    def collect_initial_items(
        self,
        *,
        start_url: str,
        crawl_rules: List[Dict],
        enable_keyword_filter: bool,
        **kwargs,
    ) -> List[Dict]:
        """
        링크 수집 및 필터링 (양천구 전용)

        3단계 수집:
        1. subnav-dep2 링크
        2. 각 페이지의 content-tab
        3. 게시판의 "더보기" 항목
        4. 전역 블랙리스트 필터링 적용

        Returns:
            필터링된 링크 목록
        """
        print("\n[1단계] 양천구 링크 수집 시작...")
        print(f"  시작 URL: {start_url}")
        print(f"  필터 키워드: '{self.filter_keyword}'")
        print("-" * 80)

        all_links = []
        seen_urls = set()

        # 페이지 가져오기
        soup = self.fetch_page(start_url)
        if not soup:
            print(f"오류: 시작 URL({start_url})에 접근할 수 없습니다.")
            return []

        base_url = start_url.split("?")[0].rsplit("/", 1)[0]

        # [1단계] subnav-dep2 링크 수집
        print("\n[1.1단계] subnav-dep2 링크 수집...")
        dep2_links = self._collect_dep2_links(soup, base_url)
        all_links.extend(dep2_links)

        # [2단계] 각 dep2 링크의 content-tab 수집 + 게시판 항목 수집
        print("\n[1.2단계] 각 페이지의 내부 탭 및 게시판 항목 수집...")
        for i, link in enumerate(dep2_links, 1):
            print(f"  [{i}/{len(dep2_links)}] {link['name']} 탐색 중...")
            time.sleep(config.RATE_LIMIT_DELAY)

            # content-tab 수집
            tab_links = self._collect_content_tabs(link["url"], base_url, seen_urls)
            all_links.extend(tab_links)

            # 게시판인지 확인 (List.do 포함)
            if "List.do" in link["url"]:
                board_items = self._collect_board_items(
                    link["url"], base_url, seen_urls
                )
                all_links.extend(board_items)

            # 탭에서 게시판 링크 확인
            for tab_link in tab_links:
                if "List.do" in tab_link["url"]:
                    time.sleep(config.RATE_LIMIT_DELAY)
                    board_items = self._collect_board_items(
                        tab_link["url"], base_url, seen_urls
                    )
                    all_links.extend(board_items)

        print(f"\n[수집 완료] 총 {len(all_links)}개의 링크 수집")

        # [3단계] 양천구 전용 블랙리스트 필터링 적용
        if enable_keyword_filter:
            print("\n[1.3단계] 양천구 전용 블랙리스트 필터링 적용...")
            all_links = self._apply_blacklist_filter(all_links)

        print(f"\n[SUCCESS] 최종 {len(all_links)}개의 링크 (필터링 후)")
        print(
            "  (양천구 3단계 수집: dep2 → content-tab → 게시판 항목 → 블랙리스트 필터)"
        )

        return all_links


if __name__ == "__main__":
    # 테스트 실행
    start_url = (
        "https://www.yangcheon.go.kr/health/health/02/10201010000002024022101.jsp"
    )
    crawler = YangcheonCrawler(start_url=start_url)
    crawler.run(start_url)
