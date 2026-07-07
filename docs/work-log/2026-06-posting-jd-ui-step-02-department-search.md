# Step 02 — 공고 등록 부서/팀 검색 UI 개선 (사용자 관리와 동일)

- **작업 일시**: 2026-06-12
- **목표**: 공고 등록 팝업의 부서 검색을 사용자 관리(사용자 상세/수정)의 부서 검색 UI와 동일하게(부서명·부서코드·전체 path/depth 표시, 선택 해제 버튼) 맞추고, 권한 범위를 백엔드에서 보장.

## 변경 API (신규)
- `GET /api/job-postings/dept-search?keyword=` — 권한 범위 부서/팀 검색.
  - 응답: `[{id, name, parent_id, path, is_leaf}]` (사용자 관리 `/api/admin/departments/search` 와 동일 스키마).
  - 권한: **ADMIN 전체 / MANAGER·VIEWER 본인 부서+하위만**(권한 밖 부서는 결과에 노출 안 됨).
  - `app/services/department_access_service.search_accessible_departments()` 신규 — 기존 `search_departments` + `get_accessible_department_ids` 재사용(중복 구현 최소화).

## 변경 화면
- `app/static/app.js`
  - `searchPostingDept()`: 클라이언트 필터(`/api/auth/me/departments`) → **신규 권한범위 API** 호출로 교체. 결과에 `부서명 + (상위 조직) / 부서코드 · 전체 path` 표시.
  - `renderPostingSelectedDept()`: 선택 부서를 `부서명 (부서코드) / 전체 path` + **[선택 해제]** 버튼으로 표시.
  - 사용하지 않게 된 `loadPostingAccessibleDepts()`/`postingAccessibleDepts` 제거.
- `app/templates/index.html` — 공고 팝업의 부서 검색 영역은 기존 `dept-search-row`/`dept-search-results`/`selected-dept-box`(사용자 관리와 동일 클래스) 그대로 사용(HTML 변경 없음).

## 권한 검증
- 프론트 검색은 권한 범위 API 로 제한 + **백엔드 등록 시 `_ensure_can_manage` 재검증**(MANAGER 가 권한 밖 department_id 로 POST → 403).

## 테스트 결과
- 라이브 DB: ADMIN `dept-search 'dx'` → path 포함 7건, MANAGER 범위 검색 6건. 응답에 id/name/path/is_leaf 포함 확인.
- E2E: MANAGER 가 권한 밖 공고 관리 시 403 확인.

## 남은 TODO
- (없음). 향후 사용자 관리/공고 부서검색 공통 컴포넌트화 검토(선택).
