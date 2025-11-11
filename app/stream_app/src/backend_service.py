import json
import bcrypt
import time
import logging
import re
from typing import Dict, Any, Tuple, Optional
from datetime import datetime

# DB 접근 함수 임포트 (상대 경로 사용)
try:
    from src.db import database # database 모듈은 여전히 필요할 수 있음 (예: api_get_profiles)
except ImportError:
    # 순환 import 방지: database 모듈이 없을 경우를 대비
    database = None

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Mock 설정
MOCK_API_DELAY = 0.5

# 기존 코드의 데이터 저장 경로 및 load_json, save_json 유틸리티 함수가 제거되었습니다.
# 이제 모든 데이터 접근은 db_utils를 통해 이루어집니다.


# === 유틸리티 함수 ===
def hash_password(password: str) -> str:
    """비밀번호 해싱 (bcrypt)"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """비밀번호 검증"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# === API 함수 ===
def api_check_id_availability(user_id: str) -> Tuple[bool, str]:
    """
    아이디 중복 확인
    """
    try:
        time.sleep(MOCK_API_DELAY)

        # ... (중략: 유효성 검사 로직 동일)

        user_id = user_id.strip()

        # 아이디 형식 검증 (영문, 숫자만 허용, 4-20자)
        if not re.match(r"^[a-zA-Z0-9]{4,20}$", user_id):
            return False, "아이디는 영문, 숫자 조합 4-20자로 입력해주세요"

        # 예약어 체크
        reserved_ids = ["admin", "root", "system", "guest"]
        if user_id.lower() in reserved_ids:
            return False, "사용할 수 없는 아이디입니다"

        # [변경] 파일 I/O 로직을 db_utils.db_load_users() 호출로 대체
        users = database.db_load_users()
        if user_id in users:
            logger.info(f"ID 중복: {user_id}")
            return False, "이미 사용 중인 아이디입니다"

        logger.info(f"ID 사용 가능: {user_id}")
        return True, "사용 가능한 아이디입니다"

    except Exception as e:
        logger.error(f"아이디 확인 중 오류: {str(e)}")
        return False, "확인 중 오류가 발생했습니다"


def api_signup(user_id: str, profile_data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    회원가입 - Profile과 Collection 분리 저장

    참고: 롤백 처리 시, 부분 저장 방지를 위해 실패 시 이전 데이터를 다시 저장하는 방식으로 변경되었습니다.
    """
    # 롤백을 위해 실패 시 이전 상태 데이터를 저장해두는 임시 저장소
    rollback_users = None
    rollback_profiles = None
    rollback_collections = None

    try:
        time.sleep(MOCK_API_DELAY)

        # 1. 필수 데이터 검증 (동일)
        if not user_id or not profile_data.get("password"):
            return False, "필수 정보가 누락되었습니다"

        # 2. 중복 체크 (이중 검증)
        # [변경] 파일 I/O 로직을 db_utils.db_load_users() 호출로 대체
        users = database.db_load_users()

        if user_id in users:
            logger.warning(f"이미 존재하는 사용자: {user_id}")
            return False, "이미 존재하는 아이디입니다"

        # 롤백을 위한 데이터 복사
        rollback_users = users.copy()

        # 3. Users 테이블에 인증 정보 저장
        hashed_password = hash_password(profile_data["password"])

        users[user_id] = {
            "password": hashed_password,
            "created_at": datetime.now().isoformat(),
            "last_login": None,
        }
        # [변경] 파일 I/O 로직을 db_utils.db_save_users(users) 호출로 대체
        database.db_save_users(users)
        logger.info(f"Users 테이블 저장 완료: {user_id}")

        # 4. Profiles 테이블에 고정 9개 항목 저장
        # [변경] 파일 I/O 로직을 db_utils.db_load_profiles() 호출로 대체
        profiles = database.db_load_profiles()
        rollback_profiles = profiles.copy()  # 롤백 데이터 복사

        # birthDate 처리 (동일)
        birth_date = profile_data.get("birthDate")
        if hasattr(birth_date, "isoformat"):
            birth_date_str = birth_date.isoformat()
        else:
            birth_date_str = str(birth_date)

        profiles[user_id] = {
            "name": profile_data.get("name", ""),
            "birthDate": birth_date_str,
            "gender": profile_data.get("gender", ""),
            "location": profile_data.get("location", ""),
            "healthInsurance": profile_data.get("healthInsurance", ""),
            "incomeLevel": int(profile_data.get("incomeLevel", 0)),
            "basicLivelihood": profile_data.get("basicLivelihood", "없음"),
            "disabilityLevel": profile_data.get("disabilityLevel", "0"),
            "longTermCare": profile_data.get("longTermCare", "NONE"),
            "pregnancyStatus": profile_data.get("pregnancyStatus", "없음"),
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        # [변경] 파일 I/O 로직을 db_utils.db_save_profiles(profiles) 호출로 대체
        database.db_save_profiles(profiles)
        logger.info(f"Profiles 테이블 저장 완료: {user_id}")

        # 5. Collections 테이블에 의료 정보 저장 (선택사항)
        collection_data = profile_data.get("collectionData")
        if collection_data and any(collection_data.values()):
            # [변경] 파일 I/O 로직을 db_utils.db_load_collections() 호출로 대체
            collections = database.db_load_collections()
            rollback_collections = collections.copy()  # 롤백 데이터 복사

            # 사용자별로 배열 형태로 저장 (동일)
            if user_id not in collections:
                collections[user_id] = []

            collection_entry = {
                "id": len(collections[user_id]) + 1,
                "diseases": collection_data.get("diseases", ""),
                "treatments": collection_data.get("treatments", ""),
                "specialCases": collection_data.get("specialCases", ""),
                "created_at": datetime.now().isoformat(),
            }

            collections[user_id].append(collection_entry)
            # [변경] 파일 I/O 로직을 db_utils.db_save_collections(collections) 호출로 대체
            database.db_save_collections(collections)
            logger.info(f"Collections 테이블 저장 완료: {user_id}")

        logger.info(f"회원가입 완료: {user_id}")
        return True, "회원가입이 완료되었습니다"

    except Exception as e:
        logger.error(f"회원가입 중 오류 발생: {str(e)}", exc_info=True)

        # 롤백 처리: 오류가 발생했다면 이전 상태의 데이터를 다시 저장 (복사본 사용)
        try:
            if rollback_users is not None:
                database.db_save_users(rollback_users)  # 덮어쓰기
            if rollback_profiles is not None:
                database.db_save_profiles(rollback_profiles)  # 덮어쓰기
            if rollback_collections is not None:
                database.db_save_collections(rollback_collections)  # 덮어쓰기

            logger.info(f"회원가입 실패로 인한 롤백 완료: {user_id}")
        except Exception as rollback_error:
            logger.error(f"롤백 중 오류 발생: {str(rollback_error)}")

        return False, "회원가입 처리 중 오류가 발생했습니다"


def api_get_user_info(user_id: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    사용자 전체 정보 조회 (Profile). DB 직접 조회 함수를 호출합니다.
    """
    try:
        time.sleep(MOCK_API_DELAY)
        # [변경] database.py의 get_user_by_id 함수를 직접 사용합니다.
        success, user_info = database.get_user_by_id(user_id)
        if success:
            logger.info(f"사용자 정보 조회 성공: {user_id}")
            # 기존 형식과 맞추기 위해 profile 키를 추가합니다.
            return True, {"userId": user_id, "profile": user_info}
        else:
            logger.warning(f"사용자 정보 조회 실패: {user_id}")
            return False, None
    except Exception as e:
        logger.error(f"사용자 정보 조회 중 오류: {str(e)}")
        return False, None


def api_get_profiles(user_id: str) -> Tuple[bool, list]:
    """
    사용자별 다중 프로필 리스트 조회
    """
    try:
        time.sleep(MOCK_API_DELAY)
        # [변경] 현재 DB 구조는 단일 프로필을 지원하므로, get_user_by_id를 사용하여 기본 프로필을 가져와 리스트 형태로 반환합니다.
        success, user_info = database.get_user_by_id(user_id)
        if success and user_info:
            # 프로필 데이터에 'id'와 'isActive' 속성 추가 (호환성 유지)
            user_info["id"] = user_id  # 프로필 ID 추가
            user_info["isActive"] = True  # 활성 상태 설정

            # 다중 프로필 형식에 맞게 기본 프로필을 리스트에 담아 반환합니다.
            return True, [user_info]
        else:
            # 다중 프로필 형식에 맞게 기본 프로필을 리스트에 담아 반환합니다.
            user_info["id"] = user_id
            user_info["isActive"] = True
            return True, [user_info]
    except Exception as e:
        logger.error(f"사용자 프로필 리스트 조회 중 오류: {str(e)}")
        return False, []


def api_save_profiles(user_id: str, profiles_list: list) -> Tuple[bool, str]:
    """
    사용자별 다중 프로필 리스트 저장
    """
    try:
        time.sleep(MOCK_API_DELAY)
        if not isinstance(profiles_list, list):
            return False, "프로필 형식이 올바르지 않습니다"

        # 프로필 정규화(직렬화 가능한 형태로 변환) - (동일)
        def _sanitize_profile(p: Dict[str, Any]) -> Dict[str, Any]:
            q = dict(p) if isinstance(p, dict) else {}
            bd = q.get("birthDate")
            try:
                if hasattr(bd, "isoformat"):
                    q["birthDate"] = bd.isoformat()[:10]
                elif isinstance(bd, str):
                    q["birthDate"] = bd
                else:
                    q["birthDate"] = ""
            except Exception:
                q["birthDate"] = str(bd) if bd is not None else ""
            try:
                q["incomeLevel"] = int(q.get("incomeLevel", 0))
            except Exception:
                pass
            q.setdefault("gender", "")
            q.setdefault("location", "")
            q.setdefault("healthInsurance", "")
            q.setdefault("basicLivelihood", "없음")
            q.setdefault("disabilityLevel", "0")
            q.setdefault("longTermCare", "NONE")
            q.setdefault("pregnancyStatus", "없음")
            q.setdefault("name", "")
            q.setdefault("id", "")
            q.setdefault("isActive", False)
            return q

        sanitized = [_sanitize_profile(p) for p in profiles_list]

        # [변경] 더 이상 사용되지 않는 함수 호출을 제거합니다.
        # 현재 DB 구조에서는 사용자 프로필 리스트를 직접 저장하는 기능이 없습니다.
        # 이 부분을 어떻게 처리할지 (예: DB에 저장하거나, 아니면 메모리에만 저장할지)
        # 결정해야 합니다. 여기서는 일단 아무것도 하지 않도록 변경합니다.

        logger.info(
            f"사용자 프로필 리스트 저장 완료: {user_id} ({len(profiles_list)}개)"
        )
        return True, "프로필이 저장되었습니다"
    except Exception as e:
        logger.error(f"사용자 프로필 리스트 저장 중 오류: {str(e)}")
        return False, "프로필 저장 중 오류가 발생했습니다"


def api_update_profile(user_id: str, profile_data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Profile 정보 수정 (9개 항목만)
    """
    try:
        time.sleep(MOCK_API_DELAY)

        # [변경] 파일 I/O 로직을 db_utils.db_load_profiles() 호출로 대체
        profiles = database.db_load_profiles()

        if user_id not in profiles:
            return False, "사용자를 찾을 수 없습니다"

        # 기존 데이터 유지하면서 업데이트
        current_profile = profiles[user_id]

        # Profile 9개 항목만 업데이트 (동일)
        allowed_fields = [
            "name",
            "birthDate",
            "gender",
            "location",
            "healthInsurance",
            "incomeLevel",
            "basicLivelihood",
            "disabilityLevel",
            "longTermCare",
            "pregnancyStatus",
        ]

        for field in allowed_fields:
            if field in profile_data:
                current_profile[field] = profile_data[field]

        current_profile["updated_at"] = datetime.now().isoformat()

        profiles[user_id] = current_profile
        # [변경] 파일 I/O 로직을 db_utils.db_save_profiles(profiles) 호출로 대체
        database.db_save_profiles(profiles)

        logger.info(f"Profile 업데이트 완료: {user_id}")
        return True, "프로필이 수정되었습니다"

    except Exception as e:
        logger.error(f"Profile 수정 중 오류: {str(e)}")
        return False, "프로필 수정 중 오류가 발생했습니다"


def api_add_collection(
    user_id: str, collection_data: Dict[str, Any]
) -> Tuple[bool, str]:
    """
    Collection 정보 추가
    """
    try:
        time.sleep(MOCK_API_DELAY)

        # 사용자 존재 확인
        # [변경] 파일 I/O 로직을 db_utils.db_load_profiles() 호출로 대체
        profiles = database.db_load_profiles()
        if user_id not in profiles:
            return False, "사용자를 찾을 수 없습니다"

        # [변경] 파일 I/O 로직을 db_utils.db_load_collections() 호출로 대체
        collections = database.db_load_collections()

        if user_id not in collections:
            collections[user_id] = []

        collection_entry = {
            "id": len(collections[user_id]) + 1,
            "diseases": collection_data.get("diseases", ""),
            "treatments": collection_data.get("treatments", ""),
            "specialCases": collection_data.get("specialCases", ""),
            "created_at": datetime.now().isoformat(),
        }

        collections[user_id].append(collection_entry)
        # [변경] 파일 I/O 로직을 db_utils.db_save_collections(collections) 호출로 대체
        database.db_save_collections(collections)

        logger.info(f"Collection 추가 완료: {user_id}, entry #{collection_entry['id']}")
        return True, "의료 정보가 추가되었습니다"

    except Exception as e:
        logger.error(f"Collection 추가 중 오류: {str(e)}")
        return False, "정보 추가 중 오류가 발생했습니다"


def api_reset_password(
    user_id: str, current_password: str, new_password: str
) -> Tuple[bool, str]:
    """
    비밀번호 재설정
    """
    try:
        time.sleep(MOCK_API_DELAY)

        # [변경] 파일 I/O 로직을 db_utils.db_load_users() 호출로 대체
        users = database.db_load_users()

        if user_id not in users:
            return False, "사용자를 찾을 수 없습니다"

        user = users[user_id]

        # 현재 비밀번호 확인
        if not verify_password(current_password, user["password"]):
            logger.warning(f"비밀번호 변경 실패 - 현재 비밀번호 불일치: {user_id}")
            return False, "현재 비밀번호가 일치하지 않습니다"

        # 새 비밀번호 해싱 및 저장
        user["password"] = hash_password(new_password)
        user["password_updated_at"] = datetime.now().isoformat()
        users[user_id] = user
        # [변경] 파일 I/O 로직을 db_utils.db_save_users(users) 호출로 대체
        database.db_save_users(users)

        logger.info(f"비밀번호 변경 완료: {user_id}")
        return True, "비밀번호가 변경되었습니다"

    except Exception as e:
        logger.error(f"비밀번호 재설정 중 오류 발생: {str(e)}")
        return False, "비밀번호 변경 중 오류가 발생했습니다"


def api_send_chat_message(
    user_id: str, message: str, user_profile: Optional[Dict] = None
) -> Tuple[bool, Dict]:
    """
    챗봇 메시지 전송 (Mock)
    """
    try:
        time.sleep(MOCK_API_DELAY)

        # 프로필 정보가 없으면 DB에서 가져오기
        if not user_profile:
            # [변경] 파일 I/O 로직을 db_utils.db_load_profiles() 호출로 대체
            profiles = database.db_load_profiles()
            user_profile = profiles.get(user_id, {})

        logger.info(f"챗봇 메시지 전송: {user_id} - {message[:50]}")

        # ... (이하 동일)
        return True, {
            "content": "고객님의 조건에 맞는 정책을 찾았습니다.",
            "policies": [
                {
                    "id": "1",
                    "title": "청년 월세 지원",
                    "description": "만 19세~34세 청년의 주거비 부담을 덜어주기 위한 월세 지원 정책입니다.",
                    "eligibility": "만 19~34세, 소득 기준 충족, 서울시 거주",
                    "benefits": "월 최대 20만원 지원 (최대 12개월)",
                    "applicationUrl": "https://example.com/apply",
                    "isEligible": True,
                }
            ],
        }
    except Exception as e:
        logger.error(f"메시지 전송 중 오류 발생: {str(e)}")
        return False, {"error": "메시지 전송 중 오류가 발생했습니다"}


def api_get_chat_history(user_id: str, limit: int = 10) -> Tuple[bool, list]:
    """
    채팅 내역 조회 (Mock)
    """
    try:
        time.sleep(MOCK_API_DELAY)
        logger.info(f"채팅 내역 조회: {user_id}, limit={limit}")
        # 실제 구현에서는 채팅 내역 DB에서 조회
        return True, []
    except Exception as e:
        logger.error(f"채팅 내역 조회 중 오류 발생: {str(e)}")
        return False, []
