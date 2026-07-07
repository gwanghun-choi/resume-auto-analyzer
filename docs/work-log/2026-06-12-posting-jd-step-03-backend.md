# Step 03 — 공고/JD 백엔드 구현

- **작업 일시**: 2026-06-12
- **작업 목표**: 공고/JD CRUD + JD 등록/수정 API와 권한 검증을 구현(부서 권한 helper 재사용).

## 생성한 파일
- `app/schemas/job_posting_schema.py` — Posting/JD 요청·응답 스키마
- `app/services/job_posting_service.py` — 공고/JD 서비스(권한/CRUD/JD upsert)
- `app/api/job_postings_router.py` — `/api/job-postings` 라우터

## 수정한 파일
- `app/main.py` — `job_postings_router` 등록

## 추가한 API (총 9개, 모두 로그인 필수)
| Method | Path | 설명 |
|---|---|---|
| GET | `/api/job-postings` | 목록(키워드/부서/플랫폼/상태/JD상태 필터, 권한 범위) |
| GET | `/api/job-postings/search?keyword=` | 공고 선택용 경량 검색 |
| GET | `/api/job-postings/{posting_id}` | 상세 |
| POST | `/api/job-postings` | 공고 등록 |
| PUT | `/api/job-postings/{posting_id}` | 공고 수정 |
| PATCH | `/api/job-postings/{posting_id}/status` | 상태 변경 |
| GET | `/api/job-postings/{posting_id}/jd` | active JD 조회(`{"jd": null}`=미등록) |
| POST | `/api/job-postings/{posting_id}/jd` | JD 등록 |
| PUT | `/api/job-postings/{posting_id}/jd` | JD 수정 |

## 권한 검증 방식 (백엔드)
- **조회**(목록/상세/JD조회/검색): `department_access_service.ensure_department_access` / `get_accessible_department_ids` → ADMIN 전체, MANAGER·VIEWER 본인 부서+하위만(권한 밖 403). VIEWER 조회 허용.
- **등록/수정**(공고/JD/상태): `_ensure_can_manage` → **VIEWER/기타 403**, MANAGER 는 대상 부서가 본인 범위(get_accessible_department_ids)일 때만. 부서 변경 시 새 부서도 재검증.
- 프론트 숨김과 무관하게 **백엔드에서 검증** → 권한 밖 department_id/posting_id 직접 호출 시 403.

## 핵심 동작
- **1공고 = 1 active JD**: `upsert_jd` 가 기존 active JD를 `is_active=false` 처리 후 새 active JD insert (DB unique 없음).
- 응답에 `department_name`/`department_path`(부서 path), `platform_label`(사람인/잡코리아/원티드/기타), `has_jd`/`jd_status`(JD 미등록/JD 등록 완료) 계산 포함.
- 플랫폼/상태 값 검증(SARAMIN/JOBKOREA/WANTED/ETC, DRAFT/OPEN/CLOSED/INACTIVE), 부서 존재 검증(404).
- 신규 모델 created_at/updated_at server_default → insert NULL 미발생.

## 테스트한 내용
- `py_compile`(스키마/서비스/라우터/main) 통과.
- 앱 import 후 라우트 테이블에 9개 `/api/job-postings*` 등록 확인(DB 쿼리 없음).
- 런타임/권한 동작은 **DB 미가동으로 미검증** → DB 복구 후 사용자 테스트 필요.

## 실패/주의사항
- `job_posting_service` 는 주입된 `db` Session 사용(admin_user_service 스타일). 라우터에서 `Depends(get_db)` 주입.
- 서버 **재시작** 해야 새 라우트 반영.

## 다음 Step TODO
- Step 04: 프론트 "공고/JD 관리" 화면(메뉴 변경, 목록, 등록 팝업, 상세/JD 팝업, 부서 검색, 플랫폼 select, JD 상태).
