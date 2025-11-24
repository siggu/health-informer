"""
마포구 보건소 전용 크롤러
"사업안내" 메뉴 필터링 및 3단계 드롭다운 메뉴 처리
depth1 (사업안내) → depth2 (카테고리) → depth3 (세부 항목)

양천구와 동일한 방식:
1. depth2 링크 수집
2. 각 depth2 페이지를 순회하며 depth3 링크 수집
"""

import time
from ..district_crawler import DistrictCrawler
from bs4 import BeautifulSoup
from typing import List, Dict, Set
from ...utils import extract_link_from_element, normalize_url
from ... import config


class MapoCrawler(DistrictCrawler):
    """마포구 보건소 전용 크롤러"""

    def __init__(self, start_url: str, output_dir: str = None, max_workers: int = 3):
        # output_dir 기본값 설정
        if output_dir is None:
            output_dir = "app/crawling/output/마포구"

        super().__init__(
            output_dir=output_dir, region="마포구", max_workers=max_workers
        )

        self.start_url = start_url
        self.filter_keyword = "사업안내"

    def _collect_dep2_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """
        snav_2st에서 depth2 링크 수집

        Returns:
            수집된 링크 목록
        """
        collected_links = []
        seen_urls = set()

        # snav_1st 확인 (사업안내 필터링)
        snav_1st = soup.select_one(".snav_1st .snav_btn")
        if snav_1st:
            menu_text = snav_1st.get_text(strip=True)
            if self.filter_keyword not in menu_text:
                print(
                    f"  [SKIP] snav_1st가 '{self.filter_keyword}'가 아님: {menu_text}"
                )
                return []
            print(f"  [OK] snav_1st 필터 통과: {menu_text}")
        else:
            print("  [WARNING] .snav_1st를 찾을 수 없습니다.")

        # snav_2st 링크 수집
        snav_2st = soup.select_one(".snav_2st")
        if not snav_2st:
            print("  경고: .snav_2st를 찾을 수 없습니다.")
            return []

        # 모든 링크 수집 (빈 링크 제외)
        dep2_links = snav_2st.select("ul li a[href]")

        for link_element in dep2_links:
            href = link_element.get("href", "")
            if href and href not in ["#", "#none", ""]:
                link_info = extract_link_from_element(link_element, base_url, seen_urls)
                if link_info:
                    normalized_url = normalize_url(link_info["url"])
                    if normalized_url not in seen_urls:
                        seen_urls.add(normalized_url)
                        collected_links.append(link_info)

        print(f"  [OK] snav_2st에서 {len(collected_links)}개 링크 수집")
        return collected_links

    def _collect_dep3_links(
        self, url: str, base_url: str, seen_urls: Set[str]
    ) -> List[Dict]:
        """
        각 depth2 페이지에서 snav_3rd 링크 수집

        Returns:
            depth3 링크 목록
        """
        dep3_links = []

        soup = self.fetch_page(url)
        if not soup:
            return []

        # snav_3rd 찾기
        snav_3rd = soup.select_one(".snav_3rd")
        if not snav_3rd:
            return []

        # depth3 링크 수집
        link_elements = snav_3rd.select("ul li a[href]")
        for link_element in link_elements:
            href = link_element.get("href", "")
            if href and href not in ["#", "#none", ""]:
                link_info = extract_link_from_element(link_element, base_url, seen_urls)
                if link_info:
                    normalized_url = normalize_url(link_info["url"])
                    if normalized_url not in seen_urls:
                        seen_urls.add(normalized_url)
                        dep3_links.append(link_info)

        if dep3_links:
            print(f"    → snav_3rd에서 {len(dep3_links)}개 링크 발견")

        return dep3_links

    def collect_initial_items(
        self,
        *,
        start_url: str,
        crawl_rules: List[Dict],
        enable_keyword_filter: bool,
        **kwargs,
    ) -> List[Dict]:
        """
        링크 수집 및 필터링 (마포구 전용)

        전략:
        1. snav_2st에서 depth2 링크 수집
        2. 각 depth2 페이지를 순회하며 snav_3rd 링크 수집

        Returns:
            수집된 링크 목록
        """
        print("\n[1단계] 마포구 링크 수집 시작...")
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

        # [1단계] snav_2st 링크 수집
        print("\n[1.1단계] snav_2st 링크 수집...")
        dep2_links = self._collect_dep2_links(soup, base_url)
        all_links.extend(dep2_links)

        # [2단계] 각 dep2 링크의 snav_3rd 수집
        print("\n[1.2단계] 각 depth2 페이지의 snav_3rd 링크 수집...")
        for i, link in enumerate(dep2_links, 1):
            print(f"  [{i}/{len(dep2_links)}] {link['name']} 탐색 중...")
            time.sleep(config.RATE_LIMIT_DELAY)

            # snav_3rd 수집
            dep3_links = self._collect_dep3_links(link["url"], base_url, seen_urls)
            all_links.extend(dep3_links)

        print(f"\n[수집 완료] 총 {len(all_links)}개의 링크 수집")
        print(f"\n[SUCCESS] 최종 {len(all_links)}개의 링크")
        print("  (마포구 3단계 수집: dep2 → 각 dep2의 dep3)")

        return all_links


if __name__ == "__main__":
    # 테스트 실행
    start_url = "https://www.mapo.go.kr/site/health/content/health04010101"
    crawler = MapoCrawler(start_url=start_url)
    crawler.run(start_url=start_url)
