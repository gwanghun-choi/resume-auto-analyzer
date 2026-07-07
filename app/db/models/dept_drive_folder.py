from sqlalchemy import Column, String, BigInteger, TIMESTAMP, Index, UniqueConstraint

from app.db.base import Base, TimestampMixin

# dept_drive_folders: 부서별 Google Drive 폴더 ID 매핑. (기존 dept_folder_map.json 을 대체 예정)


class DeptDriveFolder(Base, TimestampMixin):
    __tablename__ = "dept_drive_folders"
    __table_args__ = (
        UniqueConstraint("dept_id", name="uq_dept_drive_folders_dept_id"),
        Index("ix_dept_drive_folders_inbox_folder_id", "inbox_folder_id"),
        Index("ix_dept_drive_folders_completed_folder_id", "completed_folder_id"),
        Index("ix_dept_drive_folders_failed_folder_id", "failed_folder_id"),
        {"comment": "부서별 Google Drive 폴더 ID 매핑 정보를 저장하는 테이블입니다. inbox, completed, failed 폴더 ID를 관리합니다."},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True,
                comment="Drive 폴더 매핑 내부 식별자")
    dept_id = Column(String(100), nullable=False, comment="부서 ID")
    dept_name = Column(String(255), nullable=True, comment="동기화 시점의 부서명")
    folder_name = Column(String(500), nullable=True, comment="Google Drive에 생성된 부서 폴더명")
    inbox_folder_id = Column(String(255), nullable=True,
                             comment="Google Drive inbox 하위 부서 폴더 ID")
    completed_folder_id = Column(String(255), nullable=True,
                                 comment="Google Drive completed 하위 부서 폴더 ID")
    failed_folder_id = Column(String(255), nullable=True,
                              comment="Google Drive failed 하위 부서 폴더 ID")
    synced_at = Column(TIMESTAMP, nullable=True,
                       comment="Drive 폴더 매핑이 마지막으로 동기화된 시각")
