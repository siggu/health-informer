"""
통합 구별 메뉴 크롤러 (Strategy Pattern 버전)

각 구의 메뉴 수집 로직을 Strategy 클래스에 위임하여 코드 단순화
"""

from ..district_crawler import DistrictCrawler
from bs4 import BeautifulSoup
from typing import List, Dict
from ...utils import normalize_url
from .district_configs import get_config, GLOBAL_BLACKLIST_KEYWORDS


class DistrictMenuCrawler(DistrictCrawler):
    """설정 기반 통합 구별 메뉴 크롤러 (Strategy Pattern)"""

    def __init__(
        self,
        district_name: str,
        start_url: str,
        output_dir: str = None,
        max_workers: int = None,
    ):
        """
        Args:
            district_name: 구 이름 (예: "은평구", "강동구")
            start_url: 크롤링 시작 URL
            output_dir: 출력 디렉토리 (None이면 설정에서 가져옴)
            max_workers: 병렬 처리 worker 수 (None이면 설정에서 가져옴)
        """
        # 설정 로드
        self.config = get_config(district_name)

        # output_dir과 max_workers 설정
        if output_dir is None:
            output_dir = self.config.get(
                "output_dir", f"app/crawling/output/{district_name}"
            )
        if max_workers is None:
            max_workers = self.config.get("max_workers", 4)

        super().__init__(
            output_dir=output_dir, region=district_name, max_workers=max_workers
        )

        self.district_name = district_name
        self.start_url = start_url

        # Strategy 인스턴스 생성
        strategy_class = self.config["strategy_class"]
        filter_text = self.config.get("filter_text")
        self.strategy = strategy_class(filter_text=filter_text)

        # 전역 블랙리스트 사용
        self.blacklist_keywords = GLOBAL_BLACKLIST_KEYWORDS
        self.depth_scores = self.config.get("depth_scores", {})

    def _get_link_specificity(self, link: Dict) -> int:
        """
        링크의 구체성 레벨 계산
        depth 레벨에 따른 우선순위 부여

        Args:
            link: 링크 정보 (name, url, depth_level 포함)

        Returns:
            구체성 레벨 (높을수록 구체적)
        """
        name = link.get("name", "")
        depth_level = link.get("depth_level", 0)

        # 기본 점수: 이름 길이 (구체적인 제목일수록 길다)
        specificity = len(name)

        # depth 점수 추가
        if depth_level in self.depth_scores:
            specificity += self.depth_scores[depth_level]

        return specificity

    def _collect_links_from_menu(
        self, soup: BeautifulSoup, base_url: str
    ) -> List[Dict]:
        """
        Strategy를 사용한 메뉴 링크 수집

        Returns:
            수집된 링크 목록 (depth_level 포함)
        """
        print(f"\n[{self.district_name}] Strategy를 사용한 링크 수집...")

        # Strategy에 링크 수집 위임
        collected_links = self.strategy.collect_links(soup, base_url)

        return collected_links

    def _apply_blacklist_filter(self, links: List[Dict]) -> List[Dict]:
        """
        블랙리스트 키워드 필터 적용

        Returns:
            필터링된 링크 목록
        """
        if not self.blacklist_keywords:
            return links

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

    def _deduplicate_by_specificity(self, links: List[Dict]) -> List[Dict]:
        """
        중복 URL 제거 (더 구체적인 제목 우선)

        Returns:
            중복이 제거된 링크 목록
        """
        url_to_links = {}

        # 같은 URL의 링크들을 그룹화
        for link in links:
            normalized_url = normalize_url(link["url"])
            if normalized_url not in url_to_links:
                url_to_links[normalized_url] = []
            url_to_links[normalized_url].append(link)

        final_links = []

        # 각 URL 그룹에서 가장 구체적인 링크 선택
        for normalized_url, link_group in url_to_links.items():
            if len(link_group) == 1:
                # 중복 없음
                final_links.append(link_group[0])
            else:
                # 중복 있음 - 구체성 기준으로 정렬하여 가장 구체적인 것 선택
                sorted_links = sorted(
                    link_group, key=self._get_link_specificity, reverse=True
                )
                best_link = sorted_links[0]
                final_links.append(best_link)

                # 중복 로그 출력
                print(f"\n  [중복 URL 발견] {normalized_url}")
                print(
                    f"    ✓ 선택: '{best_link['name']}' (depth{best_link.get('depth_level', 0)}, 구체성: {self._get_link_specificity(best_link)})"
                )
                for excluded_link in sorted_links[1:]:
                    print(
                        f"    ✗ 제외: '{excluded_link['name']}' (depth{excluded_link.get('depth_level', 0)}, 구체성: {self._get_link_specificity(excluded_link)})"
                    )

        return final_links

    def collect_initial_items(
        self,
        *,
        start_url: str,
        crawl_rules: List[Dict],
        enable_keyword_filter: bool,
        **kwargs,
    ) -> List[Dict]:
        """
        링크 수집 및 필터링 (Strategy Pattern 사용)

        Returns:
            필터링된 링크 목록
        """
        print(f"\n[1단계] {self.district_name} 링크 수집 시작...")
        print(f"  시작 URL: {start_url}")
        print("-" * 80)

        # 페이지 가져오기
        soup = self.fetch_page(start_url)
        if not soup:
            print(f"오류: 시작 URL({start_url})에 접근할 수 없습니다.")
            return []

        base_url = start_url.split("?")[0].rsplit("/", 1)[0]

        # Strategy를 사용한 링크 수집
        print(f"\n[1.1단계] {self.district_name} Strategy로 링크 수집...")
        all_links = self._collect_links_from_menu(soup, base_url)

        # 블랙리스트 필터링 적용 (1차 - 중복 제거 전)
        if enable_keyword_filter and self.blacklist_keywords:
            print(f"\n[1.2단계] {self.district_name} 블랙리스트 필터링 적용 (1차)...")
            all_links = self._apply_blacklist_filter(all_links)

        # 중복 URL 제거 (구체성 기준)
        print("\n[1.3단계] 중복 URL 제거 (구체적인 제목 우선)...")
        all_links = self._deduplicate_by_specificity(all_links)

        # 블랙리스트 필터링 적용 (2차 - 중복 제거 후)
        if enable_keyword_filter and self.blacklist_keywords:
            print(f"\n[1.4단계] {self.district_name} 블랙리스트 필터링 적용 (2차)...")
            all_links = self._apply_blacklist_filter(all_links)

        # depth_level 필드 제거 (이후 처리에서 필요 없음)
        for link in all_links:
            link.pop("depth_level", None)

        print(f"\n[SUCCESS] 총 {len(all_links)}개의 링크 수집 완료")
        print(f"  ({self.district_name}: Strategy Pattern 사용)")

        return all_links


if __name__ == "__main__":
    # 테스트 실행 예시
    import sys

    if len(sys.argv) < 3:
        print("사용법: python district_menu_crawler.py <구이름> <시작URL>")
        print(
            "예시: python district_menu_crawler.py 은평구 https://www.ep.go.kr/health/contents.do?key=1582"
        )
        sys.exit(1)

    district = sys.argv[1]
    url = sys.argv[2]

    crawler = DistrictMenuCrawler(district_name=district, start_url=url)
    crawler.run(url)
