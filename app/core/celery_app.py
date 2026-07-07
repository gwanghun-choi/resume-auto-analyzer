from celery import Celery

from app.core.config import settings

# Celery 앱(비동기 작업 큐). broker/backend 는 .env(Redis) 에서 읽습니다(하드코딩 금지).
# - import 시 DB/FastAPI 앱을 강제로 기동하지 않습니다(task 모듈만 include).
# - task 는 app/tasks 아래에 두고, 각 task 는 재사용하는 service 가 내부에서 SessionLocal 로
#   DB 세션을 새로 열고 닫습니다(요청 세션/ORM 객체를 task payload 로 넘기지 않음, primitive 만).
# - 큐 분리: job_discovery(사람인 공고 JD 분석, 1차) / resume_analysis(이력서 분석, 2차).
#
# 실행 예(두 큐 모두 처리):
#   uv run celery -A app.core.celery_app.celery_app worker --loglevel=INFO -Q job_discovery,resume_analysis

# 큐 이름 상수(라우팅 + API 응답에서 공용으로 참조 — 순환 import 방지 위해 여기서 정의)
JOB_DISCOVERY_QUEUE = settings.CELERY_TASK_DEFAULT_QUEUE   # 기본값 "job_discovery"
RESUME_ANALYSIS_QUEUE = "resume_analysis"

celery_app = Celery(
    "resume_auto_analyzer",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.job_posting_tasks",
        "app.tasks.resume_analysis_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.CELERY_TIMEZONE,
    enable_utc=False,
    task_acks_late=settings.CELERY_TASK_ACKS_LATE,
    worker_prefetch_multiplier=settings.CELERY_WORKER_PREFETCH_MULTIPLIER,
    task_default_queue=JOB_DISCOVERY_QUEUE,
    # task 모듈별 큐 라우팅 (선택 A: 한 worker 가 두 큐를 -Q 로 함께 처리)
    task_routes={
        "app.tasks.job_posting_tasks.*": {"queue": JOB_DISCOVERY_QUEUE},
        "app.tasks.resume_analysis_tasks.*": {"queue": RESUME_ANALYSIS_QUEUE},
    },
)
