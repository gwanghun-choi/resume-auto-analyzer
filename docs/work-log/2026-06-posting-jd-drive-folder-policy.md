# 공고 Drive 폴더 정책 변경 (생성 시점·구조)

- **작업 일시**: 2026-06-12
- **목표**: ① 공고 Drive 폴더 생성 시점을 "공고 등록" → "JD 등록 완료" 로 이동, ② 폴더 구조에서 부서 폴더 제거(공고명 기준 바로 생성).

## 변경 Drive 정책
### 생성 시점
- **공고 등록(`POST /api/job-postings`)**: Drive 폴더 **생성 안 함**. DB 공고만 저장(JD 미등록 상태).
- **JD 저장(`POST`/`PUT /api/job-postings/{id}/jd`)**: JD 저장 성공 시, 공고에 폴더가 없으면 그 시점에 생성.
  - **멱등**: `job_postings.drive_inbox_folder_id` 가 이미 있으면 재생성하지 않음. JD 수정 시 기존 폴더 그대로 사용.
  - **트랜잭션 일관성**: JD 저장 + Drive 폴더 생성은 한 트랜잭션 → **Drive 생성 실패 시 JD 저장도 롤백**(실패 통지).

### 폴더 구조 (부서 폴더 제거)
```
resume-demo-root / inbox     / {JP000001_공고명}
resume-demo-root / completed / {JP000001_공고명}
resume-demo-root / failed    / {JP000001_공고명}
```
- 기존 `postings/{부서id_부서명}/{공고}/...` 구조는 **더 이상 생성하지 않음**. 기존 폴더는 **삭제하지 않음**(legacy 유지).
- 폴더명: `JP{id:06d}_{공고명}`, 특수문자 `_` 치환 + 길이 100자 제한.
- `job_postings.drive_folder_id` 는 단일 상위 폴더가 없으므로 `NULL`(컬럼은 유지). inbox/completed/failed folder id 는 각각 저장.

## 수정 파일
- `app/services/job_posting_drive_service.py` — `ensure_posting_folders(drive, posting_id, title)` 구조 변경(부서 폴더 제거, 길이 제한, `posting_folder_name` 헬퍼).
- `app/services/job_posting_service.py` — `create_posting` 에서 Drive 생성 제거. `upsert_jd(..., drive_factory=None)` 에 폴더 생성(멱등) 추가.
- `app/api/job_postings_router.py` — `POST /api/job-postings` Drive 인증 제거. `POST/PUT /{id}/jd` → `build_authenticated_drive` 주입(폴더 없을 때만 인증), 실패 시 503/502.

## 변경 API (동작 변화)
- `POST /api/job-postings` — Drive 폴더 미생성.
- `POST`/`PUT /api/job-postings/{id}/jd` — JD 저장 + (폴더 없으면) Drive 폴더 생성. Drive 인증 실패 503, 폴더 생성 실패 502(JD 저장 롤백).

## 업로드/분석 연동
- 업로드는 active JD 가 있어야 하므로(= 폴더 생성 완료), 공고 `drive_inbox_folder_id` 로 업로드. 분석 성공/실패 시 공고 `drive_completed_folder_id`/`drive_failed_folder_id` 로 이동(이미 공고 기준). `posting_id` 없는 legacy 는 기존 로직.

## 테스트 결과 (라이브 DB+Drive)
1. 공고 등록 후 `drive_*_folder_id` 모두 NULL(미생성) ✓
2. JD 저장 후 `inbox|completed|failed/JP000004_공고명` 생성 + folder id 저장, `drive_folder_id` NULL ✓
3. JD 수정 후 폴더 id 동일(멱등, 중복 생성 없음) ✓
- 테스트 폴더는 생성 후 휴지통 정리.

## 남은 TODO (docs/TODO.md)
- 기존 `postings/{부서}/...` 구조 정리/마이그레이션, Drive 폴더 재생성/복구 버튼, JD 저장 성공 후 Drive 실패 재시도 UX, 공고명 변경 시 폴더명 변경 정책.
