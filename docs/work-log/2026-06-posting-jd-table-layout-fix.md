# 공고/JD 테이블 가독성 개선

- **작업 일시**: 2026-06-12
- **목표**: 공고/JD 관리 목록과 분석 작업 관리의 공고 리스트에서 글자가 잘려 안 보이는 문제 개선.

## (A) 공고/JD 관리 목록 테이블
- `app/templates/index.html` — `view-jobPostings` 테이블에 `data-table-roomy` 클래스 + colgroup 조정:
  공고명 26→**32%**, 부서 16→18%, 플랫폼/상태 10→9%, JD상태 12→11%, 등록일 14→12%, 관리 12→9%.
- `app/static/app.js` `renderPostingsTable` — 공고명/부서 셀을 `cell-filename`(220px 캡) → **`cell-title`**(폭 제한 없이 컬럼 폭 채우고 말줄임 + tooltip).
- `app/static/style.css`
  - `.data-table td.cell-title { max-width: none; font-weight: 500; }`
  - `.data-table-roomy { font-size: 13.5px; }` + `th/td padding: 12px` (행 높이/글자 여유, 공고 목록에만 적용 — 다른 테이블 영향 없음).

## (B) 분석 작업 관리 공고/JD 리스트
- 좁은 좌측 패널(280px) 의 5열 테이블이 대부분 잘리던 문제 → **compact 카드 리스트**로 전환.
- `app/templates/index.html` — `tree-panel(280px)` + `<table>` → `<div class="card analysis-posting-panel">` + `<div id="analysisPostingList" class="posting-card-list">`.
- `app/static/app.js` — `loadAnalysisPostings`/`renderAnalysisPostingsTable` 를 카드 렌더로 변경(공고명 최대 2줄, 부서(코드)·플랫폼 보조 텍스트, JD 상태·대기 건수 badge). 카드 클릭 → 선택/대기 파일 로드.
- `app/static/style.css` — `.analysis-posting-panel { flex: 0 0 340px }`(패널 폭 확대) + `.posting-card-list`/`.posting-card`(.selected)/`.pc-title`(2줄 말줄임)/`.pc-meta`/`.pc-badges`.

## 변경 API
- 없음(표시 레이아웃 변경만).

## 테스트 결과
- `node --check`/CSS 균형 통과, 삭제된 id(`analysisPostingTable*`) 잔존 참조 없음. 캐시버스트 `v41`(css/js 동기).

## 남은 TODO
- 공고명이 매우 긴 경우 카드 2줄 말줄임(현 정책). 필요 시 목록 가상스크롤.
