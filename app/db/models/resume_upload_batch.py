from sqlalchemy import Column, String, Integer, Text, TIMESTAMP, Index
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base, TimestampMixin

# resume_upload_batches: 업로드 버튼을 한 번 누른 '업로드 회차' 단위.
# source_label 은 후보자명이 아니라 원본 파일명 기반 표시용 라벨입니다.


class ResumeUploadBatch(Base, TimestampMixin):
    __tablename__ = "resume_upload_batches"
    __table_args__ = (
        Index("ix_resume_upload_batches_dept_id", "dept_id"),
        Index("ix_resume_upload_batches_status", "status"),
        Index("ix_resume_upload_batches_created_at", "created_at"),
        Index("ix_resume_upload_batches_dept_id_status", "dept_id", "status"),
        Index("ix_resume_upload_batches_dept_id_created_at", "dept_id", "created_at"),
        {"comment": "이력서 업로드 회차 정보를 저장하는 테이블입니다. 사용자가 업로드 버튼을 한 번 누른 단위를 의미합니다."},
    )

    upload_id = Column(String(100), primary_key=True,
                       comment="업로드 회차 ID. 예: UPL20260609_111954")
    dept_id = Column(String(100), nullable=False, comment="업로드 대상 부서 ID")
    dept_name = Column(String(255), nullable=True, comment="업로드 시점의 부서명")
    upload_folder_name = Column(String(500), nullable=False,
                                comment="Google Drive inbox 하위에 생성된 업로드 회차 폴더명")
    source_upload_file_name = Column(String(500), nullable=True,
                                     comment="사용자가 업로드한 원본 파일명. 여러 파일이면 multiple_files")
    source_label = Column(String(255), nullable=True,
                          comment="원본 업로드 파일명 기반 표시용 라벨. 후보자명이 아닙니다.")
    upload_type = Column(String(50), nullable=True,
                         comment="업로드 유형. SINGLE_FILE, MULTIPLE_FILES, ZIP, MIXED_FILES 등")
    drive_upload_folder_id = Column(String(255), nullable=True,
                                    comment="Google Drive에 생성된 업로드 회차 폴더 ID")
    drive_path_display = Column(Text, nullable=True, comment="화면 표시용 Google Drive 경로")
    status = Column(String(50), nullable=True, comment="업로드 회차 상태")
    uploaded_count = Column(Integer, server_default="0", comment="업로드 성공 파일 수")
    skipped_count = Column(Integer, server_default="0", comment="제외 또는 스킵된 파일 수")
    completed_count = Column(Integer, server_default="0", comment="분석 완료 파일 수")
    failed_count = Column(Integer, server_default="0", comment="분석 실패 파일 수")
    pending_count = Column(Integer, server_default="0", comment="분석 대기 파일 수")
    inbox_upload_folder_cleanup = Column(JSONB, nullable=True,
                                         comment="분석 후 빈 inbox 업로드 폴더 정리 결과")
