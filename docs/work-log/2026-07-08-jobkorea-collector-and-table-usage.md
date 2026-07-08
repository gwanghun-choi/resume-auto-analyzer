# [2026-07-08] 잡코리아 수집 배치 + platform_code 자동 매핑 + 미사용 테이블 리스트업

## 1. 작업 목표

1. 사람인 배치에 더해 **잡코리아(JobKorea) 신규 공고 수집 배치** 추가(디딤(주) 필터, 공고 중심 플로우).
2. URL 도메인 → **platform_code 자동 매핑**(saramin→SARAMIN, jobkorea→JOBKOREA, 그 외→기존 기본값) 구현/확인.
3. 현재 소스코드 기준 **안 쓰는 테이블 제거 후보 리스트업**(삭제 없이 문서화만).

제약 준수: 공고 중심만 신규 개발 / 레거시 부서 중심 결합 금지 / 사람인 배치 구조 재사용(복붙 금지) / 운영 DB destructive·DROP·삭제 금지 / Playwright 미도입 / OpenAI·Drive·이력서 분석 Celery 로직 불변 / .env·키 커밋 금지.

## 2. 변경 파일

**신규**
- `app/services/jobkorea_job_collect_service.py` — 잡코리아 검색 결과 정적(SSR) 수집기. 사람인 수집기와 동일 스타일. 회사명 필터는 사람인의 `is_didim_company` 재사용(잡코리아 `㈜`(U+321C) 합자만 `(주)`로 치환 후 위임).
- `docs/db-table-usage-analysis.md` — 테이블 사용 현황/제거 후보 분석.
- `tests/test_job_collectors.py` — pytest 미도입이라 plain-assert 실행 스크립트(`uv run python tests/test_job_collectors.py`).
- 본 work-log.

**수정**
- `app/services/job_posting_discovery_service.py` — 사람인 전용 → **플랫폼 공통 코어(`_discover`)로 일반화**. `discover_saramin_didim`/`discover_jobkorea_didim` 은 얇은 wrapper. `_register_one`/`_find_existing` 에 `platform_code` 인자 추가(플랫폼별 중복 스코프). **dry-run**(`_dry_run_items`) 추가.
- `app/services/job_extract_service.py` — 공개 함수 `platform_code_for_url(url)` 추가(기존 `_platform_for_host` 재사용).
- `app/services/job_posting_service.py` — `_auto_platform_code()` 추가. `create_posting`/`update_posting` 에서 platform_code 미지정 + URL 존재 시 도메인으로 자동 채움(사용자가 고른 값은 덮지 않음, 미지원 도메인은 None 유지).
- `app/api/jobs_router.py` — `POST /api/jobs/discover/jobkorea/didim` 추가, 사람인/잡코리아 둘 다 `dry_run` 쿼리 파라미터 추가.
- `app/services/scheduler_service.py` — `run_jobkorea_didim_discovery()` 추가 + 주석 등록 블록에 잡코리아 job 추가(**실제 등록은 주석 유지**).
- `app/core/config.py` — `JOBKOREA_DIDIM_SEARCH_URL`/`_KEYWORD`/`_COMPANY_NAME`/`JOBKOREA_DISCOVERY_ENABLED`.
- 문서: `docs/TODO.md`, `docs/WORKFLOW.md`, `README.md`, `.env.example`.

## 3. 잡코리아 수집 로직

- **검색 URL**: `https://www.jobkorea.co.kr/Search/?stext=%EB%94%94%EB%94%A4%28%EC%A3%BC%29` (디딤(주)).
- **회사명 필터**: 사람인과 동일 기준 재사용 — normalize(공백 제거) 후 `{"디딤(주)","디딤주식회사"}` exact 만 통과. 잡코리아 표기 `디딤㈜` 는 `㈜→(주)` 치환 후 매칭. 제외: `㈜디딤커뮤니케이션`/`디딤정신건강의학과의원`/`서울이주여성디딤터`/`디딤돌미술학원` 등.
- **detail_url 추출**: 검색 결과가 **서버 렌더링(SSR)** — 제목 앵커(`data-sentry-component="Title"`)의 `href=".../Recruit/GI_Read/{gno}?..."` 에서 공고 고유 id(`gno`, GI_No)와 제목 span 을 잡고, 같은 gno 의 회사 앵커 span 에서 회사명을 결속.
- **normalized URL 생성**: tracking(`Oem_Code`/`logpath`/`stext`/`listno`/`sc`) 제거하고 gno 로 재구성 → `https://www.jobkorea.co.kr/Recruit/GI_Read/{gno}` (canonical). 상대경로도 gno 기준으로 항상 절대 canonical 이 되어, tracking 만 다른 같은 공고는 같은 URL.
- **중복 판단**: 1순위 `platform_code=JOBKOREA` + gno(`GI_Read/{gno}` 부분일치, 과거 tracking 저장분 포함), 2순위 normalized_url 정확일치. `platform_posting_url` 컬럼 재사용(**external_id 컬럼 미추가**). 플랫폼 스코프로 사람인 rec_idx 와 충돌 방지.
- **queue enqueue**: 사람인과 동일 — 신규 공고 insert(status=DRAFT, platform_code=JOBKOREA) → `mark_jd_lifecycle_status(JD_QUEUED)` → `analyze_job_posting_jd_task.delay(posting_id, user_id)`. 큐에는 **posting_id 만**. 이후 흐름(worker JD 분석)은 기존과 동일.

## 4. platform_code 매핑 결과

`job_extract_service.platform_code_for_url(url)` 단일 진입점(수동 등록/URL 추출/배치 공통):
- `saramin.co.kr` → `SARAMIN`
- `jobkorea.co.kr` (서브도메인 포함) → `JOBKOREA`
- 그 외(example.com 등) → `None`(기존 기본값 유지, 오류 없음)
- (참고) `wanted.co.kr`→WANTED. `jumpit`/`incruit`/`career` 는 매핑값은 있으나 **`VALID_PLATFORM`(SARAMIN/JOBKOREA/WANTED/ETC) 밖이라 수동 등록 자동 채움 대상에서 제외** → None 유지.

수동 등록/수정: `platform_code` 미입력 + URL 있으면 위 규칙으로 자동 채움. **이미 고른 값이 있으면 덮지 않음**(사용자 선택 존중). 배치: 잡코리아=JOBKOREA / 사람인=SARAMIN 명시 저장.

## 5. 테이블 사용 분석 결과 (요약)

| table | classification | recommendation |
|---|---|---|
| users / job_postings / job_posting_jds / resume_files / resume_analysis_results | KEEP | 유지 |
| resume_upload_batches | KEEP | 공식 경로 JOIN·카운트 사용 → 유지 |
| departments | KEEP | RBAC·부서트리·공고 department_id → 유지 |
| alembic_version | KEEP | Alembic 내부 |
| dept_drive_folders | LEGACY_KEEP_TEMP | 관리자 부서 동기화 + 공고폴더 fallback → 은퇴 후 제거 후보 |
| job_descriptions | LEGACY_KEEP_TEMP | 레거시 부서 JD 전용 → 은퇴 후 제거 1순위 |

- **REMOVE_CANDIDATE(코드 미사용) = 없음.** 상세 근거/선행 작업/cleanup 초안: `docs/db-table-usage-analysis.md`.

## 6. 검증 결과

- **단위 테스트** `uv run python tests/test_job_collectors.py` → **ALL PASSED**(platform 매핑 6, URL normalize 3, 회사명 필터 9, 파서 fixture 8, dry-run shape 4).
- **라이브 파서(read-only)**: 실제 검색 URL fetch → cards=20, `parser_missed=0`, 디딤(주) matched=**12**(디딤㈜ 12건, 유사명 8건 제외). **DB insert/enqueue 없음.**
- **DB 통합(일회용 Postgres, 운영 DB 아님)**:
  - `alembic upgrade head`(빈 DB) → 10 테이블 생성.
  - `create_posting` 자동 매핑: 잡코리아 URL→JOBKOREA / 사람인→SARAMIN / example.com→None / jumpit→None / (명시 WANTED + 잡코리아 URL)→WANTED(존중).
  - `_find_existing`: tracking 붙은 raw URL 저장분도 gno 로 중복 검출, 플랫폼 스코프로 cross-platform 오탐 없음.
  - dry-run: insert/enqueue 0, 중복/신규 판정 정확(이미 insert 한 gno 만 is_duplicate=true), 항목 shape(platform_code/company_name/title/raw_url/normalized_url/is_duplicate/skip_reason) 확인.
  - **사람인 회귀**: 공통 코어 일반화 후에도 `discover_saramin_didim` dry-run 정상(source=SARAMIN, normalized rec_idx URL).
- 운영 DB(원격)에는 **읽기/쓰기 모두 수행하지 않음**(검증은 전부 일회용 컨테이너).

## 7. 주의사항

- **아직 삭제하지 않은 테이블**: `dept_drive_folders`, `job_descriptions`(및 전체) — 이번 작업은 리스트업/근거만. DROP/마이그레이션 없음.
- **운영 반영 전 확인**: 잡코리아 배치는 수동 API 로만 실행(스케줄러 자동 등록은 주석). 실제 insert/enqueue 는 Redis(broker) 필요.
- **잡코리아 정적 수집 한계**: 현재 검색 결과는 SSR 이라 정적 파싱이 동작(2026-07 확인). 다만 잡코리아가 클래스/속성(`data-sentry-component="Title"`, `GI_Read` 경로)을 바꾸면 파서 수정 필요 → `parser_missed` 로그로 감지. Playwright fallback 은 이번 범위 제외(TODO).

## 8. 다음 작업

- 레거시 API deprecated 처리(`jd_router`/`jds_router`/부서 Drive 동기화) → 테이블 삭제 전 호출 제거 확인.
- 테이블 삭제 전 최종 승인 + Alembic cleanup(DEPRECATED 코멘트 → 은퇴 후 DROP 리비전) 준비.
- 잡코리아 collector fallback 고도화(속성 변경 대비 2차 파서), 라이브 dry-run 정기 점검.
- `analysis_jobs` 테이블 도입 검토(작업 상태 조회/재처리).
- 운영 스케줄러 활성화(`apscheduler`) 시 사람인/잡코리아 1시간 주기 등록.
