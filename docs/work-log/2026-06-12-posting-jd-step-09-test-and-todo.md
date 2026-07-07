# Step 09 — 정적 점검 및 남은 TODO

- **작업 일시**: 2026-06-12
- **환경 제약**: **DB 미가동** → 서버 기동/DB 연결/curl/API 호출/docker 실행 금지. **정적 검증만** 수행(import 는 engine lazy 라 DB 쿼리 미발생).

## 정적 검증 결과 (이번 세션)
| 항목 | 방법 | 결과 |
|---|---|---|
| 백엔드 컴파일 | `py_compile` (모델/스키마/서비스/라우터/main) | 통과 |
| 프론트 문법 | `node --check app/static/app.js` | 통과 |
| CSS 균형 | `{`/`}` 카운트 | 일치 |
| 모델 등록 | `Base.metadata` 에 `job_postings`/`job_posting_jds` | 등록됨 |
| 컬럼 매핑 | `ResumeFile.posting_id`, `ResumeAnalysisResult.jd_snapshot` | 매핑됨 |
| 라우트 | `/api/job-postings*` | 9개 등록 |
| 캐시버스트 | index.html css/js | `v=20260610-39` 동기 |

## DB 복구 후 사용자 테스트 시나리오 (수동)
1. **SQL 적용**: `docs/sql/2026-06-12-posting-jd.sql` 실행 → 테이블/컬럼/인덱스 생성 확인.
2. 서버 재시작 + 브라우저 정적 새로고침(v39).
3. **메뉴**: 좌측 "공고/JD 관리" 노출(ADMIN/MANAGER/VIEWER).
4. **공고 등록**(ADMIN/MANAGER): +공고 등록 → 부서 검색 선택 → 저장 → 수정 모드 전환 → JD 등록 → 목록 "JD 등록 완료".
5. **권한**:
   - VIEWER: +공고 등록 숨김, 팝업 readonly, 저장 버튼 없음. API 직접 POST → **403**.
   - MANAGER: 본인+하위 부서만. 권한 밖 department_id 로 POST/PUT → **403**.
   - ADMIN: 전체.
6. **필터/검색**: 공고명/플랫폼/상태/JD등록 필터, `/search` 경량 검색.
7. **미매핑 방어**: `posting_id IS NULL` 기존 데이터에서 기존 부서 화면 정상 동작(공고명 "-").

## 남은 TODO (요약 — 상세는 docs/TODO.md)
- **DB SQL 적용**(선결).
- **Step 05~07**: 이력서 등록/분석/현황 공고 전환(통합 지점은 Step05 PLAN 문서).
- 공고별 Drive 폴더 동기화, `audit_logs` 서비스, 1공고 N JD, 플랫폼 자동 연동, legacy `view-jd` 정리.

## 미수정 보증
- `resume_ai` 외 schema(public/타 업무/타 서비스) **미접근/미변경**.
- `users`/`departments`/`role_code`/Google·OpenAI 설정/MatchingService 산식/추천 기준/threshold — **불변**.
- DB 는 **연결하지 않음**(SQL 은 파일로만 작성, 실행은 사용자 몫).
