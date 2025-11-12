# -*- coding: utf-8 -*-
# app/dao/utils_db.py 내에 추가

from typing import Optional, Tuple, Set, List
from urllib.parse import urlparse
import sys

def extract_sitename_from_url(url: str) -> str:
    """
    URL에서 사이트명 추출

    Args:
        url: URL 문자열

    Returns:
        지역명 (예: "강남구보건소", "동작구보건소 공지사항") 또는 "unknown"
    """
    region_mapping = {
        "gangnam": "강남구보건소",
        "gangdong": "강동구보건소",
        "gangbuk": "강북구보건소",
        "gangseo": "강서구보건소",
        "guro": "구로구보건소",
        "gwanak": "관악구보건소",
        "dongjak": "동작구보건소",
        "ddm": "동대문구보건소",
        "gwangjin": "광진구보건소",
        "nowon": "노원구보건소",
        "jongno": "종로구보건소",
        "yongsan": "용산구보건소",
        "junggu": "중구보건소",
        "dobong": "도봉구보건소",
        "mapo": "마포구보건소",
        "sdm": "서대문구보건소",
        "seocho": "서초구보건소",
        "sd": "성동구보건소",
        "sb": "성북구보건소",
        "songpa": "송파구보건소",
        "yangcheon": "양천구보건소",
        "ydp": "영등포구보건소",
        "seoul-agi": "서울시 임신-출산정보센터",
        "wis.seoul": "서울복지포털",
        "news.seoul": "서울특별시 공식사이트",
        "e-health": "e보건소",
        "bokjiro": "복지로",
        "nhis": "국민건강보험공단"
    }

    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()

    for key, value in region_mapping.items():
        if key in domain:
            return value

    # 매핑 실패 시 도메인 첫 부분 반환
    return domain.split(".")[0] if "." in domain else "unknown"

# --------------------------------
# 3. 가중치 계산
# --------------------------------
def get_weight(region: str, sitename: str):
    if not region:
        return 1
    region = region.strip()
    if "전국" in region:
        return 2
    elif "서울" in region:
        if "서울복지포털" in sitename:
            return 3 # 서울복지포털(가중치 낮음)
        else:
            return 4
    else:
        if "공지사항" not in sitename:
            return 5 # 구 보건소
        else:
            return 6  # 구 보건소 공지사항

# --------------------------------
# 0. 유틸
# --------------------------------
def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)
    
def _detect_policy_edge_table(cur) -> Optional[Tuple[str, str, str]]:
    """
    policy 트리 edge 테이블과 parent/child 컬럼명을 자동 탐지.
    반환: (table, parent_col, child_col) 또는 None
    """
    table_candidates = ["policy_edges", "policy_links", "policy_graph"]
    col_pairs = [
        ("parent_policy_id", "child_policy_id"),
        ("src_policy_id", "dst_policy_id"),
        ("parent_id", "child_id"),
    ]
    for t in table_candidates:
        cur.execute("""
            SELECT 1 FROM information_schema.tables
            WHERE table_name = %s
        """, (t,))
        if cur.fetchone():
            # 이 테이블에서 가능한 컬럼쌍을 찾기
            for pcol, ccol in col_pairs:
                cur.execute("""
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name=%s AND column_name=%s
                """, (t, pcol))
                has_p = cur.fetchone() is not None
                cur.execute("""
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name=%s AND column_name=%s
                """, (t, ccol))
                has_c = cur.fetchone() is not None
                if has_p and has_c:
                    return (t, pcol, ccol)
    return None

def get_policy_root_id(conn, policy_id: int) -> int:
    """
    주어진 policy_id가 속한 트리의 root policy_id를 반환.
    edge 테이블이 없으면 입력값을 그대로 반환.
    """
    with conn.cursor() as cur:
        det = _detect_policy_edge_table(cur)
        if not det:
            return policy_id
        table, parent_col, child_col = det

        current = policy_id
        seen = set()
        while True:
            if current in seen:
                # 순환 보호
                return current
            seen.add(current)
            cur.execute(
                f"SELECT {parent_col} FROM {table} WHERE {child_col} = %s LIMIT 1",
                (current,)
            )
            row = cur.fetchone()
            if not row or row[0] is None:
                # 더 이상 부모가 없으면 current가 root
                return current
            current = int(row[0])

def get_policy_subtree_ids(conn, root_policy_id: int) -> Set[int]:
    """
    root policy_id로부터 하위 모든 policy_id(자기 자신 포함)를 집합으로 반환.
    edge 테이블이 없으면 {root_policy_id} 만 반환.
    """
    with conn.cursor() as cur:
        det = _detect_policy_edge_table(cur)
        if not det:
            return {root_policy_id}
        table, parent_col, child_col = det

        # BFS/DFS로 자식 노드 모두 수집
        result: Set[int] = set()
        stack: List[int] = [root_policy_id]
        while stack:
            pid = stack.pop()
            if pid in result:
                continue
            result.add(pid)
            cur.execute(
                f"SELECT {child_col} FROM {table} WHERE {parent_col} = %s",
                (pid,)
            )
            for (child,) in cur.fetchall():
                if child is not None and int(child) not in result:
                    stack.append(int(child))
        return result

def get_policy_subtree_ids_by_policy(conn, policy_id: int) -> Set[int]:
    """
    policy_id를 받아 root를 찾은 뒤 서브트리 전체를 반환.
    """
    root = get_policy_root_id(conn, policy_id)
    return get_policy_subtree_ids(conn, root)

def get_document_ids_in_subtree(conn, root_policy_id: int) -> List[int]:
    """
    서브트리 전체(policy_id in (...))에 속한 documents.id 목록을 반환.
    """
    pids = list(get_policy_subtree_ids(conn, root_policy_id))
    if not pids:
        return []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM documents WHERE policy_id = ANY(%s)",
            (pids,)
        )
        return [r[0] for r in cur.fetchall()]
    