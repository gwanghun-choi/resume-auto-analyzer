# [2026-07-07] 공고 중심 플로우 확정 + 레거시 부서 중심 정리

## 1. 작업 배경

시스템이 **부서(department) 중심 → 공고(job posting) 중심** 이력서/JD 흐름으로 전환 중이며, 신규/주력 경로와 레거시 경로가 공존한다. 이번 작업은 **삭제 우선이 아니라** "사용 여부 확인 → deprecated 표시 → 공고 중심 기준 문서화 → 후속 제거 대상 정리" 가 목적이다. (기능 로직/DB/프론트 대규모 변경 없음)

## 2. 현재 공존 구조 (사용 여부 확인 결과)

프론트 **런타임 fetch 호출** 기준으로 확인했다(import/주석만으로 사용 판단하지 않음).

- 프론트가 실제 호출하는 분석/이력서/공고 API 는 **모두 공고 중심**이다:
  - `/api/job-postings*`, `/api/resumes/upload-to-drive`, `/api/resumes/analyze-posting`, `/api/resumes/analyze-selected`, `/api/resumes/analyze-all`(모두 `_run_analysis_over_postings` → `analyze_posting`), `/api/resumes/status*`, `/api/resumes/posting-pending*`.
- 레거시 `/api/depts`·`/api/uploads/{deptId}`·`/api/analyze/{deptId}/{uploadId}`·`/api/resume` 는 **app.js 헤더 주석에만 존재하고 런타임 fetch 없음**.
- `/api/jd/*`(jd_router)는 `view-jd` 화면 함수(`loadJd`/`saveJd`/`recommendJd`)에 연결되어 있으나, **`view-jd` 섹션에 대응하는 메뉴 항목(`data-view="jd"`)이 없어 화면에서 도달 불가**(orphaned).
- `/api/jds`(jds_router, `job_descriptions` CRUD)는 프론트 호출 없음.
- INFRA/ADMIN(사용 중): `/api/drive/*`, `/api/departments/sync-from-drive-config`, `/api/db/counts`, `/api/admin/*`, `/api/auth/*`.

## 3. 공고 중심 KEEP 대상 (신규 개발은 이것만)

- 라우터: `job_postings_router`, `resumes_router`(analyze-posting/selected/all), `jobs_router`, `auth_router`, `admin_users_router`
- 서비스: `job_posting_service`, `job_posting_drive_service`, `job_extract_service`, `resume_drive_upload_service`, `resume_analysis_service.analyze_posting`, `resume_analysis_db_service`, `resume_upload_db_service`, `resume_status_db_service`, `resume_status_excel_service`, `department_access_service`
- 사람인 배치: `saramin_job_collect_service`, `job_posting_discovery_service`, `scheduler_service`(등록 주석)
- 공유 분석 프리미티브(KEEP): `ai_agent_service`, `matching_service`, `resume_parser_service`, `openai_llm_service`, `jd_recommend_service`
- 테이블: `job_postings`, `job_posting_jds`, `resume_files`, `resume_analysis_results`

## 4. 레거시 LEGACY 대상 (표시만, 삭제 안 함)

- 라우터: `dept_router`(/api/depts), `upload_router`(/api/uploads), `resume_router`(/api/resume), `analyze_router`(/api/analyze), `jd_router`(/api/jd), `jds_router`(/api/jds)
- 서비스: `batch_service`, `upload_service`(로컬 FS), `jd_service`, `jd_db_service`
- 모델/테이블: `job_description` / `job_descriptions`
- 더미 부서: `dept_service`(dept_router 전용). *참고:* `dummy_dept_loader` 는 INFRA `dept_config_service` 가 seed 경로로 참조하므로 LEGACY 로 표시하지 않았다.
- KEEP 모듈 내 레거시 경로: `resume_analysis_service.analyze_pending`(부서 기준, legacy job_descriptions 사용), resumes_router `/analyze-pending` 엔드포인트, **미사용** `_run_analysis_over_depts` 헬퍼(어떤 엔드포인트도 호출하지 않음).

## 5. 이번 변경 사항

동작을 바꾸지 않는 **주석/문서 위주**이며, 예외는 §5-(2) 한 건뿐이다.

1. **LEGACY 주석 추가**(동작 불변):
   - 라우터 6개(`dept`/`upload`/`resume`/`analyze`/`jd`/`jds`_router) 상단에 `LEGACY ROUTER` 블록 + 신규 대체 경로 안내.
   - 서비스 5개(`batch_service`/`upload_service`/`jd_service`/`jd_db_service`/`dept_service`) + 모델(`job_description`) 상단 `LEGACY` 주석.
   - KEEP 모듈 내 레거시 경로: `resume_analysis_service.analyze_pending`, resumes_router `/analyze-pending`·`_run_analysis_over_depts` 에 `LEGACY` 주석.
   - `app/main.py` 라우터 include 블록에 **KEEP / INFRA / LEGACY 분류 주석**(순서 변경 없음).
2. **신규 배치의 레거시 결합 제거**(최소 코드 변경): `job_posting_discovery_service` 가 legacy `jd_service.parse_skill_text` 를 import 하던 것을 **로컬 `_parse_skills` 헬퍼로 대체**(동일 동작). → 공고 중심 배치가 legacy 모듈에 의존하지 않음.
3. **문서**: `README.md`(공식 주력/레거시 매핑 표 + 신규 개발 규칙 + Celery 기준), `docs/WORKFLOW.md`(공식 9단계 공고 중심 흐름 + Legacy department-based flow 섹션), `docs/TODO.md`(후속 제거 대상), 본 work-log.

## 6. 삭제하지 않은 이유

- 요구사항: 이번 작업은 삭제 우선이 아니라 **deprecated 처리 + 문서화**. 레거시 라우터/서비스/테이블 즉시 제거 금지.
- 레거시 API 가 프론트 런타임에서 호출되지 않더라도, 외부 스크립트/직접 호출/과거 데이터 호환 가능성이 있어 **사용 중단 확정 후** 제거하는 것이 안전하다.
- `job_descriptions` 테이블·데이터는 유지(임의 DROP/삭제 금지). 제거 시 별도 마이그레이션 검토.

## 7. 사람인 신규 공고 수집 배치와의 관계 (확인)

`job_posting_discovery_service` 를 점검한 결과 **공고 중심 흐름만 사용**한다:
- 신규 공고 저장 대상 = `job_postings`(`job_posting_service.create_posting`).
- JD 저장 대상 = `job_posting_jds`(`job_posting_service.upsert_jd`).
- 중복 판단 = `platform_posting_url`(정규화 detail_url / rec_idx) 기준.
- 상세 분석 = `job_extract_service.extract_from_url` **재사용**(수동 URL 분석과 동일 경로).
- Drive 폴더 = `job_posting_service` → `job_posting_drive_service.ensure_posting_folders`.
- legacy `job_descriptions`/`jd_router`/`jd_db_service`/`upload_service`/`batch_service` **미사용**.
- 유일한 legacy 결합이던 `jd_service.parse_skill_text` 는 이번에 로컬 헬퍼로 제거함(§5-2).

## 8. 후속 Celery 도입 시 기준

- 큐 대상은 공고 중심만: `resume_analysis_service.analyze_posting`, `job_extract_service`(공고 URL/JD 추출), `job_posting_service`.
- 레거시 `analyze_pending` / `batch_service` 는 큐에 태우지 않는다.

## 9. 검증 결과

- `uv run python -m compileall -q app` → OK.
- `import app.main` → OK, 총 73 routes(라우터 include 상태 유지). 레거시 라우터 include 는 그대로(주석만 추가).
- `job_posting_discovery_service` 가 legacy `jd_service` 를 더 이상 import 하지 않음 확인, 로컬 `_parse_skills("Java, Spring\nRedis") == ["Java","Spring","Redis"]`(기존 `parse_skill_text` 와 동일 동작) 확인.
- 프론트 API 호출 확인: 공고/JD 관리·이력서 등록·분석 작업 관리·이력서 현황 화면 모두 공고 중심 라우터 사용, analyze-selected/all 은 `analyze_posting` 경로.

## 10. 남은 작업

- 레거시 API 제거 여부 최종 결정(사용 중단 확정 후).
- 인증 없는 관리/레거시 API 정리(`resume_router` 등, 이전 보안 이슈와 통합).
- `job_descriptions` 테이블 신규 사용 중단 확인 후 정리(마이그레이션 검토).
- 미사용 `_run_analysis_over_depts` 헬퍼 제거, `view-jd` 레거시 화면 코드 제거 여부(프론트 별도 작업).
- Celery 큐 도입(공고 중심 기준).
