"""
송파구 보건소 전용 크롤러
부모 카테고리를 고려한 링크 수집
"""

from ..district_crawler import DistrictCrawler
from bs4 import BeautifulSoup
from typing import List, Dict, Set
from ...utils import extract_link_from_element, normalize_url


class SongpaCrawler(DistrictCrawler):
    """송파구 보건소 전용 크롤러"""

    def __init__(self, start_url: str, output_dir: str = None, max_workers: int = 3):
        # output_dir 기본값 설정
        if output_dir is None:
            output_dir = "app/crawling/output/송파구"

        super().__init__(
            output_dir=output_dir, region="송파구", max_workers=max_workers
        )

        self.start_url = start_url

        # 송파구 전용 블랙리스트 depth1 카테고리
        self.blacklist_categories = {
            "방역소독",
            "안전도시",
            "야간휴일 의료비청구",
            "영·유아 손상기록시스템",
            "구조 및 응급처치 교육",
        }

    def _collect_links_with_category_filter(
        self, soup: BeautifulSoup, base_url: str
    ) -> List[Dict]:
        """
        송파구 사이드 메뉴에서 링크 수집 (부모 카테고리 필터링 포함)

        Returns:
            수집된 링크 목록
        """
        collected_links = []
        seen_urls = set()

        # 사이드 메뉴 찾기
        side_menu = soup.select_one(".side_menu")
        if not side_menu:
            print("  경고: .side_menu를 찾을 수 없습니다.")
            return []

        # 모든 depth1 카테고리 순회
        depth1_items = side_menu.select(".depth1_list > .depth1_item")

        for depth1_item in depth1_items:
            # depth1 링크 추출 (직접 자식)
            depth1_link = depth1_item.find("a", class_="depth1_text", recursive=False)
            if not depth1_link:
                continue

            depth1_name = depth1_link.get_text(strip=True)

            # depth1이 블랙리스트에 있으면 전체 건너뛰기 (하위도 수집 안 함)
            if depth1_name in self.blacklist_categories:
                print(f"  [SKIP] depth1 카테고리 및 하위 모두 제외: {depth1_name}")
                continue

            # depth1 링크 수집
            link_info = self._extract_link_if_valid(depth1_link, base_url, seen_urls)
            if link_info:
                collected_links.append(link_info)

            # depth2 링크 수집
            depth2_items = depth1_item.select(".depth2_list > .depth2_item")
            for depth2_item in depth2_items:
                depth2_link = depth2_item.find(
                    "a", class_="depth2_text", recursive=False
                )
                if depth2_link:
                    link_info = self._extract_link_if_valid(
                        depth2_link, base_url, seen_urls
                    )
                    if link_info:
                        collected_links.append(link_info)

                # depth3 링크 수집
                depth3_items = depth2_item.select(".depth3_list > .depth3_item")
                for depth3_item in depth3_items:
                    depth3_link = depth3_item.find(
                        "a", class_="depth3_text", recursive=False
                    )
                    if depth3_link:
                        link_info = self._extract_link_if_valid(
                            depth3_link, base_url, seen_urls
                        )
                        if link_info:
                            collected_links.append(link_info)

        print(
            f"  [OK] 총 {len(collected_links)}개 링크 수집 (부모 카테고리 필터링 적용)"
        )
        return collected_links

    def _extract_link_if_valid(
        self, link_element, base_url: str, seen_urls: Set[str]
    ) -> Dict:
        """
        링크가 유효한지 확인하고 추출
        - contents.do 포함
        - target='_self'
        - 중복 아님

        Returns:
            링크 정보 또는 None
        """
        href = link_element.get("href", "")
        target = link_element.get("target", "")

        # contents.do 포함하고 target='_self'인 것만
        if "contents.do" not in href or target != "_self":
            return None

        link_info = extract_link_from_element(link_element, base_url, seen_urls)
        if link_info:
            seen_urls.add(normalize_url(link_info["url"]))

        return link_info

    def collect_initial_items(
        self,
        *,
        start_url: str,
        crawl_rules: List[Dict],
        enable_keyword_filter: bool,
        **kwargs,
    ) -> List[Dict]:
        """
        링크 수집 및 필터링 (송파구 전용 - 키워드 필터링 비활성화)

        송파구는 부모 카테고리 필터링만 사용하고,
        개별 키워드 필터링은 건너뜁니다.

        Returns:
            필터링된 링크 목록
        """
        print("\n[1단계] 초기 링크 수집 중...")
        print(f"  시작 URL: {start_url}")
        print("-" * 80)

        # 페이지 가져오기
        soup = self.fetch_page(start_url)
        if not soup:
            print(f"오류: 시작 URL({start_url})에 접근할 수 없습니다.")
            return []

        base_url = start_url.split("?")[0].rsplit("/", 1)[0]

        # 송파구 전용 링크 수집 (부모 카테고리 필터링 포함)
        print("\n[1.2단계] 송파구 사이드 메뉴에서 링크 수집 (부모 카테고리 필터링)...")
        initial_links = self._collect_links_with_category_filter(soup, base_url)

        print(f"\n[SUCCESS] 총 {len(initial_links)}개의 초기 링크 수집 완료")
        print("  (송파구는 부모 카테고리 필터링만 적용, 개별 키워드 필터링 건너뜀)")

        return initial_links


if __name__ == "__main__":
    # 테스트 실행
    start_url = "https://www.songpa.go.kr/ehealth/contents.do?key=4525"
    crawler = SongpaCrawler(start_url=start_url)
    crawler.run(start_url)
