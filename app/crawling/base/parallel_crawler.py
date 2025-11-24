"""
병렬 처리와 탭 지원을 위한 베이스 크롤러

모든 크롤러에서 공통으로 사용하는 병렬 처리, 로그 버퍼링, 탭 링크 처리 등의 기능을 제공합니다.
"""

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Callable, Tuple, Any
from datetime import datetime
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.crawling.base.base_crawler import BaseCrawler
from app.crawling.base.llm_crawler import LLMStructuredCrawler
from app.crawling.components.link_filter import LinkFilter
from app.crawling.components.page_processor import PageProcessor
from app.crawling.utils import normalize_url
from app.crawling import config


def detect_redirect(original_url: str, final_url: str) -> Optional[str]:
    """
    리다이렉트 감지

    Args:
        original_url: 원래 요청한 URL
        final_url: 최종 리다이렉트된 URL

    Returns:
        리다이렉트 메시지 또는 None
    """
    if not final_url or normalize_url(final_url) == normalize_url(original_url):
        return None
    return f"    ℹ️  리다이렉트: {original_url} → {final_url}"


class URLTracker:
    """URL 추적 및 중복 방지 유틸리티"""

    def __init__(self):
        self.processed_urls = set()  # 정규화된 URL 저장

    def is_duplicate(self, url: str) -> bool:
        """URL 중복 체크 (정규화 후)"""
        normalized = normalize_url(url)
        return normalized in self.processed_urls

    def add_url(self, url: str) -> str:
        """URL 추가 및 정규화된 URL 반환"""
        normalized = normalize_url(url)
        self.processed_urls.add(normalized)
        return normalized


class BaseParallelCrawler(BaseCrawler):
    """병렬 처리와 탭 지원을 위한 베이스 크롤러"""

    def __init__(
        self,
        output_dir: str = "app/crawling/output",
        max_workers: int = 4,
        model: str = "gpt-4o-mini",
    ):
        """
        Args:
            output_dir: 결과 저장 디렉토리 (상대 경로 또는 절대 경로)
            max_workers: 병렬 처리 워커 수
            model: LLM 모델명
        """
        super().__init__()

        # output_dir을 절대 경로로 변환
        # 상대 경로인 경우 프로젝트 루트 기준으로 변환
        if not os.path.isabs(output_dir):
            # 프로젝트 루트 찾기 (app 폴더의 부모)
            current_file = os.path.abspath(__file__)
            # base/parallel_crawler.py -> base -> crawling -> app -> 프로젝트 루트
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_file))))
            output_dir = os.path.join(project_root, output_dir)

        self.output_dir = output_dir
        self.max_workers = max_workers

        # 공통 컴포넌트
        self.llm_crawler = LLMStructuredCrawler(model=model)
        self.link_filter = LinkFilter()
        self.page_processor = PageProcessor()

        # Thread-safe 처리
        self.lock = threading.Lock()

        # 디렉토리 생성
        os.makedirs(output_dir, exist_ok=True)

    def process_page_with_tabs(
        self,
        url: str,
        region: str,
        title: str = None,
        log_buffer: List[str] = None,
    ) -> Tuple[bool, Any, List[Dict], Optional[str]]:
        """
        페이지 처리 및 탭 링크 감지

        Args:
            url: 페이지 URL
            region: 지역명
            title: 페이지 제목 (None이면 자동 결정)
            log_buffer: 로그 버퍼 (None이면 새로 생성)

        Returns:
            (success, structured_data, tab_links, final_url)
        """
        if log_buffer is None:
            log_buffer = []

        try:
            # 1. 페이지 가져오기 (리다이렉트 추적)
            soup, final_url = self.fetch_page(url, return_final_url=True)

            # 2. 리다이렉트 로깅
            redirect_msg = detect_redirect(url, final_url)
            if redirect_msg:
                log_buffer.append(redirect_msg)

            # 3. 탭 감지
            tab_links = self.page_processor.find_tabs_on_page(
                soup, final_url or url
            )
            if tab_links:
                log_buffer.append(f"    ℹ️  탭 {len(tab_links)}개 감지")

            # 4. LLM 구조화
            structured_data = self.llm_crawler.crawl_and_structure(
                url=final_url or url, region=region, title=title
            )

            return True, structured_data, tab_links, final_url

        except Exception as e:
            error_info = {"url": url, "error": str(e)}
            log_buffer.append(f"    ✗ 크롤링 실패: {e}")
            return False, error_info, [], None

    def apply_keyword_filter(
        self,
        items: List[Dict],
        text_key: str = "name",
        enable_filter: bool = True,
        verbose: bool = True,
    ) -> List[Dict]:
        """
        키워드 필터 적용

        Args:
            items: 필터링할 항목 리스트
            text_key: 각 항목에서 텍스트를 추출할 키 (기본값: "name")
            enable_filter: 필터링 활성화 여부
            verbose: 상세 로그 출력 여부

        Returns:
            필터링된 항목 리스트
        """
        if not enable_filter or config.KEYWORD_FILTER["mode"] == "none":
            return items

        filtered = []
        for item in items:
            # 텍스트 추출 (여러 키 지원)
            if isinstance(text_key, str):
                text = item.get(text_key, "")
            elif callable(text_key):
                text = text_key(item)
            else:
                text = ""

            passed, reason = self.link_filter.check_keyword_filter(
                text,
                whitelist=config.KEYWORD_FILTER.get("whitelist"),
                blacklist=config.KEYWORD_FILTER.get("blacklist"),
                mode=config.KEYWORD_FILTER["mode"],
            )

            if passed:
                filtered.append(item)
                if verbose:
                    print(f"  ✓ [포함] {text}")
            elif verbose:
                print(f"  ✗ [제외] {text} - {reason}")

        return filtered

    def process_items_parallel(
        self,
        items: List[Dict],
        process_func: Callable,
        enable_tab_processing: bool = True,
    ) -> Tuple[List[Any], int, int]:
        """
        항목들을 병렬로 처리 (탭 링크 자동 처리 포함)

        Args:
            items: 처리할 항목 리스트
            process_func: 각 항목을 처리할 함수 (item, idx, total) -> (success, result, tab_links)
            enable_tab_processing: 탭 링크 자동 처리 여부

        Returns:
            (all_results, success_count, fail_count)
        """
        all_results = []
        success_count = 0
        fail_count = 0
        additional_tab_links = []

        # 1단계: 초기 항목 병렬 처리
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_item = {
                executor.submit(process_func, item, idx, len(items)): item
                for idx, item in enumerate(items, 1)
            }

            for future in as_completed(future_to_item):
                try:
                    success, result, tab_links = future.result()

                    if success and result:
                        all_results.append(result)
                        success_count += 1

                        # 탭 링크 수집
                        if enable_tab_processing and tab_links:
                            additional_tab_links.extend(tab_links)
                    else:
                        fail_count += 1

                except Exception as e:
                    fail_count += 1
                    with self.lock:
                        print(f"✗ 작업 처리 중 오류: {e}")

        # 2단계: 탭 링크 처리
        if enable_tab_processing and additional_tab_links:
            print(
                f"\n[탭 링크 처리] 총 {len(additional_tab_links)}개의 탭 링크 발견"
            )
            print("-" * 80)

            # 키워드 필터링
            if config.KEYWORD_FILTER["mode"] != "none":
                # text 또는 name 키 사용
                text_extractor = lambda x: x.get("text") or x.get("name", "")
                filtered_tabs = self.apply_keyword_filter(
                    additional_tab_links,
                    text_key=text_extractor,
                    enable_filter=True,
                    verbose=True,
                )
                additional_tab_links = filtered_tabs
                print(f"\n필터링 후 {len(additional_tab_links)}개 탭 링크 선택됨")

            # 탭 링크 병렬 처리
            if additional_tab_links:
                print(
                    f"\n탭 링크 크롤링 시작 ({len(additional_tab_links)}개)..."
                )

                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    future_to_tab = {
                        executor.submit(
                            process_func,
                            tab,
                            idx,
                            len(additional_tab_links),
                        ): tab
                        for idx, tab in enumerate(additional_tab_links, 1)
                    }

                    for future in as_completed(future_to_tab):
                        try:
                            success, result, _ = future.result()
                            if success and result:
                                all_results.append(result)
                                success_count += 1
                            else:
                                fail_count += 1
                        except Exception as e:
                            fail_count += 1
                            with self.lock:
                                print(f"✗ 탭 링크 처리 중 오류: {e}")

        return all_results, success_count, fail_count

    def save_results(
        self,
        results: List[Dict],
        filename: str = None,
        timestamp: bool = True,
    ) -> str:
        """
        결과를 JSON 파일로 저장

        Args:
            results: 저장할 결과 리스트
            filename: 파일명 (None이면 자동 생성)
            timestamp: 타임스탬프 추가 여부

        Returns:
            저장된 파일 경로
        """
        if filename is None:
            filename = "crawling_results"

        if timestamp:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{filename}_{ts}"

        if not filename.endswith(".json"):
            filename += ".json"

        output_path = os.path.join(self.output_dir, filename)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        return output_path

    def log_with_buffer(
        self, func: Callable, *args, **kwargs
    ) -> Any:
        """
        로그 버퍼를 사용하는 함수를 래핑하여 thread-safe 출력

        Args:
            func: 실행할 함수 (log_buffer를 인자로 받아야 함)

        Returns:
            func의 반환값
        """
        log_buffer = []
        result = func(*args, log_buffer=log_buffer, **kwargs)

        # 한 번에 출력
        with self.lock:
            for line in log_buffer:
                print(line)

        return result
