from pydantic import BaseModel, Field
from typing import List, Optional

# JD(Job Description, 채용 직무기술서) 관련 Schema(DTO) 입니다.
#
# 정책: "팀별로 JD 를 하나씩 관리한다."
#  - 한 팀(dept_id) 당 JD 파일 1개. (data/config/jd/{dept_id}.json)
#  - 그래서 JD 안에 dept_id 가 들어있습니다.
#
# 화면에서는 required_skills / preferred_skills 를 textarea(여러 줄 텍스트)로 입력받습니다.
# 그래서 "저장 요청용 Schema(JDSaveRequest)" 와 "저장/조회용 Schema(JD)" 를 나눴습니다.
#  - JDSaveRequest: 기술 스택을 '문자열' 그대로 받음 (textarea 원본)
#  - JD: 기술 스택을 '리스트' 로 보관 (서버에서 콤마/줄바꿈 기준으로 잘라서 변환)
#
# Java 비유:
#  - JDSaveRequest = 화면에서 넘어오는 RequestDTO
#  - JD            = 저장/응답에 쓰는 도메인 DTO


class JD(BaseModel):
    """팀별 JD 1건. (조회/저장/응답에 공통으로 사용하는 도메인 DTO)"""
    dept_id: str = Field(..., description="부서(팀) ID")
    dept_name: str = Field("", description="부서(팀) 이름")
    position_title: str = Field("", description="포지션명 (예: Backend Engineer)")
    job_description: str = Field("", description="JD 본문 설명")
    required_skills: List[str] = Field(default_factory=list, description="필수 기술 리스트")
    preferred_skills: List[str] = Field(default_factory=list, description="우대 기술 리스트")
    min_years: int = Field(0, description="최소 경력(년)")
    manager_email: str = Field("", description="담당자 이메일")
    version: int = Field(0, description="JD 버전 (저장할 때마다 1씩 증가)")
    update_date: Optional[str] = Field(None, description="마지막 수정 시각(ISO 문자열)")


class JDSaveRequest(BaseModel):
    """화면(JD 저장 폼)에서 넘어오는 요청 DTO. 기술 스택은 textarea 원본 문자열입니다."""
    position_title: str = Field("", description="포지션명")
    job_description: str = Field("", description="JD 본문 설명")
    required_skills: str = Field("", description="필수 기술 (콤마 또는 줄바꿈 구분)")
    preferred_skills: str = Field("", description="우대 기술 (콤마 또는 줄바꿈 구분)")
    min_years: int = Field(0, description="최소 경력(년)")
    manager_email: str = Field("", description="담당자 이메일")


class JDRecommendRequest(BaseModel):
    """추천JD 요청 DTO. 선택 부서/포지션명과 (있으면) 현재 입력값을 함께 받습니다. DB 저장 안 함."""
    dept_id: str = Field("", description="선택 부서(팀) ID")
    dept_name: str = Field("", description="선택 부서(팀) 이름")
    position_title: str = Field("", description="포지션명 (비어 있으면 '{부서명} 채용 포지션'으로 구성)")
    current_description: str = Field("", description="현재 입력된 JD 설명 (참고용)")
    current_required_skills: str = Field("", description="현재 입력된 필수 기술 (참고용)")
    current_preferred_skills: str = Field("", description="현재 입력된 우대 기술 (참고용)")
