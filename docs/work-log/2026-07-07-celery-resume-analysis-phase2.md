# [2026-07-07] Celery/Redis 2차 — 공고 이력서 분석 비동기화

## 1. 작업 배경

1차에서 사람인 공고 JD 분석을 Celery(`job_discovery` 큐)로 분리했다. 2차는 **공고 기준 이력서 분석**을 비동기로 전환한다. 기존에는 `POST /api/resumes/analyze-posting`(및 `analyze-selected`/`analyze-all`)가 요청 스레드에서 직접 `resume_analysis_service.analyze_posting` 을 실행했다 — Drive download + PDF/DOCX 파싱 + OpenAI 분석 + 점수 계산 + Drive 이동 + DB 저장을 동기로 수행하므로 파일이 많으면 요청이 오래 걸리고 타임아웃 위험이 있었다.

## 2. 1차 / 2차 범위 구분

- **1차**: 사람인 공고 JD 분석(`job_discovery` 큐, `analyze_job_posting_jd_task`).
- **2차(이번)**: 공고 이력서 분석(`resume_analysis` 큐, `analyze_resume_posting_task`). analyze-posting/selected/all enqueue 전환.
- **제외**: 레거시 부서 중심 `analyze_pending`/`analyze_router`/`resume_router`/`upload_router` 큐 전환, 작업 상태 전용 테이블(analysis_jobs) 신설, 화면 자동 polling, Celery Beat/스케줄러 활성화, OpenAI 프롬프트/Drive 이동 로직 변경.

## 3. 기존 동기 분석 문제

- 분석이 요청 안에서 끝날 때까지 응답 지연(파일 수 × OpenAI 호출 시간). `analyze-all`은 전 공고를 한 요청에서 처리 → 대량 시 타임아웃.
- Drive 인증 실패/네트워크 지연이 요청 스레드를 붙잡음.

## 4. 변경된 비동기 흐름

```
[API] POST /api/resumes/analyze-posting (권한 검사: ADMIN/MANAGER, 공고 범위)
  → active JD 확인 / 중복 가드(PROCESSING 있으면 ALREADY_PROCESSING, PENDING 없으면 NO_PENDING)
  → analyze_resume_posting_task.delay(posting_id, None, user.id)   # primitive payload
  → 즉시 {status: QUEUED, task_id, queue: resume_analysis, pending_count} 응답

[Worker · resume_analysis 큐] analyze_resume_posting_task(posting_id, resume_file_ids, requested_by_user_id)
  → 재검증: 공고/active JD/PENDING 존재 (권한은 API 에서 이미 검사)
  → build_authenticated_drive()  (실패 시 제한 재시도)
  → ResumeAnalysisService(drive).analyze_posting(posting_id, resume_file_ids)   # 기존 로직 재사용
       (파일별: set_processing → Drive download → PDF/DOCX parse → OpenAI 분석 → matching score
        → completed/failed 이동 → resume_analysis_results 저장, 파일 단위 성공/실패 격리)
  → task 상태: 전부 성공 COMPLETED / 일부 실패 PARTIAL_FAILED / 전부 실패 FAILED
```

- `analyze-selected`: 선택 파일을 공고별로 그룹핑 → 그룹마다 `analyze_resume_posting_task(posting_id, [file_ids], user_id)` enqueue.
- `analyze-all`(ADMIN): 대기 있는 공고별로 task 를 나눠 enqueue(요청 타임아웃 회피).

## 5. 변경 파일

| 파일 | 변경 |
| --- | --- |
| `app/core/celery_app.py` | `resume_analysis_tasks` include, `task_routes`(모듈별 큐), `RESUME_ANALYSIS_QUEUE`/`JOB_DISCOVERY_QUEUE` 상수 |
| `app/tasks/resume_analysis_tasks.py` | **신규** — `analyze_resume_posting_task`(재검증 → Drive 인증 → analyze_posting 재사용 → 상태 매핑) |
| `app/services/resume_analysis_db_service.py` | `get_posting_analysis_status_counts()` 추가(중복 가드/대기 판단용, read-only) |
| `app/api/resumes_router.py` | analyze-posting/selected/all → enqueue 전환(즉시 QUEUED). 미사용이 된 `_run_analysis_over_postings` 제거(내 변경이 orphan 화) |
| `app/static/app.js` | `showAnalysisSummary` queue-aware, `runPostingAnalyze` 결과렌더→요약(큐 안내) — 최소 수정 |
| `docker-compose.yml` | worker `-Q job_discovery,resume_analysis` |
| `README.md` / `docs/WORKFLOW.md` / `docs/TODO.md` | 비동기 이력서 분석/큐/실행법 반영 |

## 6. task 설계

- **payload = primitive만**: `posting_id`, `resume_file_ids`(선택 시), `requested_by_user_id`. API 요청 DB 세션/ORM 객체 미전달.
- **세션**: 재사용하는 service/db_service 가 호출마다 `SessionLocal` 을 새로 열고 닫음(요청 세션 미사용). task 는 primitive 만 받아 DB 를 다시 조회.
- **멱등/재실행 안전**: 이미 COMPLETED/FAILED 인 파일은 PENDING 이 아니라 재분석되지 않음. 중간 실패 시 미처리 파일은 PENDING 유지 → 재실행 시 남은 것만 처리.
- **재시도**: Drive 인증 실패(`DriveConfigError`, 분석 시작 전)만 제한 재시도(max_retries=2). 분석 중간 오류는 OpenAI 비용 고려해 broad retry 하지 않고 FAILED 반환(파일 단위 결과는 이미 커밋됨).
- **파일 단위 실패 격리**: 기존 `_process_targets`/`_process_one_db` 로직 그대로 유지(복붙 없음). 30개 중 1개 파싱 실패해도 나머지 계속.
- **로그**: posting_id / 파일 수 / 상태 / task_id 정도만. 이력서 원문·LLM prompt/response·HTML 전문 로그 금지.

## 7. queue 설계

- `celery_app.conf.task_routes` 로 모듈별 라우팅: `job_posting_tasks.*` → `job_discovery`, `resume_analysis_tasks.*` → `resume_analysis`.
- 선택 A(한 worker 가 두 큐 처리): `-Q job_discovery,resume_analysis`. 후속으로 `resume_analysis` 전용 worker 분리 가능(TODO).

## 8. API 응답 변경

| API | 기존 | 변경 후 |
| --- | --- | --- |
| `POST /analyze-posting` | 분석 결과 전체(results/counts) | `{status: QUEUED, posting_id, task_id, queue, pending_count}` (또는 `ALREADY_PROCESSING`/`NO_PENDING`) |
| `POST /analyze-selected` | 공고별 분석 결과 집계 | `{status: QUEUED, queue, resume_file_count, tasks:[{posting_id, resume_file_count, task_id}]}` |
| `POST /analyze-all` | 전 공고 분석 결과 집계 | `{status: QUEUED, queue, posting_count, resume_file_count, tasks:[...]}` |

- 오류/권한 응답 구조(`_error` step/hint, 403)는 그대로 유지. broker 실패 시 `enqueue_failed`(503).

## 9. 중복 방지 정책

- **posting 단위**: `get_posting_analysis_status_counts(posting_id)` 로 PROCESSING>0 → `ALREADY_PROCESSING`(enqueue 안 함), PENDING==0 → `NO_PENDING`.
- **file 단위**: `analyze-selected` 는 `file_status=UPLOADED & analysis_status=PENDING` 인 파일만 대상(이미 PROCESSING/COMPLETED 제외). analyze_posting 내부도 PENDING 만 조회.
- **worker 재방어**: task 시작 시 PENDING 재조회 → 없으면 skip(COMPLETED/no_pending_resumes). 같은 파일 재분석 최소화.

## 10. 검증 결과

일회용 컨테이너(`postgres:16-alpine`, `redis:7-alpine`) + 접속정보 환경변수 주입(운영 `.env` 미변경).

- `uv run python -m compileall -q app` → OK.
- celery import: 두 task 등록(`analyze_job_posting_jd_task`, `analyze_resume_posting_task`), 라우팅(job_discovery/resume_analysis) 확인. `import app.main` OK(순환 없음, 73 routes).
- **worker 기동**: `-Q job_discovery,resume_analysis` 로 두 큐 + 두 task 등록, redis 연결, `ready`.
- **eager 통합**(실 Postgres, `analyze_posting`/Drive stub):
  - analyze-posting: pending=2 → `QUEUED`(task_id) → (worker) COMPLETED, pending 0 소진. `analyze_posting(posting_id, None)` 호출 확인(재사용).
  - 재실행: pending 0 → `NO_PENDING`(enqueue 안 함).
  - PROCESSING 존재: `ALREADY_PROCESSING`(enqueue 안 함).
  - analyze-selected: 선택 파일 → `QUEUED`, tasks 1건, `analyze_posting(posting_id, [ids])` 호출 확인.
  - task 상태 매핑: 일부 실패 → `PARTIAL_FAILED`, 전부 실패 → `FAILED`.
  - task no-pending: 대기 없는 공고 → `COMPLETED`/`no_pending_resumes`.

## 11. 이번 범위에서 제외/주의

- **analyze-all: 적용함**(공고 단위 task 분할 enqueue). 대량 요청 타임아웃 회피 목적. (기존 동기 유지 옵션 B 가 아니라 A 선택 — 각 공고 task 독립·중복 가드 적용으로 안전)
- **polling UI: 제외**. 분석 상태는 기존 '이력서 현황' 화면 새로고침으로 확인. 자동 polling 은 후속(TODO).
- **레거시 부서 중심 플로우: 큐 미대상**. `analyze_pending`/`batch_service`/`analyze_router` 등은 전환하지 않음.
- OpenAI 프롬프트/점수 산식/Google Drive 이동·업로드 로직 불변. DB 테이블 삭제/데이터 마이그레이션 없음. 사람인 스케줄러 자동 활성화 없음.
- 프론트 `renderAnalysisResults` 는 비동기 전환으로 미호출(제거는 프론트 대규모 변경 회피 위해 보류 — 정리 대상 TODO).

## 12. 남은 작업

- 작업 상태 조회 API + 화면 polling(필요 시 `analysis_jobs` 테이블).
- `resume_analysis` 전용 worker 분리 / 동시성·prefetch·scale 정책.
- 부분 실패 파일 재분석 UX, task 결과 보존/모니터링/실패 알림.
- 미사용 코드 정리(`_run_analysis_over_depts` legacy, 프론트 `renderAnalysisResults`).
