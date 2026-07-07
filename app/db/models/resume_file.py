from sqlalchemy import Column, String, Integer, BigInteger, Text, TIMESTAMP, Index

from app.db.base import Base, TimestampMixin

# resume_files: 실제 분석 대상 파일 1개. (현재 MVP: 파일 1개 = 지원자 1명)
# ZIP 내부에서 나온 파일도 각각 resume_files 1건입니다. (candidate_bundle 미사용)


class ResumeFile(Base, TimestampMixin):
    __tablename__ = "resume_files"
    __table_args__ = (
        Index("ix_resume_files_upload_id", "upload_id"),
        Index("ix_resume_files_dept_id", "dept_id"),
        Index("ix_resume_files_posting_id", "posting_id"),
        Index("ix_resume_files_jd_id", "jd_id"),
        Index("ix_resume_files_drive_file_id", "drive_file_id"),
        Index("ix_resume_files_file_status", "file_status"),
        Index("ix_resume_files_analysis_status", "analysis_status"),
        Index("ix_resume_files_move_status", "move_status"),
        Index("ix_resume_files_created_at", "created_at"),
        Index("ix_resume_files_analyzed_at", "analyzed_at"),
        Index("ix_resume_files_dept_id_analysis_status", "dept_id", "analysis_status"),
        Index("ix_resume_files_dept_id_created_at", "dept_id", "created_at"),
        {"comment": "이력서 파일 단위 정보를 저장하는 테이블입니다. 현재 MVP에서는 파일 1개를 지원자 1명으로 간주합니다."},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="이력서 파일 내부 식별자")
    upload_id = Column(String(100), nullable=False, comment="업로드 회차 ID")
    dept_id = Column(String(100), nullable=False, comment="파일이 업로드된 부서 ID (권한/호환용, 유지)")
    # 공고/JD 중심 전환: 업로드된 공고/JD. 기존 데이터는 NULL=미매핑.
    posting_id = Column(BigInteger, nullable=True, comment="업로드된 공고 id (job_postings.id)")
    jd_id = Column(BigInteger, nullable=True, comment="업로드 시점 공고 active JD id (job_posting_jds.id)")
    original_file_name = Column(String(500), nullable=True, comment="원본 파일명")
    stored_file_name = Column(String(500), nullable=True, comment="Google Drive에 저장된 파일명")
    drive_file_id = Column(String(255), nullable=True, comment="Google Drive 파일 ID")
    file_size = Column(BigInteger, nullable=True, comment="파일 크기 byte")
    content_type = Column(String(255), nullable=True, comment="업로드 시 확인된 MIME 타입")
    extension = Column(String(50), nullable=True, comment="파일 확장자")
    file_status = Column(String(50), nullable=True, comment="파일 업로드 상태")
    analysis_status = Column(String(50), nullable=True, comment="파일 분석 상태")
    move_status = Column(String(50), nullable=True,
                         comment="Google Drive completed/failed 이동 상태")
    moved_to = Column(String(50), nullable=True,
                      comment="분석 후 이동된 위치. completed 또는 failed")
    moved_drive_file_id = Column(String(255), nullable=True,
                                 comment="이동 후 Google Drive 파일 ID")
    error_code = Column(String(100), nullable=True, comment="파일 처리 또는 분석 실패 코드")
    error_message = Column(Text, nullable=True, comment="파일 처리 또는 분석 실패 메시지")
    score = Column(Integer, nullable=True, comment="AI 분석 점수 요약. 0~100")
    recommendation = Column(String(100), nullable=True, comment="AI 추천 문구 요약")
    analyzed_at = Column(TIMESTAMP, nullable=True, comment="분석 완료 또는 실패 시각")
