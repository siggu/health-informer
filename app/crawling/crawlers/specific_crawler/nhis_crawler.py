"""
국민건강보험공단(NHIS) 전용 크롤러

국민건강보험 정책제도안내 페이지 크롤링
- URL: https://www.nhis.or.kr/nhis/minwon/wbhapa01000m01.do
- 정책/제도 목록 수집
- 상세 페이지 내용 크롤링
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
import json
from typing import List, Dict
import os
from datetime import datetime
from urllib.parse import parse_qs, urlparse
import time

from ... import config
from ...utils import normalize_url
from ...base.parallel_crawler import BaseParallelCrawler


class NHISCrawler(BaseParallelCrawler):
    """국민건강보험공단 전용 크롤러"""

    BASE_URL = "https://www.nhis.or.kr"

    def __init__(self, output_dir: str = "app/crawling/output", max_workers: int = 2):
        """
        Args:
            output_dir: 결과 저장 디렉토리
            max_workers: 병렬 처리 워커 수 (기본값: 2, 서버 부하 방지)
        """
        super().__init__(output_dir=output_dir, max_workers=max_workers)

    def get_list_page_url(
        self,
        page: int = 0,
        limit: int = 12,
        mode: str = "list",
    ) -> str:
        """
        정책제도안내 목록 페이지 URL 생성

        Args:
            page: 페이지 번호 (0부터 시작, offset 계산용)
            limit: 페이지당 아이템 수
            mode: 모드 (기본값: list)

        Returns:
            목록 페이지 URL
        """
        offset = page * limit
        url = (
            f"{self.BASE_URL}/nhis/minwon/wbhapa01000m01.do"
            f"?mode={mode}"
            f"&article.offset={offset}"
            f"&articleLimit={limit}"
        )
        return url

    def get_detail_page_url(
        self, article_no: str, offset: int = 0, limit: int = 12
    ) -> str:
        """
        게시글 상세 페이지 URL 생성

        Args:
            article_no: 게시글 번호
            offset: offset 값
            limit: limit 값

        Returns:
            상세 페이지 URL
        """
        url = (
            f"{self.BASE_URL}/nhis/minwon/wbhapa01000m01.do"
            f"?mode=view"
            f"&articleNo={article_no}"
            f"&article.offset={offset}"
            f"&articleLimit={limit}"
        )
        return url

    def extract_items(
        self, soup: BeautifulSoup, page: int = 0, limit: int = 12
    ) -> List[Dict]:
        """
        목록 페이지에서 정책/제도 항목 추출

        Args:
            soup: BeautifulSoup 객체
            page: 현재 페이지 번호
            limit: 페이지당 아이템 수

        Returns:
            [{'title': '...', 'article_no': '...', 'url': '...'}, ...]
        """
        items = []

        # 목록 찾기: ul.krds-search-list > li.li
        list_container = soup.find("ul", class_="krds-search-list")
        if not list_container:
            return items

        list_items = list_container.find_all("li", class_="li")

        for item in list_items:
            try:
                # 링크 찾기
                link = item.find("a", class_="c-text")
                if not link:
                    continue

                href = link.get("href", "")
                if not href:
                    continue

                # URL 파싱하여 articleNo 추출
                parsed = urlparse(href)
                query_params = parse_qs(parsed.query)
                article_no = query_params.get("articleNo", [None])[0]

                if not article_no:
                    continue

                # 제목 추출
                title_elem = link.find("p", class_="c-tit")
                if not title_elem:
                    continue

                title_span = title_elem.find("span", class_="span")
                if title_span:
                    title = title_span.get_text(strip=True)
                else:
                    title = title_elem.get_text(strip=True)

                if not title:
                    continue

                # 상세 페이지 URL 생성
                offset = page * limit
                detail_url = self.get_detail_page_url(article_no, offset, limit)

                items.append(
                    {"title": title, "article_no": article_no, "url": detail_url}
                )

            except Exception as e:
                print(f"  [경고] 항목 파싱 중 오류: {e}")
                continue

        return items

    def _process_item_with_tabs(self, item_info: Dict, idx: int, total: int) -> tuple:
        """
        항목 처리 및 탭 링크 감지 (병렬 처리용)

        Args:
            item_info: 항목 정보 {"title": str, "url": str}
            idx: 현재 인덱스
            total: 전체 개수

        Returns:
            (success, result, tab_links) 튜플
        """
        log_buffer = []
        url = item_info["url"]
        name = item_info.get("title", "제목없음")

        log_buffer.append(f"\n[{idx}/{total}] 처리 시도: {name}")
        log_buffer.append(f"  URL: {url}")
        log_buffer.append("    -> 내용 구조화 진행...")

        # BaseParallelCrawler의 process_page_with_tabs 사용
        success, structured_data, tab_links, final_url = self.process_page_with_tabs(
            url=url,
            region="전국",
            title=name,
            log_buffer=log_buffer,
        )

        if success:
            result = structured_data.model_dump()
            log_buffer.append("  [SUCCESS] 성공")
        else:
            result = structured_data  # error_info
            log_buffer.append("  [ERROR] 실패")

        # 로그 출력
        with self.lock:
            for line in log_buffer:
                print(line)

        return success, result, tab_links

    def fetch_detail_content(self, url: str, max_retries: int = 3) -> str:
        """
        상세 페이지 내용 가져오기 (재시도 로직 포함)

        Args:
            url: 상세 페이지 URL
            max_retries: 최대 재시도 횟수

        Returns:
            페이지 본문 텍스트
        """
        for attempt in range(max_retries):
            try:
                # 요청 간격 추가 (서버 부하 방지)
                if attempt > 0:
                    time.sleep(1 * (attempt + 1))  # 재시도 시 지연 증가

                response = self.session.get(url, timeout=20)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")

                # 본문 영역 찾기
                content_selectors = [
                    "#cms-content",
                    ".cms-search",
                    ".content-area",
                    ".article-content",
                    "#content",
                    ".detail-content",
                    "article",
                    ".view-content",
                    ".board-view",
                ]

                content_text = ""
                for selector in content_selectors:
                    content_elem = soup.select_one(selector)
                    if content_elem:
                        content_text = content_elem.get_text(separator="\n", strip=True)
                        if content_text and len(content_text) > 50:
                            break

                # 내용이 없으면 body 전체 텍스트
                if not content_text or len(content_text) < 50:
                    body = soup.find("body")
                    if body:
                        content_text = body.get_text(separator="\n", strip=True)

                return content_text

            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"  [재시도 {attempt + 1}/{max_retries}] {url[:80]}...")
                else:
                    print(f"  [경고] 상세 페이지 로드 최종 실패 ({url[:80]}...): {e}")
                continue

        return ""

    def collect_all_items(
        self,
        max_pages: int = None,
        limit: int = 12,
    ) -> List[Dict]:
        """
        모든 페이지의 항목 수집

        Args:
            max_pages: 최대 페이지 수 (None이면 빈 페이지까지)
            limit: 페이지당 아이템 수

        Returns:
            전체 항목 리스트
        """
        print("\n국민건강보험 정책제도 크롤링 시작...")

        all_items = []
        page = 0
        consecutive_failures = 0
        max_consecutive_failures = 3

        while True:
            # max_pages 제한 확인
            if max_pages and page >= max_pages:
                break

            print(f"  페이지 {page + 1} 처리 중...")

            page_url = self.get_list_page_url(page=page, limit=limit)
            soup = self.fetch_page(page_url)

            if not soup:
                print("    ✗ 페이지 로드 실패")
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    print(f"    연속 {max_consecutive_failures}회 실패 - 크롤링 종료")
                    break
                page += 1
                continue

            # 항목 추출
            items = self.extract_items(soup, page=page, limit=limit)

            # 아이템이 없으면 종료
            if not items or len(items) == 0:
                consecutive_failures += 1
                print(
                    f"    빈 페이지 ({consecutive_failures}/{max_consecutive_failures})"
                )

                if consecutive_failures >= max_consecutive_failures:
                    print(
                        f"    연속 {max_consecutive_failures}회 빈 페이지 - 크롤링 종료"
                    )
                    break

                page += 1
                continue

            consecutive_failures = 0
            all_items.extend(items)
            print(f"    ({len(items)}개)")

            page += 1
            time.sleep(0.5)  # 요청 간격

        print(f"  ✓ 총 {len(all_items)}개 항목 수집 완료")
        return all_items

    def _filter_items_by_keywords(self, items: List[Dict]) -> List[Dict]:
        """
        키워드 기반 항목 필터링

        Args:
            items: 항목 리스트 [{"title": str, "url": str, ...}, ...]

        Returns:
            필터링된 항목 목록
        """
        # 키워드 필터링이 비활성화된 경우
        if config.KEYWORD_FILTER["mode"] == "none":
            return items

        # LinkFilter로 필터링할 형식으로 변환
        items_to_filter = [
            {"name": item["title"], "url": item.get("url", "")} for item in items
        ]

        # LinkFilter로 필터링
        filtered_simple = self.link_filter.filter_by_keywords(
            items_to_filter,
            whitelist=config.KEYWORD_FILTER.get("whitelist"),
            blacklist=config.KEYWORD_FILTER.get("blacklist"),
            mode=config.KEYWORD_FILTER["mode"],
        )

        # 필터링된 제목 집합 생성
        filtered_titles = {link["name"] for link in filtered_simple}

        # 원본 items에서 필터링된 것만 반환
        filtered_items = [item for item in items if item["title"] in filtered_titles]

        print(f"  키워드 필터링: {len(items)}개 → {len(filtered_items)}개")
        return filtered_items

    def run_workflow(
        self,
        max_pages: int = None,
        limit: int = 12,
        output_filename: str = None,
        return_data: bool = False,
        save_json: bool = True,
    ):
        """
        전체 워크플로우 실행: 항목 수집 → 필터링 → 상세 내용 수집 → 저장

        Args:
            max_pages: 최대 페이지 수
            limit: 페이지당 아이템 수
            output_filename: 출력 파일명
            return_data: True면 데이터 반환
            save_json: True면 JSON 파일로 저장
        """
        print("=" * 80)
        print("국민건강보험 크롤링 워크플로우 시작")
        print("=" * 80)

        # 1단계: 항목 수집
        print("\n[1단계] 정책제도 항목 수집 중...")
        print("-" * 80)

        items = self.collect_all_items(max_pages=max_pages, limit=limit)

        if not items:
            print("수집된 항목이 없습니다. 워크플로우를 종료합니다.")
            if return_data:
                return []
            return

        # 초기 링크 저장 (name, url 형식)
        initial_links = [{"name": item["title"], "url": item["url"]} for item in items]
        links_file = os.path.join(self.output_dir, "collected_initial_links.json")
        with open(links_file, "w", encoding="utf-8") as f:
            json.dump(initial_links, f, ensure_ascii=False, indent=2)

        print(f"\n✓ 총 {len(items)}개 항목 수집 완료")
        print(f"✓ 초기 링크 저장: {links_file}")

        # 1.5단계: 키워드 필터링
        if config.KEYWORD_FILTER["mode"] != "none":
            print("\n[1.5단계] 키워드 기반 항목 필터링...")
            print("-" * 80)
            items = self._filter_items_by_keywords(items)

            if not items:
                print(
                    "키워드 필터링 후 처리할 항목이 없습니다. 워크플로우를 종료합니다."
                )
                if return_data:
                    return []
                return

        # 2단계: 각 항목 크롤링 및 구조화 (병렬 처리)
        print("\n[2단계] 정책 크롤링 및 구조화 중...")
        print(f"  - 병렬 워커 수: {self.max_workers}")
        print("-" * 80)

        all_results = []
        failed_items = []
        processed_or_queued_urls = [normalize_url(item["url"]) for item in items]

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_item = {
                executor.submit(
                    self._process_item_with_tabs, item, idx, len(items)
                ): item
                for idx, item in enumerate(items, 1)
            }

            for future in as_completed(future_to_item):
                item_info = future_to_item[future]
                try:
                    success, result, tab_links = future.result()

                    if success:
                        with self.lock:
                            all_results.append(result)
                    else:
                        with self.lock:
                            failed_items.append(result)

                except Exception as e:
                    print(f"  [ERROR] Future 처리 중 오류: {e}")

        success_count = len(all_results)
        fail_count = len(failed_items)

        # 3단계: 결과 저장/반환
        print("\n[3단계] 결과 저장/반환 중...")
        print("-" * 80)
        output_path = None
        if save_json:
            if output_filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_filename = f"structured_data_국민건강보험_{timestamp}.json"
            output_path = os.path.join(self.output_dir, output_filename)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(all_results, f, ensure_ascii=False, indent=2)

        # 결과 요약
        print("\n" + "=" * 80)
        print("워크플로우 완료")
        print("=" * 80)
        print(f"✓ 전체 링크: {len(items)}개")
        print(f"✓ 성공: {success_count}개")
        print(f"✗ 실패: {fail_count}개")
        if save_json:
            print(f"✓ 결과 파일: {output_path}")
        if return_data:
            return all_results
        print("=" * 80)

    def run(self, start_url: str = None, **kwargs):
        """
        크롤러 팩토리 호환용 run() 메서드

        Args:
            start_url: 시작 URL (사용하지 않음, 인터페이스 통일용)
            **kwargs: run_workflow()에 전달할 추가 인자

        Returns:
            크롤링 결과 데이터
        """
        return self.run_workflow(
            max_pages=kwargs.get("max_pages"),
            limit=kwargs.get("limit", 12),
            output_filename=kwargs.get("output_filename"),
            return_data=True,
            save_json=kwargs.get("save_json", True),
        )


def main():
    """메인 실행 함수"""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="국민건강보험 전용 크롤러")
    parser.add_argument(
        "--max-pages",
        type=int,
        help="최대 페이지 수 (기본값: 전체)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=12,
        help="페이지당 아이템 수 (기본값: 12)",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="출력 파일명 (기본값: 자동 생성)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="app/crawling/output",
        help="출력 디렉토리 (기본값: app/crawling/output)",
    )

    args = parser.parse_args()

    # 크롤러 생성 및 실행
    crawler = NHISCrawler(output_dir=args.output_dir)

    try:
        crawler.run_workflow(
            max_pages=args.max_pages,
            limit=args.limit,
            output_filename=args.output,
        )
    except Exception as e:
        print(f"\n✗ 워크플로우 실패: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
