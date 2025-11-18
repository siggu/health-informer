"""
서울시 복지포털(wis.seoul.go.kr) 전용 크롤러

서울시 복지포털에서 건강 관련 복지 서비스 정보를 수집합니다.
- 전체 복지 서비스 목록 가져오기
- 건강 관련 키워드로 필터링
- 각 서비스 상세 정보 크롤링 및 구조화
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
from bs4 import BeautifulSoup
import json
import re
from typing import List, Dict, Optional
import os
from datetime import datetime

from ... import config
from ...base.parallel_crawler import BaseParallelCrawler


class WelfareCrawler(BaseParallelCrawler):
    """서울시 복지포털 전용 크롤러"""

    def __init__(self, output_dir: str = "app/crawling/output", max_workers: int = 4):
        """
        Args:
            output_dir: 결과 저장 디렉토리
            max_workers: 병렬 처리 워커 수 (기본값: 4)
        """
        super().__init__(output_dir=output_dir, max_workers=max_workers)
        self.base_url = "https://wis.seoul.go.kr"
        self.search_url = "https://wis.seoul.go.kr/sec/ctg/categorySearch.do"

    def collect_all_services(self) -> List[Dict]:
        """
        서울시 복지포털에서 모든 복지 서비스 목록 수집

        Returns:
            복지 서비스 정보 리스트 [{'name': ..., 'url': ...}]
        """
        print("\n복지포털에서 전체 서비스 목록 가져오는 중...")

        try:
            # GET 방식으로 페이지 요청
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            }

            response = self.session.get(self.search_url, headers=headers, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # 카드 리스트에서 항목 추출
            card_list = soup.find("ul", class_="card-ls")

            if not card_list:
                print("오류: 복지 서비스 목록을 찾을 수 없습니다.")
                return []

            items = card_list.find_all("li")
            print(f"  ✓ 총 {len(items)}개의 복지 서비스 발견")

            services = []

            for item in items:
                service_info = self._parse_service_item(item)
                if service_info:
                    services.append(service_info)

            return services

        except Exception as e:
            print(f"오류: 복지 서비스 목록 수집 실패 - {e}")
            return []

    def _parse_service_item(self, item) -> Optional[Dict]:
        """
        개별 서비스 항목 파싱

        Args:
            item: BeautifulSoup li 요소

        Returns:
            서비스 정보 딕셔너리 또는 None
        """
        try:
            name = "제목 없음"
            detail_id = ""

            # 제목과 설명 추출
            con_dl = item.find("dl", class_="con")
            if con_dl:
                name_tag = con_dl.find("dt")
                if name_tag:
                    name = name_tag.get_text(strip=True)

            # 상세보기 ID 추출 (javascript:detailOpen(ID))
            detail_link = item.find("a", class_="btn-sss")
            if detail_link:
                href = detail_link.get("href", "")
                match = re.search(r"detailOpen\((\d+)\)", href)
                if match:
                    detail_id = match.group(1)

            if not detail_id:
                return None

            return {
                "name": name,
                "url": f"https://wis.seoul.go.kr/sec/ctg/categoryDetail.do?id={detail_id}",
            }

        except Exception as e:
            print(f"    경고: 항목 파싱 실패 - {e}")
            return None

    def filter_health_services(self, services: List[Dict]) -> List[Dict]:
        """
        건강 관련 키워드로 서비스 필터링 (config.KEYWORD_FILTER 사용)

        Args:
            services: 전체 서비스 리스트

        Returns:
            필터링된 서비스 리스트
        """
        if config.KEYWORD_FILTER["mode"] == "none":
            return services

        print(
            f"\n[키워드 필터링] 총 {len(services)}개 서비스를 '{config.KEYWORD_FILTER['mode']}' 모드로 필터링 중..."
        )

        filtered = []
        excluded = []

        for service in services:
            combined_text = service["name"]

            # LinkFilter의 check_keyword_filter 사용
            passed, reason = self.link_filter.check_keyword_filter(
                combined_text,
                whitelist=config.KEYWORD_FILTER.get("whitelist"),
                blacklist=config.KEYWORD_FILTER.get("blacklist"),
                mode=config.KEYWORD_FILTER["mode"],
            )

            if passed:
                filtered.append(service)
                print(f"  ✓ [포함] {service['name']}")
            else:
                excluded.append({"name": service["name"], "reason": reason})
                print(f"  ✗ [제외] {service['name']} - {reason}")

        print(
            f"\n[키워드 필터링 완료] {len(services)}개 중 {len(filtered)}개 서비스 선택됨 (제외: {len(excluded)}개)"
        )
        return filtered

    def _process_service_with_tabs(
        self, service_info: Dict, idx: int, total: int
    ) -> tuple:
        """
        개별 서비스를 처리하고 탭 링크를 감지합니다 (병렬 처리용).

        Args:
            service_info: 서비스 정보 {'name': ..., 'url': ..., ...}
            idx: 현재 인덱스
            total: 전체 개수

        Returns:
            (success: bool, result: Dict, tab_links: List[Dict])
        """
        log_buffer = []
        url = service_info["url"]
        name = service_info["name"]

        log_buffer.append(f"\n진행: {idx}/{total} - {name}")

        # BaseParallelCrawler의 process_page_with_tabs 사용
        success, structured_data, tab_links, final_url = self.process_page_with_tabs(
            url=url,
            region="서울시",
            title=name,
            log_buffer=log_buffer,
        )

        if success:
            result = structured_data.model_dump()
            log_buffer.append("  ✓ 완료")
        else:
            result = None
            log_buffer.append("  ✗ 실패")

        # 로그 출력 (thread-safe)
        with self.lock:
            for line in log_buffer:
                print(line)

        return success, result, tab_links

    def crawl_and_structure_service(self, service_info: Dict) -> Optional[Dict]:
        """
        복지 서비스 상세 페이지 크롤링 및 구조화

        Args:
            service_info: 서비스 정보 {'name': ..., 'url': ..., ...}

        Returns:
            구조화된 데이터 또는 None (실패 시)
        """
        try:
            # LLM 크롤러로 구조화
            structured_data = self.llm_crawler.crawl_and_structure(
                url=service_info["url"],
                region="서울시",
                title=service_info["name"],
            )

            # 표준 필드만 반환
            return structured_data.model_dump()

        except Exception as e:
            print(f"    ✗ 크롤링 실패: {e}")
            return None

    def run_workflow(
        self,
        filter_health: bool = True,
        max_items: int = None,
        output_filename: str = None,
        return_data: bool = False,
        save_json: bool = True,
    ):
        """
        전체 워크플로우 실행: 수집 → 필터링 → 크롤링 → 저장

        Args:
            filter_health: 건강 관련만 필터링할지 여부
            max_items: 최대 처리 항목 수 (None이면 전체)
            output_filename: 출력 파일명 (None이면 자동 생성)
        """
        print("=" * 80)
        print("서울시 복지포털 크롤링 워크플로우 시작")
        print("=" * 80)

        # 1단계: 전체 서비스 목록 수집
        print("\n[1단계] 복지 서비스 목록 수집 중...")
        print("-" * 80)

        all_services = self.collect_all_services()

        if not all_services:
            print("처리할 서비스가 없습니다. 워크플로우를 종료합니다.")
            return

        # 2단계: 건강 관련 필터링 (옵션)
        if filter_health:
            print("\n[2단계] 건강 관련 서비스 필터링 중...")
            print("-" * 80)
            services_to_process = self.filter_health_services(all_services)
        else:
            services_to_process = all_services

        # 최대 개수 제한
        if max_items:
            services_to_process = services_to_process[:max_items]
            print(f"\n최대 {max_items}개로 제한하여 처리합니다.")

        # 링크 목록 저장
        links_file = os.path.join(self.output_dir, "welfare_collected_links.json")
        with open(links_file, "w", encoding="utf-8") as f:
            json.dump(services_to_process, f, ensure_ascii=False, indent=2)
        print(f"\n✓ 처리 대상: {len(services_to_process)}개")
        print(f"✓ 링크 목록 저장: {links_file}")

        # 3단계: 각 서비스 크롤링 및 구조화 (병렬 처리)
        print("\n[3단계] 서비스 크롤링 및 구조화 중...")
        print(f"  병렬 처리: {self.max_workers}개 워커 사용")
        print("-" * 80)

        all_results = []
        success_count = 0
        fail_count = 0
        additional_tab_links = []

        # ThreadPoolExecutor를 사용한 병렬 처리
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 모든 작업 제출
            future_to_service = {
                executor.submit(
                    self._process_service_with_tabs,
                    service_info,
                    idx,
                    len(services_to_process),
                ): service_info
                for idx, service_info in enumerate(services_to_process, 1)
            }

            # 완료된 작업 처리
            for future in as_completed(future_to_service):
                try:
                    success, result, tab_links = future.result()

                    if success and result:
                        all_results.append(result)
                        success_count += 1

                        # 탭 링크 수집
                        if tab_links:
                            additional_tab_links.extend(tab_links)
                    else:
                        fail_count += 1

                except Exception as e:
                    fail_count += 1
                    with self.lock:
                        print(f"✗ 작업 처리 중 오류: {e}")

        # 탭 링크 처리
        if additional_tab_links:
            print(f"\n[탭 링크 처리] 총 {len(additional_tab_links)}개의 탭 링크 발견")
            print("-" * 80)

            # 키워드 필터링 적용
            if config.KEYWORD_FILTER["mode"] != "none":
                filtered_tabs = []
                for tab_link in additional_tab_links:
                    passed, reason = self.link_filter.check_keyword_filter(
                        tab_link["text"],
                        whitelist=config.KEYWORD_FILTER.get("whitelist"),
                        blacklist=config.KEYWORD_FILTER.get("blacklist"),
                        mode=config.KEYWORD_FILTER["mode"],
                    )
                    if passed:
                        filtered_tabs.append(tab_link)
                        print(f"  ✓ [포함] {tab_link['text']}")
                    else:
                        print(f"  ✗ [제외] {tab_link['text']} - {reason}")

                additional_tab_links = filtered_tabs
                print(f"\n필터링 후 {len(additional_tab_links)}개 탭 링크 선택됨")

            # 탭 링크도 병렬 처리
            if additional_tab_links:
                print(f"\n탭 링크 크롤링 시작 ({len(additional_tab_links)}개)...")

                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    # 탭 링크를 서비스 정보 형태로 변환
                    tab_services = [
                        {
                            "name": tab["text"],
                            "url": tab["url"],
                        }
                        for tab in additional_tab_links
                    ]

                    future_to_tab = {
                        executor.submit(
                            self._process_service_with_tabs,
                            tab_service,
                            idx,
                            len(tab_services),
                        ): tab_service
                        for idx, tab_service in enumerate(tab_services, 1)
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

        # 4단계: 결과 저장
        print("\n[4단계] 결과 저장 중...")
        print("-" * 80)

        output_path = None
        if save_json:
            if output_filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_filename = f"welfare_structured_data_{timestamp}.json"
            output_path = os.path.join(self.output_dir, output_filename)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(all_results, f, ensure_ascii=False, indent=2)

        # 결과 요약
        print("\n" + "=" * 80)
        print("워크플로우 완료")
        print("=" * 80)
        print(f"✓ 전체 서비스: {len(all_services)}개")
        if filter_health:
            print(f"✓ 필터링된 서비스: {len(services_to_process)}개")
        if additional_tab_links:
            print(f"✓ 탭 링크 추가 처리: {len(additional_tab_links)}개")
        print(f"✓ 성공: {success_count}개")
        print(f"✗ 실패: {fail_count}개")
        if save_json:
            print(f"✓ 결과 파일: {output_path}")
        print("=" * 80)

        if return_data:
            return all_results

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
            filter_health=kwargs.get("filter_health", True),
            max_items=kwargs.get("max_items"),
            output_filename=kwargs.get("output_filename"),
            return_data=True,
            save_json=kwargs.get("save_json", True),
        )


def main():
    """메인 실행 함수"""
    import argparse

    parser = argparse.ArgumentParser(description="서울시 복지포털 전용 크롤러")
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="건강 관련 필터링 비활성화 (전체 서비스 크롤링)",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        help="최대 처리 항목 수 (기본값: 전체)",
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
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="병렬 처리 워커 수 (기본값: 4)",
    )

    args = parser.parse_args()

    # 크롤러 생성 및 실행
    crawler = WelfareCrawler(output_dir=args.output_dir, max_workers=args.max_workers)

    try:
        crawler.run_workflow(
            filter_health=not args.no_filter,
            max_items=args.max_items,
            output_filename=args.output,
        )
    except Exception as e:
        print(f"\n✗ 워크플로우 실패: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
