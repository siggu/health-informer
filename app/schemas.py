"""Pydantic 스키마 정의 파일입니다.
사용자, 인증, 프로필 등 다양한 데이터 구조를 정의합니다. 11.18 수정"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

# ==============================================================================
# 인증 및 토큰 관련 스키마
# ==============================================================================


class TokenData(BaseModel):
    """
    JWT 토큰 내부에 포함될 데이터의 스키마를 정의합니다.

    Attributes:
        email (Optional[str]): 사용자의 username (아이디).
                                인증 시 토큰을 디코딩하여 이 정보를 사용합니다.
    """

    # 토큰에 username을 담을지 여부는 선택사항(Optional)으로 처리.
    # 토큰 검증 과정에서 None이 될 수도 있기 때문.
    username: Optional[str] = None  # DB의 username을 저장


class Token(BaseModel):
    """
    클라이언트에게 반환될 토큰 정보를 정의합니다.
    """

    access_token: str
    token_type: str = "bearer"
    refresh_token: Optional[str] = None


class SuccessResponse(BaseModel):
    """성공 메시지 반환"""

    message: str


class RefreshTokenRequest(BaseModel):
    """토큰 재발급 요청 시 사용"""

    refresh_token: str


# 11.18 추가: 비밀번호 변경 요청 스키마(리프레시 토큰 무효화를 위한)
class PasswordChangeRequest(BaseModel):
    """비밀번호 변경 요청 시 사용"""

    current_password: str
    new_password: str


# ==============================================================================
# 사용자 및 프로필 관련 스키마
# ==============================================================================


class UserBase(BaseModel):
    """사용자 기본 정보 구조"""

    username: Optional[str] = None


class UserCreate(UserBase):
    """회원가입 시 필요한 사용자 정보 구조"""

    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=8, max_length=72)
    name: str = Field(..., min_length=2, max_length=50)
    birth_date: Optional[str] = None
    sex: Optional[str] = None
    residency_sgg_code: Optional[str] = None
    insurance_type: Optional[str] = None
    median_income_ratio: Optional[float] = None
    basic_benefit_type: Optional[str] = None
    disability_grade: Optional[str] = None
    ltci_grade: Optional[str] = None
    pregnant_or_postpartum12m: Optional[str] = None


class UserLogin(BaseModel):
    """사용자 로그인 정보 구조"""

    username: str
    password: str


# 11.18 수정: 프론트엔드 필드명과 일치하도록 UserProfile 스키마 수정
class UserProfile(BaseModel):
    """사용자 프로필 정보 구조"""

    name: Optional[str] = None
    gender: Optional[str] = None
    birthDate: Optional[str] = None
    location: Optional[str] = None
    healthInsurance: Optional[str] = None
    incomeLevel: Optional[float] = None
    basicLivelihood: Optional[str] = None
    disabilityLevel: Optional[str] = None
    longTermCare: Optional[str] = None
    pregnancyStatus: Optional[str] = None
    isActive: Optional[bool] = None

    def to_db_dict(self) -> dict:
        """프론트엔드 필드명을 DB 필드명으로 변환"""

        # ✅ 프론트엔드 → DB 매핑 (한글/영문 → DB enum)
        gender_map = {"남성": "M", "여성": "F"}

        insurance_map = {
            "직장": "EMPLOYED",
            "지역": "REGIONAL",
            "피부양": "DEPENDENT",
            "의료급여": "MEDICAL",
        }

        livelihood_map = {
            "없음": "NONE",
            "생계": "LIVELIHOOD",
            "의료": "MEDICAL",
            "주거": "HOUSING",
            "교육": "EDUCATION",
        }

        # 장애 등급: "0", "1", "2" → None, 1, 2
        disability_map = {"0": None, "1": 1, "2": 2}

        # 장기요양: "NONE", "G1", ... → 그대로
        # (프론트엔드에서 이미 LONGTERM_CARE_MAP으로 변환됨)

        # 임신 상태: 한글 → bool
        pregnancy_map = {"없음": False, "임신중": True, "출산후12개월이내": True}

        return {
            "name": self.name,
            "sex": gender_map.get(self.gender, self.gender),
            "birth_date": self.birthDate,
            "residency_sgg_code": self.location,
            "insurance_type": insurance_map.get(
                self.healthInsurance, self.healthInsurance
            ),
            "median_income_ratio": self.incomeLevel,
            "basic_benefit_type": livelihood_map.get(
                self.basicLivelihood, self.basicLivelihood
            ),
            "disability_grade": (
                disability_map.get(self.disabilityLevel)
                if self.disabilityLevel
                else None
            ),
            "ltci_grade": self.longTermCare,  # 이미 "NONE", "G1" 등으로 변환됨
            "pregnant_or_postpartum12m": pregnancy_map.get(self.pregnancyStatus, False),
        }

    @classmethod
    def from_db_dict(cls, db_data: dict):
        """DB 필드명을 프론트엔드 필드명으로 변환"""

        # ✅ DB → 프론트엔드 역매핑
        gender_reverse = {"M": "남성", "F": "여성"}

        insurance_reverse = {
            "EMPLOYED": "직장",
            "REGIONAL": "지역",
            "DEPENDENT": "피부양",
            "MEDICAL": "의료급여",
        }

        livelihood_reverse = {
            "NONE": "없음",
            "LIVELIHOOD": "생계",
            "MEDICAL": "의료",
            "HOUSING": "주거",
            "EDUCATION": "교육",
        }

        # 장애 등급: None, 1, 2 → "0", "1", "2"
        disability_grade = db_data.get("disability_grade")
        if disability_grade is None:
            disability_str = "0"
        else:
            disability_str = str(disability_grade)

        # 장기요양: "NONE", "G1", ... → 그대로 (프론트엔드가 처리)

        # 임신 상태: bool → 한글
        pregnancy_reverse = {False: "없음", True: "임신중"}

        return cls(
            name=db_data.get("name"),
            gender=gender_reverse.get(db_data.get("sex"), db_data.get("sex")),
            birthDate=(
                str(db_data.get("birth_date")) if db_data.get("birth_date") else None
            ),
            location=db_data.get("residency_sgg_code"),
            healthInsurance=insurance_reverse.get(
                db_data.get("insurance_type"), db_data.get("insurance_type")
            ),
            incomeLevel=db_data.get("median_income_ratio"),
            basicLivelihood=livelihood_reverse.get(
                db_data.get("basic_benefit_type"), db_data.get("basic_benefit_type")
            ),
            disabilityLevel=disability_str,
            longTermCare=db_data.get("ltci_grade"),
            pregnancyStatus=pregnancy_reverse.get(
                db_data.get("pregnant_or_postpartum12m"), "없음"
            ),
            isActive=db_data.get("is_active"),
        )


class UserProfileWithId(UserProfile):
    """DB에서 조회 시 사용, 프로필 ID 포함"""

    id: int


class User(UserBase):
    """사용자 정보 구조, 프로필 포함"""

    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    profile: Optional[UserProfile] = None

    class Config:
        from_attributes = True


# --------------------------------------------------
# End of Pydantic 스키마 정의 파일
# --------------------------------------------------
