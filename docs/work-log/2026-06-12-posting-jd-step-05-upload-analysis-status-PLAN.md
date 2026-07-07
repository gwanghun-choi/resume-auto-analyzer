# Step 05~07 — 이력서 등록/분석/현황 공고 전환 (계획 / TODO)

- **작업 일시**: 2026-06-12
- **상태**: **보류(계획만)**. 이유: DB 미가동으로 런타임 테스트 불가 + upload/analysis/status 는 현재 정상 동작하는 핵심 경로라, 무테스트로 한 번에 바꾸면 앱이 깨질 위험이 큼. 견고한 additive 기반(Step 02~04)을 먼저 확정하고, 본 단계는 **정확한 통합 지점**을 명시해 다음 세션에서 안전하게 구현.

## 이미 준비된 것 (이번 세션)
- DB 컬럼: `resume_files.posting_id/jd_id`, `resume_analysis_results.posting_id/jd_id/jd_snapshot` (SQL/모델 추가 완료, 적용 대기).
- 공고/JD 백엔드 + 공고 검색 API(`/api/job-postings/search`).

## Step 05 — 이력서 등록 (공고/JD 선택 기반)
- **프론트(`view-resume`)**: 부서 트리 선택 → **공고 검색/선택**으로 교체. 공고 선택 시 공고명/부서/플랫폼/JD등록상태 표시. JD 미등록 공고는 업로드 버튼 비활성 + "JD가 등록된 공고에만 이력서를 업로드할 수 있습니다." (공고 검색은 `/api/job-postings/search` 사용)
- **백엔드(`POST /api/resumes/upload-to-drive`, `resume_drive_upload_service.save_upload`)**:
  - 폼 파라미터 `dept_id` → **`posting_id`** 추가(호환 위해 dept_id 도 한동안 허용 가능).
  - 업로드 권한: `posting.department_id` 기준으로 `ensure_can_upload_resume`(기존 helper) 검증.
  - 저장 시 `resume_files.posting_id = posting_id`, `jd_id = posting active JD id`, **`dept_id = posting.department_id` 복사**.
  - active JD 없으면 업로드 거부(400, "공고에 등록된 JD가 없어 업로드할 수 없습니다.").
- **Drive**: `job_postings.drive_*_folder_id` 가 없으면 업로드 시 공고 폴더(inbox/completed/failed) 생성 후 저장(기존 dept_folder_sync_service 패턴 재사용). 또는 공고 등록 시 생성. **안정성 위해 "업로드 시 없으면 생성"** 권장.

## Step 06 — 분석 작업 관리 (공고/JD 기준)
- **프론트(`view-analysisJobs`)**: 좌측 부서 트리 + [전체 부서] → **공고 검색/선택** + [전체](ADMIN). 테이블 컬럼에 **공고명** 추가.
- **백엔드**:
  - pending 조회: `posting_id` 필터 추가(`resume_upload_db_service`/`resume_status_db_service`).
  - 분석 실행: `resume_file.posting_id → job_posting_jds(active)` 로 JD 조회 → 그 JD의 required/preferred/jd_content 를 `MatchingService` 에 전달(**산식·프롬프트 불변**). JD 없으면 "공고에 등록된 JD가 없어 분석할 수 없습니다."
  - `analysis_results` 저장 시 `posting_id/jd_id` + `jd_snapshot`(title/required/preferred/jd_content) 기록.
  - 공고 분석 API `POST /api/analysis/run/posting {posting_id}` 추가, 전체분석은 ADMIN 전용 유지.
  - 권한: posting.department_id 로 `ensure_can_run_analysis`.
- **주의**: 현재 분석은 dept active JD(job_descriptions) + dept Drive 폴더 기준. 공고 기준으로 바꾸려면 `ResumeAnalysisService._lookup_map`/JD 조회를 posting 기준으로 분기해야 함 → **부서 경로는 fallback 으로 유지**.

## Step 07 — 이력서 현황 (공고/JD 필터 + 공고명)
- **프론트(`view-resumeStatus`)**: 기존 부서 필터 유지 + **공고 필터** 추가, 목록에 **공고명 컬럼**, 상세 팝업에 공고명/JD명. 파일명 다운로드 유지.
- **백엔드**: `GET /api/resumes/status` 에 `posting_id` 필터 추가, 응답에 `posting_title`/`jd_id` 추가(resume_files JOIN job_postings). `get_status_detail` 에도 공고명/JD명.
- **미매핑 방어**: `posting_id IS NULL` 기존 데이터는 공고명 **"-"(미매핑)** 으로 표시(이미 status 화면은 dept 기준으로 동작하므로 깨지지 않음).

## 감사 로그 (audit_logs) — TODO
- `audit_logs` 모델/서비스 없음(테이블만 가정). 최소 `AuditLogService.log(event, user_id, target, meta)`(실패 무시) 추가 후 공고/JD 등록·수정, 업로드, 분석 실행 이벤트 기록. **핵심 기능 우선이라 이번 보류** → docs/TODO.md.

## 호환성 원칙(공통)
- posting_id 없는 기존 resume_files/analysis_results 는 **부서 기준 기존 화면/로직으로 그대로 동작**(legacy fallback 삭제 금지). 신규 흐름부터 posting_id 필수.
