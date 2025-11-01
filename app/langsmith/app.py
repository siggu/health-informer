# service_graph.py
# 목적: Router → (Profile/Collection Saver) → Retrieval Planner → Answer LLM
#       전 과정을 LangGraph로 통합한 실행 파이프라인
#
# 준비:
#   pip install langgraph python-dotenv openai psycopg pydantic
#   환경변수: OPENAI_API_KEY, DATABASE_URL
#
# 파일 구성(동일 디렉터리 가정):
#   - router_node.py           (router_node)
#   - profile.py               (profile_saver_node)
#   - collection_saver.py      (collection_saver_node)
#   - retrieval_planner.py     (retrieval_planner_node)
#   - answer_llm.py            (answer_llm_node)

from __future__ import annotations
import os
from typing import TypedDict, Any, Dict

from dotenv import load_dotenv
load_dotenv()

# LangGraph
from langgraph.graph import StateGraph, END

# 각 노드 import
from router import router_node
from profile import profile_saver_node
from collection import collection_saver_node
from retrieval_planner import retrieval_planner_node
from answer_creator import answer_llm_node


# ─────────────────────────────────────────────────────────────────────────────
# 상태 정의(공유 스테이트)
# ─────────────────────────────────────────────────────────────────────────────
class GraphState(TypedDict, total=False):
    user_id: str
    input_text: str
    # router
    router: Dict[str, Any]
    # persist
    profile_delta: Dict[str, Any]
    triples_delta: Any
    persist_result: Dict[str, Any]
    # retrieval/answer
    retrieval: Dict[str, Any]
    answer: Dict[str, Any]


# ─────────────────────────────────────────────────────────────────────────────
# 분기 헬퍼: router.target 에 따라 흐름 제어
# ─────────────────────────────────────────────────────────────────────────────
def _route_after_router(state: GraphState) -> str:
    """
    router_node 실행 후 분기 결정:
      - PROFILE  → 'profile_saver'
      - COLLECTION → 'collection_saver'
      - BOTH → 'profile_saver' (이후 profile_saver에서 collection_saver로 추가 분기)
      - NONE → 'retrieval_planner'
    """
    r = (state.get("router") or {})
    tgt = (r.get("target") or "NONE").upper()
    if tgt == "PROFILE":
        return "profile_saver"
    if tgt == "COLLECTION":
        return "collection_saver"
    if tgt == "BOTH":
        return "profile_saver"
    return "retrieval_planner"

def _route_after_profile(state: GraphState) -> str:
    """
    profile_saver_node 이후:
      - router.target == BOTH 이면 collection_saver 도 진행
      - 아니면 retrieval_planner 로
    """
    r = (state.get("router") or {})
    tgt = (r.get("target") or "NONE").upper()
    if tgt == "BOTH":
        return "collection_saver"
    return "retrieval_planner"


# ─────────────────────────────────────────────────────────────────────────────
# 그래프 구성
# ─────────────────────────────────────────────────────────────────────────────
def build_graph():
    g = StateGraph(GraphState)

    # 1) 노드 등록
    g.add_node("router", router_node)
    g.add_node("profile_saver", profile_saver_node)
    g.add_node("collection_saver", collection_saver_node)
    g.add_node("retrieval_planner", retrieval_planner_node)
    g.add_node("answer_llm", answer_llm_node)

    # 2) 시작 노드
    g.set_entry_point("router")

    # 3) 조건 분기
    g.add_conditional_edges("router", _route_after_router, {
        "profile_saver": "profile_saver",
        "collection_saver": "collection_saver",
        "retrieval_planner": "retrieval_planner"
    })

    # 4) profile_saver 후 분기
    g.add_conditional_edges("profile_saver", _route_after_profile, {
        "collection_saver": "collection_saver",
        "retrieval_planner": "retrieval_planner"
    })

    # 5) collection_saver → retrieval_planner (직결)
    g.add_edge("collection_saver", "retrieval_planner")

    # 6) retrieval_planner → answer_llm → END
    g.add_edge("retrieval_planner", "answer_llm")
    g.add_edge("answer_llm", END)

    return g.compile()


# ─────────────────────────────────────────────────────────────────────────────
# 실행 유틸
# ─────────────────────────────────────────────────────────────────────────────
def run_once(user_id: str, text: str, *, source_id: str | None = None) -> Dict[str, Any]:
    """
    단일 입력 실행 도우미.
    반환: 최종 state(dict)
    """
    app = build_graph()
    init_state: GraphState = {
        "user_id": user_id,
        "input_text": text,
    }
    # source_id를 collection_saver에서 사용하고 싶다면 상태로 넘겨도 OK
    if source_id:
        init_state["source_id"] = source_id  # collection_saver에서 읽음

    # 동기 실행
    final_state: GraphState = app.invoke(init_state)  # langgraph>=0.2 스타일
    return final_state


# ─────────────────────────────────────────────────────────────────────────────
# 간단 실행 예시
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uid = os.getenv("TEST_USER_ID", "u_demo_1")

    samples = [
        "저 68세고 의료급여 2종입니다. 재난적의료비 대상일까요?",
        "6월에 유방암 C50.9 진단받고 항암 치료 중이고, 진단서 있습니다.",
        "안녕하세요",
        "저 68세고 6월에 유방암 C50.9 진단받고 항암 중입니다."  # BOTH 시나리오
    ]
    for i, s in enumerate(samples, 1):
        print("\n", "="*80, f"\n[Sample {i}] {s}\n", "="*80)
        out = run_once(uid, s, source_id=f"msg:{i}")
        # 최종 답변
        ans = (out.get("answer") or {}).get("text", "")
        print(ans)
