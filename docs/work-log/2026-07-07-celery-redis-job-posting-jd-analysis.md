# [2026-07-07] Celery/Redis 도입 1차 — 공고 JD 분석 비동기화

## 1. 작업 배경

사람인 신규 공고 수집 배치는 신규 공고를 `job_postings` 에 insert 한 뒤, 상세 URL 분석 + JD 저장(+Drive 폴더)을 **동기(요청 스레드)로** 처리하고 있었다. 상세 분석은 네트워크 fetch + OpenAI 호출이라 느리고 실패 가능성이 있어, 요청/스케줄러 흐름에서 분리해야 한다. 이번 1차 작업은 **Redis + Celery 기반 비동기 큐**를 도입하고 **공고 JD 분석만** worker 로 분리한다.

## 2. 1차 / 2차 범위 분리

- **1차(이번 작업)**: 사람인 신규 공고 발견 → 공고 insert → **JD 분석 task enqueue(posting_id)** → worker 가 상세 분석 + JD 저장 + Drive 폴더 생성. 큐 하나(`job_discovery`).
- **2차(예정)**: 이력서 분석(`/api/resumes/analyze-posting`·`analyze-selected`·`analyze-all`)의 Celery 전환, 작업 상태 조회 API/화면 polling, `resume_analysis` 전용 큐 분리.
- **제외(이번 작업 안 함)**: 이력서 분석 큐 전환, analysis_jobs 테이블, 프론트 대규모 변경, 레거시 부서 중심 `analyze_pending`/`upload_router`/`analyze_router`/`resume_router` 큐 전환, OpenAI 프롬프트/Drive 로직 변경.

## 3. Redis / Celery 연결 정보

- broker/result backend 는 Redis. `.env`(`CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND`)에서 읽고 **코드 하드코딩 없음**.
- Docker Compose 내부는 `redis://redis:6379/0`(broker) · `redis://redis:6379/1`(result). 로컬 직접 실행은 `redis://localhost:6379/...`.
- 기본 큐 `job_discovery`, timezone `Asia/Seoul`, `worker_prefetch_multiplier=1`, `task_acks_late=true`.

## 4. .env.example 구조

`.env.example` 에 Celery/Redis 섹션 추가(placeholder/예시만, 실제 운영 URL/비밀번호 금지). `config.py` 는 미설정 시 `redis://localhost:6379/...` 기본값을 갖는다(로컬 import 안전).

## 5. 신규 처리 흐름

```
[수동 API POST /api/jobs/discover/saramin/didim 또는 Scheduler(주석)]
 saramin 수집 → 디딤(주) 필터 → detail_url(rec_idx) 중복 확인
 → 신규만 job_posting_service.create_posting(status=DRAFT)
 → mark_jd_lifecycle_status(JD_QUEUED)          # enqueue 전에 기록(race 방지)
 → analyze_job_posting_jd_task.delay(posting_id, requested_by_user_id)

[Celery worker · job_discovery]
 analyze_job_posting_jd_task(posting_id, requested_by_user_id):
   SessionLocal() 신규 개설
   posting 재조회 (없으면 not_found)
   idempotent: active JD 있거나 JD_READY/ACTIVE 면 skip
   detail_url 없으면 JD_FAILED
   mark_jd_lifecycle_status(JD_PROCESSING)
   job_extract_service.extract_from_url(detail_url)     # 기존 로직 재사용
     - 재시도 대상(fetch_failed/openai_rate_limited/openai_network_failed) → self.retry
     - 그 외 실패/회사 미검증 → JD_FAILED
   job_posting_service.upsert_jd(..., drive_factory=build_authenticated_drive)  # JD 저장 + Drive 폴더(재사용)
     - DriveConfigError → self.retry(제한)
     - HTTPException → JD_FAILED
   mark_jd_lifecycle_status(JD_READY)
   finally: db.close()
```

**핵심 원칙 준수**: 큐 payload 는 `posting_id`(+`requested_by_user_id`) primitive 만. API 요청 db 세션을 task 에 넘기지 않고 task 내부에서 SessionLocal 신규 개설, finally close. 상세 분석/JD 저장/Drive 로직은 **복붙 없이 기존 서비스 재사용**(job_extract_service / job_posting_service / job_posting_drive_service). 레거시 `job_descriptions`/`jd_router`/`upload_service`/`batch_service` 미사용.

## 6. 변경 파일

| 파일 | 변경 |
| --- | --- |
| `pyproject.toml` / `uv.lock` | `celery`, `redis` 의존성 추가(`uv add`) |
| `app/core/config.py` | `CELERY_*` 설정 6종 추가 |
| `.env.example` | Celery/Redis 섹션 추가(예시만) |
| `app/core/celery_app.py` | **신규** — Celery 앱(broker/backend/큐/serializer/timezone) |
| `app/tasks/__init__.py` | **신규** — tasks 패키지 |
| `app/tasks/job_posting_tasks.py` | **신규** — `analyze_job_posting_jd_task`(+`_parse_skills`/`_resolve_user`/재시도 정책) |
| `app/services/job_posting_service.py` | `JD_LIFECYCLE_STATUS` + `mark_jd_lifecycle_status()` 추가(VALID_STATUS 와 분리) |
| `app/services/job_posting_discovery_service.py` | 동기 분석 제거 → **create_posting + enqueue** 로 전환, 요약에 `queued_count` 추가 |
| `app/api/jobs_router.py` | discover 엔드포인트 docstring 갱신(큐 흐름 반영) |
| `docker-compose.yml` | `redis` + `resume-ai-worker` 서비스 추가, app `depends_on: redis` |
| `README.md` / `docs/WORKFLOW.md` / `docs/TODO.md` | 비동기 흐름/실행법/1차·2차 반영 |

## 7. 상태값 정책

`job_postings.status` 는 자유 `varchar(30)`(DB enum/check 없음). 사용자 편집용 `VALID_STATUS = {DRAFT, OPEN, CLOSED, INACTIVE}` 는 **그대로 유지**(공고 등록/수정 UI·검증·필터 불변). JD 분석 파이프라인 전용 상태 `JD_LIFECYCLE_STATUS = {JD_QUEUED, JD_PROCESSING, JD_READY, JD_FAILED}` 는 **별도 헬퍼 `mark_jd_lifecycle_status`** 로 같은 컬럼에 기록(사용자 검증 경로 우회, 권한 검사 없이 내부 배치/worker 전용).
- 매핑: 신규 발견=DRAFT → 큐 적재=JD_QUEUED → 처리 중=JD_PROCESSING → 성공=JD_READY → 실패=JD_FAILED.
- Alembic 변경 불필요(자유 varchar). ※ 후속에서 상태 표준화/enum 도입 시 별도 검토(TODO).

## 8. 수동 실행 방법

```bash
POST /api/jobs/discover/saramin/didim        # 권한: ADMIN/MANAGER
```
응답: `collected_count / matched_company_count / new_count / queued_count / skipped_duplicate_count / failed_count / items[{posting_id,title,detail_url,status:"JD_QUEUED"}]`.

## 9. Worker 실행 방법

- 로컬: `uv run celery -A app.core.celery_app.celery_app worker --loglevel=INFO -Q job_discovery`
- Compose: `docker compose up -d --build resume-ai-worker` / `docker compose logs -f resume-ai-worker`
- worker 는 app 과 동일 이미지/`.env`/볼륨(google secrets, data) → DB/OpenAI/Google Drive/회사 CA 동일 접근.

## 10. 검증 결과

일회용 컨테이너(`postgres:16-alpine`, `redis:7-alpine`) + 접속정보 `DATABASE_URL`/`CELERY_*` 환경변수 주입(운영 `.env` 미변경).

- `uv run python -m compileall -q app` → OK.
- `from app.core.celery_app import celery_app` → main=`resume_auto_analyzer`, default queue=`job_discovery`. task `app.tasks.job_posting_tasks.analyze_job_posting_jd_task` 등록 확인.
- `import app.main` → OK(순환 import 없음, 73 routes).
- Redis: `redis-cli ping` → PONG.
- **Worker 기동**: 실제 worker 가 `redis://...:0` broker 연결, `job_discovery` 큐 + task 등록, `celery@... ready.` 확인.
- **Eager 통합**(실 Postgres, 외부 호출 stub): 사람인 수집→공고 2건 insert→enqueue→(worker) JD_PROCESSING→JD_READY, JD 저장(자격요건→required/우대→preferred/주요업무→jd_content) + Drive 폴더 id 세팅. `new_count=2, queued_count=2, failed=0`.
  - **중복 재실행**: 동일 detail_url 2건 duplicate skip, 공고 중복 insert 없음, task 중복 enqueue 없음.
  - **멱등**: JD_READY 공고에 task 재호출 → `skipped`.
  - **실패**: 상세 추출 non-retryable(not_html) → 공고 status `JD_FAILED`.

## 11. 이번 범위에서 제외한 작업

- 이력서 분석 `analyze_posting`/`analyze-selected`/`analyze-all` 의 Celery 전환(2차).
- 작업 상태 조회 API / 화면 polling / `analysis_jobs` 테이블 / `resume_analysis` 큐 분리(2차).
- 레거시 부서 중심 `analyze_pending`/`batch_service`/`upload_router` 등 큐 전환(대상 아님).
- 운영 스케줄러 자동 실행(여전히 주석 처리 — 서버 startup 자동 실행 없음).
- OpenAI 프롬프트, Google Drive 업로드/이동 로직 변경(불변).

## 12. 후속 작업 / 주의사항

- 운영 반영 시 `.env` 에 실제 Redis 연결정보 필요. Redis 는 기본 내부 네트워크 접근(compose `redis` host 포트 미노출) — 필요 시 방화벽/비밀번호 설정.
- broker(Redis) 다운 시 discover API 는 공고 insert 후 enqueue 실패 → 해당 공고 `JD_FAILED`(공고 자체는 유지). 재수집 시 동일 URL 은 duplicate skip 되므로, 실패 공고 재처리 정책은 후속 검토.
- 재시도 정책은 좁게(fetch/OpenAI rate·network, Drive 인증)만. broad Exception 재시도 금지, idempotent(활성 JD 있으면 skip)로 중복 JD 방지.
- 2차에서 이력서 분석 큐(`resume_analysis`) 분리 및 worker scale/동시성 정책 정리.
