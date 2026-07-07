# Step 04 — 공고/JD 관리 프론트

- **작업 일시**: 2026-06-12
- **작업 목표**: 좌측 메뉴 "JD 관리" → "공고/JD 관리"로 전환, 목록/검색·필터/등록 팝업/상세+JD 팝업 구현.

## 수정한 파일
- `app/templates/index.html`
  - 메뉴: `JD 관리`(data-view=jd) → **`공고/JD 관리`**(data-view=jobPostings, roles ADMIN,MANAGER,VIEWER)
  - 신규 `view-jobPostings`: 헤더(+공고 등록), 필터(공고명/플랫폼/상태/JD등록), 테이블(공고명·부서·플랫폼·상태·JD상태·등록일·관리)
  - 신규 `postingModalOverlay`: 공고 등록/수정 + JD 섹션
  - 기존 `view-jd`(부서 중심 JD)는 **legacy 로 DOM 유지**(메뉴에서 제거, 주석 표기)
  - 캐시버스트 `v38→v39`
- `app/static/app.js`
  - `SECTION_ROLES.jobPostings`, showView 훅, init `setupJobPostingsUI()`
  - 모듈: `loadJobPostings/renderPostingsTable/openCreatePosting/openEditPosting/savePosting/loadPostingJd/savePostingJd/searchPostingDept` 등
- (CSS 신규 없음 — 기존 `.view-head-row/.status-toolbar/.data-table/.dept-search-*/.modal-footer/.user-notice/.upload-section-title` 재사용)

## 화면 동작
- **목록**: 권한 범위 공고를 테이블로. 플랫폼은 한글 라벨, 상태/JD상태 badge. row 클릭 → 상세/수정 팝업.
- **검색/필터**: 공고명/플랫폼/상태/JD등록(전체·등록완료·미등록) → `GET /api/job-postings?...`
- **공고 등록**(+공고 등록): 공고명, **부서 검색 선택**(=`/api/auth/me/departments` 권한범위 재사용 + 클라 키워드 필터), 플랫폼 select, URL, 상태. 저장 후 같은 팝업이 수정 모드로 전환되어 JD 섹션 노출.
- **상세/JD**: row 클릭 → 공고 필드 채움 + JD 섹션(현재 active JD 로드). JD 미등록이면 [JD 등록], 등록되어 있으면 [JD 수정]. JD 저장 시 목록 JD 상태 갱신.
- **권한(프론트)**: VIEWER 는 [+공고 등록] 숨김 + 팝업 전체 readonly + 저장 버튼 숨김. (백엔드에서도 403 재검증)

## 부서 검색 방식
관리자 부서검색(`/api/admin/departments/search`)은 ADMIN 전용이라, 공고용은 **`/api/auth/me/departments`**(ADMIN 전체 / MANAGER 본인+하위)를 캐시해 클라이언트에서 키워드 필터 → 권한 범위 자동 보장(신규 백엔드 불필요).

## 테스트한 내용
- `node --check`(app.js) 통과, CSS 균형 OK, 재사용 CSS 클래스 존재 확인.
- index.html 에 view/모달/요소 ID 렌더 확인.
- **DB 미가동으로 실제 동작 미검증** → DB 복구 + 서버 재시작 후 사용자 테스트 필요.

## 실패/주의사항
- 서버 재시작 + 브라우저 새 정적(v39) 로드 필요.
- `view-jd`(legacy) 와 그 init 리스너(saveJdBtn/recommendJdBtn 등)는 깨짐 방지 위해 유지. 추후 제거는 영향도 확인 후(TODO).

## 다음 Step TODO
- Step 05~07: 이력서 등록/분석/현황을 공고/JD 기준으로 전환(백엔드 hook + 프론트). 이번 세션은 **무테스트 리스크로 보류** → 상세 계획을 Step 05~07 work-log 와 docs/TODO.md 에 명시.
