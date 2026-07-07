# Step 03 — 공고 등록 시 Google Drive 공고 폴더 생성

- **작업 일시**: 2026-06-12
- **목표**: 공고 등록 성공 시 Google Drive 에 공고별 폴더(inbox/completed/failed)를 생성하고 folder id 를 `job_postings` 에 저장. 기존 Drive 인증/부서 동기화는 그대로 유지.

## Drive 구조
```
resume-demo-root / postings / {부서id_부서명} / {JP000001_공고명} / inbox|completed|failed
```
- 폴더명 특수문자(`/ \ : * ? " < > |`)는 `sanitize_folder_name`(부서 동기화 재사용)으로 `_` 치환.
- 공고 코드: `JP{id:06d}` (예: `JP000002`).

## 변경/신규 파일
- `app/services/job_posting_drive_service.py` (신규) — `ensure_posting_folders(drive, posting_id, title, department_id, dept_name)`:
  `ensure_project_folders()`(기존, root+inbox/... 보장) → `postings` → `{부서}` → `{공고}` → inbox/completed/failed 생성, folder id 반환.
- `app/services/google_drive_service.py` — `build_authenticated_drive()` 추가(기존 authenticate/save_token/build_drive 재사용 래퍼, **새 인증 로직 아님**).
- `app/services/job_posting_service.create_posting(db, user, data, drive=None)`:
  insert → `flush()`(id 확보) → Drive 폴더 생성 → `drive_*_folder_id` 저장 → `commit()`.
  **Drive 폴더 생성 실패 시 `rollback()` → 공고 등록도 취소**(트랜잭션 일관성, 사용자에게 실패 통지).
- `app/api/job_postings_router.py` `POST /api/job-postings`: 권한 검증 후 `build_authenticated_drive()` 로 인증된 drive 주입. Drive 인증 실패 503, 폴더 생성 실패 502.
- DB 컬럼 `job_postings.drive_folder_id / drive_inbox_folder_id / drive_completed_folder_id / drive_failed_folder_id` (이미 `docs/sql/2026-06-12-posting-jd.sql` 에 포함, 적용 완료).

## 보안/제약 준수
- credentials.json / token.json / .env 미변경. 인증 로직 신규 작성 없음(기존 재사용).
- resume_ai 스키마만 변경.

## 감사 로그
- `audit_logs` 테이블/인프라가 현재 없어 본 단계에서는 미적용(선택 사항). → `docs/TODO.md` 에 누적.

## 테스트 결과
- 라이브 Drive: 인증 OK, `postings/{부서}/JPxxxxxx_공고명/inbox|completed|failed` 생성 + 폴더명 sanitize(`/ : *` → `_`) 확인 후 테스트 폴더 휴지통 정리.
- E2E: `create_posting(drive=...)` → 4개 folder id 저장 확인, 정리(공고 삭제 + 폴더 trash).

## 남은 TODO
- 공고 폴더 재동기화/이름변경 기능(현재 생성만), `audit_logs` 서비스 추가 시 공고 등록/폴더 생성 이벤트 기록.
