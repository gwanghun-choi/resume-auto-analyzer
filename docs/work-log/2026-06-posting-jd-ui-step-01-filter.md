# Step 01 — 공고/JD 관리 검색 영역 개선 (필터 백엔드 포함)

- **작업 일시**: 2026-06-12
- **목표**: 공고/JD 관리 검색 바를 이력서 현황 패턴(한 줄 컴팩트)으로 재배치하고, 오늘 버튼·등록일 범위 검색을 추가. 모든 필터는 백엔드에서 적용.

## 변경 화면
- `app/templates/index.html` — `view-jobPostings` 검색 toolbar 재구성:
  `[오늘] [등록일 시작]~[등록일 종료] [플랫폼] [상태] [JD 등록] [공고명 검색] [검색] [초기화]`
  - 공고명 검색 input 을 검색 버튼 옆으로 이동, `postingTodayBtn` / `postingDateFrom` / `postingDateTo` 추가.
  - JD 등록 옵션값을 `REGISTERED` / `NOT_REGISTERED` 로 정렬.
- `app/static/app.js`
  - `loadJobPostings()`: `date_from`/`date_to` 파라미터 추가.
  - `setupJobPostingsUI()`: 오늘 버튼(시작=종료=오늘 후 검색) + 초기화에 날짜 포함. 공용 `todayIso()` 추가.

## 변경 API
- `GET /api/job-postings` — 쿼리 파라미터 추가: `date_from`, `date_to`(YYYY-MM-DD). `jd_status` = `ALL`/`REGISTERED`/`NOT_REGISTERED`(`NONE` 하위호환).
  - `app/api/job_postings_router.py`, `app/services/job_posting_service.list_postings()` 에서 **백엔드 필터** 적용(프론트 필터 아님).
  - 권한 필터는 기존 그대로: ADMIN 전체 / MANAGER·VIEWER 본인 부서+하위.

## 테스트 결과
- `node --check` 통과, 라이브 DB 스모크: `list_postings(date_from/date_to, jd_status=ALL)` 정상 동작 확인.
- 잘못된 날짜 형식 → 400.

## 남은 TODO
- (없음 — 본 단계 범위 완료). 플랫폼/상태 옵션은 기존 코드 유지.
