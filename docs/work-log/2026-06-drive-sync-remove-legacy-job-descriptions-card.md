# Drive 설정/동기화 화면에서 legacy job_descriptions 카드 제거

- **작업 일시**: 2026-06-12
- **작업 목표**: 공고/JD 중심 전환에 따라 `관리자 > Drive 설정/동기화 > 부서 DB 동기화 (resume_ai)` 영역의 **`job_descriptions` 카드**와 그 detail(부서별 JD 등록 현황 팝업)/카운트 로직을 제거. **부서/Drive 폴더 동기화 기능은 유지.**

## 수정 파일
- `app/db/health.py` — `_COUNT_TABLES` 에서 `job_descriptions` 제외(주석/docstring 정리).
- `app/api/db_router.py` — `/api/db/counts` docstring "6개 테이블" → "주요 테이블".
- `app/api/jds_router.py` — `GET /api/jds/status-by-department` 엔드포인트 제거(카드 클릭 팝업 전용이었음). JD CRUD(`/api/jds`, `/active`, `/{jd_id}`)는 legacy 로 유지.
- `app/services/jd_db_service.py` — `status_by_department()` 함수 + 그로 인해 orphan 된 `Department` import 제거.
- `app/static/app.js` — `loadDeptDbCounts` 의 job_descriptions 카드/클릭 핸들러 제거, 팝업 함수(`openJdStatusModal`/`closeJdStatusModal`/`jdStatusBadge`/`renderJdStatusTable`/`goToJdManageWithDepartment`) 제거, init 의 jdStatusModal 와이어링 + ESC 핸들러의 `closeJdStatusModal()` 제거.
- `app/templates/index.html` — `jdStatusModalOverlay` 팝업 DOM 제거. 캐시버스트 `v45→v46`.
- `app/static/style.css` — `.stat-card.clickable`, `.jd-status-table*`, `.badge-muted` 제거(주석으로 정리 표기). `.stat-row`/`.stat-card` 는 남은 2개 카드용으로 유지.

## 제거한 화면 요소
- 부서 DB 동기화 영역의 **`job_descriptions` 카드**(클릭 시 열리던 "부서별 JD 등록 현황" 팝업 포함).
- 변경 후 카드: `departments`, `dept_drive_folders` 2개만 표시(레이아웃은 `.stat-row` flex 로 자연 정렬).
- 안내 문구(부서 원천/조회 기준/Drive 폴더 매핑 기준)는 그대로 유지.

## 제거/유지한 API 응답 필드
- 제거: `/api/db/counts` 응답 `counts.job_descriptions` (전체 검색 결과 소비처는 제거한 카드뿐이라 안전 제거). 잔여 keys: departments, dept_drive_folders, resume_upload_batches, resume_files, resume_analysis_results.
- 제거: `GET /api/jds/status-by-department`(팝업 전용, 다른 화면 사용처 없음).
- 유지: `/api/db/counts`(필드만 축소), `/api/jds` JD CRUD(legacy), `/api/db/health|tables|table-comments`.

## 제거한 JS 렌더링/이벤트
- `loadDeptDbCounts` 의 `jdCountCard` 렌더 + click → 팝업 오픈 이벤트.
- 팝업 렌더/이벤트 함수 전체 + 모달 닫기/overlay/ESC 이벤트.

## 유지한 기능 (영향 없음 — 확인 완료)
- 부서 JSON 검증 / Drive 에 부서 JSON 저장 / Drive config → DB 부서 동기화 / departments·dept_drive_folders 카운트 / 최근 동기화 상태 / Drive 바로가기 / 관리자 메뉴·권한 / Google Drive 인증·토큰 / dept_config.json 연동.
- 공고/JD 관리·이력서 등록·이력서 현황·분석 작업 관리 영향 없음(job_descriptions 카드/팝업과 무관).

## job_descriptions 잔여 참조 (검색 결과)
- 정적 자산(app.js/index.html/style.css): **0건**(주석 제외).
- 백엔드: `job_descriptions` 테이블 모델/`jd_service`/`jd_db_service` CRUD/`resume_analysis_service` 의 legacy 부서 기준 분석 fallback 은 **의도적으로 유지**(이번 범위 아님 — 공고/JD 전환 완료 시 별도 정리 TODO).

## 테스트 결과
- `py_compile`(health/db_router/jds_router/jd_db_service) + `node --check`(app.js) + CSS 균형 통과.
- 제거 대상 식별자(jdStatusModal/jdCountCard/openJdStatusModal/…/jd-status-table/badge-muted/c.job_descriptions) 잔존 참조 **0**.
- 라이브: `table_counts()` 에 job_descriptions 없음(departments/dept_drive_folders 포함), `/api/jds/status-by-department` 라우트 제거 확인, 앱 import 정상.
- (참고) 화면/Console/Network 시각 확인은 서버 재시작 + 브라우저 v46 새로고침 후 사용자 확인.

## 남은 TODO (docs/TODO.md)
- legacy JD 시스템(job_descriptions 테이블·jds_router CRUD·jd_service·부서 기준 분석 fallback) 전체 정리 여부 결정(공고/JD 전환 완료 후).
