import streamlit as st
from datetime import date
import uuid
import time

from src.state_manger import initialize_session_state
from src.widgets.auth_widgets import (
    initialize_auth_state,
    render_auth_modal,
    render_login_tab,
    render_signup_tab,
)
from src.widgets.sidebar import render_sidebar
from src.widgets.policy_card import render_policy_card
from src.utils.template_loader import load_template, render_template, load_css
from src.utils.session_manager import load_session, clear_session
from src.backend_service import (
    api_send_chat_message,
    api_reset_password,
    api_delete_account,
)

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

# 공통 기본 프로필 데이터
DEFAULT_NEW_PROFILE = {
    "name": "",
    "birthDate": date(1950, 1, 1),
    "gender": "남성",
    "location": "",
    "healthInsurance": "직장",
    "incomeLevel": 0,
    "basicLivelihood": "없음",
    "disabilityLevel": "0",
    "longTermCare": "NONE",
    "pregnancyStatus": "없음",
}

if "profiles" not in st.session_state:
    st.session_state.profiles = [
        {
            "id": str(uuid.uuid4()),
            "name": "기본 프로필",
            "birthDate": date(1950, 1, 1),
            "gender": "남성",
            "location": "서울시 강남구",
            "healthInsurance": "직장",
            "incomeLevel": 100,
            "basicLivelihood": "없음",
            "disabilityLevel": "0",
            "longTermCare": "NONE",
            "pregnancyStatus": "없음",
            "isActive": True,
        }
    ]
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
    st.session_state.newProfile = DEFAULT_NEW_PROFILE.copy()
if "editingData" not in st.session_state:
    st.session_state.editingData = {}
if "settings_modal_open" not in st.session_state:  # SettingsModal 상태
    st.session_state.settings_modal_open = False

# SettingsModal 내부 상태
if "font_size" not in st.session_state:
    st.session_state.font_size = "medium"
if "notifications" not in st.session_state:
    st.session_state.notifications = {
        "newPolicy": True,
        "deadline": True,
        "updates": False,
    }
if "show_delete_confirm" not in st.session_state:
    st.session_state.show_delete_confirm = False
if "show_password_reset" not in st.session_state:
    st.session_state.show_password_reset = False
if "password_data" not in st.session_state:
    st.session_state.password_data = {"current": "", "new": "", "confirm": ""}
if "password_error" not in st.session_state:
    st.session_state.password_error = ""

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


def calculate_age(birth_date):
    """생년월일(date 객체)을 기준으로 나이를 계산합니다."""
    today = date.today()
    return (
        today.year
        - birth_date.year
        - ((today.month, today.day) < (birth_date.month, birth_date.day))
    )


def is_profile_incomplete(profile):
    """필수 필드가 비어 있는지 확인합니다."""
    required_fields = [
        "name",
        "birthDate",
        "gender",
        "location",
        "healthInsurance",
        "incomeLevel",
    ]
    for field in required_fields:
        if not profile.get(field) and profile.get(field) != 0:
            return True
    return False


# --- 프로필 관리 핸들러 ---
def handle_profile_switch(profile_id):
    for p in st.session_state.profiles:
        p["isActive"] = p["id"] == profile_id
    st.rerun()


def handle_delete_profile(profile_id):
    if len(st.session_state.profiles) <= 1:
        st.warning("최소한 하나의 프로필은 남겨야 합니다.")
        return
    new_profiles = [p for p in st.session_state.profiles if p["id"] != profile_id]
    is_deleted_active = next(
        (p for p in st.session_state.profiles if p["id"] == profile_id), {}
    ).get("isActive", False)
    if is_deleted_active:
        new_profiles[0]["isActive"] = True
    st.session_state.profiles = new_profiles
    st.rerun()


def handle_add_profile(new_profile_data):
    if not new_profile_data["name"] or not new_profile_data["location"]:
        st.error("프로필 이름과 거주지는 필수 입력 항목입니다.")
        return
    for p in st.session_state.profiles:
        p["isActive"] = False
    new_profile = {"id": str(uuid.uuid4()), **new_profile_data, "isActive": True}
    st.session_state.profiles.append(new_profile)
    st.session_state.isAddingProfile = False
    st.session_state.newProfile = DEFAULT_NEW_PROFILE.copy()
    st.rerun()


def handle_start_edit(profile):
    st.session_state.editingProfileId = profile["id"]
    # 필요한 모든 필드를 editingData에 복사
    st.session_state.editingData = profile.copy()
    st.rerun()


def handle_save_edit(edited_data):
    pid = st.session_state.editingProfileId
    if not edited_data["name"] or not edited_data["location"]:
        st.error(
            "프로필 이름과 거주지는 필수 입력 항목입니다. 편집 내용을 확인해주세요."
        )
        return
    new_profiles = [
        ({**p, **edited_data} if p["id"] == pid else p)
        for p in st.session_state.profiles
    ]
    st.session_state.profiles = new_profiles
    st.session_state.editingProfileId = None
    st.session_state.editingData = {}
    st.rerun()


def handle_cancel_edit():
    st.session_state.editingProfileId = None
    st.session_state.editingData = {}
    st.rerun()


def handle_logout():
    st.info("👋 로그아웃되었습니다.")
    st.session_state.settings_modal_open = False


# --- SettingsModal 핸들러 ---
def handle_font_size_change(size):
    st.session_state.font_size = size
    st.success(f"글자 크기가 '{size}로 설정되었습니다.")


def update_notification(key):
    st.session_state.notifications[key] = st.session_state[f"switch_{key}"]


def handle_password_reset():
    data = st.session_state.password_data
    if not data["current"] or not data["new"] or not data["confirm"]:
        st.session_state.password_error = "모든 필드를 입력해주세요."
        return
    if data["new"] != data["confirm"]:
        st.session_state.password_error = "새 비밀번호가 일치하지 않습니다."
        return
    if len(data["new"]) < 8:
        st.session_state.password_error = "비밀번호는 8자 이상이어야 합니다."
        return

    # 비밀번호 변경 (Mock)
    success, message = api_reset_password(data["current"], data["new"])

    if success:
        st.success(f"🔒 {message}")
        st.session_state.show_password_reset = False
        st.session_state.password_data = {"current": "", "new": "", "confirm": ""}
        st.session_state.password_error = ""
    else:
        st.session_state.password_error = message


def reset_password_form():
    st.session_state.show_password_reset = False
    st.session_state.password_data = {"current": "", "new": "", "confirm": ""}
    st.session_state.password_error = ""


def toggle_delete_confirm(value):
    st.session_state.show_delete_confirm = value


def handle_account_delete():
    # 회원 탈퇴 (Mock)
    success, message = api_delete_account()

    if success:
        st.error(f"🗑️ {message}")
        st.session_state.settings_modal_open = False
        st.session_state["is_logged_in"] = False
        clear_session()
        st.rerun()
    else:
        st.error(f"🗑️ {message}")


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


# --- B. SettingsModal 컴포넌트 ---
def render_settings_modal():
    """설정 모달 렌더링 (5번째 사진 참고)"""
    # 모달 오버레이 및 스타일
    st.markdown(
        """
        <style>
        .settings-modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: rgba(0, 0, 0, 0.5);
            z-index: 1000;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # 모달 헤더
    col_title, col_close = st.columns([9, 1])
    with col_title:
        st.markdown("### ⚙️ 설정")
        st.caption("계정 및 알림 설정을 관리합니다.")
    with col_close:
        if st.button("✕", key="btn_close_settings"):
            st.session_state.settings_modal_open = False
            st.rerun()

    st.markdown("---")

    # 글자 크기 조절
    st.markdown("#### 글자 크기 조절")
    col_small, col_medium, col_large = st.columns(3)

    with col_small:
        is_small = st.session_state.font_size == "small"
        if st.button(
            "작게",
            key="font_small",
            type="primary" if is_small else "secondary",
            use_container_width=True,
            on_click=handle_font_size_change,
            args=("small",),
        ):
            pass

    with col_medium:
        is_medium = st.session_state.font_size == "medium"
        if st.button(
            "보통",
            key="font_medium",
            type="primary" if is_medium else "secondary",
            use_container_width=True,
            on_click=handle_font_size_change,
            args=("medium",),
        ):
            pass

    with col_large:
        is_large = st.session_state.font_size == "large"
        if st.button(
            "크게",
            key="font_large",
            type="primary" if is_large else "secondary",
            use_container_width=True,
            on_click=handle_font_size_change,
            args=("large",),
        ):
            pass

    st.markdown("---")

    # 알림 수신 설정
    st.markdown("#### 알림 수신 설정")
    st.checkbox(
        "신규 정책 알림",
        value=st.session_state.notifications.get("newPolicy", True),
        key="switch_newPolicy",
        on_change=lambda: update_notification("newPolicy"),
    )
    st.checkbox(
        "마감 임박 알림",
        value=st.session_state.notifications.get("deadline", True),
        key="switch_deadline",
        on_change=lambda: update_notification("deadline"),
    )
    st.checkbox(
        "정책 업데이트 알림",
        value=st.session_state.notifications.get("updates", False),
        key="switch_updates",
        on_change=lambda: update_notification("updates"),
    )

    st.markdown("---")

    # 비밀번호 변경
    st.markdown("#### 비밀번호 변경")
    if not st.session_state.show_password_reset:
        st.text_input(
            "비밀번호 변경",
            key="password_change_input",
            placeholder="비밀번호 변경",
            disabled=True,
        )
    else:
        with st.form(key="password_reset_form"):
            st.text_input("현재 비밀번호 *", type="password", key="current-password")
            st.text_input("새 비밀번호 *", type="password", key="new-password")
            st.text_input("새 비밀번호 확인 *", type="password", key="confirm-password")
            st.session_state.password_data["current"] = st.session_state.get(
                "current-password", ""
            )
            st.session_state.password_data["new"] = st.session_state.get(
                "new-password", ""
            )
            st.session_state.password_data["confirm"] = st.session_state.get(
                "confirm-password", ""
            )

            if st.session_state.get("password_error"):
                st.error(f"⚠️ {st.session_state.password_error}")

            col_submit, col_cancel = st.columns(2)
            with col_submit:
                if st.form_submit_button("변경하기", use_container_width=True):
                    handle_password_reset()
            with col_cancel:
                if st.form_submit_button(
                    "취소", on_click=reset_password_form, use_container_width=True
                ):
                    pass

    st.markdown("---")

    # 회원 탈퇴
    st.markdown("#### 회원 탈퇴")
    if not st.session_state.show_delete_confirm:
        if st.button(
            "회원 탈퇴",
            key="delete_button_initial",
            on_click=toggle_delete_confirm,
            args=(True,),
            use_container_width=True,
            type="primary",
        ):
            pass
    else:
        st.warning(
            "⚠️ 회원 탈퇴 시 모든 데이터가 삭제되며 복구할 수 없습니다. 정말로 탈퇴하시겠습니까?"
        )
        col_delete, col_cancel_delete = st.columns(2)
        with col_delete:
            st.button(
                "탈퇴하기",
                key="delete_button_confirm",
                on_click=handle_account_delete,
                use_container_width=True,
            )
        with col_cancel_delete:
            st.button(
                "취소",
                key="delete_button_cancel",
                on_click=toggle_delete_confirm,
                args=(False,),
                use_container_width=True,
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
    """로그인 후 챗봇 메인 화면 렌더링"""
    # CSS 로드
    load_css("components/chat_messages.css")
    load_css("components/chat_ui.css")

    # 헤더
    col_header_left, col_header_right = st.columns([8, 1])
    with col_header_left:
        render_template("components/chat_header.html")
    with col_header_right:
        if st.button("👤", key="btn_my_page", help="마이페이지"):
            st.session_state["show_profile"] = True
            st.rerun()

    # 메인 제목 및 설명
    render_template("components/chat_title.html")

    # 채팅 메시지 표시 (초기 메시지 포함)
    if st.session_state.get("messages"):
        for message in st.session_state.messages:
            if message["role"] == "user":
                render_template(
                    "components/chat_message_user.html", content=message["content"]
                )
            elif message["role"] == "assistant":
                render_template(
                    "components/chat_message_assistant.html", content=message["content"]
                )
                if "policies" in message:
                    for policy in message["policies"]:
                        render_policy_card(policy)

    # 추천 질문
    render_template("components/suggested_questions_header.html")

    cols = st.columns(2)
    for idx, question in enumerate(SUGGESTED_QUESTIONS):
        with cols[idx % 2]:
            if st.button(
                question,
                key=f"suggest_{idx}",
                use_container_width=True,
                type="secondary",
            ):
                handle_send_message(question)

    # 입력 필드
    st.markdown("<div style='margin-top: 40px;'></div>", unsafe_allow_html=True)
    col_input, col_send = st.columns([9, 1])
    with col_input:
        user_input = st.text_input(
            "정책에 대해 질문해주세요...",
            key="user_input",
            label_visibility="collapsed",
        )
    with col_send:
        if st.button("✈️", key="btn_send", use_container_width=True):
            if user_input.strip():
                handle_send_message(user_input)

    # 면책 조항
    render_template("components/disclaimer.html")


def handle_send_message(message: str):
    """메시지 전송 처리"""
    if not message.strip() or st.session_state.get("is_loading", False):
        return

    # 사용자 메시지 추가
    user_message = {
        "id": str(uuid.uuid4()),
        "role": "user",
        "content": message,
        "timestamp": time.time(),
    }
    if "messages" not in st.session_state:
        st.session_state.messages = []
    st.session_state.messages.append(user_message)

    # 로딩 상태 설정
    st.session_state["is_loading"] = True

    # 현재 활성 프로필 가져오기
    active_profile = next(
        (p for p in st.session_state.profiles if p.get("isActive", False)), None
    )

    # 챗봇 메시지 전송 (Mock)
    success, response = api_send_chat_message(message, active_profile)

    if success:
        # 챗봇 응답 추가
        assistant_message = {
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "content": response.get("content", "응답을 받았습니다."),
            "timestamp": time.time(),
        }

        # 정책 정보가 있으면 추가
        if "policies" in response:
            assistant_message["policies"] = response["policies"]

        st.session_state.messages.append(assistant_message)
    else:
        # 에러 메시지 추가
        error_message = {
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "content": f"죄송합니다. 오류가 발생했습니다: {response.get('error', '알 수 없는 오류')}",
            "timestamp": time.time(),
        }
        st.session_state.messages.append(error_message)

    st.session_state["is_loading"] = False
    st.session_state["user_input"] = ""
    st.rerun()


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
            age = calculate_age(active_profile.get("birthDate", date.today()))
            birth_display = (
                f"{age}세"
                if isinstance(active_profile.get("birthDate"), date)
                else "미입력"
            )
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
                value=(
                    ed.get("birthDate", date(1990, 1, 1))
                    if isinstance(ed.get("birthDate"), date)
                    else date(1990, 1, 1)
                ),
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
        clear_session()  # 세션 파일 삭제 부분 주석 처리
        # st.success("로그아웃 되었습니다.")
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
            render_settings_modal()
        elif st.session_state.get("show_profile", False):
            # 마이페이지가 열려있으면 설정 모달 닫기
            st.session_state["settings_modal_open"] = False
            render_my_page_modal()

        # 메인 챗봇 화면
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
