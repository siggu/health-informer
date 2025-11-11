"""PostgreSQL 데이터베이스 연결 및 CRUD 함수"""

import os
from passlib.hash import bcrypt  # 비밀번호 해시 검증을 위해 추가
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, Any, Tuple, Optional, List
from datetime import datetime, date
import logging
import uuid  # users.id에 사용할 고유 ID 생성을 위해 추가

logger = logging.getLogger(__name__)

# DB 연결 정보 (환경변수 또는 하드코딩)
# 🚨 주의: 비밀번호 'test1234'는 실제 배포 시 반드시 환경 변수로 변경해야 합니다.
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "140.238.10.51"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "team02"),
    "user": os.getenv("DB_USER", "test01"),
    "password": os.getenv("DB_PASSWORD", "test1234"),
}


def get_db_connection():
    """PostgreSQL DB 연결 객체를 반환합니다."""
    try:
        conn = psycopg2.connect(
            host=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            database=DB_CONFIG["database"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            client_encoding="UTF8",  # 한글 처리를 위한 인코딩 설정
        )
        return conn
    except Exception as e:
        logger.error(f"데이터베이스 연결 오류: {e}")
        return None


def _normalize_birth_date(birth_date: Any) -> Optional[str]:
    """birthDate를 YYYY-MM-DD 문자열로 변환"""
    if birth_date is None:
        return None
    if isinstance(birth_date, date):
        return birth_date.isoformat()
    if isinstance(birth_date, str):
        # 이미 YYYY-MM-DD 형식인지 확인
        if len(birth_date) >= 10:
            return birth_date[:10]
        return birth_date
    return str(birth_date)


def _normalize_insurance_type(
    insurance_str: str,
) -> Optional[str]:  # auth.py에서 이미 매핑된 값 기대
    """건강보험 종류를 DB 형식으로 변환 (auth.py에서 이미 매핑된 값 기대)"""
    if not insurance_str:
        return None
    # auth.py에서 이미 영문 ENUM 값으로 매핑되어 넘어온다고 가정
    return insurance_str


def _normalize_benefit_type(benefit_str: str) -> str:  # auth.py에서 이미 매핑된 값 기대
    """기초생활보장 급여 종류를 DB 형식으로 변환 (auth.py에서 이미 매핑된 값 기대)"""
    if not benefit_str:
        return "NONE"
    # auth.py에서 이미 영문 ENUM 값으로 매핑되어 넘어온다고 가정
    return benefit_str


def _normalize_sex(gender: str) -> Optional[str]:
    """성별을 DB 형식으로 변환 (남성->M, 여성->F 등)"""
    if not gender:
        return None
    gender_lower = gender.lower()
    if "남" in gender_lower or "male" in gender_lower or "m" == gender_lower:
        return "M"
    if "여" in gender_lower or "female" in gender_lower or "f" == gender_lower:
        return "F"
    return gender[:1].upper() if gender else None


def _normalize_disability_grade(disability_level: Any) -> Optional[int]:
    """장애 등급을 정수로 변환"""
    if not disability_level or str(disability_level) in ("0", "미등록"):
        return None
    try:
        return int(disability_level)
    except (ValueError, TypeError):
        return None


def _normalize_ltci_grade(long_term_care: str) -> str:
    """장기요양 등급 정규화"""
    if not long_term_care or long_term_care in ("없음", "해당없음", "NONE"):
        return "NONE"
    return long_term_care.upper()


def _normalize_pregnant_status(pregnancy_status: str) -> Optional[bool]:
    """임신/출산 여부를 Boolean으로 변환"""
    if not pregnancy_status:
        return None
    status_lower = pregnancy_status.lower()
    if (
        "임신" in status_lower
        or "출산" in status_lower
        or status_lower in ("true", "t")
    ):
        return True
    return False


def _normalize_income_ratio(income_level: Any) -> Optional[float]:
    """소득 수준을 NUMERIC(5,2)로 변환"""
    if income_level is None:
        return None
    try:
        val = float(income_level)
        return round(val, 2)
    except (ValueError, TypeError):
        return None


def create_user_and_profile(user_data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    새로운 사용자의 인증 정보 (users), 기본 프로필 (profiles),
    및 초기 컬렉션 (collections) 정보를 트랜잭션으로 삽입합니다.

    Args:
        user_data: 회원가입 폼 데이터 (username, password, profile, collection 포함)

    Returns:
        (성공 여부, 메시지)
    """
    conn = get_db_connection()
    if not conn:
        return False, "데이터베이스 연결 실패"

    # auth.py에서 이미 해싱된 비밀번호와 매핑된 필드명을 기대합니다.
    username = user_data.get(
        "username", ""
    ).strip()  # auth.py에서 userId -> username으로 변경됨
    password_hash = user_data.get(
        "password", ""
    ).strip()  # auth.py에서 이미 해싱된 비밀번호

    if not username or not password_hash:
        return False, "아이디와 비밀번호는 필수 입력 항목입니다."

    # users.id는 TEXT 타입이므로 UUID를 사용
    new_user_id = str(uuid.uuid4())

    try:
        with conn.cursor() as cursor:
            # 1. users 테이블 INSERT (인증 정보)
            # users 테이블의 ID는 TEXT(UUID)입니다.
            # main_profile_id는 profiles 테이블이 생성된 후 업데이트할 예정이므로 NULL로 둡니다.
            user_insert_query = """
            INSERT INTO users (id, username, password_hash, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW());
            """
            # 아이디 중복 확인은 이 쿼리의 무결성 제약 조건(UNIQUE INDEX on username)에 의해 처리됩니다.
            cursor.execute(user_insert_query, (new_user_id, username, password_hash))
            logger.info(f"1. users 테이블에 삽입 완료. user_id: {new_user_id}")

            # 2. profiles 테이블 INSERT (기본 프로필)
            # users.id를 profiles.user_id로 사용하고, profiles.id(BIGINT)를 RETURNING으로 받습니다.

            # --- 프로필 데이터 정규화 (auth.py에서 이미 매핑된 필드명 사용) ---
            birth_date_str = _normalize_birth_date(user_data.get("birthDate"))
            sex = _normalize_sex(user_data.get("gender", ""))
            residency_sgg_code = (
                user_data.get("residency_sgg_code", "").strip() or None
            )  # auth.py에서 location -> residency_sgg로 변경됨
            insurance_type = _normalize_insurance_type(
                user_data.get(
                    "insurance_type", ""
                )  # auth.py에서 healthInsurance -> insurance_type으로 변경됨
            )
            median_income_ratio = _normalize_income_ratio(
                user_data.get("incomeLevel")
            )  # auth.py에서 incomeLevel -> median_income으로 변경됨
            basic_benefit_type = _normalize_benefit_type(
                user_data.get(
                    "basicLivelihood", "NONE"
                )  # auth.py에서 basicLivelihood -> basic_benefit_type으로 변경됨
            )
            disability_grade = _normalize_disability_grade(
                user_data.get(
                    "disabilityLevel", "0"
                )  # auth.py에서 disabilityLevel -> disability_grade로 변경됨
            )
            ltci_grade = _normalize_ltci_grade(
                user_data.get("longTermCare", "NONE")
            )  # auth.py에서 longTermCare -> ltci_grade로 변경됨
            pregnant_or_postpartum12m = _normalize_pregnant_status(
                user_data.get(
                    "pregnancyStatus", "없음"
                )  # auth.py에서 pregnancyStatus -> pregnant_or_postpartum으로 변경됨
            )

            profile_insert_query = """
            INSERT INTO profiles (
                user_id, birth_date, sex, residency_sgg_code, insurance_type,
                median_income_ratio, basic_benefit_type, disability_grade,
                ltci_grade, pregnant_or_postpartum12m, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            RETURNING id; 
            """

            profile_data_tuple = (
                new_user_id,
                birth_date_str,
                sex,
                residency_sgg_code,
                insurance_type,
                median_income_ratio,
                basic_benefit_type,
                disability_grade,
                ltci_grade,
                pregnant_or_postpartum12m,
            )

            cursor.execute(profile_insert_query, profile_data_tuple)
            new_profile_id = cursor.fetchone()[0]  # profiles.id 획득 (BIGINT)
            logger.info(f"2. profiles 테이블에 삽입 완료. profile_id: {new_profile_id}")

            # 3. collections 테이블 INSERT (초기 멀티 프로필 데이터)
            # profiles.id를 collections.profile_id로 사용합니다.

            # 컬렉션 데이터 (예시로 기본값 또는 폼에서 받은 초기 값 사용)
            collection_data = user_data.get(
                "initial_collection",
                {"subject": "기본", "predicate": "상태", "object": "정상"},
            )

            collection_insert_query = """
            INSERT INTO collections (
                profile_id, subject, predicate, object,
                code_system, code, onset_date, end_date,
                negation, confidence, source_id, created_at
            )
            VALUES (%s, %s, %s, %s, NULL, NULL, NULL, NULL, FALSE, 1.0, NULL, NOW());
            """

            # subject, predicate, object 만 사용하고 나머지는 NULL 또는 기본값 사용
            collection_data_tuple = (
                new_profile_id,
                collection_data.get("subject"),
                collection_data.get("predicate"),
                collection_data.get("object"),
            )

            cursor.execute(collection_insert_query, collection_data_tuple)
            logger.info("3. collections 테이블에 삽입 완료.")

            # 4. users 테이블의 main_profile_id 업데이트 (옵션)
            # 기본 프로필이 생성되었으므로, users 테이블에 main_profile_id를 연결
            update_user_query = """
            UPDATE users SET main_profile_id = %s, updated_at = NOW()
            WHERE id = %s;
            """
            cursor.execute(update_user_query, (new_profile_id, new_user_id))
            logger.info("4. users 테이블 main_profile_id 업데이트 완료.")

            # ✅ 최종 성공: 모든 쿼리가 성공했으므로 커밋
            conn.commit()
            return True, "회원가입 및 전체 프로필 설정이 성공적으로 완료되었습니다."

    except psycopg2.IntegrityError as e:
        conn.rollback()
        # username unique constraint 위반 시
        if "users_username_key" in str(e):
            return False, "이미 사용 중인 아이디입니다."
        logger.warning(f"프로필 저장 실패 (무결성 오류): {username} - {e}")
        return False, "데이터 무결성 오류로 저장에 실패했습니다."
    except psycopg2.Error as e:
        conn.rollback()
        logger.error(f"프로필 저장 중 DB 오류: {username} - {e}")
        return False, f"DB 저장 중 오류 발생: {str(e)}"
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"프로필 저장 중 예상치 못한 오류: {username} - {e}")
        return False, f"예상치 못한 오류 발생: {str(e)}"
    finally:
        if conn:
            conn.close()


# --- 기존 함수는 테이블 변경에 따라 수정이 필요합니다. ---


def get_user_by_id(user_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    user_id로 users와 profiles 테이블을 조인하여 사용자 정보를 조회합니다.
    """
    conn = get_db_connection()
    if not conn:
        return False, {"error": "DB 연결 실패"}

    try:
        # profiles 테이블만 조회하는 대신, users 테이블과 JOIN
        query = """
        SELECT 
                u.username AS "userId", -- username을 userId로 반환
            p.birth_date AS "birthDate",
            p.sex AS "gender",
            p.residency_sgg_code AS "location", 
            p.insurance_type AS "healthInsurance",
            p.median_income_ratio AS "incomeLevel",
            p.basic_benefit_type AS "basicLivelihood",
            p.disability_grade AS "disabilityLevel",
            p.ltci_grade AS "longTermCare",
            p.pregnant_or_postpartum12m AS "pregnancyStatus",
            u.username
            FROM users u
            LEFT JOIN profiles p ON u.id = p.user_id
            WHERE u.username = %s -- username으로 조회
            """

        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, (user_id,))
            row = cursor.fetchone()

            if row:
                user_dict = dict(row)
                # 기존 함수 출력 형식과 맞추기 위해 데이터 변환
                result = {
                    "userId": user_dict.get("userId"),
                    "username": user_dict.get("username"),
                    "birthDate": (
                        str(user_dict.get("birthDate", ""))
                        if user_dict.get("birthDate")
                        else ""
                    ),
                    "gender": (
                        "남성"
                        if user_dict.get("gender") == "M"
                        else (
                            "여성"
                            if user_dict.get("gender") == "F"
                            else user_dict.get("gender", "")
                        )
                    ),
                    "location": user_dict.get("location", ""),
                    "healthInsurance": user_dict.get("healthInsurance", ""),
                    "incomeLevel": (
                        float(user_dict.get("incomeLevel", 0.0))
                        if user_dict.get("incomeLevel")
                        else 0.0
                    ),
                    "basicLivelihood": user_dict.get("basicLivelihood", "NONE"),
                    "disabilityLevel": (
                        str(user_dict.get("disabilityLevel", "0"))
                        if user_dict.get("disabilityLevel") is not None
                        else "0"
                    ),
                    "longTermCare": user_dict.get("longTermCare", "NONE"),
                    "pregnancyStatus": (
                        "임신중" if user_dict.get("pregnancyStatus") else "없음"
                    ),
                }
                return True, result
            return False, {"error": "사용자를 찾을 수 없습니다."}

    except psycopg2.Error as e:
        logger.error(f"사용자 조회 중 DB 오류: {user_id} - {e}")
        return False, {"error": f"DB 조회 오류: {str(e)}"}
    except Exception as e:
        logger.error(f"사용자 조회 중 예상치 못한 오류: {user_id} - {e}")
        return False, {"error": f"예상치 못한 오류: {str(e)}"}
    finally:
        if conn:
            conn.close()


# ✅ [추가] 비밀번호 해시 조회 함수
def get_user_password_hash(username: str) -> Optional[str]:
    """DB에서 사용자의 비밀번호 해시를 조회합니다."""
    conn = get_db_connection()
    if not conn:
        return None
    try:
        # 'users' 테이블과 'password_hash' 컬럼이 있다고 가정합니다.
        query = "SELECT password_hash FROM users WHERE username = %s"
        with conn.cursor() as cursor:
            cursor.execute(query, (username,))
            result = cursor.fetchone()
            return result[0] if result else None
    except Exception as e:
        logger.error(f"비밀번호 해시 조회 중 오류: {username} - {e}")
        return None
    finally:
        if conn:
            conn.close()


def check_user_exists(username: str) -> bool:
    """username이 이미 존재하는지 확인 (users 테이블 기준)"""
    conn = get_db_connection()
    if not conn:
        return False

    try:
        # 조회 테이블을 core_profile에서 users로 변경
        query = "SELECT 1 FROM users WHERE username = %s LIMIT 1"
        with conn.cursor() as cursor:
            cursor.execute(query, (username,))
            return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"사용자 존재 확인 중 오류: {username} - {e}")
        return False
    finally:
        if conn:
            conn.close()


def delete_user_account(username: str) -> Tuple[bool, str]:
    """사용자 계정과 관련된 모든 데이터를 삭제합니다 (users, profiles, collections)."""
    conn = get_db_connection()
    if not conn:
        return False, "데이터베이스 연결 실패"

    try:
        with conn.cursor() as cursor:
            # users 테이블에서 username으로 id를 찾습니다.
            cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
            user_record = cursor.fetchone()
            if not user_record:
                return False, "사용자를 찾을 수 없습니다."

            user_id_to_delete = user_record[0]

            # CASCADE 제약조건이 있다면 users 레코드만 삭제해도 관련 데이터가 삭제됩니다.
            # 제약조건이 없다면 profiles, collections 등을 수동으로 삭제해야 합니다.
            # 여기서는 users 테이블의 id를 사용하여 직접 삭제하는 방식을 가정합니다.

            # users 테이블에서 삭제
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id_to_delete,))

            conn.commit()
            logger.info(f"회원 탈퇴 완료: {username} (user_id: {user_id_to_delete})")
            return True, "회원 탈퇴가 완료되었습니다."

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"회원 탈퇴 중 오류 발생: {username} - {e}")
        return False, "회원 탈퇴 처리 중 오류가 발생했습니다."
    finally:
        if conn:
            conn.close()


# 나머지 함수들은 그대로 유지합니다.
