# -*- coding: utf-8 -*-
# retrieval_planner.py
# -------------------------------------------------------------------
# 기능:
#   1) ephemeral + DB 프로필/컬렉션 merge
#   2) SentenceTransformer(bge-m3-ko) 임베딩
#   3) pgvector 기반 문서 검색 (use_rag=True일 때만)
#   4) state["retrieval"]에 profile_ctx, collection_ctx, rag_snippets 저장
#      + 자연어 프로필 요약을 쿼리에 반영
# -------------------------------------------------------------------

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

import psycopg
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

# LangSmith trace 데코레이터 (없으면 no-op)
try:
    from langsmith import traceable
except Exception:  # pragma: no cover
    def traceable(func):
        return func

from app.langgraph.state.ephemeral_context import State
from app.langgraph.utils.merge_utils import merge_profile, merge_collection
from app.dao.db_user_utils import fetch_profile_from_db, fetch_collections_from_db
from app.langgraph.utils.retrieval_filters import filter_candidates_by_profile  # 추가

load_dotenv()

# -------------------------------------------------------------------
# DB URL
# -------------------------------------------------------------------
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    raise RuntimeError("DATABASE_URL not configured")

# psycopg3 전용 DSN 형태로 통일
if DB_URL.startswith("postgresql+psycopg://"):
    DB_URL = DB_URL.replace("postgresql+psycopg://", "postgresql://", 1)


# -------------------------------------------------------------------
# Embedding Model (SentenceTransformer, BGE-m3-ko)
# -------------------------------------------------------------------
_EMBED_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "dragonkue/bge-m3-ko")
_EMBED_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")

_embedding_model: Optional[SentenceTransformer] = None


def _get_embed_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(_EMBED_MODEL_NAME, device=_EMBED_DEVICE)
    return _embedding_model


def _embed_text(text: str) -> List[float]:
    """
    SentenceTransformer encode → list[float]
    - normalize_embeddings=True 로 cosine distance에 맞춘다.
    """
    model = _get_embed_model()
    return model.encode(text or "", normalize_embeddings=True).tolist()


# -------------------------------------------------------------------
# DB Connection
# -------------------------------------------------------------------
def _get_conn():
    return psycopg.connect(DB_URL)


# -------------------------------------------------------------------
# Keyword Extraction (단순 토큰 추출)
# -------------------------------------------------------------------
def extract_keywords(text: str, max_k: int = 8) -> List[str]:
    """
    쿼리 텍스트에서 한글/영문/숫자 토큰만 뽑고
    자주 쓰이는 불용어를 제거한 뒤 상위 max_k개만 반환.
    """
    if not text:
        return []
    tokens = re.findall(r"[가-힣A-Za-z0-9]+", text)
    stop = {"그리고", "하지만", "근데", "가능", "문의", "신청", "여부", "있나요", "해당", "사용자", "상태", "현재", "질문"}
    out, seen = [], set()
    for t in tokens:
        t = t.lower()
        if len(t) >= 2 and t not in stop:
            if t not in seen:
                seen.add(t)
                out.append(t)
                if len(out) >= max_k:
                    break
    return out


# -------------------------------------------------------------------
# Region Sanitizer
# -------------------------------------------------------------------
def _sanitize_region(region_value: Optional[Any]) -> Optional[str]:
    """
    region 값을 문자열로 정리.
    - dict 형태({'value': '강남구'})도 지원.
    - 공백/빈 문자열이면 None.
    """
    if region_value is None:
        return None

    if isinstance(region_value, dict):
        region_value = region_value.get("value")

    if region_value is None:
        return None

    region_str = str(region_value).strip()
    return region_str or None

# -------------------------------------------------------------------
# 코드값 → 한국어 라벨 매핑
# -------------------------------------------------------------------
INSURANCE_TYPE_LABELS = {
    "EMPLOYED": "직장가입자",
    "LOCAL": "지역가입자",
    "REGIONAL": "지역가입자",
    "DEPENDENT": "피부양자",
    "MEDICAL_AID": "의료급여 수급자",
    "NONE": None,
}

BASIC_BENEFIT_LABELS = {
    "LIVELIHOOD": "생계급여",
    "MEDICAL": "의료급여",
    "HOUSING": "주거급여",
    "EDUCATION": "교육급여",
    "NONE": None,
}

LTCI_GRADE_LABELS = {
    "LEVEL_1": "장기요양 1등급",
    "LEVEL_2": "장기요양 2등급",
    "LEVEL_3": "장기요양 3등급",
    "LEVEL_4": "장기요양 4등급",
    "LEVEL_5": "장기요양 5등급",
    "NONE": None,
    "0": None,
}

# 질환 코드/영문 → 한국어 라벨 간단 매핑 (필요하면 점점 늘리면 됨)
CONDITION_LABELS = {
    "diabetes": "당뇨병",
    "diabetes mellitus": "당뇨병",
    "dm": "당뇨병",
    "breast cancer": "유방암",
    "cancer": "암",
}

def _norm_code(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def _map_with_labels(value: Any, labels: Dict[str, Optional[str]]) -> Optional[str]:
    code = _norm_code(value)
    if not code:
        return None
    if code in labels:
        return labels[code]
    # 매핑에 없으면 원문 그대로(이미 한글일 수도 있음)
    return str(value).strip() or None


def _map_condition_name(name: str) -> str:
    """
    영문/코드 질환명을 최대한 한국어로 바꿔주고,
    모르는 건 원문 그대로 둔다.
    """
    if not name:
        return ""
    raw = name.strip()
    code = raw.lower()
    # 간단 매핑
    for k, v in CONDITION_LABELS.items():
        if k in code:
            return v
    return raw

# -------------------------------------------------------------------
# Profile / Collection → 자연어 텍스트 요약
# -------------------------------------------------------------------
def _extract_profile_field(profile: Optional[Dict[str, Any]], key: str) -> Any:
    if not profile:
        return None
    v = profile.get(key)
    if isinstance(v, dict):
        return v.get("value")
    return v


def _profile_collection_to_text(
    profile: Optional[Dict[str, Any]],
    collection: Optional[Dict[str, Any]],
) -> str:
    """
    merged_profile / merged_collection을 LLM이 보기 쉬운 짧은 한국어 상태 요약으로 변환.
    예:
      사용자 상태: 강남구 거주; 건강보험 직장가입자; 기준중위소득 약 120% 수준;
                 기초생활보장 생계급여 수급 이력; 임신 3개월 차; 주요 질환: 당뇨병
    """
    pieces: List[str] = []

    # ---------- Profile 쪽 ----------

    if profile:
        # 1) 거주지
        region = _extract_profile_field(profile, "residency_sgg_code") or _extract_profile_field(
            profile, "region_gu"
        )
        if region:
            pieces.append(f"{region} 거주")

        # 2) 건강보험 자격
        ins_raw = _extract_profile_field(profile, "insurance_type")
        ins_label = _map_with_labels(ins_raw, INSURANCE_TYPE_LABELS)
        if ins_label:
            # "보험 자격: EMPLOYED" → "건강보험 직장가입자"
            pieces.append(f"건강보험 {ins_label}")

        # 3) 기준중위소득 비율
        mir_raw = _extract_profile_field(profile, "median_income_ratio")
        if mir_raw is not None:
            try:
                r = float(mir_raw)
                # 0~10 사이면 비율, 10 이상이면 이미 %라고 가정
                if r <= 10:
                    pct = int(round(r * 100))
                else:
                    pct = int(round(r))
                # 너무 말도 안 되는 값은 버림
                if 0 < pct <= 300:
                    pieces.append(f"기준중위소득 약 {pct}% 수준")
            except Exception:
                # 이상하면 그냥 원문을 짧게 보존
                pieces.append(f"소득 수준: {mir_raw}")

        # 4) 기초생활보장 급여
        basic_raw = _extract_profile_field(profile, "basic_benefit_type")
        basic_label = _map_with_labels(basic_raw, BASIC_BENEFIT_LABELS)
        if basic_label:
            pieces.append(f"기초생활보장 {basic_label} 수급 이력")

        # 5) 장애등급
        dis = _extract_profile_field(profile, "disability_grade")
        if dis:
            # "3" → "장애 3급" 정도로 보정
            dis_str = str(dis).strip()
            if dis_str.isdigit():
                pieces.append(f"장애 {dis_str}급")
            else:
                pieces.append(f"장애등급 {dis_str}")

        # 6) 장기요양등급
        ltci_raw = _extract_profile_field(profile, "ltci_grade")
        ltci_label = _map_with_labels(ltci_raw, LTCI_GRADE_LABELS)
        if ltci_label:
            pieces.append(ltci_label)

        # 7) 임신/출산 12개월 이내 여부
        preg = _extract_profile_field(profile, "pregnant_or_postpartum12m")
        if preg:
            pieces.append("임신 중이거나 출산 후 12개월 이내")

    # ---------- Collection(triples) 쪽 ----------

    conditions: List[str] = []
    preg_text: Optional[str] = None
    has_basic_doc = False

    if collection and isinstance(collection, dict):
        triples = collection.get("triples") or []

        for t in triples:
            if not isinstance(t, dict):
                continue
            pred = (t.get("predicate") or "").strip().upper()
            obj = (t.get("object") or "").strip()
            if not obj:
                continue

            # 질환/상태 → 주요 질환으로 묶기
            if pred in ("HAS_CONDITION", "DISEASE", "HAS_DISEASE"):
                cond = _map_condition_name(obj)
                if cond:
                    conditions.append(cond)
                continue

            # 임신 상태
            if pred in ("PREGNANCY_STATUS", "PREGNANCY"):
                # "임신 3달차" → "임신 3개월 차" 정도로 가볍게 보정
                txt = obj.replace("달", "개월")
                preg_text = txt
                continue

            # 생계급여 서류/수급 관련
            if pred in ("HAS_DOCUMENT", "HAS_BENEFIT"):
                if "생계급여" in obj:
                    has_basic_doc = True
                # 굳이 별도 텍스트로 남기진 않음 (위에서 basic_benefit_type과 합쳐짐)
                continue

            # 그 외 predicate들은 너무 장황해지지 않도록 일단 무시
            # 필요하면 여기서 점점 확장하면 됨.

    # collection에서 얻은 정보 반영
    if preg_text:
        pieces.append(preg_text)

    if has_basic_doc and not any("생계급여" in p for p in pieces):
        pieces.append("생계급여 수급 이력")

    if conditions:
        # 중복 제거 + 3개까지만
        uniq: List[str] = []
        for c in conditions:
            if c not in uniq:
                uniq.append(c)
            if len(uniq) >= 3:
                break
        pieces.append("주요 질환: " + ", ".join(uniq))

    if not pieces:
        return ""

    return "사용자 상태: " + "; ".join(pieces)

# -------------------------------------------------------------------
# 최근 대화 히스토리 텍스트 구성
# -------------------------------------------------------------------
def _build_history_text(state: State, max_chars: int = 600) -> str:
    """
    messages에서 최근 user/assistant 발화 몇 개를 뽑아 한글 라벨을 붙여 요약.
    """
    msgs = list(state.get("messages") or [])
    if not msgs:
        return ""

    lines: List[str] = []
    # 최근 순으로 6개 정도만
    for m in msgs[-6:]:
        role = m.get("role") or "user"
        if role not in ("user", "assistant"):
            continue
        content = (m.get("content") or "").strip()
        if not content:
            continue
        prefix = "사용자" if role == "user" else "AI"
        lines.append(f"{prefix}: {content}")

    if not lines:
        return ""

    text = "\n".join(lines)
    # 너무 길면 뒤쪽 max_chars만 사용
    if len(text) > max_chars:
        text = text[-max_chars:]
    return text


# -------------------------------------------------------------------
# Hybrid Document Search (현재는 Vector + optional region filter)
# -------------------------------------------------------------------
def _hybrid_search_documents(
    query_text: str,
    merged_profile: Optional[Dict[str, Any]],
    top_k: int = 8,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    query_text 임베딩 기반 pgvector 검색.
    query_text 안에는 이미 "최근 대화 + 사용자 상태 요약 + 현재 질문"이 포함되어 있음.
    """
    query_text = (query_text or "").strip()
    if not query_text:
        return [], []

    keywords = extract_keywords(query_text, max_k=8)

    # region filter: merged_profile 내 residency_sgg_code(or region_gu)을 사용
    region_filter = None
    if merged_profile:
        # 우선 residency_sgg_code, 없으면 region_gu를 사용
        region_val = merged_profile.get("residency_sgg_code")
        if region_val is None:
            region_val = merged_profile.get("region_gu")
        region_filter = _sanitize_region(region_val)
        if region_filter is None:
            # 디버깅용 로그 정도로만 사용 (필수 아님)
            print("[retrieval_planner] region_filter empty or missing")

    # embedding
    try:
        qvec = _embed_text(query_text)
    except Exception as e:
        print(f"[retrieval_planner] embed failed: {e}")
        return [], keywords

    # psycopg3에서 VECTOR 타입으로 캐스팅하기 위해 문자열 리터럴 사용
    qvec_str = "[" + ",".join(f"{v:.6f}" for v in qvec) + "]"

    sql = """
        SELECT
            d.id,
            d.title,
            d.requirements,
            d.benefits,
            d.region,
            d.url,
            1 - (e.embedding <=> %(qvec)s::vector) AS similarity
        FROM documents d
        JOIN embeddings e ON d.id = e.doc_id
    """

    params: Dict[str, Any] = {"qvec": qvec_str}

    if region_filter:
        sql += " WHERE TRIM(d.region) = %(region)s::text"
        params["region"] = region_filter

    sql += """
        ORDER BY e.embedding <=> %(qvec)s::vector
        LIMIT %(limit)s
    """
    params["limit"] = top_k

    rows = []
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    results: List[Dict[str, Any]] = []
    for r in rows:
        similarity = float(r[6]) if r[6] is not None else None
        requirements = (r[2] or "").strip() if isinstance(r[2], str) else None
        benefits = (r[3] or "").strip() if isinstance(r[3], str) else None
        region = (r[4] or "").strip() if isinstance(r[4], str) else None
        url = (r[5] or "").strip() if isinstance(r[5], str) else None

        snippet_lines: List[str] = []
        if requirements:
            snippet_lines.append(f"[신청 요건]\n{requirements}")
        if benefits:
            snippet_lines.append(f"[지원 내용]\n{benefits}")
        snippet_text = "\n\n".join(snippet_lines).strip()

        results.append(
            {
                "doc_id": r[0],
                "title": (r[1] or "").strip() if isinstance(r[1], str) else None,
                "requirements": requirements,
                "benefits": benefits,
                "region": region,
                "url": url,
                "similarity": similarity,
                "snippet": snippet_text,
            }
        )

    # similarity 내림차순 정렬 (SQL에서도 정렬하지만 혹시 모르니)
    results.sort(key=lambda x: (x["similarity"] is not None, x["similarity"]), reverse=True)

    # rag_snippets 포맷으로 재구성
    snippets: List[Dict[str, Any]] = []
    for r in results:
        snippet_entry: Dict[str, Any] = {
            "doc_id": r["doc_id"],
            "title": r["title"],
            "source": r["region"] or "policy_db",
            "snippet": r["snippet"] or r["benefits"] or r["requirements"] or "",
            "score": r["similarity"],
        }
        if r["region"]:
            snippet_entry["region"] = r["region"]
        if r["url"]:
            snippet_entry["url"] = r["url"]
        if r["requirements"]:
            snippet_entry["requirements"] = r["requirements"]
        if r["benefits"]:
            snippet_entry["benefits"] = r["benefits"]
        snippets.append(snippet_entry)

    return snippets, keywords


# -------------------------------------------------------------------
# use_rag 결정 함수
# -------------------------------------------------------------------
def _decide_use_rag(router: Optional[Dict[str, Any]], query_text: str) -> bool:
    """
    router 정보와 쿼리 텍스트를 바탕으로 RAG 사용 여부를 결정.
    - 1순위: router["use_rag"] 값
    - 2순위: category/텍스트 기반 휴리스틱 (필요하면 확장 가능)
    """
    if not router:
        return True  # 기본값: 사용

    if "use_rag" in router:
        return bool(router["use_rag"])

    # fallback 휴리스틱 (지금은 매우 보수적으로 사용)
    text = (query_text or "").lower()
    if any(k in text for k in ["자격", "지원", "혜택", "대상", "요건", "급여", "본인부담"]):
        return True

    return False

# -------------------------------------------------------------------
# Retrieval Planner Node
# -------------------------------------------------------------------
@traceable
def plan(state: State) -> State:
    """
    LangGraph 노드 함수.

    입력 State (중요 필드):
      - profile_id: int | None
      - user_input: str
      - router: {category, save_profile, save_collection, use_rag, .}
      - ephemeral_profile: 세션 중 추출된 프로필 오버레이
      - ephemeral_collection: 세션 중 추출된 컬렉션(triples)

    동작:
      1) DB에서 profile/collections 읽기 (profile_id 기준)
      2) merge_profile / merge_collection으로 ephemeral과 병합
         (ephemeral에 우선순위)
      3) router/use_rag 플래그를 보고 RAG ON/OFF 결정
      4) "최근 대화 + 사용자 상태 요약 + 현재 질문"을 합친 search_text로 문서 검색
      5) state["retrieval"]에 저장

    출력:
      state["retrieval"] = {
        "used_rag": bool,
        "profile_ctx": merged_profile or None,
        "collection_ctx": merged_collection or None,
        "rag_snippets": [.],
        "keywords": [.],
        "debug_search_text": str | None,   # LangSmith 디버깅용
        "profile_summary_text": str | None # 자연어 프로필 요약
      }
    """
    profile_id = state.get("profile_id")
    query_text = state.get("user_input") or ""
    router_info: Dict[str, Any] = state.get("router") or {}

    # --- ephemeral ---
    eph_profile = state.get("ephemeral_profile")
    eph_collection = state.get("ephemeral_collection")

    # --- DB fetch (profile_id 기준) ---
    db_profile = None
    db_collection = None
    if profile_id is not None:
        try:
            db_profile = fetch_profile_from_db(profile_id)
        except Exception as e:
            print(f"[retrieval_planner] fetch_profile_from_db error: {e}")

        try:
            db_collection = fetch_collections_from_db(profile_id)
        except Exception as e:
            print(f"[retrieval_planner] fetch_collections_from_db error: {e}")

    # --- merge ephemeral + DB ---
    #   ※ merge_utils 설계상 ephemeral 우선이므로 (ephemeral, db) 순서로 호출
    merged_profile = merge_profile(eph_profile, db_profile)
    merged_collection = merge_collection(eph_collection, db_collection)

    # --- 자연어 프로필 요약 & 히스토리 ---
    history_text = _build_history_text(state)
    profile_summary_text = _profile_collection_to_text(merged_profile, merged_collection)

    # search_text = [최근 대화] + [사용자 상태 요약] + [현재 질문]
    search_parts: List[str] = []
    if history_text:
        search_parts.append("[최근 대화]\n" + history_text)
    if profile_summary_text:
        search_parts.append(profile_summary_text)
    if query_text:
        search_parts.append("현재 질문: " + query_text.strip())

    search_text = "\n\n".join(search_parts).strip() if search_parts else query_text

    # --- RAG 사용 여부 결정 ---
    use_rag = _decide_use_rag(router_info, query_text)

    rag_docs: List[Dict[str, Any]] = []
    keywords: List[str] = []

    if use_rag and search_text:
        try:
            rag_docs, keywords = _hybrid_search_documents(
                query_text=search_text,
                merged_profile=merged_profile,
                top_k=8,
            )
        except Exception as e:
            print(f"[retrieval_planner] document search failed: {e}")
            rag_docs = []
            keywords = extract_keywords(search_text, max_k=8)
    else:
        keywords = extract_keywords(search_text or query_text, max_k=8)

    # --- 프로필 기반 필터 적용 ---
    if merged_profile and rag_docs:
        before = len(rag_docs)
        rag_docs = filter_candidates_by_profile(rag_docs, merged_profile)
        after = len(rag_docs)

        print(f"[retrieval_planner] profile filter: {before} -> {after} candidates")

    # 대화 저장 안내 스니펫 추가 조건
    end_requested = bool(state.get("end_session"))
    save_keywords = ("저장", "보관", "기록")
    refers_to_save = any(k in query_text for k in save_keywords)
    if end_requested or refers_to_save:
        rag_docs.append({
            "doc_id": "system:conversation_persist",
            "title": "대화 저장 안내",
            "snippet": "대화를 종료하면 저장 파이프라인이 자동 실행되어 대화 내용이 보관됩니다.",
            "score": 1.0,
        })

    state["retrieval"] = {
        "used_rag": use_rag,
        "profile_ctx": merged_profile,
        "collection_ctx": merged_collection,
        "rag_snippets": rag_docs,
        "keywords": keywords,
        "debug_search_text": search_text,
        "profile_summary_text": profile_summary_text,
    }

    state["rag_snippets"] = rag_docs

    return state

