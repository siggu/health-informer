import uuid
import time
from datetime import date
import streamlit as st


def _parse_birthdate(value):
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except Exception:
            return None
    return None


def calculate_age(birth_date):
    bd = _parse_birthdate(birth_date)
    if not bd:
        return None
    today = date.today()
    years = today.year - bd.year
    if (today.month, today.day) < (bd.month, bd.day):
        years -= 1
    return years


def is_profile_incomplete(profile):
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
    if is_deleted_active and new_profiles:
        new_profiles[0]["isActive"] = True
    st.session_state.profiles = new_profiles
    st.rerun()


def handle_add_profile(new_profile_data):
    if not new_profile_data.get("name") or not new_profile_data.get("location"):
        st.error("프로필 이름과 거주지는 필수 입력 항목입니다.")
        return
    for p in st.session_state.profiles:
        p["isActive"] = False
    new_profile = {"id": str(uuid.uuid4()), **new_profile_data, "isActive": True}
    st.session_state.profiles.append(new_profile)
    st.session_state.isAddingProfile = False
    # st.session_state.newProfile = {}
    st.rerun()


def handle_start_edit(profile):
    st.session_state.editingProfileId = profile["id"]
    st.session_state.editingData = profile.copy()
    st.rerun()


def handle_save_edit(edited_data):
    pid = st.session_state.editingProfileId
    if not edited_data.get("name") or not edited_data.get("location"):
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

    col_title, col_close = st.columns([9, 1])
    with col_title:
        st.markdown("### 마이페이지")
        st.caption("프로필 정보와 설정을 관리하세요")
    with col_close:
        if st.button("✕", key="btn_close_my_page"):
            st.session_state["show_profile"] = False
            st.rerun()

    st.markdown("---")

    st.markdown("#### 프로필 관리")
    if not st.session_state.get("isAddingProfile", False):
        if st.button("➕ 프로필 추가", key="btn_add_profile", use_container_width=True):
            st.session_state["isAddingProfile"] = True
            st.session_state["newProfile"] = {}
            st.rerun()

    st.markdown("")

    active_profile = next(
        (p for p in st.session_state.profiles if p.get("isActive", False)), None
    )
    if active_profile and is_profile_incomplete(active_profile):
        st.warning("정확한 추천을 위해 프로필 정보를 완성해주세요.")

    st.markdown("---")

    if st.session_state.get("isAddingProfile", False):
        st.markdown("##### 새 프로필 추가")
        np = st.session_state.get("newProfile", {})
        with st.form("add_profile_form"):
            name = st.text_input(
                "프로필 이름 *", value=np.get("name", ""), key="add_name"
            )
            birth = st.date_input(
                "생년월일",
                value=_parse_birthdate(np.get("birthDate")) or date(2000, 1, 1),
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
                    st.session_state["newProfile"] = {}
                    st.rerun()

        st.markdown("---")

    st.markdown("#### 기본 프로필")
    if active_profile:
        col_active, col_edit = st.columns([8, 1])
        with col_active:
            st.markdown("**활성** ✓")
            age = calculate_age(active_profile.get("birthDate"))
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
        st.info("등록된 프로필이 없습니다. 새 프로필이 필요합니다.")

    st.markdown("---")

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

    # 계정 관련 액션 (비밀번호 변경/회원 탈퇴/로그아웃)
    st.markdown("#### 계정")
    col_pw, col_delete, col_logout = st.columns(3)
    with col_pw:
        if st.button(
            "🔒 비밀번호 재설정", key="btn_reset_pw", use_container_width=True
        ):
            # 설정 모달을 열고 비밀번호 폼 표시
            st.session_state["show_profile"] = False
            st.session_state["settings_modal_open"] = True
            st.session_state["show_password_reset"] = True
            st.rerun()
    with col_delete:
        if st.button("🗑️ 회원 탈퇴", key="btn_delete_account", use_container_width=True):
            # 설정 모달에서 탈퇴 확인을 처리
            st.session_state["show_profile"] = False
            st.session_state["settings_modal_open"] = True
            st.session_state["show_delete_confirm"] = True
            st.rerun()
    with col_logout:
        if st.button("→ 로그아웃", key="btn_logout", use_container_width=True):
            from src.utils.session_manager import update_login_status as _uls

            _uls(is_logged_in=False)
            st.session_state["is_logged_in"] = False
            st.session_state["show_profile"] = False
            st.session_state["messages"] = [
                {
                    "id": str(uuid.uuid4()),
                    "role": "assistant",
                    "content": "안녕하세요! 정책 추천 챗봇입니다. 나이, 거주지, 관심 분야를 알려주시면 맞춤형 정책을 추천해드립니다.",
                    "timestamp": time.time(),
                }
            ]
            st.success("로그아웃 되었습니다.")
            st.rerun()
