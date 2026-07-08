# DB 테이블 사용 현황 분석 (제거 후보 리스트업)

> 작성: 2026-07-08 · 근거: **현재 소스코드(코드 기준)** grep + 라우터/서비스/모델 추적.
> **이 문서는 "제거 후보 리스트업 + 근거 정리"까지만 합니다.** 실제 `DROP TABLE`/삭제 마이그레이션은 만들지 않았습니다.
> 공식 기준 플로우는 **공고(job posting) 중심**입니다. 레거시 부서 중심 경로는 `LEGACY` 주석으로 표시되어 있고 동작만 유지됩니다.

현재 `resume_ai` 스키마 테이블(10개): `alembic_version`, `departments`, `dept_drive_folders`, `job_descriptions`, `job_posting_jds`, `job_postings`, `resume_analysis_results`, `resume_files`, `resume_upload_batches`, `users`.

---

## 1. 분류 요약표

| table | classification | used_by_models | used_by_routers | used_by_services | current_flow_usage | risk_if_removed | recommendation |
|---|---|---|---|---|---|---|---|
| `users` | **KEEP** | `User` | auth, admin_users, (전 라우터 인증 의존) | auth_service, admin_user_service, department_access_service, job_posting_service(created_by), tasks | 로그인/RBAC/`created_by`(공고·JD) 전반 | 인증·권한 전체 붕괴 | 유지 |
| `job_postings` | **KEEP** | `JobPosting` | job_postings, jobs | job_posting_service, job_posting_discovery_service, job_posting_tasks, resume_analysis_db_service, resume_status_db_service | 공고 중심 플로우의 중심 엔티티 | 공고/JD/분석 전체 붕괴 | 유지 |
| `job_posting_jds` | **KEEP** | `JobPostingJD` | job_postings | job_posting_service(upsert/active JD), resume_analysis_db_service | 공고별 공식 JD(1 active) | JD·분석 붕괴 | 유지 |
| `resume_files` | **KEEP** | `ResumeFile` | resumes | resume_upload_db_service, resume_analysis_db_service, resume_status_db_service | 이력서 파일/상태의 중심 | 업로드/분석/현황 붕괴 | 유지 |
| `resume_analysis_results` | **KEEP** | `ResumeAnalysisResult` | resumes | resume_analysis_db_service, resume_status_db_service | 분석 상세 결과 저장 | 분석 결과 조회 붕괴 | 유지 |
| `resume_upload_batches` | **KEEP** | `ResumeUploadBatch` | resumes | resume_upload_db_service, resume_analysis_db_service(`upload_id` JOIN + 카운트 갱신), resume_status_db_service | 공고 업로드 회차/집계(완료·실패·대기 카운트) — 공식 경로에서 JOIN 사용 | 업로드 회차/현황 집계 붕괴 | 유지 |
| `departments` | **KEEP** | `Department` | admin_users, departments, auth | department_access_service(RBAC·subtree), department_db_service, resume_analysis_db_service, resume_status_db_service, job_posting_service(부서명/권한) | 권한(RBAC)·부서 트리·공고 `department_id` 참조 | 권한 범위/부서 필터 붕괴 | 유지(공고 중심에서도 권한 기준으로 사용) |
| `alembic_version` | **KEEP** | (Alembic 내부) | - | - | 마이그레이션 버전 추적 | 마이그레이션 이력 관리 불가 | 유지(Alembic 관리) |
| `dept_drive_folders` | **LEGACY_KEEP_TEMP** | `DeptDriveFolder` | drive | dept_drive_folder_db_service, dept_folder_sync_service, resume_drive_upload_service(**legacy fallback**), resume_analysis_service(legacy 부서 분석) | 공식 업로드는 **공고 폴더**(`job_postings.drive_*`) 사용. 부서 매핑은 관리자 Drive 동기화 + 공고 폴더 없을 때 fallback | 관리자 부서 폴더 동기화/legacy 업로드 fallback 붕괴 | 당장 삭제 금지. 레거시 부서 업로드/동기화 은퇴 후 제거 후보 |
| `job_descriptions` | **LEGACY_KEEP_TEMP** | `JobDescription` | jd(`/api/jd`), jds(`/api/jds`) *(둘 다 LEGACY)* | jd_service, jd_db_service, resume_analysis_service(`analyze_pending` legacy) | 공식 JD 는 `job_posting_jds`. 이 테이블은 부서 기준 legacy JD 전용 | legacy 부서 JD API/부서 기준 분석 fallback 붕괴 | 당장 삭제 금지. 레거시 JD/분석 은퇴 후 제거 후보(최우선) |

> **REMOVE_CANDIDATE(현재 코드 어디에서도 미사용)** = **없음.** 10개 테이블 모두 코드 참조가 존재합니다.
> **NEEDS_DECISION** = 실질적으로 `dept_drive_folders` / `job_descriptions` 두 legacy 테이블의 **은퇴 시점 결정**이 핵심입니다(아래 4·5·6 참고).

---

## 2. 공식 공고 중심 플로우에서 필요한 테이블

- `users`, `job_postings`, `job_posting_jds`, `resume_files`, `resume_analysis_results`, `resume_upload_batches`, `departments`, `alembic_version`.
- 근거: 공고/JD 등록·URL 추출·이력서 업로드·(Celery)분석·현황·Excel 이 모두 위 테이블을 직접 사용. `departments` 는 공고 중심 전환 후에도 **RBAC(부서+하위 subtree 권한)와 공고 `department_id`(optional)** 로 필수.

## 3. 레거시 부서 중심 플로우에만 남은 테이블

- `job_descriptions` — 부서 기준 JD(`/api/jd`, `/api/jds`, `jd_service`/`jd_db_service`, `resume_analysis_service.analyze_pending`). 공식 JD(`job_posting_jds`)와 **별개 테이블**. 관련 라우터/서비스/모델에 이미 `LEGACY` 주석.
- `dept_drive_folders` — 부서별 Drive `inbox/completed/failed` 매핑. 공식 업로드는 공고 폴더를 쓰고, 이 테이블은 **관리자 부서 폴더 동기화 화면**과 **공고 폴더 미존재 시 legacy fallback**에서만 사용.

## 4. 제거 후보 (이번 작업에서는 문서화만)

우선순위 순:
1. **`job_descriptions`** — 레거시 부서 JD 전용. 공고 중심 전환이 끝나고 legacy JD API(`/api/jd`,`/api/jds`)·부서 기준 분석(`analyze_pending`)이 실제로 사용 중단되면 제거 1순위.
2. **`dept_drive_folders`** — 레거시 부서 Drive 매핑. 공고 폴더 구조로 완전 이관 + 관리자 부서 동기화 화면 은퇴 후 제거 후보.

> `departments` 는 **제거 후보가 아닙니다**(공고 중심 RBAC/부서 트리로 계속 사용). `resume_upload_batches` 도 공식 경로에서 JOIN·카운트로 사용되므로 **KEEP**.

## 5. 즉시 삭제하면 안 되는 이유

- **레거시 라우터/서비스가 아직 include/참조** 중: `/api/jd`·`/api/jds`(job_descriptions), `/api/drive` 부서 폴더 동기화(dept_drive_folders). 라우터는 `app/main.py` 에 여전히 include 되어 있어 호출 시 테이블 접근.
- **공식 경로의 fallback 의존**: `resume_drive_upload_service` 는 공고 inbox 폴더가 없을 때 `dept_drive_folders` 로 fallback(코드 주석에 명시).
- **데이터 보존 원칙**: 운영 DB destructive 금지. 과거 부서 기준 데이터가 남아 있을 수 있어 임의 DROP 시 복구 불가.
- **FK/인덱스 영향**: 삭제 전 참조 무결성/인덱스 사용처 확인 필요.

## 6. 삭제 전 선행 작업 (체크리스트)

1. **프론트 호출 제거 확인** — legacy 화면(`view-jd`) / 관리자 부서 Drive 동기화가 해당 테이블을 더 이상 호출하지 않는지 런타임/모니터링으로 확정.
2. **레거시 API deprecated 처리** — `jd_router`/`jds_router`/`drive_router`(부서 폴더) 응답에 deprecated 표기 → 일정 기간 후 include 제거.
3. **운영 DB 백업** — `pg_dump`(스키마+데이터) 후 진행.
4. **데이터 이관 필요 여부 확인** — 부서 기준 JD/폴더 데이터를 공고 중심으로 옮길지, "미매핑 유지"로 폐기할지 정책 결정.
5. **FK/index 영향 확인** — 참조 제약/인덱스 사용처 점검(현재 두 legacy 테이블을 참조하는 FK 없음 확인).
6. **Alembic downgrade 전략 검토** — DROP 마이그레이션은 `downgrade` 로 재생성 가능하게 작성(데이터 복구는 백업 기준).
7. **개발 DB 에서만 DROP 검증** — 일회용/개발 DB 에서 `upgrade`/`downgrade` 왕복 검증.
8. **운영 반영 전 승인** — 담당자 승인 후에만 운영 반영. (본 저장소는 리스트업까지만)

## 7. 후속 Alembic cleanup 계획 초안 (참고 — 이번 미실행)

```
# 예시(미작성): 0006_deprecate_legacy_dept_jd.py
#  - job_descriptions / dept_drive_folders 는 즉시 DROP 하지 않고,
#    (선택) 코멘트로 DEPRECATED 표기만. 실제 DROP 은 은퇴 확정 후 별도 리비전.
#  - upgrade: op.execute("COMMENT ON TABLE resume_ai.job_descriptions IS 'DEPRECATED ...'")
#  - downgrade: 코멘트 원복
# 실제 DROP 리비전은 위 6번 선행 작업 완료 + 승인 후에만 작성.
```
