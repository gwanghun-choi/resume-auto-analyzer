# Step 05 — 이력서 현황 + 분석 작업 관리 공고 기준 전환

- **작업 일시**: 2026-06-12
- **목표**: 이력서 현황을 공고 기준 조회/필터로, 분석 작업 관리를 공고 리스트 + 체크박스 기반으로 전환. 전체 분석은 ADMIN 전용.

## (A) 이력서 현황
### 변경 화면
- 검색 바에 **공고명 검색**(`statusPostingKeyword`) 추가, 목록에 **공고명 컬럼** 추가(미매핑 데이터는 `-`).
- 상세 팝업 기본 정보에 **공고명/JD명** 표시. 부서/팀 컬럼·파일명 다운로드 유지. 부서 트리 필터는 보조로 유지.
### 변경 API
- `GET /api/resumes/status`, `GET /api/resumes/status/export-excel` — `posting_id`, `posting_keyword` 필터 추가.
  - 응답 목록/상세에 `posting_id` / `posting_title`(+ 상세 `jd_id`) 추가. Excel 에 `공고명` 컬럼 추가.
  - `resume_files JOIN job_postings`(`_name_maps` 에 posting 맵). 권한 부서 필터 유지(Excel 동일 권한).
  - 미매핑(`posting_id IS NULL`) legacy 데이터는 공고명 `-` 로 안전 표시.

## (B) 분석 작업 관리
### 변경 화면
- 부서 트리 → **공고 리스트 테이블**(공고명/부서/플랫폼/JD상태/**분석 대기 건수**) + 검색 바(`[오늘][등록일][플랫폼][공고명][검색][초기화]`).
- 공고 선택 → 우측 **분석 대기 파일 테이블**(체크박스/공고명/부서/파일명/업로드시간).
- 분석 실행 버튼: **선택 공고 분석 / 선택 항목 분석 / 전체 분석(ADMIN 전용 — 비ADMIN 숨김)**.
- JS: `loadAnalysisPostings`/`renderAnalysisPostingsTable`/`selectAnalysisPosting`/`loadPostingPending`/`renderPostingPending`/`runPostingAnalyze`/`runSelectedAnalyze`(공고기준)/`runAllAnalyze`(ADMIN)/`setupAnalysisJobsUI`. 부서 트리 기반 함수 제거.
### 변경 API
- `GET /api/resumes/posting-pending-counts` (신규) — 권한 범위 공고별 대기 건수 맵.
- `GET /api/resumes/posting-pending/{posting_id}` (신규) — 공고 분석 대기 파일 목록(조회 권한 검증).
- `POST /api/resumes/analyze-posting` (신규) — 선택 공고 분석(VIEWER/권한 밖 403).
- `POST /api/resumes/analyze-selected` — **공고 기준 재작성**: 각 파일 `posting_id` 의 active JD 로 분석, posting 단위 권한 재검증, 공고 미매핑 파일 차단.
- `POST /api/resumes/analyze-all` — **ADMIN 전용**(MANAGER/VIEWER 403), 공고 기준 전체.
- 분석 로직: `resume_file.posting_id → job_posting_jds(active)` JD 로 `MatchingService`(산식/프롬프트 불변), 공고 completed/failed 폴더로 이동, `analysis_results.posting_id/jd_id/jd_snapshot` 저장.
  - `ResumeAnalysisService.analyze_posting()` + 공용 `_process_targets()`(부서/공고 공용), `resume_analysis_db_service`(posting 컨텍스트/대기/저장).

## 권한 검증 (백엔드 강제)
- 조회: ADMIN 전체 / MANAGER·VIEWER 본인 부서+하위.
- 분석 실행: ADMIN 전체 / MANAGER 본인 부서+하위 / VIEWER 403. **전체 분석은 ADMIN 만**(API 403 재검증, 프론트 버튼 숨김).

## 테스트 결과
- 라이브 DB 스모크: `status_list(posting_keyword)`, `posting_pending_counts`, `get_posting_analysis_context` 정상. `node --check`/`py_compile` 통과.
- E2E: 공고 분석 컨텍스트(JD+completed/failed 폴더) 정상.
- (참고) HTTP 세션 로그인 기반 UI 시나리오는 사용자 측 수동 테스트 필요(서버 재시작 + 정적 v40 새로고침).

## 남은 TODO
- 추천 결과 관리 화면 공고 기준화, 분석 비동기 큐 전환, 1공고 N JD, 공고별 감사 로그. (`docs/TODO.md`)
