"""
크롤러 팩토리 - URL에서 자동으로 적절한 크롤러 선택

사용법:
    from app.crawling.crawler_factory import get_crawler_for_url

    crawler = get_crawler_for_url(url)
    crawler.run(start_url=url)
"""

import sys
import os

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.crawling.crawlers.district_crawler import DistrictCrawler
from app.crawling.crawlers.specific_crawler.district_menu_crawler import (
    DistrictMenuCrawler,
)
from app.crawling.crawlers.specific_crawler.songpa_crawler import SongpaCrawler
from app.crawling.crawlers.specific_crawler.yangcheon_crawler import YangcheonCrawler
from app.crawling.crawlers.specific_crawler.mapo_crawler import MapoCrawler
from app.crawling.crawlers.specific_crawler.ehealth_crawler import EHealthCrawler
from app.crawling.crawlers.specific_crawler.welfare_crawler import WelfareCrawler
from app.crawling.crawlers.specific_crawler.nhis_crawler import NHISCrawler
from app.crawling import utils


def get_crawler_for_url(
    url: str,
    output_dir: str = None,
    max_workers: int = 4,
    auto_detect_region: bool = True,
):
    """
    URL에서 자동으로 적절한 크롤러 인스턴스 반환

    Args:
        url: 크롤링 시작 URL
        output_dir: 출력 디렉토리 (None이면 자동 설정)
        max_workers: 병렬 처리 worker 수
        auto_detect_region: 지역명 자동 추출 여부

    Returns:
        적절한 크롤러 인스턴스

    Examples:
        >>> crawler = get_crawler_for_url("https://health.gangdong.go.kr/...")
        >>> crawler.run(start_url=url)
    """
    # 지역명 추출
    region_name = None
    if auto_detect_region:
        region_name = utils.extract_region_from_url(url)
        if not region_name or region_name == "unknown":
            region_name = None

    # output_dir 자동 설정
    if output_dir is None and region_name:
        output_dir = f"app/crawling/output/{region_name}"

    # URL 기반 크롤러 선택
    url_lower = url.lower()

    # 1. 특수 크롤러 (도메인 기반)
    if "nhis.or.kr" in url_lower or "국민건강보험" in url_lower:
        print("[Crawler Factory] 국민건강보험 크롤러 선택")
        return NHISCrawler(
            output_dir=output_dir or "app/crawling/output/국민건강보험",
            max_workers=max_workers,
        )

    if "wis.seoul.go.kr" in url_lower or "서울복지포털" in url_lower:
        print("[Crawler Factory] 서울복지포털 크롤러 선택")
        return WelfareCrawler(
            output_dir=output_dir or "app/crawling/output/서울복지포털"
        )

    if "e-health" in url_lower or "e-보건소" in url_lower:
        print("[Crawler Factory] e보건소 크롤러 선택")
        return EHealthCrawler(output_dir=output_dir or "app/crawling/output/e보건소")

    # 2. 구별 특수 크롤러
    if "songpa" in url_lower or "송파" in (region_name or ""):
        print("[Crawler Factory] 송파구 크롤러 선택")
        return SongpaCrawler(
            start_url=url,
            output_dir=output_dir or "app/crawling/output/송파구",
            max_workers=max_workers,
        )

    if "yangcheon" in url_lower or "양천" in (region_name or ""):
        print("[Crawler Factory] 양천구 크롤러 선택")
        return YangcheonCrawler(
            start_url=url,
            output_dir=output_dir or "app/crawling/output/양천구",
            max_workers=max_workers,
        )

    if "mapo" in url_lower or "마포" in (region_name or ""):
        print("[Crawler Factory] 마포구 크롤러 선택")
        return MapoCrawler(
            start_url=url,
            output_dir=output_dir or "app/crawling/output/마포구",
            max_workers=max_workers,
        )

    # 3. 통합 메뉴 크롤러
    if region_name in [
        "은평구",
        "강동구",
        "관악구",
        "동대문구",
        "종로구",
        "중랑구",
        "중구",
        "성동구",
        "영등포구",
        "용산구",
        # "서초구",
    ]:
        print(f"[Crawler Factory] {region_name} 통합 메뉴 크롤러 선택")
        return DistrictMenuCrawler(
            district_name=region_name,
            start_url=url,
            output_dir=output_dir,
            max_workers=max_workers,
        )

    # 4. 기본 district_crawler (범용)
    print(
        f"[Crawler Factory] 기본 District 크롤러 선택 (지역: {region_name or '미상'})"
    )
    return DistrictCrawler(
        output_dir=output_dir or "app/crawling/output",
        region=region_name,
        max_workers=max_workers,
    )


# 편의 함수: URL로 바로 크롤링 시작
def crawl_url(url: str, **kwargs):
    """
    URL을 받아서 자동으로 크롤링 시작

    Args:
        url: 크롤링 시작 URL
        **kwargs: get_crawler_for_url()에 전달할 추가 인자

    Returns:
        크롤링 결과 요약

    Examples:
        >>> from app.crawling.crawler_factory import crawl_url
        >>> summary = crawl_url("https://health.gangdong.go.kr/...")
    """
    crawler = get_crawler_for_url(url, **kwargs)
    return crawler.run(start_url=url)


if __name__ == "__main__":
    url = input("크롤링할 URL을 입력하세요: ").strip()
    print(f"URL: {url}")
    print("=" * 80)

    crawler = get_crawler_for_url(url)
    print(f"선택된 크롤러: {crawler.__class__.__name__}")
    print("=" * 80)

    # 실제 크롤링 시작
    crawler.run(start_url=url)
