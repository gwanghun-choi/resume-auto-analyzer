from sqlalchemy import Column, MetaData, TIMESTAMP, func
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# 모든 ORM 모델의 공통 Base 입니다.
# metadata 에 schema 를 지정해, 테이블이 resume_ai 스키마에 생성되도록 합니다.
# (Alembic 의 target_metadata 로도 이 Base.metadata 를 사용합니다.)


class Base(DeclarativeBase):
    metadata = MetaData(schema=settings.DB_SCHEMA)


class TimestampMixin:
    """created_at / updated_at 공통 컬럼. (모든 테이블에 반복 추가하지 않도록 mixin 으로 분리)"""
    created_at = Column(
        TIMESTAMP, nullable=False, server_default=func.now(),
        comment="DB 레코드 생성 시각",
    )
    updated_at = Column(
        TIMESTAMP, nullable=True, onupdate=func.now(),
        comment="DB 레코드 수정 시각",
    )


# Alembic 이 모든 모델의 metadata 를 인식하도록, Base 정의 후 모델들을 import 합니다.
# (모델들은 위에서 정의한 Base/TimestampMixin 을 사용하므로 정의 이후에 import)
from app.db import models  # noqa: E402,F401
