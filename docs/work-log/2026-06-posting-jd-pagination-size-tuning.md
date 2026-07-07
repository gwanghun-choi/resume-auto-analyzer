# 페이징 UI 보정: 분석 공고 목록 5개 고정 + 이력서 현황 size select 추가

- **작업 일시**: 2026-06-12
- **작업 목표**: ① 분석 작업 관리 > 공고/JD 목록의 page size select 제거 + 한 페이지 5개 고정, ② 이력서 현황 목록에 20/30/50 page size select 추가. **백엔드 로직 변경 없음(프론트 size 연동만).**

## 수정 파일
- `app/templates/index.html` — 분석 공고/JD 카드의 size select 제거, 이력서 현황 테이블 카드 상단에 `list-head-row`(총 N건 + size select) 추가. 캐시버스트 `v44→v45`.
- `app/static/app.js` — 분석 공고 size=5 고정 + size select 와이어링 제거, 이력서 현황 `statusPageSize` let 전환 + size select 연동.

## 변경 화면 / JS
### 1. 분석 작업 관리 > 공고/JD 목록 (5개 고정)
- 공고/JD 카드 상단 `list-head-row` 에서 `analysisPostingSizeSelect`(20개씩 select) **제거**(총 N건 표시는 유지).
- JS: `analysisPostingSize = 5` 고정. `setupAnalysisJobsUI` 에서 size select change 리스너 + 초기화의 size 재설정 코드 제거. 이전/다음 페이지네이션은 5개 기준 유지.
- 검색/부서 선택/초기화 시 `page=1, size=5` 로 재조회(기존 `search()`/`onAnalysisDeptSelected` 가 `analysisPostingPage=1` 처리). 공고 선택 → 분석 대기 조회 등 기존 동작 유지.

### 2. 이력서 현황 목록 (20/30/50 select)
- 테이블 카드 상단을 `list-head-row` 로: 왼쪽 `총 N건`(`statusListMeta`), 오른쪽 `statusSizeSelect`(20/30/50, 기본 20).
- JS: `const statusPageSize` → `let statusPageSize`. size select change → `statusPageSize` 갱신 + `statusPage=1` + 재조회. 초기화 시 size=20 으로 리셋. 이전/다음은 선택 size 기준 동작.
- **API 연동**: 이력서 현황은 이미 `GET /api/resumes/status?...&page&size` 백엔드 페이징 사용 중 → 프론트에서 `size`만 select 값으로 전달(프론트 slice 아님). 응답 `{total, page, size, items}` 그대로. total 은 기존대로 **권한 필터 적용값**(ADMIN 전체 / MANAGER·VIEWER 본인+하위). Excel 다운로드는 page/size 무관하게 현재 검색 조건 전체(`buildStatusFilterParams`) 유지.

## 기존 기능 영향
- 공고/JD 관리·이력서 등록 page size select(20/30/50)는 **그대로 유지**(이 작업과 무관).
- 분석 검색/부서 필터/공고 선택/분석 실행(선택 공고/선택 항목/전체 ADMIN), 이력서 현황 검색/초기화/오늘/Excel/상세 팝업/다운로드 모두 유지.

## 테스트 결과
- `node --check` OK, `analysisPostingSizeSelect` 잔존 참조 0(html/js), `statusSizeSelect` 존재(html 1, js 2: change+reset), `analysisPostingSize=5`/`let statusPageSize=20` 확인. CSS 변경 없음(기존 `.list-head-row`/`.page-size-select` 재사용). 캐시버스트 v45 동기.
- (참고) size 변경/페이지네이션 시각 동작은 서버 재시작 + 브라우저 v45 새로고침 후 사용자 확인 필요.

## 남은 TODO (docs/TODO.md)
- 분석 공고 목록 5개 고정값을 상수/설정으로 분리(추후 조정 대비). 이력서 현황 size 선택을 세션에 기억(새로고침 후 유지) 검토.
