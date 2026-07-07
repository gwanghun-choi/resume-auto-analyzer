from sqlalchemy import Column, String, Text, BigInteger, TIMESTAMP, Index, func

from app.db.base import Base

# job_postings: 채용 공고. 외부 플랫폼 공고와 대응(현재 1공고=1 active JD).
# 부서/팀은 권한·조직 기준으로 유지하므로 department_id 를 보유합니다. (users 와 동일하게 하드 FK 없이 문자열 참조)
# created_by → users.id 의 DB FK 는 SQL(docs/sql/2026-06-12-posting-jd.sql)에서 ON DELETE SET NULL 로 둡니다.


class JobPosting(Base):
    __tablename__ = "job_postings"
    __table_args__ = (
        Index("ix_job_postings_department_id", "department_id"),
        Index("ix_job_postings_status", "status"),
        Index("ix_job_postings_platform_code", "platform_code"),
        {"comment": "채용 공고. 부서는 권한 기준으로 유지, 실제 채용 단위는 공고."},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="공고 PK")
    title = Column(String(255), nullable=False, comment="공고명/JD명")
    department_id = Column(String(50), nullable=True, comment="공고 소속 부서 id (departments.id, 권한 필터 기준). 선택사항(미지정 가능)")
    platform_code = Column(String(50), nullable=True, comment="외부 플랫폼: SARAMIN/JOBKOREA/WANTED/ETC")
    platform_posting_url = Column(Text, nullable=True, comment="외부 플랫폼 공고 URL")
    status = Column(String(30), nullable=False, server_default="OPEN",
                    comment="공고 상태: DRAFT/OPEN/CLOSED/INACTIVE")
    drive_folder_id = Column(String(255), nullable=True, comment="공고 Drive 폴더 id")
    drive_inbox_folder_id = Column(String(255), nullable=True)
    drive_completed_folder_id = Column(String(255), nullable=True)
    drive_failed_folder_id = Column(String(255), nullable=True)
    created_by = Column(BigInteger, nullable=True, comment="생성자 users.id")
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now(), comment="생성 시각")
    updated_at = Column(TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now(),
                        comment="수정 시각")
