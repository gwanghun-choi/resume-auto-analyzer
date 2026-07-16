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
    DB_NAME: str = "resume_ai"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "change_me"
    DB_SCHEMA: str = "resume_ai"
    DATABASE_URL: Optional[str] = None
    DB_ECHO: bool = False  # SQL 로그 출력 여부 (기본 false)

    # 세션 미들웨어(SessionMiddleware) 서명 키. 운영에서는 반드시 .env 에 안전한 값을 설정하세요.
    # 기본값은 '개발용'임이 드러나는 값으로만 둡니다. (민감값 하드코딩 금지)
    SESSION_SECRET_KEY: str = "dev-session-secret-change-me"

    # ------------------------------------------------------------------
    # 수집 대상 회사(target company)
    # ------------------------------------------------------------------
    # 이 앱은 채용 플랫폼 검색 결과에서 '특정 회사'의 신규 공고만 골라 등록합니다.
    # 회사명은 배포 환경마다 다르므로 코드에 기본값을 두지 않고 .env 로만 주입합니다.
    # 미설정 시 수집/검증 기능만 명확한 에러로 실패하고, 나머지 기능은 정상 동작합니다.
    #
    # TARGET_COMPANY_NAME    : 대표 표기 1개 (로그/응답에 노출)
    # TARGET_COMPANY_NAMES   : 공백 제거 후 exact 매칭할 허용 표기 목록(쉼표 구분).
    #                          검색어가 같아도 다른 회사가 섞이므로 exact 매칭만 통과시킵니다.
    # TARGET_COMPANY_KEYWORDS: 공고 본문/제목에서 회사 결속을 확인할 부분일치 키워드(쉼표 구분).
    TARGET_COMPANY_NAME: Optional[str] = None
    TARGET_COMPANY_NAMES: Optional[str] = None
    TARGET_COMPANY_KEYWORDS: Optional[str] = None

    # 사람인 검색 결과에서 대상 회사 신규 공고를 수집하는 배치 설정.
    # (수동 실행 API + 스케줄러가 사용. 실제 1시간 주기 스케줄 등록은 코드상 주석 처리 — 운영 반영 시 해제)
    # 검색 URL 은 회사명이 쿼리스트링에 들어가므로 기본값 없이 .env 로만 주입합니다.
    SARAMIN_SEARCH_URL: Optional[str] = None
    SARAMIN_SEARCH_KEYWORD: Optional[str] = None
    SARAMIN_DISCOVERY_ENABLED: bool = False   # 스케줄러 자동 실행 여부(현재 주석 처리 상태 — 참고용 플래그)

    # 잡코리아 검색 결과에서 대상 회사 신규 공고를 수집하는 배치 설정(사람인과 동일 구조).
    # 검색 결과는 서버 렌더링(SSR)이라 정적 HTML 로 수집 가능. 실제 1시간 주기 등록은 코드상 주석 처리 — 운영 반영 시 해제.
    JOBKOREA_SEARCH_URL: Optional[str] = None
    JOBKOREA_SEARCH_KEYWORD: Optional[str] = None
    JOBKOREA_DISCOVERY_ENABLED: bool = False   # 스케줄러 자동 실행 여부(현재 주석 처리 상태 — 참고용 플래그)

    # 좌측 메뉴 'Drive 바로가기' 링크. 미설정 시 메뉴 항목을 숨깁니다.
    DRIVE_SHORTCUT_URL: Optional[str] = None

    # Celery / Redis (비동기 작업 큐). 실제 URL/비밀번호는 .env 에서만 읽습니다(하드코딩 금지).
    # Docker Compose 내부에서는 broker 를 redis 서비스명(redis://redis:6379/...)으로, 로컬 직접 실행은 localhost 로.
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    CELERY_TASK_DEFAULT_QUEUE: str = "job_discovery"
    CELERY_TIMEZONE: str = "Asia/Seoul"
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = 1
    CELERY_TASK_ACKS_LATE: bool = True

    @property
    def target_company_names(self) -> set[str]:
        """exact 매칭용 허용 회사명 집합(모든 공백 제거 후 비교). 미설정이면 빈 집합."""
        raw = self.TARGET_COMPANY_NAMES or self.TARGET_COMPANY_NAME or ""
        return {
            "".join(part.split())
            for part in raw.split(",")
            if part.strip()
        }

    @property
    def target_company_keywords(self) -> list[str]:
        """공고 본문에서 회사 결속 확인용 부분일치 키워드. 미설정이면 빈 목록."""
        raw = self.TARGET_COMPANY_KEYWORDS or self.TARGET_COMPANY_NAME or ""
        return [part.strip() for part in raw.split(",") if part.strip()]

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
