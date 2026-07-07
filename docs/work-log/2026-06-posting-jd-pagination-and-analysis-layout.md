# 공고/JD·이력서 등록·분석 목록 페이징 + 분석 작업 관리 3컬럼 구조

- **작업 일시**: 2026-06-12
- **작업 목표**: 공고/JD 관리·이력서 등록 공고 목록 + 분석 대기 파일 목록에 백엔드 페이징 추가, 분석 작업 관리를 "부서/팀 → 공고/JD → 분석 대기 파일" 3컬럼 구조로 변경하고 부서/팀을 검색조건으로 적용. **분석/점수/Drive 핵심 로직 불변.**

## 수정 파일
- 백엔드: `app/services/department_access_service.py`(`subtree_department_ids`), `app/services/job_posting_service.py`(`list_postings` 페이징+부서 subtree), `app/services/resume_analysis_db_service.py`(`get_posting_pending_view` 페이징), `app/api/job_postings_router.py`(GET page/size), `app/api/resumes_router.py`(posting-pending page/size).
- 프론트: `app/templates/index.html`, `app/static/app.js`, `app/static/style.css`, 캐시버스트 `v43→v44`.

## 변경 API
- `GET /api/job-postings` — **페이징 응답**으로 변경: `{"items": [...], "total": N, "page": p, "size": s}`. 쿼리 `page`(기본 1)/`size`(기본 20, 최대 200) + `department_id`(해당 부서+**하위 부서 subtree**, 권한 밖 403). total 은 **권한 필터가 적용된 값**. (`GET /search` 는 기존 list 응답 유지 — 경량 선택용)
- `GET /api/resumes/posting-pending/{posting_id}` — `page`/`size` 추가, `{posting_id, total, page, size, pending_count(=total), files:[현재 페이지]}`.
- 권한: ADMIN 전체 / MANAGER 본인+하위(요청 department_id 가 범위 밖이면 403) / VIEWER 조회만·분석 불가. 백엔드 `ensure_department_access` + `get_accessible_department_ids` 로 검증.

## 변경 화면 / JS / CSS
### 1. 공고/JD 관리 · 2. 이력서 등록 목록 페이징
- 테이블 카드 상단: `총 N건`(좌) + 페이지당 표시 select(20/30/50, 우, `.list-head-row` + `.page-size-select`).
- 하단: `[이전] p / N 페이지 [다음]`(기존 `status-pagination` 스타일 재사용).
- 공용 `renderPager(prefix, page, size, total)` 헬퍼로 total/페이지정보/이전·다음 disabled 갱신.
- 기본 size 20, **검색/오늘/초기화/size 변경 시 1페이지부터** 재조회. 초기화는 size 도 20으로. 공고 선택/업로드(이력서 등록)·검색/Enter 기존 동작 유지.

### 3·4. 분석 작업 관리 3컬럼 + 부서/팀 검색조건
- 본문을 `[부서/팀 카드][공고/JD 카드(320px)][분석 대기+실행]` 3컬럼으로(`analysis-split`). 부서/팀 카드는 **이력서 현황 트리 UI 재사용**(`renderDeptTree`/`setupDeptSearch`/전체 부서 버튼), 카드 캡+내부 스크롤(`.analysis-dept-panel`).
- 부서 선택 → `department_id`로 공고 목록 1페이지 재조회 + 선택 공고/대기 초기화(`resetAnalysisSelection`). 상위 부서 선택 시 하위 부서 공고까지(subtree). 전체 부서 = `department_id` 해제. 공고/JD 카드에도 페이징(총 N건/size/이전·다음).

### 5. 분석 대기 파일 페이징
- 대기 파일 카드 상단 `총 N건`(`pendingMeta`) + size select, 하단 이전/다음. **페이지 변경 시 체크박스 초기화**(목록 재렌더). 헤더 전체 선택은 현재 페이지 항목만 선택. 선택 공고 분석 버튼은 전체 대기 건수(total) 기준 활성/비활성.

### 6. 분석 실행 버튼 동작 유지
- 선택 공고/선택 항목/전체(ADMIN 전용, MANAGER 숨김) 분석 모두 유지. 분석 후 현재 부서 조건 유지 + 공고 목록 재조회(`refreshAnalysisPostingCounts`) + 선택 공고 대기 재조회 + 체크 초기화.

## 테스트 결과 (라이브 DB)
- `py_compile`/`node --check`/CSS 균형 통과, 신규 element id 존재, 함수 중복 정의 없음, 라우트 등록 확인.
- list_postings 페이징 응답 `{items,total,page,size}`(total 4), 페이징 미지정 시 list 반환(search 호환), 부서 subtree 필터(D00035→2부서, total 1), pending view 페이징 정상.
- MANAGER 권한범위 total=1, **권한 밖 department_id 요청 → 403** 확인.
- (참고) 페이징 버튼/3컬럼/체크 초기화 등 시각 확인은 서버 재시작 + 브라우저 v44 새로고침 후 사용자 확인 필요.

## 남은 TODO (docs/TODO.md)
- 공고 목록 페이징이 현재 application-level slice(필터 후 전체 빌드 → slice). 공고 수가 매우 커지면 DB-level limit/offset + jd_status 조인 최적화 검토. 분석 대기 페이지 변경 시 선택 유지 옵션(현재는 초기화). 대형 화면 3컬럼 비율 반응형.
