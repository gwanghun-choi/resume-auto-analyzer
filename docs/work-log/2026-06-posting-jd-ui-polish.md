# 공고/JD 중심 UI/UX 정리 + 추천 JD 복구

- **작업 일시**: 2026-06-12
- **작업 목표**: 검색/초기화 버튼 레이아웃 정리, 이력서 현황 부서 트리 높이/스크롤 수정, 상위 부서 클릭 선택, 공고 상세 팝업 카드 분리·버튼 우측 정렬, JD 상세에 **추천 JD** 기능 복구.

## 수정 파일
- `app/api/job_postings_router.py` — `POST /api/job-postings/{id}/jd/recommend` 추가.
- `app/services/job_posting_service.py` — `posting_dept_name()` 헬퍼.
- `app/templates/index.html` — 툴바 버튼 그룹(`toolbar-actions`), 이력서 현황 Excel 버튼을 `view-head-row` 로 이동, 공고 모달 카드 분리(`modal-card`)·추천 JD 버튼.
- `app/static/app.js` — `recommendPostingJd()`, 추천 버튼 wiring/VIEWER 숨김, 부서 트리 상위 선택, 날짜 Enter 검색, clear-selection 보정.
- `app/static/style.css` — `toolbar-actions`, `btn-row.right`, `modal-card`, 이력서 현황 트리 패널 max-height/flex, `tree-group.selected`.

## 변경 API
- **신규** `POST /api/job-postings/{posting_id}/jd/recommend` — 공고명/부서명 기반 OpenAI JD 초안 추천(DB 저장 안 함).
  - 권한: ADMIN 전체 / MANAGER 본인 부서+하위 / VIEWER 403(`ensure_can_manage_posting`).
  - 기존 `jd_recommend_service.recommend_jd`(레거시 `/api/jd/recommend` 와 동일 서비스) 재사용 — MatchingService/점수 산식과 무관.
  - 응답: `{status:"OK", data:{title, required_skills[], preferred_skills[], jd_content}}`. 실패 시 `{status:"ERROR", step, error_message, hint}`.

## 변경 화면 / JS / CSS
1. **검색/초기화 레이아웃**: 공고/JD 관리·이력서 등록·분석·이력서 현황 toolbar 에서 `[공고명 검색][(파일명 검색)][검색][초기화]` 를 `.toolbar-actions`(inline-flex)로 묶어 **항상 같은 줄** 유지(wrap 시에도 분리 안 됨). 공고명/파일명/날짜 input **Enter 검색**.
2. **이력서 현황 Excel**: toolbar → 화면 **우측 상단**(`view-head-row`, [+ 공고 등록] 패턴)으로 이동. 권한/필터 정책 불변.
3. **부서 트리 높이**: `.resume-status-tree-panel` 을 `display:flex; flex-direction:column; max-height: calc(100vh - 230px)` 로 카드 자체를 캡, 헤더/검색은 고정(`flex:0`), `.dept-tree` 만 `flex:1; min-height:0; overflow-y:auto` → **부서 트리로 인한 페이지 전체 스크롤 제거**(트리 내부 스크롤). 우측 테이블은 `align-items:flex-start` 로 독립 높이.
4. **상위 부서 선택**: 트리에서 **부서명 클릭 = 선택(검색조건 적용)**, **화살표 클릭 = 펼치기/접기**(분리). 상위 부서(`tree-group`)도 `.selected` 강조. `기업부설연구소` 같은 상위 조직 선택 가능. 전체 부서 버튼/하위 포함 조회 정책 불변. (공통 컴포넌트라 JD(legacy) 트리에도 동일 적용)
5. **공고 모달**: 공고 기본 정보/JD 상세를 각각 `modal-card` 로 시각 분리. `공고 저장`·`JD 저장` 버튼 우측 정렬(`btn-row.right`). JD 카드 우상단 **[추천 JD]**(JD 상태 badge 옆).
6. **추천 JD 동작**: 클릭 → (기존 입력값 있으면 "추천 JD로 덮어쓰시겠습니까?" confirm) → 추천 API → JD 제목/필수/우대/상세내용 자동 채움. 실제 저장은 사용자가 [JD 저장]. VIEWER 는 버튼 숨김(readonly), 백엔드 403.

## 권한 처리
- 추천 JD: 프론트(VIEWER 숨김) + 백엔드(`ensure_can_manage_posting` → VIEWER/권한 밖 403).
- Excel: 기존 권한/필터 그대로(`_resolve_allowed_dept_ids`).

## 테스트 결과
- `node --check`/`py_compile`/CSS 균형 통과. 신규 element id 존재, 라우트 등록 확인.
- 라이브: `recommend_jd("HR팀","0612 TEST 04")` → required 6 / preferred 4 / description 정상(추천 JD 동작 확인). `posting_dept_name`/`ensure_can_manage_posting` 정상.
- 캐시버스트 `v42`(css/js 동기).
- (참고) 트리 스크롤/모달 레이아웃 등 시각 확인은 브라우저(서버 재시작 + v42)에서 사용자 확인 필요.

## 남은 TODO (docs/TODO.md)
- 추천 JD 프롬프트에 플랫폼/URL/기존 입력값 반영(현재는 공고명+부서명 기반 — 레거시 서비스 재사용). 부서 트리 패널 max-height 상수(230px) 화면별 미세조정.
