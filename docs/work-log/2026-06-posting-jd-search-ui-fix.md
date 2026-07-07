# 공고/JD 관리 검색 영역 UI 정리 + Enter 검색

- **작업 일시**: 2026-06-12
- **목표**: 공고명 검색 input 이 필터 아래로 길게 내려가던 문제를 고쳐 한 줄로 정리하고, 검색 input/날짜에서 Enter 검색 지원.

## 원인
- 전역 CSS `input[type="text"] { width: 100% }`(style.css 361행) 때문에, toolbar 의 공고명 검색 input 이 100% 폭으로 늘어나 **자기 줄로 wrap** 됨. (statusKeyword 만 별도 width 규칙이 있었음)

## 변경 화면
- `app/static/style.css`
  - `.status-toolbar input[type="text"] { width: 200px; min-width: 160px; }` 추가 → 모든 toolbar 텍스트 검색 input(공고명/파일명/공고명 검색 등)이 compact 하게 **검색/초기화 버튼과 같은 줄** 유지.
- `app/static/app.js`
  - `wireEnterSearch(ids, fn)` 헬퍼 추가 — 지정 input 에서 Enter 시 검색 실행.
  - 공고/JD 관리·이력서 등록·분석 작업 관리 toolbar 에 적용: 공고명 검색 + 등록일 시작/종료 input 에서 Enter → 검색.

## 배치
`[오늘] [등록일] [시작일] ~ [종료일] [플랫폼] [상태] [JD 등록] [공고명 검색] [검색] [초기화]` (좁으면 wrap, 공고명+검색+초기화는 같은 줄). 초기화 = 날짜/플랫폼/상태/JD등록/공고명 모두 초기화. 오늘 = 시작=종료=오늘 후 검색.

## 변경 API
- 없음(기존 `GET /api/job-postings` 필터 `keyword/date_from/date_to/platform_code/status/jd_status` 백엔드 적용 — 프론트 전용 필터 아님).

## 테스트 결과
- `node --check`/CSS 균형 통과. toolbar 텍스트 input 폭 규칙이 전역 100% 보다 우선(specificity) 적용됨 확인.

## 남은 TODO
- (없음). 매우 좁은 화면에서 2줄 wrap 은 의도된 동작.
