# app/langgraph/nodes/persist_pipeline.py
# -*- coding: utf-8 -*-
"""
persist_pipeline.py

세션 종료 시:
  1) Cleaner: 메시지 PII 마스킹 / no_store 정책 / 길이 제한
  2) Summarizer: rolling_summary + 메시지 기반 최종 요약 생성
  3) DiffMerger: ephemeral_profile / ephemeral_collection ↔ DB 병합
  4) Vectorizer: dragonkue/bge-m3-ko 임베딩 생성
  5) Persister: profiles / collections(트리플) / conversations / messages /
                conversation_embeddings 를 하나의 트랜잭션으로 upsert/insert

주의:
  - Policy DB(documents/embeddings)는 여기서 건드리지 않는다. (조회 전용)
  - collections 스키마는 트리플 기반:
      collections(
        id BIGINT PK,
        profile_id BIGINT,
        subject TEXT,
        predicate TEXT,
        object TEXT,
        code_system TEXT,
        code TEXT
      )
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, TypedDict, Literal
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

import psycopg  # psycopg3
from sentence_transformers import SentenceTransformer

from app.langgraph.utils.cleaner_utils import clean_messages
from app.dao import db_user_utils


# ─────────────────────────────────────────────────────────
# 환경 변수 (Cleaner 기본값 및 DB / 임베딩 모델)
# ─────────────────────────────────────────────────────────
ENV_ENABLE = os.getenv("PERSIST_ENABLE_CLEANER", "true").lower() == "true"
ENV_MODE: Literal["full", "mask-only", "off"] = os.getenv("PERSIST_CLEANER_MODE", "full").lower()
ENV_NO_STORE_POLICY: Literal["drop", "redact"] = os.getenv("PERSIST_NO_STORE_POLICY", "redact").lower()

DB_URL = os.getenv("DATABASE_URL")
if DB_URL and DB_URL.startswith("postgresql+psycopg://"):
    DB_URL = DB_URL.replace("postgresql+psycopg://", "postgresql://", 1)

# 임베딩 모델 이름 (우선순위: CONV_EMB_MODEL > EMBEDDING_MODEL > 기본값)
EMBED_MODEL_NAME = (
    os.getenv("CONV_EMB_MODEL")
    or os.getenv("EMBEDDING_MODEL")
    or "dragonkue/bge-m3-ko"
)

# lazy 로딩용 전역
_EMB_MODEL: Optional[SentenceTransformer] = None


def _get_embedding_model() -> SentenceTransformer:
    global _EMB_MODEL
    if _EMB_MODEL is None:
        _EMB_MODEL = SentenceTransformer(EMBED_MODEL_NAME)
    return _EMB_MODEL


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Message(TypedDict, total=False):
    role: Literal["user", "assistant", "tool"]
    content: str
    created_at: str
    meta: Dict[str, Any]


class PersistResult(TypedDict, total=False):
    ok: bool
    conversation_id: Optional[str]
    counts: Dict[str, int]
    warnings: List[str]


def _append_tool(msgs: List[Message], text: str, meta: Optional[Dict[str, Any]] = None) -> Message:
    """
    msgs 리스트에 tool 로그 1개를 append 하고, 그 Message를 반환.
    - persist 내부에서는 cleaned(실제 DB 저장용)에만 추가하고
      그래프로 리턴할 delta 리스트에는 반환값을 따로 모은다.
    """
    msg: Message = {
        "role": "tool",
        "content": text,
        "created_at": _now_iso(),
        "meta": meta or {},
    }
    msgs.append(msg)
    return msg


def _parse_median_income_ratio(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None

    # "120%" → "120"
    if s.endswith("%"):
        s = s[:-1].strip()

    try:
        v = float(s)
    except ValueError:
        return None

    # 0~10 사이는 비율(배)로 보고, 그 이상은 퍼센트로 본다
    # 1.2 → 1.2  /  120 → 1.2
    if v <= 10:
        return v
    else:
        return v / 100.0


# ─────────────────────────────────────────────────────────
# Summarizer (간단 버전)
#  - rolling_summary + 최근 user 메시지 기반 텍스트 요약
# ─────────────────────────────────────────────────────────
def _summarize_session(rolling_summary: Optional[str], messages: List[Message]) -> str:
    last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    base = rolling_summary or ""
    return f"[SUMMARY]\nprev={base[:120]}\nlast_user={last_user[:120]}"


# ─────────────────────────────────────────────────────────
# Vectorizer (dragonkue/bge-m3-ko 사용)
# ─────────────────────────────────────────────────────────
def _embed_chunks(text: str) -> List[Dict[str, Any]]:
    """
    세션 요약 텍스트를 1개 chunk로 보고 dragonkue/bge-m3-ko 임베딩 생성.
    - 반환 형식: [{"chunk_id": str, "embedding": List[float]}]
    - DB 스키마의 VECTOR 차원(CONV_EMB_DIM)과 모델 차원을 맞춰야 함.
    """
    if not text:
        return []

    model = _get_embedding_model()
    # bge 계열 권장: normalize_embeddings=True (코사인 유사도 계산용)
    vec = model.encode([text], normalize_embeddings=True)[0]
    emb_list = vec.tolist()  # numpy.ndarray → list[float]

    return [{
        "chunk_id": "full",
        "embedding": emb_list,
    }]


# ─────────────────────────────────────────────────────────
# DiffMerger: ephemeral_profile / ephemeral_collection ↔ DB
# ─────────────────────────────────────────────────────────
def _merge_profile(ephemeral: Dict[str, Any], db_profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    임시 프로필과 DB 프로필 병합.
    - ephemeral 값이 있으면 우선 적용
    - dict 형태 {value, confidence}면 confidence>=0.7 일 때만 반영
    - 중위소득 비율(income_median_ratio/median_income_ratio)은
      _parse_median_income_ratio 를 통해 숫자로 정규화해서
      profiles.median_income_ratio 컬럼에만 저장한다.
    """
    merged: Dict[str, Any] = dict(db_profile or {})
    changes = 0

    # 0) 기존 DB에 문자열로 들어있을 수도 있는 median_income_ratio 방어적으로 정규화
    existing_mir = merged.get("median_income_ratio")
    if isinstance(existing_mir, str):
        parsed = _parse_median_income_ratio(existing_mir)
        if parsed is not None:
            merged["median_income_ratio"] = parsed

    eph = dict(ephemeral or {})

    # 1) 중위소득 비율 특수 처리
    #    - ephemeral["income_median_ratio"] 또는 ["median_income_ratio"] 중 하나 사용
    raw_ratio_field = eph.get("income_median_ratio")
    if raw_ratio_field in (None, "", [], {}):
        raw_ratio_field = eph.get("median_income_ratio")

    if raw_ratio_field not in (None, "", [], {}):
        conf = 1.0
        raw_val = raw_ratio_field
        if isinstance(raw_ratio_field, dict) and "value" in raw_ratio_field and "confidence" in raw_ratio_field:
            conf = float(raw_ratio_field.get("confidence", 1.0))
            raw_val = raw_ratio_field.get("value")

        if conf >= 0.7:
            parsed = _parse_median_income_ratio(raw_val)
            if parsed is not None and merged.get("median_income_ratio") != parsed:
                merged["median_income_ratio"] = parsed
                changes += 1

    # 2) 나머지 필드 일반 처리 (income/median 관련 키는 스킵)
    for k, v in eph.items():
        if k in ("income_median_ratio", "median_income_ratio"):
            continue  # 위에서 별도 처리했음

        if v in (None, "", [], {}):
            continue

        conf = 1.0
        if isinstance(v, dict) and "value" in v and "confidence" in v:
            conf = float(v.get("confidence", 1.0))
            v = v.get("value")

        if conf < 0.7:
            continue

        if merged.get(k) != v:
            merged[k] = v
            changes += 1

    merged["updated_at"] = datetime.now(timezone.utc)
    merged["_merge_changes"] = changes
    return merged


def _merge_collection(ephemeral: Any, db_coll: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """
    컬렉션 병합 (트리플 기반):

    - db_coll: DB에서 읽어온 기존 rows (list[dict])
      각 dict는 {"id", "profile_id", "subject", "predicate", "object", "code_system", "code"}를 가정
    - ephemeral:
        * dict 형태: {"triples": [ {...}, ... ]}
        * 또는 list 형태: [ {...}, ... ] 로 들어온 경우도 허용

    반환: {
      "triples": [merged_triples...],
      "_merge_changes": int(새로 추가된 트리플 수)
    }
    """
    existing_triples: List[Dict[str, Any]] = list(db_coll or [])
    merged: List[Dict[str, Any]] = list(existing_triples)

    # 기존 키 집합 (profile_id는 upsert 시 외부에서 넣음)
    existing_keys = set()
    for t in existing_triples:
        key = (
            (t.get("subject") or "").strip(),
            (t.get("predicate") or "").strip(),
            (t.get("object") or "").strip(),
            (t.get("code_system") or "") or "",
            (t.get("code") or "") or "",
        )
        existing_keys.add(key)

    # ephemeral에서 새 트리플 후보 가져오기
    new_triples: List[Dict[str, Any]] = []
    if isinstance(ephemeral, dict):
        triples_from_dict = ephemeral.get("triples")
        if isinstance(triples_from_dict, list):
            new_triples = list(triples_from_dict)
    elif isinstance(ephemeral, list):
        new_triples = list(ephemeral)

    changes = 0
    for t in new_triples:
        subj = (t.get("subject") or "").strip()
        pred = (t.get("predicate") or "").strip()
        obj = (t.get("object") or "").strip()
        cs = (t.get("code_system") or "") or None
        cd = (t.get("code") or "") or None

        if not subj or not pred or not obj:
            continue

        key = (subj, pred, obj, cs or "", cd or "")
        if key in existing_keys:
            continue

        existing_keys.add(key)
        merged.append({
            "subject": subj,
            "predicate": pred,
            "object": obj,
            "code_system": cs,
            "code": cd,
        })
        changes += 1

    return {
        "triples": merged,
        "_merge_changes": changes,
    }


def _diff_merge(cur, state: Dict[str, Any]) -> Dict[str, Any]:
    """
    전체 병합 파이프라인:
      - DB에서 profile/collection 조회
      - ephemeral_* 과 병합
    """
    profile_id = state.get("profile_id")
    if profile_id is None:
        # 프로필이 없으면 병합 생략
        return {
            "merged_profile": None,
            "merged_collection": None,
            "merge_log": ["no profile_id; skip merge"],
        }

    eprof = dict(state.get("ephemeral_profile") or {})
    ecoll = state.get("ephemeral_collection") or {}

    db_prof = db_user_utils.get_profile_by_id(cur, profile_id)
    db_coll = db_user_utils.get_collection_by_profile(cur, profile_id)

    merged_prof = _merge_profile(eprof, db_prof)
    merged_coll = _merge_collection(ecoll, db_coll)

    merge_log = []
    if merged_prof.get("_merge_changes"):
        merge_log.append(f"profile: {merged_prof['_merge_changes']} fields updated")
    if merged_coll.get("_merge_changes"):
        merge_log.append(f"collection: {merged_coll['_merge_changes']} triples added")

    return {
        "merged_profile": merged_prof,
        "merged_collection": merged_coll,
        "merge_log": merge_log,
    }


# ─────────────────────────────────────────────────────────
# 메인: persist 노드
# ─────────────────────────────────────────────────────────
def persist(
    state: Dict[str, Any],
    *,
    enable_cleaner: Optional[bool] = None,
    cleaner_mode: Optional[Literal["full", "mask-only", "off"]] = None,
    no_store_policy: Optional[Literal["drop", "redact"]] = None,
) -> Dict[str, Any]:
    """
    LangGraph 노드: 세션 종료 시 호출.
    - Cleaner 동작은 (인자) > (환경변수) 순으로 결정.
    - DB upsert는 psycopg 트랜잭션 안에서 수행.

    중요:
      - state["messages"]는 그래프 전체에서 append-only로 관리되므로,
        여기서는 그 전체를 읽어 DB에 저장만 하고,
        그래프에 되돌려줄 "messages"는 이번 노드에서 새로 남긴 tool 로그(delta)만 리턴한다.
    """
    # DB URL 없으면 DB 작업을 스킵하고 로그만 남김
    if not DB_URL:
        raw_msgs: List[Message] = list(state.get("messages") or [])
        msgs_for_db = raw_msgs  # 그대로 사용 (cleaner도 안 들어감)
        # delta 용 로그
        log_msg = _append_tool(
            msgs_for_db,
            "[persist_pipeline] DATABASE_URL not set; skipping DB upsert",
        )
        result: PersistResult = {
            "ok": False,
            "conversation_id": None,
            "counts": {"messages": len(msgs_for_db), "embeddings": 0},
            "warnings": ["DATABASE_URL not set"],
        }
        return {
            "messages": [log_msg],  # delta만 리턴
            "persist_result": result,
            "rolling_summary": state.get("rolling_summary"),
        }

    # 그래프 state에서 messages 전체를 읽어서 DB에 저장용으로 사용
    raw_msgs: List[Message] = list(state.get("messages") or [])
    rolling_summary = state.get("rolling_summary")
    profile_id = state.get("profile_id")

    # 1) Cleaner 토글 파라미터 결정
    _enable = ENV_ENABLE if enable_cleaner is None else bool(enable_cleaner)
    _mode = ENV_MODE if cleaner_mode is None else cleaner_mode
    _no_store = ENV_NO_STORE_POLICY if no_store_policy is None else no_store_policy

    # 2) state.messages 내에서 중복 제거 (content + role 기준)
    #    → LLM은 전체 대화 이력을 참조하지만, DB에는 중복 없이 저장
    seen = set()
    deduped_msgs: List[Message] = []
    for m in raw_msgs:
        key = (m.get("content", ""), m.get("role", ""))
        if key not in seen:
            seen.add(key)
            deduped_msgs.append(m)

    # 3) 메시지 클리닝 (PII 마스킹, no_store 처리, 길이 제한)
    cleaned: List[Message] = clean_messages(
        messages=deduped_msgs,  # 중복 제거된 메시지 사용
        enable=_enable,
        mode=_mode,
        no_store_policy=_no_store,
    )

    # delta 로 반환할 tool 로그들은 따로 모은다.
    log_messages: List[Message] = []

    # cleaner 적용 로그는 cleaned에도(실제 DB 저장용) 남기고,
    # 반환 delta(log_messages)에도 공유한다.
    log_messages.append(
        _append_tool(
            cleaned,
            "[persist_pipeline] cleaner applied",
            {"enable": _enable, "mode": _mode, "no_store_policy": _no_store},
        )
    )

    # 3) 최종 요약 생성
    final_summary = _summarize_session(rolling_summary, cleaned)

    # 4) 임베딩 (bge-m3-ko)
    embeddings = _embed_chunks(final_summary)

    # 5) DB upsert (트랜잭션)
    warnings: List[str] = []
    conversation_id: Optional[str] = None
    msg_count = len(cleaned)
    emb_count = len(embeddings)

    try:
        with psycopg.connect(DB_URL, autocommit=False) as conn:
            with conn.cursor() as cur:
                merged_profile = None
                merged_collection = None
                merge_log: List[str] = []

                # 5-1) profile / collections 병합 + upsert
                if profile_id is not None:
                    merge_result = _diff_merge(cur, state)
                    merged_profile = merge_result.get("merged_profile")
                    merged_collection = merge_result.get("merged_collection")
                    merge_log = merge_result.get("merge_log") or []

                    log_messages.append(
                        _append_tool(
                            cleaned,
                            "[persist_pipeline] diff_merge completed",
                            {"log": merge_log},
                        )
                    )

                    # profiles upsert
                    if merged_profile is not None:
                        pid = db_user_utils.upsert_profile(cur, merged_profile)
                        profile_id = pid  # 새로 생성됐을 경우 갱신

                    # collections upsert (트리플 기반)
                    if merged_collection is not None:
                        triples = merged_collection.get("triples") or []
                        db_user_utils.upsert_collection(cur, profile_id, triples)

                else:
                    warnings.append("profile_id is None; skip profile/collection upsert")
                    log_messages.append(
                        _append_tool(
                            cleaned,
                            "[persist_pipeline] no profile_id; skip profile/collection",
                        )
                    )

                # 5-2) conversations upsert
                summary_obj: Dict[str, Any] = {"text": final_summary}
                model_stats = state.get("model_stats") or {}
                if profile_id is not None:
                    conversation_id = db_user_utils.upsert_conversation(
                        cur,
                        profile_id=profile_id,
                        summary=summary_obj,
                        model_stats=model_stats,
                        ended_at=datetime.now(timezone.utc),
                    )
                else:
                    warnings.append("conversation not saved: profile_id is None")

                # 5-3) messages / embeddings insert
                if conversation_id is not None:
                    db_user_utils.bulk_insert_messages(cur, conversation_id, cleaned)
                    if embeddings:
                        db_user_utils.bulk_insert_conversation_embeddings(cur, conversation_id, embeddings)

                conn.commit()

    except Exception as e:
        warnings.append(f"DB error: {e}")
        log_messages.append(
            _append_tool(
                cleaned,
                "[persist_pipeline] DB error; rollback",
                {"error": str(e)},
            )
        )

    # 6) 결과 리턴
    result: PersistResult = {
        "ok": len(warnings) == 0,
        "conversation_id": conversation_id,
        "counts": {"messages": msg_count, "embeddings": emb_count},
        "warnings": warnings,
    }

    log_messages.append(
        _append_tool(
            cleaned,
            "[persist_pipeline] done",
            {
                "ok": result["ok"],
                "conversation_id": conversation_id,
                "counts": result["counts"],
                "warnings": warnings,
            },
        )
    )

    return {
        # 🔹 그래프에는 이번 노드에서 새로 생성한 tool 로그(delta)만 넘긴다.
        "messages": log_messages,
        "persist_result": result,
        "rolling_summary": final_summary,
        "profile_id": profile_id,
    }
