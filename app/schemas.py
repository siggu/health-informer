"""Pydantic 스키마 정의 파일입니다.
사용자, 인증, 프로필 등 다양한 데이터 구조를 정의합니다. 11.13 수정"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

# ==============================================================================
# 인증 및 토큰 관련 스키마
# ==============================================================================


class TokenData(BaseModel):
    """
    JWT 토큰 내부에 포함될 데이터의 스키마를 정의합니다.

    Attributes:
        email (Optional[str]): 사용자의 이메일 또는 고유 식별자.
                                인증 시 토큰을 디코딩하여 이 정보를 사용합니다.
    """

    # 토큰에 email을 담을지 여부는 선택사항(Optional)으로 처리합니다.
    # 토큰 검증 과정에서 None이 될 수도 있기 때문입니다.
    email: Optional[str] = None


class Token(BaseModel):
    """
    클라이언트에게 반환될 토큰 정보를 정의합니다.
    """

    access_token: str
    token_type: str = "bearer"


class SuccessResponse(BaseModel):
    """성공 메시지 반환"""

    message: str


# ==============================================================================
# 사용자 및 프로필 관련 스키마
# ==============================================================================


class UserBase(BaseModel):
    email: str
    username: Optional[str] = None


class UserCreate(UserBase):
    password: str


class UserLogin(BaseModel):
    email: str
    password: str


class UserProfile(BaseModel):
    """사용자 프로필 정보 구조"""

    name: Optional[str] = None
    gender: Optional[str] = None
    location: Optional[str] = None
    healthInsurance: Optional[str] = None
    incomeLevel: Optional[str] = None
    basicLivelihood: Optional[str] = None
    disabilityLevel: Optional[str] = None
    longTermCare: Optional[str] = None
    pregnancyStatus: Optional[str] = None
    isActive: Optional[bool] = None


class UserProfileWithId(UserProfile):
    """DB에서 조회 시 사용, 프로필 ID 포함"""

    id: int


class User(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime
    profile: Optional[UserProfile] = None

    class Config:
        from_attributes = (
            True  # orm_mode = True는 Pydantic v2에서 from_attributes로 변경됨
        )
