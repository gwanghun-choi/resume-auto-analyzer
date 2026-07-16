from app.db.session import SessionLocal
from app.db.models.user import User
from app.services import job_posting_discovery_service
from app.services.google_drive_service import _log

# 배치 스케줄러. 현재는 "진입점 함수" 만 제공하고, 실제 1시간 주기 등록은 아래에 주석으로 둡니다.
# (서버 startup 에서 자동 실행되지 않습니다. 운영 반영 시 주석 해제 — 아래 안내 참고)
#
# 수동 실행은 API(POST /api/jobs/discover/saramin)로 가능합니다. 스케줄러와 수동 실행 모두
# 같은 service(job_posting_discovery_service.discover_saramin)를 호출합니다.


def _resolve_system_user(db):
    """스케줄러(무인) 실행용 시스템 사용자. 활성 ADMIN 중 가장 먼저 만들어진 계정을 사용합니다.
    (created_by 및 공고/JD 등록 권한 검사에 필요. 없으면 배치를 건너뜁니다.)"""
    return (
        db.query(User)
        .filter(User.role_code == "ADMIN", User.is_active.is_(True))
        .order_by(User.id.asc())
        .first()
    )


def run_saramin_discovery():
    """스케줄러/배치 진입점. 시스템 ADMIN 권한으로 대상 회사 신규 공고를 수집·등록합니다.
    배치가 실패해도 예외를 전파하지 않습니다(로그만 남김). 반환: 요약 dict 또는 None."""
    db = SessionLocal()
    try:
        user = _resolve_system_user(db)
        if not user:
            _log("[saramin-discovery] 활성 ADMIN 계정이 없어 배치를 건너뜁니다.")
            return None
        return job_posting_discovery_service.discover_saramin(db, user)
    except Exception as e:
        # 민감정보/HTML 은 로그에 남기지 않습니다. 실패 유형만 기록.
        _log(f"[saramin-discovery] 배치 실패: {type(e).__name__}: {e}")
        return None
    finally:
        db.close()


def run_jobkorea_discovery():
    """스케줄러/배치 진입점(잡코리아). 사람인과 동일 구조 — 시스템 ADMIN 권한으로 수집·등록합니다.
    배치가 실패해도 예외를 전파하지 않습니다(로그만 남김). 반환: 요약 dict 또는 None."""
    db = SessionLocal()
    try:
        user = _resolve_system_user(db)
        if not user:
            _log("[jobkorea-discovery] 활성 ADMIN 계정이 없어 배치를 건너뜁니다.")
            return None
        return job_posting_discovery_service.discover_jobkorea(db, user)
    except Exception as e:
        _log(f"[jobkorea-discovery] 배치 실패: {type(e).__name__}: {e}")
        return None
    finally:
        db.close()


# =============================================================================
# 1시간 주기 자동 실행 (운영 반영 시 주석 해제)
#
# 현재 기본 비활성화입니다. 실제 자동 실행을 켜려면:
#   1) 의존성 추가: pyproject.toml 에 apscheduler 추가 후 `uv sync`
#      (현재 프로젝트 dependencies 에는 apscheduler 가 없습니다 — 임의 추가하지 않았습니다.)
#   2) 아래 start_scheduler() 주석을 해제
#   3) app/main.py 의 startup 이벤트에서 settings.SARAMIN_DISCOVERY_ENABLED 가 true 일 때만 start_scheduler() 호출
#      (서버가 여러 프로세스/워커로 뜨면 중복 실행되지 않도록 단일 프로세스에서만 켜세요.)
#
# from apscheduler.schedulers.background import BackgroundScheduler
#
# _scheduler = None
#
# def start_scheduler():
#     global _scheduler
#     if _scheduler is not None:
#         return _scheduler
#     _scheduler = BackgroundScheduler(timezone="Asia/Seoul")
#     _scheduler.add_job(
#         run_saramin_discovery,
#         "interval",
#         hours=1,
#         id="discover_saramin_jobs",
#         replace_existing=True,
#         max_instances=1,   # 이전 실행이 안 끝났으면 겹쳐 실행하지 않음
#         coalesce=True,     # 밀린 실행은 한 번으로 합침
#     )
#     _scheduler.add_job(
#         run_jobkorea_discovery,
#         "interval",
#         hours=1,
#         id="discover_jobkorea_jobs",
#         replace_existing=True,
#         max_instances=1,
#         coalesce=True,
#     )
#     _scheduler.start()
#     return _scheduler
# =============================================================================
