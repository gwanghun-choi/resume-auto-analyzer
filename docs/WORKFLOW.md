# 업무 플로우 (사용자 관점)

사용자가 화면에서 실제로 사용하는 순서를 정리한 문서입니다.
(코드 내부 구조 설명이 아니라 **사용 흐름** 중심입니다.)

화면 메뉴 구조(현재): **채용 관리 [ 공고/JD 관리 · 이력서 등록 · 이력서 현황 · 분석 작업 관리 ] / 관리자 [ Drive 설정·동기화 · 사용자 관리 ]**

---

## 공식 업무 흐름 (공고 중심, 2026-07 확정)

**현재 공식 주력 플로우는 공고(job posting) 중심**입니다. 신규 기능/배치/분석은 모두 이 흐름만 사용합니다.

1. **공고 등록** 또는 **채용 플랫폼 신규 공고 자동 수집**(사람인·잡코리아 대상 회사 배치) → `job_postings`
2. **공고 상세 URL 분석** → `job_extract_service`(대상 회사 검증 + LLM JD 구조화)
3. **공고별 JD 생성/저장** → `job_posting_jds`(`job_posting_service.upsert_jd`)
4. **Drive 공고 폴더 생성**(JD 저장 성공 시, 한 트랜잭션) → `job_posting_drive_service`
5. **공고 기준 이력서 업로드** → `resumes_router` + `resume_drive_upload_service`(Drive inbox), PENDING 저장
6. **공고 기준 분석 요청** → `resumes_router`(analyze-posting/selected/all)가 **Celery `resume_analysis` 큐에 enqueue** 후 즉시 `QUEUED` 응답
7. **Worker 분석 처리** → `analyze_resume_posting_task` 가 `resume_analysis_service.analyze_posting` 재사용: Drive download → PDF/DOCX 파싱 → OpenAI 분석 → 점수 계산 → completed/failed 이동 → `resume_analysis_results` 저장(`posting_id`/`jd_id`/`jd_snapshot`), 파일 단위 성공/실패 격리
8. **Drive completed/failed 이동** → `google_drive_service.move_file_to_folder`(부모 변경, worker 내부)
9. **이력서 현황/Excel 조회** → `resume_status_db_service` / `resume_status_excel_service` (파일 상태 PENDING/PROCESSING/COMPLETED/FAILED)

이력서 분석 비동기 흐름:
```text
공고 기준 이력서 업로드 → PENDING 저장
→ 분석 실행 요청(analyze-posting/selected/all)
→ resume_analysis 큐 enqueue (posting_id[, resume_file_ids], requested_by_user_id) → 즉시 QUEUED 응답
→ Worker: Drive download / PDF·DOCX parse / OpenAI 분석 / 점수 계산 / Drive 이동 / DB 저장 (파일 단위 격리)
→ 이력서 현황 화면에서 결과 확인 (자동 polling 미도입 — 새로고침)
```
> Celery 큐 대상은 **공고 중심 경로만**입니다(`analyze_posting`/`job_extract_service`/`job_posting_service`). 레거시 부서 중심 `analyze_pending`/`batch_service` 는 큐에 태우지 않습니다.

### Legacy department-based flow (레거시 부서 중심 흐름)

아래 부서(department) 중심 경로는 **과거 호환용**이며 **신규 개발 대상이 아닙니다**. 코드에는 `LEGACY` 주석으로 표시되어 있고, 동작은 그대로 유지합니다(이번 정리에서 삭제하지 않음). **향후 제거/비활성화 검토 대상**입니다(docs/TODO).

- 부서 기준 JD: `/api/jd`(jd_router) · `/api/jds`(jds_router) · `job_descriptions` 테이블 · `jd_service`/`jd_db_service`.
  - 참고: 부서 기준 JD 등록 화면(`view-jd`)은 현재 **메뉴에 연결되어 있지 않아 화면에서 도달할 수 없습니다**(orphaned).
- 부서 기준 업로드/분석: `/api/uploads`(upload_router) · `/api/analyze`(analyze_router) · `/api/resume`(resume_router, 단일 파일) · `upload_service`/`batch_service`(로컬 파일시스템) · `resume_analysis_service.analyze_pending`.
  - 이들 레거시 API 는 현재 프론트 런타임에서 호출하지 않습니다(app.js 헤더 주석에만 흔적).
- 부서 더미 목록: `/api/depts`(dept_router) · `dept_service`.

---

## 1) 초기 관리자 설정 플로우

처음 서버를 띄우고 Google Drive/DB 연동을 준비하는 단계입니다.

1. **환경변수 확인** — `.env` 의 `OPENAI_API_KEY`, `GOOGLE_*_PATH`, `DB_*`/`DATABASE_URL`, `SSL_CERT_FILE` 등.
2. **DB 마이그레이션** — `uv run alembic upgrade head`. 빈 DB 에서 이 한 번으로 `resume_ai` 스키마의 모든 테이블/컬럼/제약/인덱스가 생성됩니다(`users`, `job_postings`, `job_posting_jds` 포함). **수동 SQL(`docs/sql/*.sql`) 선실행 불필요** — 기존 DB 는 idempotent 하게 전진하거나 `alembic stamp head`. (자세한 절차: [README](../README.md) 의 "DB 초기화 / 마이그레이션 (Alembic)")
3. **서버 실행** (로컬 `uv run uvicorn app.main:app --reload` 또는 Docker `docker compose up -d`).
4. **Google credentials/token 확인** — `secrets/google/credentials.json`, `token.json` 존재 여부.
5. **Google Drive 연결 확인** — `GET /api/drive/test` (또는 화면의 동기화 영역)로 인증/기본 폴더 생성 확인.
6. **Drive 부서 JSON 불러오기** — 관리자 > Google Drive 동기화 > "Drive 부서 JSON 불러오기" (`dept_config.json` 로드).
7. **부서 트리 확인** — JD 등록/이력서 등록 화면의 좌측 부서 트리에 부서가 보이는지 확인.
8. **부서 폴더 동기화** — "부서 폴더 동기화 실행"으로 `inbox/completed/failed` 하위 부서 폴더 생성/매핑(`dept_drive_folders`).
9. **DB 연결 확인** — `GET /api/db/health` (그리고 `GET /api/db/counts`)로 DB 연결/테이블 확인.

> `관리자 > Drive 설정/동기화` 의 "부서 DB 동기화 (resume_ai)" 영역은 부서/Drive 폴더 매핑 중심 화면입니다.
> 카운트 카드는 `departments` / `dept_drive_folders` 2개만 표시합니다. (legacy `job_descriptions` 카드/현황 팝업은 공고/JD 중심 전환으로 제거 — 공고/JD 현황은 `공고/JD 관리` 화면에서 확인)

---

## 2) 부서 / JD 관리 플로우

1. **부서 선택** — JD 등록 화면에서 좌측 트리에서 팀 선택(부서명 검색 가능).
2. **JD 입력 또는 등록** — 포지션명/JD 설명/필수 기술/우대 기술/최소 경력/기준 점수/담당자 이메일 입력.
3. **추천JD 기능 사용** — "추천JD" 버튼 클릭 → 선택 부서/포지션명 기반으로 OpenAI 가 초안 생성.
4. **OpenAI 추천 결과 확인** — JD 설명/필수 기술/우대 기술이 입력란에 자동 채워짐.
5. **JD 저장/수정/삭제**
   - 저장: "JD 저장" 버튼(추천 결과만으로는 저장되지 않음 — 사용자가 직접 저장).
   - 조회/수정: 부서 선택 시 기존 JD 로드 후 수정 저장.
   - 삭제: JD CRUD API(`/api/jds`) 기준(soft delete 정책).
6. **향후 JD 버전 관리 필요성** — 현재는 부서별 단일 JD 위주. 향후 변경 이력/버전 관리 필요(→ `docs/TODO.md`).

---

## 3) 이력서 업로드 플로우

1. **이력서 등록 화면 진입** → 좌측 트리에서 **대상 부서/팀 선택**.
2. **이력서 파일 선택** — PDF/DOC/DOCX/HWP/HWPX/TXT/MD/RTF/CSV/JSON/ZIP (ZIP 은 내부 파일 개별 처리).
3. **업로드 실행** — "Google Drive에 업로드" 클릭.
4. **Google Drive 업로드 확인** — 선택 부서의 `inbox/{회차}` 폴더에 저장됨.
5. **DB 저장 확인** — `resume_upload_batches`(회차) / `resume_files`(파일) 기록.
6. **업로드 상태 확인** — 업로드 결과 표시 + "분석 대기 파일" 목록 자동 갱신.

---

## 4) 이력서 분석 플로우

1. **분석 대상 확인** — 이력서 등록 화면의 "분석 대기 파일"(PENDING) 확인.
2. **분석 실행** — "분석 실행" 버튼 클릭(`POST /api/resumes/analyze-pending`).
3. **OpenAI 분석 호출** — Drive 에서 파일 다운로드 → 텍스트 추출 → JD 기준 OpenAI 분석.
4. **분석 결과 저장** — `resume_analysis_results`(상세) + `resume_files`(요약: 점수/추천/상태) 저장.
5. **분석 결과 화면 확인** — 파일별 점수/추천/요약/강점·보완점/매칭·부족 기술 표시.
6. **Google Drive 파일 이동** — 성공 → `completed`, 실패 → `failed` 로 이동(파일 단위).
7. **실패 시 처리/개선 방향**
   - 현재: 파일 단위로 실패 기록(`error_code`/`error_message`), 한 파일 실패가 전체를 막지 않음. 실패 파일은 `failed` 로 이동.
   - 향후: 큐/재시도/수동 재분석 버튼(→ `docs/TODO.md` 3·4).

---

## 5) 이력서 현황 조회 플로우

1. **전체 목록 조회** — 이력서 현황 화면 진입 시 목록 자동 조회(페이징 20건).
2. **부서별 필터** — 좌측 트리에서 부서 선택(또는 "전체 부서").
3. **상태별/추천/파일명/날짜 필터** — 상단 toolbar(분석상태·추천결과·파일명 검색·업로드일 범위·"오늘").
4. **분석 결과 확인** — 행의 "상세" 버튼 → 상세 모달(기본 정보/분석 상태/분석 결과/오류 정보).
5. **실패 건 확인** — 분석상태 `FAILED` 필터 + 상세 모달의 `error_code`/`error_message`.
6. **Excel 다운로드** — 현재 필터 조건 그대로 `.xlsx` 다운로드.
7. **향후 재분석/재처리 버튼 필요성** — 현재 현황 화면은 조회 중심. 재분석 버튼은 향후(→ `docs/TODO.md` 3·4).

---

## 6) 운영자 플로우

1. **Docker Compose 실행** — `docker compose build` → `docker compose up -d`.
2. **로그 확인** — `docker compose logs -f` (startup 의 `[llm] ...`, Drive `[drive] ...` 로그).
3. **Google Drive 연결 테스트** — `GET /api/drive/test` 또는 부서 JSON 불러오기.
4. **DB 연결 테스트** — `GET /api/db/health`, `GET /api/db/counts`.
5. **OpenAI API 연결 테스트** — JD 추천 1회 실행(성공/실패 step 확인) 또는 로그의 `[llm] provider/version/model`.
6. **장애 발생 시 확인 순서**
   1. 컨테이너 상태 `docker compose ps` / 로그.
   2. DB: `/api/db/health` (timeout 이면 `DB_HOST`/`DATABASE_URL`/`host.docker.internal` 점검).
   3. Drive/SSL: `curl` 성공인데 API 실패면 CA 번들(`/etc/ssl/certs/ca-certificates.crt`) 점검.
   4. OpenAI: `[llm] error type/message` 로 인증/모델/네트워크 구분.
7. **배포 후 점검 순서** — 방화벽/보안그룹에서 `APP_HOST_PORT` 오픈 → 서버 내부 `curl http://localhost:28080/` → `/api/db/health` → 브라우저 접속.

---

## 7) 향후 권한 기반 플로우 (예정 — 미구현)

> 아래는 **아직 구현되지 않은** 역할별 사용 흐름 초안입니다. (→ `docs/TODO.md` 1·2)

- **관리자**: 모든 메뉴. Google Drive 동기화/부서 설정 변경/사용자·권한 관리/감사 로그 조회.
- **HR 담당자**: 이력서 등록/분석 실행/이력서 현황(전 부서 또는 허용 범위), JD 등록.
- **부서 담당자**: 본인 부서 JD 등록/수정, 본인 부서 이력서 현황 조회(부서 스코프 제한).
- **면접관 / 검토자**: 배정된 후보자/이력서 분석 결과 열람(읽기 중심), 코멘트(향후).
- **읽기 전용 사용자**: 현황/결과 조회만, 업로드/분석/동기화 불가.

각 역할의 메뉴/기능 노출은 **백엔드 권한 검사 + 프론트 메뉴 분기** 로 구현 예정입니다.

---

## 공고/JD 중심 업무 흐름 (2026-06, 적용 완료)

이력서 등록/분석/현황은 **공고(job_posting) 중심**으로 동작합니다. 위쪽 부서 기준 절은 legacy 이며, 공고 미매핑(`posting_id IS NULL`) 데이터 호환을 위해 유지됩니다. 부서/팀은 **권한·필터 기준**으로 그대로 유지됩니다.

1. **공고 + JD 통합 등록** — Resume AI **공고/JD 관리 > [+ 공고 등록]**. 팝업에 **공고 기본 정보 + JD 상세가 처음부터 함께** 표시되며, 저장 버튼은 **하나**(신규=`공고 등록` / 수정=`공고 수정`)로 공고+JD를 함께 저장합니다.
   - 공고명/JD명, **부서/팀(선택사항 — 미지정 가능, 사용자가 직접 권한 범위 검색·선택)**, 플랫폼, 플랫폼 공고 URL, 상태. JD: 자격 요건/우대 사항/주요 업무(줄바꿈 입력 → 저장 시 기존 로직으로 JSONB 배열 변환).
   - **(선택) URL 자동 채우기**: 플랫폼 공고 URL 입력 후 **[공고 내용 가져오기]** → **대상 회사 공고로 확인된 경우에만** 본문을 수집해 LLM 으로 공고명/주요 업무/자격 요건/우대 사항을, 플랫폼은 **URL 도메인 기준**으로 채움.
     - **공고명/JD명(`job_title`)은 "모집분야"가 아니라 공고 상단 제목을 우선 사용**: `og:title`/`<title>` 에서 정적 추출 후 사이트명·마감 D-day·회사명 대괄호 suffix 를 제거(예: `[샘플(주)] 인프라 운영 엔지니어 채용(D-28) - 사람인` → `인프라 운영 엔지니어 채용`). 상단 제목을 못 찾으면 LLM 추출값 → 모집분야 순으로 fallback. (응답에 `posting_title`/`recruit_field` 참고 필드 분리)
     - **수집 fallback**: 정적 HTML 본문(STATIC_HTML) → 사람인 상세 iframe `relay/view-detail?rec_idx=` 정적 fetch(SARAMIN_DETAIL) → 동일 출처 iframe(IFRAME). (사람인 JD 는 JS 로드 iframe 에 있어 메인 HTML 에 없지만 상세 URL 을 정적으로 가져와 채움 — Playwright 미사용)
     - 본문에 섹션이 있는데 추출이 비면 성공이 아닌 **경고**(warning/debug_reason)로 안내. **이미 입력값이 있으면 confirm 후 교체**(취소 시 유지), **부서/팀·상태는 변경하지 않음**. **자동 저장하지 않으며** 사용자가 확인·수정 후 저장 버튼을 눌러야 기존 Drive 연동/DB 저장이 동작합니다. (권한 ADMIN/MANAGER, SSRF 방어)
   - 공고만 저장(JD 입력 없음) 시 "JD 미등록", Drive 폴더 미생성.
2. **JD 저장 (= Drive 폴더 생성)** — JD 내용을 입력하고 저장하면(통합 버튼) 공고당 1 active JD upsert(**`resume_ai.job_posting_jds`** — `job_postings` 와 별도 테이블. legacy `job_descriptions` 와 무관). 자격 요건/우대 사항 textarea(줄바꿈) → `required_skills`/`preferred_skills` JSONB 배열, 주요 업무 → `jd_content`. 등록되면 "JD 등록 완료".
   - **JD 저장 성공 시점에** 공고 Drive 폴더(`inbox|completed|failed / {JP코드_공고명}`)가 없으면 생성하고 folder id 저장(있으면 재생성 안 함 — 멱등). 부서 폴더는 중간 경로에 두지 않습니다.
   - JD 저장 + Drive 폴더 생성은 한 트랜잭션 → **Drive 생성 실패 시 JD 저장도 롤백**. (기존 `postings/{부서}/...` 구조는 legacy, 삭제하지 않음)
   - 공고 상세/수정 팝업은 **공고 기본 정보 + JD 상세 통합 입력**, 단일 버튼으로 공고+JD 함께 저장. **저장 전체 성공 시 팝업 자동 닫힘 + 목록 갱신**(JD 저장만 실패하면 팝업 유지 + 오류 안내). JD 카드 우상단 **[추천 JD]** 버튼. VIEWER 는 버튼 숨김(백엔드 403).
3. **이력서 등록** — **이력서 등록** 화면의 공고 리스트에서 **JD 등록 완료 공고**를 골라 [업로드]. 업로드 영역 상단에 해당 공고의 **기존 미처리(분석 대기) 이력서 요약**(건수+파일명 일부, `posting-pending` 재사용) 표시 → 파일 업로드. 공고 inbox 폴더로 저장, `resume_files`에 `posting_id`/`jd_id`/`dept_id(=공고 부서)` 기록.
4. **분석** — **분석 작업 관리** 화면은 3컬럼 `[부서/팀] → [공고/JD] → [분석 대기 파일]`. 부서/팀 선택(상위 부서 = 하위 포함, 전체 부서 가능) → 해당 범위 공고/JD 목록(페이징) → 공고 선택 → 대기 파일 테이블(페이징·체크박스). [선택 공고 분석]/[선택 항목 분석]/[전체 분석(ADMIN)]. `resume_file.posting_id → active JD` 로 분석(MatchingService 산식/추천 기준 불변), 결과에 `posting_id`/`jd_id`/`jd_snapshot` 저장, 공고 completed/failed 폴더로 이동.
5. **이력서 현황** — 공고명 검색/필터로 조회, 목록·상세에 공고명/JD명 표시. 원본 파일 다운로드·Excel(공고명 컬럼) 유지. 미매핑은 공고명 "-".
6. **추천 결과** — (예정) 공고/JD 단위 조회.

검색/필터(공고/JD 관리·이력서 등록·분석): `[오늘] [등록일 시작]~[등록일 종료] [플랫폼] [상태] [JD 등록] [공고명 검색] [검색] [초기화]` — 모두 백엔드 필터. 검색/초기화는 한 줄 유지(`toolbar-actions`), 공고명/파일명/날짜 input Enter 검색. 이력서 현황 Excel 은 우측 상단.

화면 레이아웃: 이력서 현황 부서 트리 카드는 뷰포트 높이로 캡 + 내부 스크롤(페이지가 트리로 밀리지 않음). 분석 작업 관리는 3컬럼(부서/팀 · 공고/JD · 대기+실행).

목록 페이징: 공고/JD 관리·이력서 등록·이력서 현황은 페이지당 표시 select(20/30/50, 기본 20). 분석 작업 관리 공고/JD 목록은 size select 없이 **5개 고정**(이전/다음만), 분석 대기 파일은 20/30/50. 모두 백엔드 페이징, total 은 권한 필터 적용.

권한:
- **ADMIN**: 전체 공고/JD 등록·수정·조회, 전체 이력서/분석/현황, **전체 분석**.
- **MANAGER**: 본인 `department_id` 및 하위 부서 공고/JD만 등록·수정, 해당 범위 이력서/분석(선택 공고/항목)/현황. 전체 분석 불가.
- **VIEWER**: 권한 범위 공고/JD **조회만**(등록/수정/업로드/분석 불가, 백엔드 403).

> 단계별 작업 기록: [`docs/work-log/`](work-log/) 의 `2026-06-posting-jd-ui-step-01~05`.

---

## 채용 플랫폼 대상 회사 신규 공고 자동 수집 (배치, 2026-07)

수동 공고 등록(위 1~2)과 별개로, **사람인·잡코리아** 검색 결과에서 **대상 회사** 신규 공고를 자동으로 찾아 등록하는 배치입니다. 두 플랫폼은 **같은 등록/큐 로직(`job_posting_discovery_service._discover`)을 재사용**하며, **JD 분석은 Celery worker 가 비동기로 처리**하고, 상세 URL 분석/JD 저장/Drive 폴더 생성은 위 수동 흐름과 **같은 service 를 재사용**합니다.

**지원 플랫폼**: 사람인(SARAMIN) · 잡코리아(JOBKOREA). **platform_code 자동 매핑**은 URL 도메인 기준(`job_extract_service.platform_code_for_url`) — `saramin.co.kr→SARAMIN`, `jobkorea.co.kr→JOBKOREA`, 그 외→기존 기본값(None). 수동 공고 등록/수정도 platform_code 미입력 시 URL 로 자동 채웁니다(사용자가 고른 값은 유지).

**dry-run**: `POST /api/jobs/discover/{saramin|jobkorea}?dry_run=true` — 실제 insert/큐 적재 없이 수집·중복 판단 결과만(`platform_code`/`company_name`/`title`/`raw_url`/`normalized_url`/`is_duplicate`/`skip_reason`) 반환.

```text
[수동 API 또는 Scheduler(주석)]
사람인 수집
→ 대상 회사 필터 + detail_url 중복 확인
→ 신규 공고 insert (status=DRAFT)
→ JD 분석 task enqueue (posting_id)  → status=JD_QUEUED

[Celery worker · job_discovery 큐]
→ posting_id 로 공고 재조회 (status=JD_PROCESSING)
→ Worker 가 상세 URL 분석 (job_extract_service 재사용)
→ JD 저장 (job_posting_service.upsert_jd)
→ Drive 공고 폴더 생성
→ status=JD_READY (실패 시 JD_FAILED)
```

1. **사람인 검색 결과 수집** — `SARAMIN_SEARCH_URL`(대상 회사 검색) 페이지를 정적 수집(SSRF 방어 재사용) → 카드 단위로 회사명/제목/`rec_idx`/detail_url 파싱. 정적 HTML 파싱은 `item_recruit` 카드 → `corp_name` 세그먼트 + `a.str_tit`/`rec_link` → 링크 전체 스캔 순으로 fallback 하여 detail_url 을 보강 수집합니다(회사명 결속 없는 링크는 미등록). ※ 검색 결과가 JS 렌더링인 경우 정적 수집 한계 → 렌더링 DOM fallback 은 후속(docs/TODO).
2. **신규 공고 판단** — 회사명 normalize 후 **`TARGET_COMPANY_NAMES` 목록** 과 exact 일치만 통과. detail_url 은 `rec_idx` 기준 표준 URL 로 정규화, `job_postings.platform_posting_url`(rec_idx) 로 **중복 확인** → 신규만 진행.
3. **신규 공고 insert + 큐 적재** — `job_posting_service.create_posting`(status=DRAFT, platform=SARAMIN, 부서 미지정) 후 **`analyze_job_posting_jd_task.delay(posting_id)`** 로 큐 적재, 공고 status=`JD_QUEUED`. (큐에는 posting_id 만)
4. **Worker: URL 분석/JD 생성/Drive 폴더** — worker 가 posting_id 로 재조회 → `JD_PROCESSING` → `job_extract_service.extract_from_url` → `upsert_jd`(JD 저장 + Drive 폴더, 한 트랜잭션) → `JD_READY`. 실패 시 `JD_FAILED`, 일시적 실패는 제한 재시도. 이미 active JD 있으면 skip(멱등).

- **수동 실행**: `POST /api/jobs/discover/saramin` · `POST /api/jobs/discover/jobkorea` (ADMIN/MANAGER). 결과 요약(collected/matched/new/**queued**/duplicate/failed + 항목별 상태) 반환. 같은 API 를 두 번 실행하면 2회차는 동일 공고를 duplicate 로 skip(task 중복 enqueue 없음).
- **스케줄러(1시간 주기)**: `app/services/scheduler_service.py` 에 사람인/잡코리아 진입점(`run_saramin_discovery`/`run_jobkorea_discovery`)과 등록 코드가 있으나 **실제 등록은 주석 처리**(서버 startup 자동 실행 안 함).
- 공고 하나가 실패해도 나머지는 계속 처리합니다. 민감정보/HTML 전체는 로그로 남기지 않습니다.

### 잡코리아 수집 특이점

- **검색 결과가 서버 렌더링(SSR)** 이라 정적 HTML 로 카드가 존재합니다(사람인 검색 목록이 JS 렌더링이던 것과 대비). 제목 앵커(`data-sentry-component="Title"`)의 `href=".../Recruit/GI_Read/{gno}"` 에서 공고 고유 id(`gno`, GI_No)·제목을 잡고, 같은 gno 의 회사 앵커에서 회사명을 결속합니다. 회사명 결속 없는 링크는 미등록(false positive 방지).
- **normalized URL**: tracking(`Oem_Code`/`logpath`/`stext`/`listno`/`sc`) 제거하고 gno 로 재구성 → `https://www.jobkorea.co.kr/Recruit/GI_Read/{gno}`. tracking 만 다른 같은 공고는 같은 canonical → 중복 insert 안 됨.
- **중복 판단**: `platform_code=JOBKOREA` + gno(과거 tracking 저장분 포함) → normalized_url. 플랫폼 스코프로 사람인 rec_idx 와 충돌하지 않습니다.
- 회사명의 `㈜`(U+321C) 합자 표기는 `(주)`로 치환 후 사람인과 **동일한 회사명 필터**를 재사용합니다. Playwright 미사용(정적 수집). 구조 변경은 `parser_missed` 로그로 감지.

> **이력서 분석 비동기화(`/api/resumes/analyze-posting` 등)는 2차 작업**에서 진행합니다. 레거시 부서 중심 `analyze_pending`/`batch_service` 는 큐 대상이 아닙니다.
> 작업 기록: [`docs/work-log/2026-07-07-saramin-job-discovery-batch.md`](work-log/2026-07-07-saramin-job-discovery-batch.md), [`docs/work-log/2026-07-07-celery-redis-job-posting-jd-analysis.md`](work-log/2026-07-07-celery-redis-job-posting-jd-analysis.md).
