from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# SQLAlchemy engine / Session 설정입니다. (Spring 의 DataSource + SessionFactory 와 비슷)
#
# - create_engine 은 '지연 연결' 입니다. import 시점에 DB 에 접속하지 않으므로,
#   DB 가 꺼져 있어도 앱은 정상적으로 뜨고, 실제 쿼리 시점에만 연결합니다.
# - pool_pre_ping=True: 풀에서 커넥션을 꺼낼 때 죽은 커넥션을 미리 걸러냅니다.

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=settings.DB_ECHO,
    future=True,
)


@event.listens_for(engine, "connect")
def _set_search_path(dbapi_connection, connection_record):
    """커넥션마다 search_path 를 resume_ai 로 설정합니다. (스키마가 없어도 에러 없음)"""
    with dbapi_connection.cursor() as cursor:
        cursor.execute(f'SET search_path TO "{settings.DB_SCHEMA}", public')


# autocommit/autoflush 는 끄고, 명시적으로 commit 하는 방식을 씁니다.
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


def get_db():
    """FastAPI 의존성 주입용 DB 세션 제공자. (Spring 의 @Transactional 범위와 비슷)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
