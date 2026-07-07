from sqlalchemy import Column, String, Integer, TIMESTAMP, Index

from app.db.base import Base, TimestampMixin

# departments: Drive config/dept_config.json 에서 동기화된 부서 정보를 저장합니다.
# id 는 dept_id(=Drive config JSON 의 id) 를 그대로 사용합니다.


class Department(Base, TimestampMixin):
    __tablename__ = "departments"
    __table_args__ = (
        Index("ix_departments_parent_id", "parent_id"),
        Index("ix_departments_status", "status"),
        Index("ix_departments_name", "name"),
        {"comment": "부서 정보를 저장하는 테이블. Google Drive config/dept_config.json에서 동기화된 부서 트리 데이터입니다."},
    )

    id = Column(String(100), primary_key=True,
                comment="부서 ID. Drive config JSON의 id 값을 그대로 사용합니다.")
    name = Column(String(255), nullable=False, comment="부서명")
    parent_id = Column(String(100), nullable=True,
                       comment="상위 부서 ID. 부서 트리 구성에 사용합니다.")
    manager_id = Column(String(100), nullable=True, comment="부서 관리자 ID")
    email = Column(String(255), nullable=True, comment="부서 또는 담당자 이메일")
    sort = Column(Integer, nullable=True, comment="부서 정렬 순서")
    status = Column(Integer, nullable=True,
                    comment="부서 상태값. 원본 부서 JSON의 status 값을 저장합니다.")
    register_date = Column(TIMESTAMP, nullable=True, comment="원본 시스템의 부서 등록일")
    update_date = Column(TIMESTAMP, nullable=True, comment="원본 시스템의 부서 수정일")
    synced_at = Column(TIMESTAMP, nullable=True,
                       comment="Drive config 기준으로 DB에 마지막 동기화된 시각")
