# -*- coding: utf-8 -*-
from bs4 import BeautifulSoup
import json
from typing import Optional, Dict
from openai import OpenAI
from pydantic import BaseModel, Field
import os
import uuid
from dotenv import load_dotenv
import sys
import re

# 환경 변수 로드
load_dotenv()

# 상위 디렉토리 경로 추가 (프로젝트 구조에 맞게 조정)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# BaseCrawler import (프로젝트의 기존 경로에 맞춰 유지)
from base.base_crawler import BaseCrawler


# ─────────────────────────────────────────────────────────────────────
# Pydantic 모델: 최종 산출 스키마 (+ 평가 점수, faithfulness 제외)
# ─────────────────────────────────────────────────────────────────────
class HealthSupportInfo(BaseModel):
    """건강 지원 정보 표준 스키마 + 평가 점수(0~100)"""

    id: str = Field(description="고유 ID (UUID)")
    title: str = Field(description="공고/사업/프로그램의 제목(한 줄)")
    support_target: str = Field(description="지원 대상 또는 신청/참가 자격 요약")
    support_content: str = Field(description="지원 내용/혜택/지원 항목 요약")
    raw_text: Optional[str] = Field(default=None, description="원문 텍스트")
    source_url: Optional[str] = Field(default=None, description="출처 URL")
    region: Optional[str] = Field(default=None, description="지역명 (예: 광진구, 전국)")
    eval_scores: Optional[Dict[str, int]] = Field(default=None, description="세부 평가 점수(JSON)")
    eval_overall: Optional[int] = Field(default=None, description="총점(0~100)")


# LLM 응답 스키마(Structured Output)
class _EvalScores(BaseModel):
    richness_target: int = Field(ge=0, le=100)
    richness_content: int = Field(ge=0, le=100)
    criterion_fit_target: int = Field(ge=0, le=100)
    criterion_fit_content: int = Field(ge=0, le=100)


class _LLMResponseWithTitle(BaseModel):
    title: str
    support_target: str
    support_content: str
    scores: _EvalScores
    overall: int = Field(ge=0, le=100)


class _LLMResponseNoTitle(BaseModel):
    support_target: str
    support_content: str
    scores: _EvalScores
    overall: int = Field(ge=0, le=100)


# ─────────────────────────────────────────────────────────────────────
# Crawler 본체
# ─────────────────────────────────────────────────────────────────────
class LLMStructuredCrawler(BaseCrawler):
    """LLM을 사용하여 크롤링 데이터를 구조화하는 크롤러 (weak inference 제거, 수치 가산 유지)"""

    def __init__(self, api_key: str = None, model: str = "gpt-4o"):
        super().__init__()
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY가 필요합니다.")
        self.client = OpenAI(api_key=self.api_key)
        self.model = model

    # ─────────────────────────────────────────────────────────────────
    # HTML 파싱/정리
    # ─────────────────────────────────────────────────────────────────
    def parse_html_file(self, file_path: str) -> BeautifulSoup:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            return BeautifulSoup(html_content, "html.parser")
        except Exception as e:
            print(f"파일 읽기 실패: {e}")
            return None

    def _extract_text_content(self, soup: BeautifulSoup, max_chars: int = 200000) -> str:
        """HTML에서 주요 텍스트 내용 추출"""
        soup_copy = BeautifulSoup(str(soup), "html.parser")

        # 1) 불필요 요소 제거
        for selector in [
            "nav", "header", "footer", ".sidebar", ".menu", ".navigation",
            "#nav", "#header", "#footer", ".ad", ".advertisement",
            "script", "style", "noscript", ".cookie-banner", ".popup",
        ]:
            for el in soup_copy.select(selector):
                el.decompose()

        # 2) 메인 콘텐츠 영역 선택
        content_area = None
        for selector in [
            "main", "#content", "#main", ".content", ".main-content",
            ".contentArea", ".content-area", "article", ".article", "[role='main']",
        ]:
            content_area = soup_copy.select_one(selector)
            if content_area:
                break
        if not content_area:
            content_area = soup_copy.find("body") or soup_copy

        # 3) 테이블을 구조화 텍스트로 변환
        text_parts = []
        for table in content_area.find_all("table"):
            table_lines = ["[표 시작]"]
            headers = [th.get_text(strip=True) for th in table.find_all("th") if th.get_text(strip=True)]
            if headers:
                header_line = " | ".join(headers)
                table_lines.append(header_line)
                table_lines.append("-" * len(header_line))
            for row in table.find_all("tr"):
                cells = [cell.get_text(strip=True) for cell in row.find_all(["td", "th"]) if cell.get_text(strip=True)]
                if cells:
                    table_lines.append(" | ".join(cells))
            table_lines.append("[표 끝]\n")
            text_parts.append("\n".join(table_lines))
            table.decompose()

        # 4) 일반 텍스트
        text = content_area.get_text(separator="\n", strip=True)
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        general_text = "\n".join(lines)
        cleaned_text = general_text + ("\n\n" + "\n\n".join(text_parts) if text_parts else "")

        # 5) 길이 제한
        if len(cleaned_text) > max_chars:
            print(f"    ⚠️ 텍스트가 너무 깁니다 ({len(cleaned_text):,}자). {max_chars:,}자로 자릅니다.")
            cleaned_text = cleaned_text[:max_chars] + "\n\n[... 텍스트가 잘렸습니다 ...]"
        return cleaned_text

    # ─────────────────────────────────────────────────────────────────
    # 지역 일반화(후처리): 강북구민/동작구 주민 등 → 지역구민 (근거 없으면 제거)
    # ─────────────────────────────────────────────────────────────────
    def _generalize_region_terms(self, text: str) -> str:
        if not text:
            return text
        t = re.sub(r"([가-힣]+구)\s*(주민|구민|거주자)", "지역구민", text)
        t = re.sub(r"([가-힣]+구[\s·,]+)+주민", "지역구민", t)
        return t

    # ─────────────────────────────────────────────────────────────────
    # 추론 방지 / 증거 기반 강제 로직 (weak inference 제거)
    # ─────────────────────────────────────────────────────────────────
    _TARGET_KEYS = [
        "지원대상", "대상", "신청대상", "참여대상", "이용대상",
        "신청자격", "자격요건", "자격", "해당자"
    ]
    _RESIDENT_KEYS = ["구민", "주민", "거주자", "거주", "주소지", "해당 구"]

    def _has_explicit_target_signal(self, raw: str) -> bool:
        raw_no_space = raw.replace(" ", "")
        return any(k in raw or k in raw_no_space for k in self._TARGET_KEYS)

    def _has_resident_evidence(self, raw: str) -> bool:
        return any(k in raw for k in self._RESIDENT_KEYS)

    def _contains_numeric_detail(self, text: str) -> bool:
        if not text:
            return False
        # 금액, 횟수, 기간, 비율 등 숫자 패턴 탐지
        return bool(re.search(r"(\d[\d,\.]*\s*(원|회|일|개월|주|시간|%|명|가구|건))", text))

    def _dedupe_lines(self, text: str) -> str:
        """간단 중복 제거: 공백/기호 차이만 있는 유사 라인 정규화 후 dedupe"""
        if not text:
            return text
        norm = lambda s: re.sub(r"[ \t]+", " ", re.sub(r"[·•\-\u2022]+", "-", s.strip().lower()))
        seen = set()
        out = []
        for ln in text.splitlines():
            if not ln.strip():
                continue
            key = norm(ln)
            if key in seen:
                continue
            seen.add(key)
            out.append(ln.strip())
        return "\n".join(out)

    def _enforce_no_inference(self, raw_text: str, target_text: str, title: str) -> str:
        """
        약한 추론 제거:
        - 원문에 '대상/자격' 신호가 전혀 없으면 => '정보 없음'
        - '지역구민'이지만 원문에 주민/거주자 근거가 없으면 => '정보 없음'
        - '계획/예정/추정' 등 추론성 어휘만 있을 때 => 원문에도 없으면 '정보 없음'
        """
        if not target_text or not target_text.strip():
            return "정보 없음"

        explicit_signal = self._has_explicit_target_signal(raw_text)
        resident_evidence = self._has_resident_evidence(raw_text)

        # 대상 신호가 없으면 무조건 정보 없음
        if not explicit_signal:
            return "정보 없음"

        # 주민 근거 없는 '지역구민' 제거
        if "지역구민" in (target_text or "") and not resident_evidence:
            return "정보 없음"

        # 추론성 어휘 필터
        if re.search(r"(계획|예정|추정|추측|가능성|의심)", target_text):
            if not re.search(r"(계획|예정|추정|추측|가능성|의심)", raw_text):
                return "정보 없음"

        return target_text.strip()

    # ─────────────────────────────────────────────────────────────────
    # LLM 구조화
    # ─────────────────────────────────────────────────────────────────
    def structure_with_llm(
        self,
        soup: BeautifulSoup,
        title: Optional[str] = None,
        use_structured_output: bool = True,
    ) -> HealthSupportInfo:
        # 1) 텍스트 추출
        raw_text = self._extract_text_content(soup)

        # 2) 공통 규칙 (weak inference 없음)
        common_rules = """
너는 한국 복지/보건 사업 문서를 구조적으로 요약하고 평가하는 보조자다.
반드시 다음을 지켜라:
1) 지원대상(support_target)에는 '누가/어떤 조건으로'만 담고, 지원내용(support_content)에는 '무엇을/얼마나/어떻게 제공'만 담아라. 섞여 있으면 분리한다.
2) 지역 일반화: '강북구민/동작구 주민/영등포구·서초구 주민' 등 구체 지자체 명칭은 모두 지원 대상(자격) 요약 시 무시한다. (지역 정보는 별도 태그로 관리됨)
3) **추론 금지:** 원문에 나타나지 않는 대상·조건·수치·기간을 새로 만들지 마라. 특히 '정보 제공/안내/캠페인' 류 페이지에서 '대상'이 명시되지 않으면 support_target은 반드시 '정보 없음'으로 표기한다.
4) 결과는 아래 JSON 스키마로만 반환한다 (추가 텍스트 금지):
{
  "support_target": "...",
  "support_content": "...",
  "scores": {
    "richness_target": 0-100,
    "richness_content": 0-100,
    "criterion_fit_target": 0-100,
    "criterion_fit_content": 0-100
  },
  "overall": 0-100
}
5) overall은 다음 가중합의 정수 반올림으로 산출한다:
   overall = 0.2*richness_target + 0.2*richness_content + 0.30*criterion_fit_target + 0.30*criterion_fit_content
6) **지원내용 수치 가산 규칙:** support_content 안에 원문에 실제로 존재하는 구체 수치(예: 금액, %, 회/일/개월/시간, 명/가구/건)가 포함되면
   criterion_fit_content에 최대 +15, richness_content에 최대 +10까지 가산하도록 점수를 책정하라(과도한 가산은 금지).
"""

        if title:
            system_prompt = f"""{common_rules}
과제: '{title}' 사업의 원문을 읽고 스키마에 맞춰 요약과 평가 점수를 동시에 산출하라.
- 원문에 '대상/자격' 신호가 없으면 support_target='정보 없음'으로 하라."""
            user_prompt = f"""원문:
================ RAW TEXT ================
{raw_text}
========================================="""
            response_model = _LLMResponseNoTitle
        else:
            system_prompt = f"""{common_rules}
과제: 다음 원문에서 제목을 1개 추출한 뒤, 스키마에 맞춰 요약과 평가 점수를 동시에 산출하라.
- 원문에 '대상/자격' 신호가 없으면 support_target='정보 없음'으로 하라."""
            user_prompt = f"""원문:
================ RAW TEXT ================
{raw_text}
========================================="""
            response_model = _LLMResponseWithTitle

        # 3) LLM 호출 (방어적 파싱 포함)
        parsed_ok = False
        raw_content = None
        if use_structured_output:
            completion = self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=response_model,
                temperature=0.1,
            )
            msg = completion.choices[0].message
            raw_content = getattr(msg, "content", None)
            response_data = getattr(msg, "parsed", None)
            parsed_ok = response_data is not None
        else:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            raw_content = completion.choices[0].message.content
            try:
                result_json = json.loads(raw_content)
                response_data = response_model(**result_json)
                parsed_ok = True
            except Exception:
                parsed_ok = False
                response_data = None

        # JSON 폴백: parse 실패 시 content를 JSON으로 한 번 더 시도
        if not parsed_ok and raw_content:
            try:
                result_json = json.loads(raw_content)
                response_data = response_model(**result_json)
                parsed_ok = True
            except Exception:
                pass

        if not parsed_ok or response_data is None:
            print("⚠️ LLM 응답 파싱 실패. 최소 스켈레톤으로 진행합니다.")
            empty_scores = {"richness_target": 0, "richness_content": 0, "criterion_fit_target": 0, "criterion_fit_content": 0}
            if title:
                response_data = _LLMResponseNoTitle(
                    support_target="정보 없음",
                    support_content="정보 없음",
                    scores=_EvalScores(**empty_scores),
                    overall=0
                )
            else:
                response_data = _LLMResponseWithTitle(
                    title="제목 없음",
                    support_target="정보 없음",
                    support_content="정보 없음",
                    scores=_EvalScores(**empty_scores),
                    overall=0
                )

        # 4) 후처리 및 조립
        if title:
            out_title = title
            out_target = self._generalize_region_terms(response_data.support_target)
            out_content = self._generalize_region_terms(response_data.support_content)
        else:
            out_title = response_data.title
            out_target = self._generalize_region_terms(response_data.support_target)
            out_content = self._generalize_region_terms(response_data.support_content)

        # (A) 자격 자동 생성 금지 (weak inference 없이)
        out_target = self._enforce_no_inference(raw_text, out_target, out_title)

        # (B) 지원내용 중복 제거(간단)
        out_content = self._dedupe_lines(out_content)

        info = HealthSupportInfo(
            id=str(uuid.uuid4()),
            title=out_title,
            support_target=out_target,
            support_content=out_content,
            raw_text=raw_text,
        )

        # (C) 점수 반영(방어적 처리 + 하한 보정)
        try:
            raw_scores = getattr(response_data, "scores", None)
            if raw_scores is None:
                raw_scores = {}
            if hasattr(raw_scores, "model_dump"):
                scores_dict = raw_scores.model_dump()
            elif isinstance(raw_scores, dict):
                scores_dict = raw_scores
            else:
                scores_dict = {}

            for k in ["richness_target", "richness_content", "criterion_fit_target", "criterion_fit_content"]:
                scores_dict[k] = int(scores_dict.get(k, 0) or 0)

            # content에 숫자 존재 & 원문에도 실제 숫자 존재 시 보정 하한선
            if self._contains_numeric_detail(out_content) and self._contains_numeric_detail(raw_text):
                scores_dict["criterion_fit_content"] = max(scores_dict["criterion_fit_content"], 60)
                scores_dict["richness_content"] = max(scores_dict["richness_content"], 55)

            info.eval_scores = {k: int(max(0, min(100, v))) for k, v in scores_dict.items()}

        except Exception as e:
            print(f"⚠️ 점수 파싱 에러: {e}")
            info.eval_scores = {
                "richness_target": 0,
                "richness_content": 0,
                "criterion_fit_target": 0,
                "criterion_fit_content": 0,
            }

        # overall은 항상 재계산해서 보장
        rt = info.eval_scores.get("richness_target", 0)
        rc = info.eval_scores.get("richness_content", 0)
        ct = info.eval_scores.get("criterion_fit_target", 0)
        cc = info.eval_scores.get("criterion_fit_content", 0)
        info.eval_overall = int(round(0.2*rt + 0.2*rc + 0.30*ct + 0.30*cc))

        return info

    # ─────────────────────────────────────────────────────────────────
    # 외부 인터페이스
    # ─────────────────────────────────────────────────────────────────
    def crawl_and_structure(
        self,
        url: str = None,
        file_path: str = None,
        region: str = None,
        title: Optional[str] = None,
    ) -> HealthSupportInfo:
        # 1) HTML 가져오기
        if url:
            soup = self.fetch_page(url)
            source_url = url
        elif file_path:
            soup = self.parse_html_file(file_path)
            source_url = file_path
        else:
            raise ValueError("url 또는 file_path 중 하나는 필수입니다.")

        if not soup:
            raise ValueError("HTML을 가져올 수 없습니다.")

        # 2) LLM 구조화
        structured_data = self.structure_with_llm(soup, title=title)

        # 3) 메타 정보
        structured_data.source_url = source_url
        if region:
            structured_data.region = region

        return structured_data

    # 유틸: 저장/출력(옵션)
    def save_to_json(self, data: HealthSupportInfo, output_path: str):
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data.model_dump(), f, ensure_ascii=False, indent=2)
            print(f"[OK] 데이터가 {output_path}에 저장되었습니다.")
        except Exception as e:
            print(f"[ERROR] 파일 저장 실패: {e}")

    def print_structured_data(self, data: HealthSupportInfo):
        print("\n" + "=" * 80)
        print(f"■ ID: {data.id}")
        print(f"■ 제목: {data.title}")
        if data.region:
            print(f"■ 지역: {data.region}")
        print("=" * 80)
        if data.support_target:
            print("\n■ 지원 대상(자격)")
            self._print_multiline(data.support_target, indent=1)
        if data.support_content:
            print("\n■ 지원 내용")
            self._print_multiline(data.support_content, indent=1)
        if data.eval_scores:
            print("\n■ 평가 점수(0~100)")
            for k, v in data.eval_scores.items():
                print(f"  - {k}: {v}")
            if data.eval_overall is not None:
                print(f"  - overall: {data.eval_overall}")
        if data.source_url:
            print(f"\n■ 출처: {data.source_url}")
        print("\n" + "=" * 80)

    def _print_multiline(self, text: str, indent: int = 0):
        prefix = "  " * indent
        for line in text.split("\n"):
            if line.strip():
                print(f"{prefix}{line.strip()}")


# 단독 실행 테스트용 (옵션)
def main():
    import argparse

    parser = argparse.ArgumentParser(description="LLM을 사용하여 의료/복지 사업 텍스트를 구조화합니다.")
    parser.add_argument("--url", type=str, help="크롤링할 웹페이지 URL")
    parser.add_argument("--file", type=str, help="로컬 HTML 파일 경로")
    parser.add_argument("--output", type=str, default="structured_output.json", help="출력 JSON 파일 경로")
    parser.add_argument("--model", type=str, default="gpt-4o-mini", help="사용 모델 (예: gpt-4o, gpt-4o-mini)")

    args = parser.parse_args()

    if not args.url and not args.file:
        print("\n" + "=" * 80)
        print("LLM 기반 구조화 테스트")
        print("=" * 80)
        args.url = input("웹페이지 URL을 입력하세요 (없으면 엔터): ").strip() or None
        if not args.url:
            args.file = input("로컬 HTML 파일 경로를 입력하세요: ").strip()
        args.output = input("출력 파일명 (기본 structured_output.json): ").strip() or "structured_output.json"

    crawler = LLMStructuredCrawler(model=args.model)

    try:
        if args.url:
            data = crawler.crawl_and_structure(url=args.url)
        else:
            data = crawler.crawl_and_structure(file_path=args.file)
        crawler.print_structured_data(data)
        crawler.save_to_json(data, args.output)
        print(f"\n[완료] {args.output} 저장")
    except Exception as e:
        print(f"[ERROR] 처리 실패: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
