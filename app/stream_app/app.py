import streamlit as st
from datetime import date
import uuid
import time
import json
import re

from src.state_manger import initialize_session_state
from src.pages.auth import (
    initialize_auth_state,
    render_auth_modal,
    render_login_tab,
    render_signup_tab,
)

from src.widgets.sidebar import render_sidebar
from src.utils.template_loader import load_template, render_template, load_css
from src.utils.session_manager import load_session, update_login_status

from src.backend_service import (
    api_send_chat_message,
    api_reset_password,
    api_delete_account,
    api_get_user_info,
)
from src.pages.settings import (
    render_settings_modal as render_settings_modal_external,
    initialize_settings_state as initialize_settings_state_external,
)
from src.pages.my_page import render_my_page_modal as render_my_page_modal_external
from src.pages.chat import render_chatbot_main as render_chatbot_main_external
from dotenv import load_dotenv


load_dotenv()

# ==============================================================================
# 0. 전역 설정 및 CSS 주입
# ==============================================================================

st.set_page_config(
    page_title="의료 혜택 정보 제공 에이전트 챗봇",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS 스타일 주입
load_css("custom.css")


# ==============================================================================
# 1. 상태 초기화 (st.session_state)
# ==============================================================================

if "profiles" not in st.session_state:
    st.session_state.profiles = []
# ================세션 초기화 기본 문법=============================
# # Initialization
# if 'key' not in st.session_state:
#     st.session_state['key'] = 'value'

# # Session State also supports attribute based syntax
# if 'key' not in st.session_state:
#     st.session_state.key = 'value'
# =============================================================


# 마이페이지 / 설정 모달 관련 상태
if "isAddingProfile" not in st.session_state:  # 프로필 추가 열렸는지 확인
    st.session_state.isAddingProfile = False
if "editingProfileId" not in st.session_state:  # 프로필 수정 상태 초기화
    st.session_state.editingProfileId = None
if "newProfile" not in st.session_state:  # 프로필 추가 세션
    st.session_state.newProfile = {}
if "editingData" not in st.session_state:
    st.session_state.editingData = {}
initialize_settings_state_external()

# 사이드바/챗봇 관련 상태
# 대화 내용 검색 필드의 초기값 설정
if "search_query" not in st.session_state:
    st.session_state.search_query = ""


# 사이드바 검색 입력 필드의 초기값 설정.
if "sidebar_search_input" not in st.session_state:
    st.session_state.sidebar_search_input = ""

# ==============================================================================
# 2. 유틸리티 및 핸들러 함수
# ==============================================================================


def handle_logout():
    st.info("👋 로그아웃되었습니다.")
    st.session_state.settings_modal_open = False


# --- Sidebar 핸들러 ---
def handle_search_update():
    st.session_state.search_query = st.session_state.sidebar_search_input


def handle_settings_click():
    st.session_state.settings_modal_open = True


# ==============================================================================
# 3. 컴포넌트 렌더링 함수
# ==============================================================================


# --- A. ErrorMessage 컴포넌트 ---
def render_error_message(error_type: str, message: str, on_action_click=None):
    def get_error_config(type_key):
        if type_key == "no-policy":
            return {
                "title": "정책을 찾을 수 없습니다",
                "action": "다른 정책 검색해보기",
            }
        elif type_key == "llm-error":
            return {"title": "서버 연결 오류", "action": "다시 시도"}
        elif type_key == "inappropriate":
            return {"title": "부적절한 내용", "action": None}
        elif type_key == "unclear":
            return {
                "title": "질문이 명확하지 않습니다",
                "action": "구체적으로 질문하기",
            }
        else:
            return {"title": "오류 발생", "action": "다시 시도"}

    config = get_error_config(error_type)

    st.error(f"**{config['title']}**")
    st.markdown(
        f"<p style='font-size: 14px; color: gray; margin-top: -15px;'>{message}</p>",
        unsafe_allow_html=True,
    )

    if config["action"]:
        st.button(
            f"🔄 {config['action']}",
            key=f"error_action_{error_type}",
            on_click=(
                on_action_click
                # if on_action_click
                # else lambda: st.toast(f"액션 실행: {config['action']}")
                if on_action_click
                else lambda: st.info(f"액션 실행: {config['action']}")
            ),
        )



# ==============================================================================
# 4. 메인 앱 실행 로직 (Application Flow)
# ==============================================================================

# 추천 질문 목록
SUGGESTED_QUESTIONS = [
    "청년 주거 지원 정책이 궁금해요",
    "취업 지원 프로그램 알려주세요",
    "창업 지원금 신청 방법은?",
    "육아 지원 혜택 찾아주세요",
]


def render_chatbot_main():
    # 외부 모듈에서 임포트된 함수 사용 (src.pages.chat)
    render_chatbot_main_external()


def render_my_page_modal():
    """마이페이지 모달 렌더링 (프로필 추가 / 편집 기능 포함)"""
    st.markdown(
        """
        <style>
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: rgba(0, 0, 0, 0.5);
            z-index: 1000;
            display: flex;
            justify-content: flex-end;
            align-items: stretch;
        }
        .modal-content {
            background-color: white;
            width: 420px;
            height: 100vh;
            overflow-y: auto;
            padding: 24px;
            box-shadow: -2px 0 8px rgba(0,0,0,0.1);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # 헤더
    col_title, col_close = st.columns([9, 1])
    with col_title:
        st.markdown("### 마이페이지")
        st.caption("프로필 정보와 설정을 관리하세요")
    with col_close:
        if st.button("✕", key="btn_close_my_page"):
            st.session_state["show_profile"] = False
            st.rerun()

    st.markdown("---")

    # 프로필 관리 헤더 및 추가 버튼
    st.markdown("#### 프로필 관리")
    if not st.session_state.get("isAddingProfile", False):
        if st.button("➕ 프로필 추가", key="btn_add_profile", use_container_width=True):
            # 토글 및 임시 newProfile 초기화
            st.session_state["isAddingProfile"] = True
            st.session_state["newProfile"] = DEFAULT_NEW_PROFILE.copy()
            st.rerun()

    st.markdown("")

    # 현재 활성 프로필 확인
    active_profile = next(
        (p for p in st.session_state.profiles if p.get("isActive", False)), None
    )
    if active_profile and is_profile_incomplete(active_profile):
        st.warning("정확한 추천을 위해 프로필 정보를 완성해주세요.")

    st.markdown("---")

    # --- 새 프로필 추가 폼 ---
    if st.session_state.get("isAddingProfile", False):
        st.markdown("##### 새 프로필 추가")
        np = st.session_state.get("newProfile", DEFAULT_NEW_PROFILE.copy())
        with st.form("add_profile_form"):
            name = st.text_input(
                "프로필 이름 *", value=np.get("name", ""), key="add_name"
            )
            birth = st.date_input(
                "생년월일",
                value=np.get("birthDate", date(2000, 1, 1)),
                min_value=date(1920, 1, 1),
                max_value=date.today(),
                key="add_birthdate",
            )
            gender = st.selectbox(
                "성별",
                options=["남성", "여성"],
                index=0 if np.get("gender", "남성") == "남성" else 1,
                key="add_gender",
            )
            location = st.text_input(
                "거주지 *", value=np.get("location", ""), key="add_location"
            )
            health = st.selectbox(
                "건강보험",
                options=["직장", "지역", "피부양", "의료급여"],
                index=0 if np.get("healthInsurance", "직장") == "직장" else 1,
                key="add_health",
            )
            income = st.number_input(
                "소득 수준(숫자)",
                min_value=0,
                max_value=100000000,
                value=np.get("incomeLevel", 0),
                key="add_income",
            )
            basic = st.selectbox(
                "기초생활수급",
                options=["없음", "생계", "의료", "주거", "교육"],
                index=0 if np.get("basicLivelihood", "없음") == "없음" else 0,
                key="add_basic",
            )

            col_submit, col_cancel = st.columns([1, 1])
            with col_submit:
                if st.form_submit_button("추가", use_container_width=True):
                    new_profile_data = {
                        "name": name.strip(),
                        "birthDate": birth,
                        "gender": gender,
                        "location": location.strip(),
                        "healthInsurance": health,
                        "incomeLevel": income,
                        "basicLivelihood": basic,
                        "disabilityLevel": np.get("disabilityLevel", "0"),
                        "longTermCare": np.get("longTermCare", "NONE"),
                        "pregnancyStatus": np.get("pregnancyStatus", "없음"),
                    }
                    if not new_profile_data["name"] or not new_profile_data["location"]:
                        st.error("프로필 이름과 거주지는 필수 입력 항목입니다.")
                    else:
                        handle_add_profile(new_profile_data)
            with col_cancel:
                if st.form_submit_button("취소", use_container_width=True):
                    st.session_state["isAddingProfile"] = False
                    st.session_state["newProfile"] = DEFAULT_NEW_PROFILE.copy()
                    st.rerun()

        st.markdown("---")

    # --- 기본(활성) 프로필 표시 및 편집 진입 ---
    st.markdown("#### 기본 프로필")
    if active_profile:
        col_active, col_edit = st.columns([8, 1])
        with col_active:
            st.markdown("**활성** ✓")
            # 간단한 요약 표시
            bd_val = active_profile.get("birthDate")
            age = calculate_age(bd_val)
            birth_display = f"{age}세" if isinstance(age, int) else "미입력"
            st.write(f"- 이름: {active_profile.get('name', '미입력')}")
            st.write(f"- 생년월일: {birth_display}")
            st.write(f"- 거주지: {active_profile.get('location', '미입력')}")
        with col_edit:
            if st.button("✏️", key=f"btn_edit_profile_{active_profile['id']}"):
                st.session_state["editingProfileId"] = active_profile["id"]
                st.session_state["editingData"] = active_profile.copy()
                st.rerun()
    else:
        st.info("등록된 프로필이 없습니다. 새 프로필을 추가하세요.")

    st.markdown("---")

    # --- 편집 모드 폼 ---
    if st.session_state.get("editingProfileId"):
        st.markdown("##### 프로필 수정")
        ed = st.session_state.get("editingData", {})
        with st.form("edit_profile_form"):
            name = st.text_input(
                "프로필 이름 *", value=ed.get("name", ""), key="edit_name"
            )
            birth = st.date_input(
                "생년월일",
                value=_parse_birthdate(ed.get("birthDate")) or date(1990, 1, 1),
                min_value=date(1920, 1, 1),
                max_value=date.today(),
                key="edit_birthdate",
            )
            gender = st.selectbox(
                "성별",
                options=["남성", "여성"],
                index=0 if ed.get("gender", "남성") == "남성" else 1,
                key="edit_gender",
            )
            location = st.text_input(
                "거주지 *", value=ed.get("location", ""), key="edit_location"
            )
            health = st.selectbox(
                "건강보험",
                options=["직장", "지역", "피부양", "의료급여"],
                index=0 if ed.get("healthInsurance", "직장") == "직장" else 0,
                key="edit_health",
            )
            income = st.number_input(
                "소득 수준(숫자)",
                min_value=0,
                max_value=100000000,
                value=ed.get("incomeLevel", 0),
                key="edit_income",
            )
            basic = st.selectbox(
                "기초생활수급",
                options=["없음", "생계", "의료", "주거", "교육"],
                index=0 if ed.get("basicLivelihood", "없음") == "없음" else 0,
                key="edit_basic",
            )

            col_save, col_cancel = st.columns([1, 1])
            with col_save:
                if st.form_submit_button("저장", use_container_width=True):
                    edited_data = {
                        "id": st.session_state.editingProfileId,
                        "name": name.strip(),
                        "birthDate": birth,
                        "gender": gender,
                        "location": location.strip(),
                        "healthInsurance": health,
                        "incomeLevel": income,
                        "basicLivelihood": basic,
                        "disabilityLevel": ed.get("disabilityLevel", "0"),
                        "longTermCare": ed.get("longTermCare", "NONE"),
                        "pregnancyStatus": ed.get("pregnancyStatus", "없음"),
                    }
                    if not edited_data["name"] or not edited_data["location"]:
                        st.error("프로필 이름과 거주지는 필수 입력 항목입니다.")
                    else:
                        handle_save_edit(edited_data)
            with col_cancel:
                if st.form_submit_button("취소", use_container_width=True):
                    handle_cancel_edit()

        st.markdown("---")

    # --- 프로필 리스트: 선택/삭제 ---
    st.markdown("#### 등록된 프로필")
    for profile in st.session_state.profiles:
        cols = st.columns([6, 1, 1])
        with cols[0]:
            st.write(
                f"- {profile.get('name', '무명')} ({profile.get('location','미입력')})"
            )
        with cols[1]:
            if st.button("선택", key=f"select_{profile['id']}"):
                handle_profile_switch(profile["id"])
        with cols[2]:
            if st.button("삭제", key=f"del_{profile['id']}"):
                handle_delete_profile(profile["id"])

    st.markdown("---")

    # 알림 / 비밀번호 재설정 / 회원 탈퇴 / 로그아웃 기존 로직 유지
    st.markdown("#### 알림 설정")
    st.checkbox(
        "신규 정책 알림",
        value=st.session_state.notifications.get("newPolicy", False),
        key="mp_new_policy",
    )
    st.checkbox(
        "마감 임박 알림",
        value=st.session_state.notifications.get("deadline", False),
        key="mp_deadline",
    )

    st.markdown("---")

    st.markdown("#### 비밀번호 재설정")
    if st.button("🔒 비밀번호 재설정", key="btn_reset_pw", use_container_width=True):
        st.session_state["show_profile"] = False
        st.session_state["settings_modal_open"] = True
        st.session_state["show_password_reset"] = True
        st.rerun()

    st.markdown("---")

    st.markdown("#### 회원 탈퇴")
    if st.button("🗑️ 회원 탈퇴", key="btn_delete_account", use_container_width=True):
        st.session_state["show_delete_confirm"] = True
        st.rerun()

    st.markdown("---")

    if st.button("→ 로그아웃", key="btn_logout", use_container_width=True):
        # 로그아웃 상태 저장(세션 파일 유지)
        update_login_status(is_logged_in=False)
        st.session_state["is_logged_in"] = False
        st.session_state["show_profile"] = False
        # 기본 메시지 초기화
        st.session_state["messages"] = [
            {
                "id": str(uuid.uuid4()),
                "role": "assistant",
                "content": "안녕하세요! 정책 추천 챗봇입니다. 나이, 거주지, 관심 분야를 알려주시면 맞춤형 정책을 추천해드립니다.",
                "timestamp": time.time(),
            }
        ]
        # clear_session()  # 세션 파일 삭제 부분 주석 처리
        st.success("로그아웃 되었습니다.")
        st.rerun()


def main_app():
    # 사이드바 네비게이션 숨기기
    st.markdown(
        """
        <style>
            [data-testid="stSidebarNav"] {display: none !important;}
            .main-content {
                max-width: 100%;
                padding: 20px;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    initialize_session_state()
    initialize_auth_state()

    # 저장된 세션이 있으면 복원
    if not st.session_state.get("is_logged_in", False):
        saved_session = load_session()
        if saved_session and saved_session.get("is_logged_in"):
            st.session_state["is_logged_in"] = True
            st.session_state["user_info"] = saved_session.get("user_info", {})
            # 프로필도 복원 (백엔드에서 조회)
            user_id = saved_session.get("user_id")
            if user_id:
                ok, user_info = api_get_user_info(user_id)
                if ok:
                    st.session_state["user_info"] = user_info
                    profile = user_info.get("profile", {}) or {}
                    st.session_state["profiles"] = [
                        {
                            "id": user_id,
                            "name": user_info.get("profile", {}).get("name", ""),
                            "birthDate": profile.get("birthDate", ""),
                            "gender": profile.get("gender", ""),
                            "location": profile.get("location", ""),
                            "healthInsurance": profile.get("healthInsurance", ""),
                            "incomeLevel": profile.get("incomeLevel", 0),
                            "basicLivelihood": profile.get("basicLivelihood", "없음"),
                            "disabilityLevel": profile.get("disabilityLevel", "0"),
                            "longTermCare": profile.get("longTermCare", "NONE"),
                            "pregnancyStatus": profile.get("pregnancyStatus", "없음"),
                            "isActive": True,
                        }
                    ]
            # 세션 복원 완료

    # 로그인 상태 확인
    if not st.session_state.get("is_logged_in", False):
        # 비로그인 상태: 첫 화면에 로그인/회원가입 모두 표시
        render_landing_page()
    else:
        # 로그인 상태
        # 사이드바 렌더링
        render_sidebar()

        # 설정 모달과 마이페이지 모달은 동시에 열리지 않도록 처리
        if st.session_state.get("settings_modal_open", False):
            # 설정 모달이 열려있으면 마이페이지 닫기
            st.session_state["show_profile"] = False
            render_settings_modal_external()
        elif st.session_state.get("show_profile", False):
            # 마이페이지가 열려있으면 설정 모달 닫기
            st.session_state["settings_modal_open"] = False
            render_my_page_modal_external()
        else:
            # 메인 챗봇 화면 (모달이 열려있지 않을 때만)
            render_chatbot_main()


def render_landing_page():
    """첫 화면: 로그인/회원가입 모두 표시"""
    # CSS 로드
    load_css("components/landing_page.css")

    # 랜딩 페이지 HTML 렌더링
    render_template("landing_page.html")

    # 로그인/회원가입 탭
    login_tab, signup_tab = st.tabs(["로그인", "회원가입"])

    with login_tab:
        render_login_tab()

    with signup_tab:
        render_signup_tab()


if __name__ == "__main__":
    main_app()
