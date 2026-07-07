from sqlalchemy import Column, String, Integer, BigInteger, Boolean, Text, Index
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base, TimestampMixin

# LEGACY: 부서별 JD 테이블(job_descriptions). 공고 중심 전환으로 신규 개발 대상이 아닙니다.
#         신규 JD 는 공고별 job_posting_jds(JobPostingJD) 를 사용하세요. 테이블/데이터는 삭제하지 않고 유지합니다.
#         (jd_db_service/jd_service/jds_router/analyze_pending(legacy) 에서만 사용 — 후속 제거 검토 docs/TODO.)
#
# job_descriptions: 부서별 JD. 이력서 분석 시 부서별 평가 기준으로 사용됩니다.
# (FK 는 향후 JSON→DB 이관 시 정합성 문제를 피하려고 두지 않고 인덱스만 둡니다.)


class JobDescription(Base, TimestampMixin):
    __tablename__ = "job_descriptions"
    __table_args__ = (
        Index("ix_job_descriptions_dept_id", "dept_id"),
        Index("ix_job_descriptions_is_active", "is_active"),
        Index("ix_job_descriptions_dept_id_is_active", "dept_id", "is_active"),
        {"comment": "부서별 채용 JD 정보를 저장하는 테이블입니다. 이력서 분석 시 부서별 평가 기준으로 사용됩니다."},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="JD 내부 식별자")
    dept_id = Column(String(100), nullable=False, comment="JD가 연결된 부서 ID")
    title = Column(String(255), nullable=True, comment="JD 제목 또는 포지션명")
    description = Column(Text, nullable=True, comment="JD 본문 또는 업무 설명")
    required_skills = Column(JSONB, nullable=True, comment="필수 기술/요건 목록")
    preferred_skills = Column(JSONB, nullable=True, comment="우대 기술/요건 목록")
    min_years = Column(Integer, nullable=True, comment="최소 요구 경력 연수")
    version = Column(Integer, nullable=False, server_default="1", comment="JD 버전")
    is_active = Column(Boolean, nullable=False, server_default="true",
                       comment="현재 사용 중인 JD 여부")
