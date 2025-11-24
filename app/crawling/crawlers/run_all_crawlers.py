"""
여러 보건소 URL을 순회하며 district_crawler의 워크플로우를 실행하는 스크립트
"""

import os
import sys
import time
import traceback
from app.crawling import utils
from app.crawling.crawler_factory import get_crawler_for_url


# 이 파일의 위치(app/crawling/crawlers)를 기준으로
# 프로젝트 최상위 경로(HealthInformer)를 찾아 시스템 경로에 추가합니다.
project_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
sys.path.insert(0, project_root)


def run_batch_crawling():
    """
    지정된 보건소 URL 목록을 순회하며 크롤링을 실행하고,
    각 결과를 지역별로 분리된 디렉터리에 저장합니다.
    """
    # =================================================================
    # 크롤링할 보건소의 '보건사업' 또는 유사한 메뉴의 시작 URL 목록
    # 여기에 다른 보건소 URL을 추가하거나 수정할 수 있습니다.
    # =================================================================
    target_urls = [
        "https://health.gangnam.go.kr/web/business/support/sub01.do",  # 강남구
        "https://health.gangdong.go.kr/health/site/main/content/GD20030100",  # 강동구
        "https://www.gangbuk.go.kr/health/main/contents.do?menuNo=400151",  # 강북구
        "https://www.gangseo.seoul.kr/health/ht020231",  # 강서구
        "https://www.gwanak.go.kr/site/health/05/10502010600002024101710.jsp",  # 관악구
        "https://www.gwangjin.go.kr/health/main/contents.do?menuNo=300080",  # 광진구
        "https://www.guro.go.kr/health/contents.do?key=1320&",  # 구로구
        "https://health.dobong.go.kr/Contents.asp?code=10005042",  # 도봉구
        "https://www.ddm.go.kr/health/contents.do?key=1257",  # 동대문구
        "https://www.dongjak.go.kr/healthcare/main/contents.do?menuNo=300342",  # 동작구
        "https://www.sdm.go.kr/health/contents/infectious/law",  # 서대문구
        "https://www.seocho.go.kr/site/sh/03/10301000000002015070902.jsp",  # 서초구
        "https://www.sb.go.kr/bogunso/contents.do?key=6553",  # 성북구
        "https://www.yangcheon.go.kr/health/health/02/10201010000002024022101.jsp",  # 양천구
        "https://www.ydp.go.kr/health/contents.do?key=6073&",  # 영등포구
        "https://www.yongsan.go.kr/health/main/contents.do?menuNo=300064",  # 용산구
        "https://www.ep.go.kr/health/contents.do?key=1582",  # 은평구
        "https://www.songpa.go.kr/ehealth/contents.do?key=4525&",  # 송파구
        "https://jongno.go.kr/Health.do?menuId=401309&menuNo=401309",  # 종로구
        "https://www.junggu.seoul.kr/health/content.do?cmsid=15845",  # 중구
        "https://www.jungnang.go.kr/health/bbs/list/B0000412.do?menuNo=400364#n",  # 중랑구
    ]

    # 절대 경로를 사용하여 output 디렉토리 위치를 명확히 지정합니다.
    base_output_dir = os.path.join(project_root, "app", "crawling", "output")
    print(f"총 {len(target_urls)}개의 보건소에 대한 크롤링을 시작합니다.")
    print("=" * 80)

    batch_start_time = time.time()

    # 각 URL에 대해 워크플로우 실행
    for i, url in enumerate(target_urls, 1):
        try:
            # URL에서 지역명 추출
            region_name = utils.extract_region_from_url(url)
            if not region_name or region_name == "unknown":
                print(
                    f"[{i}/{len(target_urls)}] 경고: {url} 에서 지역명을 추출할 수 없습니다. 'unknown_region_{i}'으로 처리합니다."
                )
                region_name = f"unknown_region_{i}"

            print(f"[{i}/{len(target_urls)}] '{region_name}' 보건소 워크플로우 시작...")
            print(f"  - URL: {url}")

            # 결과를 저장할 지역별 출력 디렉토리 설정
            output_dir_for_region = os.path.join(base_output_dir, region_name)
            os.makedirs(output_dir_for_region, exist_ok=True)

            # 크롤러 팩토리 사용 (URL만으로 자동 선택)
            workflow = get_crawler_for_url(
                url=url,
                output_dir=output_dir_for_region,
                max_workers=4,
            )

            summary = workflow.run(start_url=url)

            print(f"[{i}/{len(target_urls)}] '{region_name}' 보건소 워크플로우 완료.")
            if summary:
                print(
                    f"  - 결과 요약: {summary.get('successful_structured', 0)}개 성공, {summary.get('failed_processing', 0)}개 실패"
                )
            else:
                print("  - 요약 정보를 가져오지 못했습니다.")
            print("-" * 80)

        except Exception as e:
            print(f"[{i}/{len(target_urls)}] URL {url} 처리 중 심각한 오류 발생: {e}")
            traceback.print_exc()
            print("-" * 80)

    batch_duration = time.time() - batch_start_time

    print("\n" + "=" * 80)
    print("모든 보건소 크롤링 작업이 완료되었습니다.")
    print(f"총 실행 시간: {batch_duration:.2f}초 ({batch_duration / 60:.2f}분)")
    print("=" * 80)

    # 전체 통계 출력
    utils.get_timing_stats().print_summary()


if __name__ == "__main__":
    run_batch_crawling()
