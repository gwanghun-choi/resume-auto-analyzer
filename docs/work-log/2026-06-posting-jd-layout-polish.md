# 공고/JD 중심 화면 레이아웃/가독성 보정 (필터 한 줄·트리 높이·분석 width)

- **작업 일시**: 2026-06-12
- **작업 목표**: 검색 필터 한 줄 정리, 이력서 현황 부서 트리로 인한 페이지 스크롤 제거, 분석 작업 관리 본문 width 확대. **기능/DB/분석 로직 변경 없음 — HTML/CSS만.**

## 수정 파일
- `app/static/style.css` — 툴바 input/select width, 이력서 현황 트리 카드 overflow/높이, 분석 레이아웃 width.
- `app/templates/index.html` — 분석 split 에 `analysis-split` 클래스 추가, 캐시버스트 `v42→v43`.

## 변경 화면 / CSS
### 1. 검색 필터 한 줄 정리 (공고/JD 관리·이력서 등록·이력서 현황·분석 공통 — `.status-toolbar`)
- select 폭 `145px→128px`(min 120), 날짜 input `150px→138px`, 텍스트 검색 input `200px→180px`(min 150)로 축소 → 일반 데스크톱에서 `[오늘][날짜~날짜][플랫폼][상태][JD등록][공고명 검색][검색][초기화]`가 한 줄에 들어옴.
- 검색/초기화(+검색 input)는 기존 `.toolbar-actions`(inline-flex, `margin-left:auto`)로 묶여 **항상 같은 줄** 유지(좁으면 그룹 단위 wrap). Enter 검색/오늘/초기화/Excel 위치 등 기존 동작 그대로.

### 2. 이력서 현황 부서/팀 트리 높이·스크롤
- `.resume-status-tree-panel` 에 **`overflow: hidden`** 추가 + `height:auto; display:flex; flex-direction:column; max-height: calc(100vh - 240px)`.
  - 카드 자체를 뷰포트로 캡하고 overflow:hidden 으로 flex 자식(트리)이 카드 밖으로 넘쳐 body 를 미는 것을 차단 → **전체 페이지 세로 스크롤 제거**.
  - 헤더/검색은 `flex:0`(상단 고정), `.dept-tree` 만 `flex:1; min-height:0; overflow-y:auto`(트리 내부 스크롤).
- 우측 테이블은 `.resume-status-content { align-items: flex-start }`(기존)로 좌측 트리 높이에 종속되지 않음. 전체 부서/검색/상위 부서 선택/펼치기 기능 모두 유지.

### 3. 분석 작업 관리 width
- 분석 본문 `<div class="split">` → `class="split analysis-split"`.
- `.analysis-split { width:100% }`, `.analysis-split .analysis-posting-panel { flex: 0 0 400px }`(좌측 공고/JD 340→400px), `.analysis-split .form-panel { max-width: none }`(우측 대기/실행 카드의 820px 상한 해제 → 남은 폭 전부 사용).
- 상단 검색 카드(전체 폭)와 본문 좌우 라인이 맞고, 공고명이 덜 잘림(공고 카드 2줄 말줄임은 기존 유지).

## 기존 기능 영향
- 없음(레이아웃/폭만 조정). 검색/Enter/오늘/초기화/Excel, 공고·JD 등록/수정, 추천 JD, 업로드/현황/분석(선택 공고·선택 항목·전체(ADMIN)), 부서 트리 선택/펼치기 모두 그대로.

## 테스트 결과
- CSS 균형 OK, `node --check` OK(JS 미변경), `analysis-split` 적용 확인, 캐시버스트 `v43` css/js 동기.
- (참고) 한 줄 정렬/트리 스크롤/분석 폭은 브라우저(서버 재시작 + v43 새로고침)에서 시각 확인 필요.

## 남은 TODO (docs/TODO.md)
- 트리 패널 `max-height: calc(100vh - 240px)` 상수의 화면별 미세조정(작은 화면). 초대형 모니터에서 분석 좌측 400px 비율 재검토. 매우 좁은 화면에서 toolbar 2줄 wrap 시 그룹 정렬 점검.
