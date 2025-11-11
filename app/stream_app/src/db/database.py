"""PostgreSQL 데이터베이스 연결 및 CRUD 함수"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, Any, Tuple, Optional, List
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)

# DB 연결 정보 (환경변수 또는 하드코딩)
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "140.238.10.51"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "team02"),
    "user": os.getenv("DB_USER", "test01"),
    "password": os.getenv("DB_PASSWORD", "test1234"),  # 환경변수에서 가져오거나 secrets에서
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


def _normalize_insurance_type(insurance_str: str) -> Optional[str]:
    """건강보험 종류를 DB 형식으로 변환"""
    if not insurance_str:
        return None
    # DB enum에 한글 값이 직접 저장되어 있으므로 변환 없이 그대로 반환
    return insurance_str


def _normalize_benefit_type(benefit_str: str) -> str:
    """기초생활보장 급여 종류를 DB 형식으로 변환"""
    if not benefit_str or benefit_str == "없음":
        return "NONE"
    mapping = {"생계": "LIVELIHOOD", "의료": "MEDICAL", "주거": "HOUSING", "교육": "EDUCATION"}
    return mapping.get(benefit_str)


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
    if not disability_level or disability_level == "0" or disability_level == "미등록":
        return None
    try:
        return int(disability_level)
    except (ValueError, TypeError):
        return None


def _normalize_ltci_grade(long_term_care: str) -> str:
    """장기요양 등급 정규화"""
    if not long_term_care or long_term_care == "없음" or long_term_care == "해당없음":
        return "NONE"
    return long_term_care.upper()


def _normalize_pregnant_status(pregnancy_status: str) -> Optional[bool]:
    """임신/출산 여부를 Boolean으로 변환"""
    if not pregnancy_status:
        return None
    status_lower = pregnancy_status.lower()
    if "임신" in status_lower or "출산" in status_lower:
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
    새로운 사용자의 프로필 정보를 core_profile 테이블에 삽입합니다.
    
    Args:
        user_data: 회원가입 폼 데이터
        
    Returns:
        (성공 여부, 메시지)
    """
    conn = get_db_connection()
    if not conn:
        return False, "데이터베이스 연결 실패"

    try:
        # 프로필 데이터 정규화
        user_id = user_data.get("userId", "").strip()
        if not user_id:
            return False, "사용자 ID가 필요합니다"

        birth_date_str = _normalize_birth_date(user_data.get("birthDate"))
        sex = _normalize_sex(user_data.get("gender", ""))
        residency_sgg_code = user_data.get("location", "").strip() or None # 거주지
        insurance_type = _normalize_insurance_type(user_data.get("healthInsurance", ""))
        median_income_ratio = _normalize_income_ratio(user_data.get("incomeLevel"))
        basic_benefit_type = _normalize_benefit_type(user_data.get("basicLivelihood", "없음"))
        disability_grade = _normalize_disability_grade(user_data.get("disabilityLevel", "0"))
        ltci_grade = _normalize_ltci_grade(user_data.get("longTermCare", "NONE"))
        pregnant_or_postpartum12m = _normalize_pregnant_status(user_data.get("pregnancyStatus", "없음"))

        insert_query = """
        INSERT INTO core_profile (
            user_id, birth_date, sex, residency_sgg_code, insurance_type,
            median_income_ratio, basic_benefit_type, disability_grade,
            ltci_grade, pregnant_or_postpartum12m, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (user_id) DO UPDATE SET
            birth_date = EXCLUDED.birth_date,
            sex = EXCLUDED.sex,
            residency_sgg_code = EXCLUDED.residency_sgg_code,
            insurance_type = EXCLUDED.insurance_type,
            median_income_ratio = EXCLUDED.median_income_ratio,
            basic_benefit_type = EXCLUDED.basic_benefit_type,
            disability_grade = EXCLUDED.disability_grade,
            ltci_grade = EXCLUDED.ltci_grade,
            pregnant_or_postpartum12m = EXCLUDED.pregnant_or_postpartum12m,
            updated_at = NOW()
        """

        data = (
            user_id,
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

        with conn.cursor() as cursor:
            cursor.execute(insert_query, data)
            conn.commit()
            logger.info(f"프로필 저장 완료: {user_id}")
            return True, "회원가입이 완료되었습니다"

    except psycopg2.IntegrityError as e:
        conn.rollback()
        logger.warning(f"프로필 저장 실패 (무결성 오류): {user_id} - {e}")
        return False, "이미 사용 중인 아이디입니다."
    except psycopg2.Error as e:
        conn.rollback()
        logger.error(f"프로필 저장 중 DB 오류: {user_id} - {e}")
        return False, f"DB 저장 중 오류 발생: {str(e)}"
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"프로필 저장 중 예상치 못한 오류: {user_id} - {e}")
        return False, f"예상치 못한 오류 발생: {str(e)}"
    finally:
        if conn:
            conn.close()


def get_user_by_id(user_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    user_id로 core_profile에서 사용자 정보를 조회합니다.
    
    Args:
        user_id: 사용자 ID
        
    Returns:
        (성공 여부, 사용자 정보 딕셔너리)
    """
    conn = get_db_connection()
    if not conn:
        return False, {"error": "DB 연결 실패"}

    try:
        query = """
        SELECT 
            user_id AS "userId",
            birth_date AS "birthDate",
            sex AS "gender",
            residency_sgg_code AS "location",
            insurance_type AS "healthInsurance",
            median_income_ratio AS "incomeLevel",
            basic_benefit_type AS "basicLivelihood",
            disability_grade AS "disabilityLevel",
            ltci_grade AS "longTermCare",
            pregnant_or_postpartum12m AS "pregnancyStatus",
            updated_at
        FROM core_profile 
        WHERE user_id = %s
        """

        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, (user_id,))
            row = cursor.fetchone()
            
            if row:
                # RealDictCursor는 dict를 반환하지만, 키를 소문자로 변환
                user_dict = dict(row)
                # 키를 camelCase로 변환 (기존 코드와 호환)
                result = {
                    "userId": user_dict.get("userId") or user_id,
                    "name": "",  # core_profile에는 name이 없으므로 빈 문자열
                    "birthDate": str(user_dict.get("birthDate", "")) if user_dict.get("birthDate") else "",
                    "gender": "남성" if user_dict.get("gender") == "M" else ("여성" if user_dict.get("gender") == "F" else user_dict.get("gender", "")),
                    "location": user_dict.get("location", ""),
                    "healthInsurance": user_dict.get("healthInsurance", ""),
                    "incomeLevel": int(user_dict.get("incomeLevel", 0)) if user_dict.get("incomeLevel") else 0,
                    "basicLivelihood": user_dict.get("basicLivelihood", "없음"),
                    "disabilityLevel": str(user_dict.get("disabilityLevel", "0")) if user_dict.get("disabilityLevel") else "0",
                    "longTermCare": user_dict.get("longTermCare", "NONE"),
                    "pregnancyStatus": "임신중" if user_dict.get("pregnancyStatus") else "없음",
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


def check_user_exists(user_id: str) -> bool:
    """user_id가 이미 존재하는지 확인"""
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        query = "SELECT 1 FROM core_profile WHERE user_id = %s LIMIT 1"
        with conn.cursor() as cursor:
            cursor.execute(query, (user_id,))
            return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"사용자 존재 확인 중 오류: {user_id} - {e}")
        return False
    finally:
        if conn:
            conn.close()
