"""세션 관리 유틸리티 - 로그인 상태 영구 저장"""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any


def get_session_file_path() -> Path:
    """세션 파일 경로 반환"""
    base_dir = Path(__file__).parent.parent.parent
    session_dir = base_dir / ".session"
    session_dir.mkdir(exist_ok=True)
    return session_dir / "user_session.json"


def save_session(user_id: str, user_info: Dict[str, Any]):
    """로그인 세션을 파일에 저장"""
    session_file = get_session_file_path()
    session_data = {"user_id": user_id, "user_info": user_info, "is_logged_in": True}

    try:
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        print(f"세션 저장 실패: {e}")


def load_session() -> Optional[Dict[str, Any]]:
    """저장된 세션을 파일에서 로드"""
    session_file = get_session_file_path()

    if not session_file.exists():
        return None

    try:
        with open(session_file, "r", encoding="utf-8") as f:
            session_data = json.load(f)
        return session_data
    except Exception as e:
        print(f"세션 로드 실패: {e}")
        return None


def clear_session():
    """세션 파일 삭제"""
    session_file = get_session_file_path()
    try:
        if session_file.exists():
            session_file.unlink()
    except Exception as e:
        print(f"세션 삭제 실패: {e}")
