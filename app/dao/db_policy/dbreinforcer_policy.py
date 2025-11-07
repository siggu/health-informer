# -*- coding: utf-8 -*-
"""
dbreinforcer.py — eval_target / eval_content 기반 보강 (weight 미사용)
- 보강 필요 기준:
  · requirements: eval_target <= 5
  · benefits    : eval_content <= 5
- 소스 선정:
  · requirements 보강용 top5: eval_target DESC
  · benefits    보강용 top5: eval_content DESC
- 지역 특화 표현 일반화:
  예) "동작구 청년" → "청년", "강북구 거주자" → "주민", "서울시 구민" → "주민"
"""

import os
import sys
import re
import json
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

import psycopg2
from psycopg2.extras import Json, execute_values
from dotenv import load_dotenv
from openai import OpenAI


# ──────────────────────────────────────────────────────────────────────────────
# DSN
# ──────────────────────────────────────────────────────────────────────────────
def build_dsn_from_env() -> str:
    load_dotenv()
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME")
    user = os.getenv("DB_USER")
    pwd  = os.getenv("DB_PASSWORD")
    if not all([name, user, pwd]):
        raise ValueError("DATABASE_URL 또는 (DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD)가 필요합니다.")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{name}"


# ──────────────────────────────────────────────────────────────────────────────
# 문자열 후처리: 지역 특화 일반화
# ──────────────────────────────────────────────────────────────────────────────
_REGION = r"(?:서울특별시|부산광역시|대구광역시|인천광역시|광주광역시|대전광역시|울산광역시|세종특별자치시|제주특별자치도|[가-힣]{2,}(?:도|시|군|구))"
_RESIDENT = r"(?:주민|구민|시민|도민|군민|거주자)"
_GROUP = r"(?:청년|아동|노인|장애인|임산부|산모|영유아|다문화가정|부모|가구|학생|수급자|차상위|저소득층|한부모가정|자립준비청년|영세사업자)"

def generalize_local_terms(text: str) -> str:
    if not text:
        return text
    s = text

    # 1) "OO구 청년/아동/..." → "청년/아동/..."
    s = re.sub(fr"{_REGION}\s*{_GROUP}", lambda m: re.sub(fr"^{_REGION}\s*", "", m.group(0)), s)

    # 2) "OO시/구 {_RESIDENT}" → "주민"
    s = re.sub(fr"{_REGION}\s*{_RESIDENT}", "주민", s)

    # 3) 'OO지역 내', 'OO 관할' 등 지역 수식 제거(너무 공격적이지 않게 한정)
    s = re.sub(fr"{_REGION}\s*(?:지역|관할|내)\s*", "", s)

    # 4) 중복 공백/개행 정리
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


# ──────────────────────────────────────────────────────────────────────────────
# SQL
# ──────────────────────────────────────────────────────────────────────────────
ALTER_DOCUMENTS_SQL = """
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS llm_reinforced BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS llm_reinforced_sources JSONB,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
"""

# 대상 조회: policy_id 존재 + (eval_target<=5 또는 eval_content<=5)
TARGET_SELECT = """
SELECT
    d.id,
    d.title,
    d.requirements,
    d.benefits,
    d.raw_text,
    d.url,
    d.policy_id,
    d.sitename,
    d.eval_target,     -- 0~10
    d.eval_content     -- 0~10
FROM documents d
WHERE d.policy_id IS NOT NULL
  AND (
        (d.eval_target  IS NOT NULL AND d.eval_target  <= %(th_req)s) OR
        (d.eval_content IS NOT NULL AND d.eval_content <= %(th_ben)s)
      )
  {extra_filters}
ORDER BY d.id ASC
LIMIT %(limit)s
"""

# 소스 조회(요소별 정렬 기준 분리) — weight 사용 안 함
SOURCES_SELECT_BASE = """
SELECT
    s.id,
    s.title,
    s.requirements,
    s.benefits,
    s.raw_text,
    s.url,
    s.sitename,
    s.eval_target,
    s.eval_content
FROM documents s
WHERE s.policy_id = %(policy_id)s
  AND s.id <> %(target_id)s
  AND (
        (s.requirements IS NOT NULL AND length(TRIM(s.requirements)) > 0)
     OR (s.benefits    IS NOT NULL AND length(TRIM(s.benefits))    > 0)
     OR (s.raw_text    IS NOT NULL AND length(TRIM(s.raw_text))    > 0)
      )
"""

SOURCES_ORDER_REQ = "ORDER BY COALESCE(s.eval_target, 0) DESC, GREATEST(length(COALESCE(s.requirements,'')), length(COALESCE(s.raw_text,''))) DESC LIMIT %(k)s"
SOURCES_ORDER_BEN = "ORDER BY COALESCE(s.eval_content, 0) DESC, GREATEST(length(COALESCE(s.benefits,'')), length(COALESCE(s.raw_text,''))) DESC LIMIT %(k)s"

# 업데이트
UPDATE_TARGET_SQL = """
UPDATE documents
SET
    requirements = COALESCE(%(requirements)s, requirements),
    benefits     = COALESCE(%(benefits)s,     benefits),
    raw_text     = CASE
                     WHEN %(reinforce_note)s IS NULL THEN raw_text
                     WHEN raw_text IS NULL OR raw_text = '' THEN %(reinforce_note)s
                     ELSE raw_text || %(reinforce_note)s
                   END,
    llm_reinforced = TRUE,
    llm_reinforced_sources = %(provenance)s,
    updated_at = NOW()
WHERE id = %(doc_id)s
"""

DELETE_OLD_EMB = "DELETE FROM embeddings WHERE doc_id = %(doc_id)s AND field = ANY(%(fields)s)"
INSERT_EMB = "INSERT INTO embeddings (doc_id, field, embedding) VALUES %s"


# ──────────────────────────────────────────────────────────────────────────────
# LLM
# ──────────────────────────────────────────────────────────────────────────────
def build_prompt(title: str, sources: List[Dict[str, Any]], mode: str) -> Tuple[str, str]:
    """
    mode: 'requirements' | 'benefits' | 'both'
    """
    common_rules = """너는 한국의 보건/복지 문서를 통합·정제하는 전문가야.
여러 사이트에서 게시된 동일 정책의 텍스트를 모아 '지원 대상'과/또는 '지원 내용'을 정확하고 간결하게 통합해.
반드시 지킬 규칙:
1) 꾸미거나 추정하지 말 것 — 출처에 없는 수치/조건/절차 생성 금지. 불명확하면 '정보 없음' 유지.
2) 중복/모순 정리 — 표현은 간결하게, 상충 시 더 일반적이고 최신으로 보이는 표현을 선택. 확신 없으면 보수적으로.
3) 결과는 문장형 3~6줄 권장(불릿 허용). 동일/유사 문장은 합치기.
4) 지역 특화 표현은 일반화: '동작구 청년' → '청년', 'OO구 구민/거주자' → '주민' 등.
5) 반환은 JSON 한 줄:
   - requirements 모드: {"support_target": "..."}
   - benefits    모드: {"support_content": "..."}
   - both        모드: {"support_target": "...", "support_content": "..."}"""

    blocks = []
    for i, s in enumerate(sources, 1):
        meta = {
            "id": s["id"],
            "title": s.get("title") or "",
            "sitename": s.get("sitename") or "",
            "eval_target": s.get("eval_target"),
            "eval_content": s.get("eval_content"),
            "url": s.get("url") or "",
        }
        req = (s.get("requirements") or "").strip()
        ben = (s.get("benefits") or "").strip()
        raw = (s.get("raw_text") or "").strip()
        if len(raw) > 3000:
            raw = raw[:3000] + "\n[... 이하 생략 ...]"
        blocks.append(
            f"[SOURCE #{i}]\nMETA: {json.dumps(meta, ensure_ascii=False)}\n"
            f"REQUIREMENTS:\n{req if req else '(없음)'}\n"
            f"BENEFITS:\n{ben if ben else '(없음)'}\n"
            f"RAW:\n{raw if raw else '(없음)'}"
        )

    if mode == "requirements":
        want = 'JSON 스키마: {"support_target": "..."}'
    elif mode == "benefits":
        want = 'JSON 스키마: {"support_content": "..."}'
    else:
        want = 'JSON 스키마: {"support_target": "...", "support_content": "..."}'

    system = common_rules
    user = f"""정책 제목: {title}

소스들:
-------------------------------------------------------------------------------
{chr(10).join(blocks)}
-------------------------------------------------------------------------------
요청: 위 규칙에 따라 통합 정제 결과를 JSON으로만 반환.
{want}"""
    return system, user


def get_embedding(client: OpenAI, text: str, model: str):
    if not text or not text.strip():
        return None
    resp = client.embeddings.create(model=model, input=text.replace("\n", " "))
    return resp.data[0].embedding


# ──────────────────────────────────────────────────────────────────────────────
# Core
# ──────────────────────────────────────────────────────────────────────────────
def fetch_sources(conn, policy_id: int, target_id: int, k: int, for_field: str) -> List[Dict[str, Any]]:
    """
    for_field: 'requirements' | 'benefits'
    """
    order_sql = SOURCES_ORDER_REQ if for_field == "requirements" else SOURCES_ORDER_BEN
    with conn.cursor() as cur:
        cur.execute(SOURCES_SELECT_BASE + "\n" + order_sql, {"policy_id": policy_id, "target_id": target_id, "k": k})
        rows = cur.fetchall()

    cols = ["id","title","requirements","benefits","raw_text","url","sitename","eval_target","eval_content"]
    return [dict(zip(cols, r)) for r in rows]


def reinforce_field(
    conn,
    client: OpenAI,
    emb_model: str,
    llm_model: str,
    target_row: Dict[str, Any],
    field: str,           # 'requirements' or 'benefits'
    k: int,
    dry_run: bool = False
) -> bool:
    assert field in ("requirements", "benefits")
    target_id = target_row["id"]
    policy_id = target_row["policy_id"]
    title     = target_row["title"]

    sources = fetch_sources(conn, policy_id, target_id, k=k, for_field=field)
    if not sources:
        print(f"    · {field}: 소스 없음 → 건너뜀")
        return False

    # 디버그: 상위 5 소스 id와 점수
    if field == "requirements":
        dbg = ", ".join(f"{s['id']}:t={s.get('eval_target')}" for s in sources[:5])
    else:
        dbg = ", ".join(f"{s['id']}:c={s.get('eval_content')}" for s in sources[:5])
    print(f"    [Top5 {field} sources] {dbg}")

    # 프롬프트 (필요한 필드만)
    mode = "requirements" if field == "requirements" else "benefits"
    system, user = build_prompt(title, sources, mode)

    try:
        comp = client.chat.completions.create(
            model=llm_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        payload = json.loads(comp.choices[0].message.content)
        if field == "requirements":
            new_text = (payload.get("support_target") or "").strip()
        else:
            new_text = (payload.get("support_content") or "").strip()
    except Exception as e:
        print(f"    · {field}: LLM 실패 - {e}")
        return False

    if not new_text:
        print(f"    · {field}: 결과 비어있음")
        return False

    # 지역 일반화 후처리
    new_text = generalize_local_terms(new_text)

    if dry_run:
        print(f"    · {field}: (dry-run) '{new_text[:60]}{'...' if len(new_text)>60 else ''}'")
        return True

    # 업데이트 + 임베딩
    prov = {
        "policy_id": policy_id,
        "source_doc_ids": [s["id"] for s in sources],
        "rank_metric": "eval_target" if field == "requirements" else "eval_content",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "llm_model": llm_model,
        "target_field": field,
    }
    note = f"\n\n[LLM Reinforced {field} at {datetime.utcnow().isoformat()}Z] sources={','.join([str(s['id']) for s in sources])}\n"

    with conn.cursor() as cur:
        cur.execute(
            UPDATE_TARGET_SQL,
            {
                "requirements": new_text if field == "requirements" else None,
                "benefits":     new_text if field == "benefits"     else None,
                "reinforce_note": note,
                "provenance": Json(prov),
                "doc_id": target_id,
            },
        )
        # 임베딩 재계산(필드 한정)
        cur.execute(DELETE_OLD_EMB, {"doc_id": target_id, "fields": [field]})
        vec = get_embedding(client, new_text, emb_model)
        if vec:
            execute_values(cur, INSERT_EMB, [(target_id, field, vec)], template="(%s, %s, %s)")

    print(f"    · {field}: 업데이트 완료")
    return True


def main():
    p = argparse.ArgumentParser(description="LLM 보강 — eval_target/eval_content 기반 (weight 미사용)")
    p.add_argument("--policy-id", type=int, help="특정 policy_id만 처리")
    p.add_argument("--doc-id", type=int, help="특정 document id만 처리")

    # 기준(요청 고정값: 0~10에서 5 이하가 보강 대상)
    p.add_argument("--th-req", type=int, default=5, help="requirements 보강 임계값(eval_target ≤ th)")
    p.add_argument("--th-ben", type=int, default=5, help="benefits 보강 임계값(eval_content ≤ th)")

    p.add_argument("--k", type=int, default=5, help="각 필드 보강 시 사용할 소스 상위 K")
    p.add_argument("--limit", type=int, default=200, help="대상 문서 최대 개수")
    p.add_argument("--model", default="gpt-4o-mini", help="LLM 모델명")
    p.add_argument("--embed-model", default="text-embedding-3-small", help="임베딩 모델명")
    p.add_argument("--dry-run", action="store_true", help="DB 갱신 없이 시뮬레이션")
    p.add_argument("--no-add-columns", action="store_true", help="보강 컬럼 추가 생략")
    args = p.parse_args()

    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("환경변수 OPENAI_API_KEY가 필요합니다.", file=sys.stderr)
        sys.exit(1)

    dsn = build_dsn_from_env()
    conn = psycopg2.connect(dsn)
    client = OpenAI(api_key=api_key)

    try:
        with conn.cursor() as cur:
            if not args.no_add_columns:
                cur.execute(ALTER_DOCUMENTS_SQL)
        conn.commit()

        extra = []
        params = {"th_req": args.th_req, "th_ben": args.th_ben, "limit": args.limit}
        if args.policy_id:
            extra.append("AND d.policy_id = %(policy_id)s")
            params["policy_id"] = args.policy_id
        if args.doc_id:
            extra.append("AND d.id = %(doc_id)s")
            params["doc_id"] = args.doc_id

        sql = TARGET_SELECT.format(extra_filters="\n  " + "\n  ".join(extra) if extra else "")
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        cols = ["id","title","requirements","benefits","raw_text","url","policy_id","sitename","eval_target","eval_content"]
        targets = [dict(zip(cols, r)) for r in rows]

        if not targets:
            print("보강 대상 문서가 없습니다.")
            return

        print(f"대상 문서 수: {len(targets)}")
        ok = 0
        for i, t in enumerate(targets, 1):
            tid = t["id"]
            need_req = (t.get("eval_target")  is not None) and (t["eval_target"]  <= args.th_req)
            need_ben = (t.get("eval_content") is not None) and (t["eval_content"] <= args.th_ben)

            print(f"[{i}/{len(targets)}] ID={tid} policy_id={t['policy_id']} title={t['title']}")
            print(f"    eval_target={t.get('eval_target')}  eval_content={t.get('eval_content')}")
            updated_any = False

            if need_req:
                if reinforce_field(conn, client, args.embed_model, args.model, t, "requirements", args.k, args.dry_run):
                    updated_any = True
                    conn.commit()

            if need_ben:
                if reinforce_field(conn, client, args.embed_model, args.model, t, "benefits", args.k, args.dry_run):
                    updated_any = True
                    conn.commit()

            if updated_any:
                ok += 1

        print(f"완료: {ok}/{len(targets)} 문서 보강")

    except Exception as e:
        conn.rollback()
        print(f"에러 발생: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
