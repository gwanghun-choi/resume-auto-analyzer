from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text
from alembic import context

# 앱 설정/메타데이터를 재사용합니다.
#  - DATABASE_URL 은 app/core/config.py(.env) 에서 읽습니다. (alembic.ini 에 비밀번호를 두지 않음)
#  - target_metadata 는 app/db/base.py 의 Base.metadata 를 사용합니다.
from app.core.config import settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# .env 의 접속 URL 을 alembic 에 주입합니다.
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """offline 모드: 실제 연결 없이 SQL 스크립트를 생성합니다."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=settings.DB_SCHEMA,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """online 모드: 실제 DB 에 연결해 마이그레이션을 적용합니다."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # alembic_version 등 마이그레이션이 들어갈 schema 를 먼저 보장합니다.
        # (commit 으로 이 트랜잭션을 끝내야 이후 alembic 트랜잭션의 commit 이 정상 동작합니다.
        #  SQLAlchemy 2.0 에서는 commit 없이 connect 블록을 나가면 rollback 되기 때문)
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{settings.DB_SCHEMA}"'))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=settings.DB_SCHEMA,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
