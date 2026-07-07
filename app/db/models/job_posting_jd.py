from sqlalchemy import Column, String, Text, Boolean, BigInteger, TIMESTAMP, Index, func
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base

# job_posting_jds: 공고에 연결된 JD 상세.
# 현재 정책: 공고당 1개 active JD 만 허용 (DB unique 제약 없이 service 에서 강제 — 향후 1공고 N JD 확장 대비).
# required_skills/preferred_skills 는 MatchingService 호환을 위해 '문자열 리스트'(JSONB)로 저장합니다.


class JobPostingJD(Base):
    __tablename__ = "job_posting_jds"
    __table_args__ = (
        Index("ix_job_posting_jds_posting_id", "posting_id"),
        Index("ix_job_posting_jds_is_active", "is_active"),
        {"comment": "공고에 연결된 JD 상세. 현재 공고당 1 active JD(서비스 강제)."},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="JD PK")
    posting_id = Column(BigInteger, nullable=False, comment="job_postings.id")
    title = Column(String(255), nullable=True, comment="JD 제목(기본값=공고명)")
    required_skills = Column(JSONB, nullable=True, comment="필수 기술 리스트")
    preferred_skills = Column(JSONB, nullable=True, comment="우대 기술 리스트")
    jd_content = Column(Text, nullable=True, comment="JD 상세 내용")
    is_active = Column(Boolean, nullable=False, server_default="true", comment="현재 사용 중인 JD 여부")
    created_by = Column(BigInteger, nullable=True, comment="생성자 users.id")
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now(), comment="생성 시각")
    updated_at = Column(TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now(),
                        comment="수정 시각")
