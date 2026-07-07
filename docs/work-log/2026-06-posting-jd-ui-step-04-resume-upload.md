# Step 04 — 이력서 등록 화면을 공고 리스트 기반으로 전환

- **작업 일시**: 2026-06-12
- **목표**: 부서 선택 → 업로드 방식을 폐기하고, 공고 리스트에서 공고를 선택해 해당 공고에 업로드하는 방식으로 전환.

## 변경 화면 (`app/templates/index.html`, `app/static/app.js`)
- `view-resume`: 좌측 부서 트리 → **공고 리스트 테이블 + 검색 바**로 교체.
  - 검색 바: `[오늘] [등록일 시작]~[등록일 종료] [플랫폼] [상태] [JD 등록] [공고명 검색] [검색] [초기화]`.
  - 테이블 컬럼: 공고명/JD명 · 부서/팀 · 플랫폼 · 상태 · JD 상태 · 등록일 · **업로드**.
  - JD 등록 완료 공고만 [업로드] 활성. JD 미등록은 disabled + 안내 title.
  - [업로드] 클릭 → 하단 **업로드 패널**(공고명 표시 + 파일 선택 + 업로드/닫기 + 결과/실패) 노출.
- JS: `loadResumePostings` / `renderResumePostingsTable` / `openResumeUpload` / `closeResumeUpload` / `uploadResumesToDrive`(공고 기준) / `setupResumeUI` / 공용 `buildPostingFilterParams`.
- 기존 부서 트리 업로드 UI(`onResumeTeamSelected`, `resumeEmpty/resumeWork`)는 제거(공고 기준으로 흡수). 부서 동기화/Drive config 연동 자체는 유지.

## 변경 API
- `POST /api/resumes/upload-to-drive` — 폼 파라미터 **`posting_id` 추가**(공고 기준).
  - 권한: `ensure_can_manage_posting`(ADMIN 전체 / MANAGER 본인 부서+하위 / VIEWER 403).
  - active JD 없으면 차단(`posting_jd_required`), 공고 inbox 폴더 없으면 차단.
  - 저장: `resume_files.posting_id` / `jd_id` 저장, **`dept_id = posting.department_id` 복사 저장**, 업로드는 **공고 `drive_inbox_folder_id`** 로.
  - `dept_id` 폼 파라미터(legacy 부서 업로드)는 호환 위해 유지(주 흐름 아님).
- 관련: `app/services/resume_drive_upload_service.upload(..., inbox_entry, posting_id, jd_id)`, `resume_upload_db_service.save_upload`(posting_id/jd_id 기록).

## 테스트 결과
- E2E: 공고 생성 → JD 등록 → 업로드 컨텍스트(권한/JD/inbox 폴더) 정상. `node --check` 통과.
- 업로드 결과 UI(기존 깔끔한 결과 화면) 재사용 유지.

## 남은 TODO
- 업로드 결과의 `drive_path_display` 를 공고 폴더 경로로 표기(현재 cosmetic 으로 inbox 표기). legacy 부서 업로드 폼 파라미터 제거는 영향도 확인 후.
