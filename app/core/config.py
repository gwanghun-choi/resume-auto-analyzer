from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

# Settings 는 .env 에서 DB 접속정보를 읽어옵니다. (Spring 의 application.yml + @ConfigurationProperties 와 비슷)
#
# - DATABASE_URL 이 있으면 그대로 사용합니다.
# - 없으면 DB_HOST/PORT/NAME/USER/PASSWORD 를 조합해 URL 을 만듭니다.
# - 비밀번호 등 실제 값은 코드에 두지 않고 .env 에서만 읽습니다.


class Settings(BaseSettings):
    # .env 를 읽되, 선언하지 않은 키(OPENAI_API_KEY 등)는 무시합니다.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "didim_api"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "change_me"
    DB_SCHEMA: str = "resume_ai"
    DATABASE_URL: Optional[str] = None
    DB_ECHO: bool = False  # SQL 로그 출력 여부 (기본 false)

    # 세션 미들웨어(SessionMiddleware) 서명 키. 운영에서는 반드시 .env 에 안전한 값을 설정하세요.
    # 기본값은 '개발용'임이 드러나는 값으로만 둡니다. (민감값 하드코딩 금지)
    SESSION_SECRET_KEY: str = "dev-session-secret-change-me"

    # 사람인 '디딤' 검색 결과에서 디딤(주) 신규 공고를 수집하는 배치 설정.
    # (수동 실행 API + 스케줄러가 사용. 실제 1시간 주기 스케줄 등록은 코드상 주석 처리 — 운영 반영 시 해제)
    SARAMIN_DIDIM_SEARCH_URL: str = (
        "https://www.saramin.co.kr/zf_user/search?searchword=%EB%94%94%EB%94%A4"
        "&go=&flag=n&searchMode=1&searchType=search&search_done=y&search_optional_item=n"
    )
    SARAMIN_DIDIM_KEYWORD: str = "디딤"
    SARAMIN_DIDIM_COMPANY_NAME: str = "디딤(주)"
    SARAMIN_DISCOVERY_ENABLED: bool = False   # 스케줄러 자동 실행 여부(현재 주석 처리 상태 — 참고용 플래그)

    # Celery / Redis (비동기 작업 큐). 실제 URL/비밀번호는 .env 에서만 읽습니다(하드코딩 금지).
    # Docker Compose 내부에서는 broker 를 redis 서비스명(redis://redis:6379/...)으로, 로컬 직접 실행은 localhost 로.
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    CELERY_TASK_DEFAULT_QUEUE: str = "job_discovery"
    CELERY_TIMEZONE: str = "Asia/Seoul"
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = 1
    CELERY_TASK_ACKS_LATE: bool = True

    @property
    def database_url(self) -> str:
        """SQLAlchemy 가 사용할 접속 URL. DATABASE_URL 우선, 없으면 DB_* 조합."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )


# 앱 전역에서 공유하는 설정 인스턴스
settings = Settings()
