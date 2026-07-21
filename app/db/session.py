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


def resolve_session(session=None):
    """
    db_service 공용 세션 해석기.

    - session 이 주어지면(예: FastAPI get_db 로 주입된 '요청 세션') 그대로 재사용하고,
      (own=False) 호출부가 close 하지 않습니다. 세션 생명주기는 주입한 쪽(get_db)이 소유합니다.
      → 한 요청 안에서 라우터의 주입 세션과 db_service 가 여는 세션이 분리되어
        읽기/트랜잭션이 비일관해지던 문제를 없앱니다.
    - session 이 없으면(Celery task/서비스 클래스 등 '요청 밖') 새 세션을 열고(own=True),
      호출부가 finally 에서 close 합니다. (기존 동작과 동일 — 하위 호환)

    반환: (session, own)  — own 이 True 인 경우에만 호출부가 session.close() 해야 합니다.
    """
    if session is not None:
        return session, False
    return SessionLocal(), True
