# 프로젝트 분석: Resume Auto Analyzer

> 작성일: 2026-07-07 · 분석 대상: 현재 소스 트리(`app/`, `alembic/`, `docs/`, 배포 설정) 전수 · **소스 변경 없음(read-only 분석)**
> 본 문서는 서브에이전트 병렬 분석(API / Services / Data Model / Frontend·Deploy)을 종합한 결과입니다.
> 함께 볼 것: [`README.md`](../README.md), [`docs/WORKFLOW.md`](WORKFLOW.md), [`docs/TODO.md`](TODO.md), [`docs/work-log/`](work-log/)

---

## 1. 한눈에 보기

**Resume Auto Analyzer**는 **채용 공고(job posting)와 그에 연결된 JD를 기준으로 이력서를 자동 분석·점수화·추천**하는 FastAPI 기반 웹/API 시스템입니다. 사내 채용 검토를 돕는 MVP이며, Google Drive를 이력서 저장소로, OpenAI를 분석/추천 엔진으로, PostgreSQL(`resume_ai` 스키마)을 기준 저장소로 사용합니다.

| 항목 | 내용 |
|---|---|
| 성격 | 사내 채용 이력서 분석/매칭 관리 도구 (단일 페이지 관리 UI + REST API) |
| 백엔드 | Python 3.12, FastAPI, SQLAlchemy 2.x, Pydantic v2, `uv` 패키지 관리 |
| 프론트 | Jinja2 템플릿 + Vanilla JS(프레임워크 없음), 서명 쿠키 세션 인증 |
| DB | PostgreSQL, 스키마 `resume_ai`, Alembic + 수동 SQL 이원 관리 |
| AI/LLM | OpenAI **`gpt-4.1-mini`**(기본) — 이력서 분석, JD 추천, 공고 URL 추출 |
| 외부 연동 | Google Drive(OAuth) — 이력서 업로드/이동, 부서/공고 폴더 동기화 |
| 배포 | Docker / Docker Compose, NCP 서버 배포, 사내 Fortinet Root CA 대응 |
| 권한 | RBAC 3단계 — ADMIN / MANAGER / VIEWER |

### 아키텍처 전환 중 (핵심 맥락)
프로젝트는 **"부서(department) 중심" → "공고(job posting) 중심"** 으로 이전하는 과도기입니다. 신규/주력 경로와 레거시 경로가 공존합니다.

- **현행(주력)**: `job_postings` + `job_posting_jds`(공고당 1 active JD) → `resumes_router` / `job_postings_router` / `jds_router`
- **레거시(호환 유지)**: 부서별 `job_descriptions`, `dept_router` / `upload_router` / `resume_router` / `analyze_router` / `jd_router`, 로컬 파일시스템 기반 `batch_service`/`upload_service`

---

## 2. 도메인 & 업무 흐름

```
외부 플랫폼(사람인/잡코리아/원티드 등) 공고 등록
        │
        ▼
[공고/JD 관리]  공고 등록  ──►  공고 상세에서 JD 등록
                                    │  (이 시점에 Drive 공고 폴더 자동 생성)
                                    ▼
[이력서 등록]  공고 선택 → 파일/ZIP 업로드 → Drive inbox 저장 (PENDING)
        │
        ▼
[분석 작업 관리]  공고 선택 → 대기 파일 분석 실행
        │        (Drive download → 텍스트 추출 → OpenAI 분석 → 점수/매칭 → DB 저장 → completed/failed 이동)
        ▼
[이력서 현황]  공고 기준 조회 · 상세 모달 · Excel 다운로드
```

**Drive 폴더 구조** (공고 기준, 2026-06 정책):
```
resume-demo-root / inbox     / {JP000001_공고명}
resume-demo-root / completed / {JP000001_공고명}
resume-demo-root / failed    / {JP000001_공고명}
resume-demo-root / config    / dept_config.json      (부서 트리 원천)
```
- 폴더 생성 시점 = **JD 등록/저장 성공 시점**(JD 미등록 공고는 업로드/분석 대상 아님). JD 저장 + Drive 폴더 생성은 **한 트랜잭션**이라 Drive 실패 시 JD 저장도 롤백. 멱등(이미 있으면 재생성 안 함).
- 파일 이동은 삭제/재업로드가 아니라 **부모 폴더(parent)만 변경**하는 방식.

---

## 3. 계층 구조

```
app/
├── main.py            FastAPI 앱 조립(세션 미들웨어, 14개 라우터, 정적/템플릿, startup)
├── api/               라우터 14개 (HTTP 경계, 인증만 처리하고 세밀 인가는 service에 위임)
├── services/          도메인 로직 27개 (AI 파이프라인 / Drive / DB / 인증·권한)
├── db/
│   ├── base.py        DeclarativeBase + MetaData(schema=resume_ai) + TimestampMixin
│   ├── session.py     engine + SessionLocal + search_path 고정
│   ├── health.py      DB 헬스/메타 조회
│   └── models/        SQLAlchemy 모델 10개
├── schemas/           Pydantic DTO (요청/응답, ORM과 분리)
├── core/              config(설정) / security(세션 인증) / password(bcrypt) / paths(OAuth 경로)
├── templates/         index.html(관리 SPA), login.html
└── static/            app.js(~3000줄), login.js, style.css
```

---

## 4. API 계층 (`app/api/`, `app/main.py`)

- **인증 방식**: 서명 쿠키 **세션**(`starlette SessionMiddleware`, 세션 키 `user_id`) — JWT 아님. `app/core/security.py`의 `get_current_user`(없거나 비활성이면 401), `require_admin`(비 ADMIN 403) 의존성 사용.
- **인가 위치**: 라우터는 **인증**만 담당하고, 부서 단위 **인가**는 `department_access_service`/`job_posting_service`의 `ensure_*` 헬퍼가 파일 읽기·Drive·LLM 호출 **이전**에 검증.
- **앱 조립(`main.py`)**: title `Resume AI Analyzer (OpenAI GPT)`, SessionMiddleware(`same_site=lax`, `https_only=False`), `/static` 마운트 + Jinja2 템플릿, startup 시 `openai_llm_service.log_llm_config()`(OPENAI_API_KEY 미설정 경고). `GET /`는 미로그인 시 `/login`으로 302.

### 현행(주력) 라우터

| 라우터 | prefix | 역할 | 인증 |
|---|---|---|---|
| `auth_router` | `/api/auth` | 로그인/로그아웃, `/me`, 프로필 수정, 접근 가능 부서 | 세션 |
| `admin_users_router` | `/api/admin` | 사용자 CRUD·활성 토글·비번 초기화·부서 검색 | **ADMIN 전용** |
| `job_postings_router` | `/api/job-postings` | 공고/JD 관리, 목록/검색/상세, JD upsert(+Drive 폴더), JD 추천 | 세션 + 권한 |
| `resumes_router` | `/api/resumes` | 이력서 Drive 업로드, 현황 조회, Excel, 분석 실행(공고/선택/전체) | 세션 + 권한 |
| `jds_router` | `/api/jds` | `job_descriptions` JD CRUD(버전 관리) | 조회 공개 / 쓰기 권한 |
| `jobs_router` | `/api/jobs` | 공고 URL → LLM 자동 추출(`extract-from-url`) | ADMIN·MANAGER |

**분석 실행 엔드포인트**(`resumes_router`): `POST /analyze-posting`(공고 단위) · `POST /analyze-selected`(체크 항목) · `POST /analyze-all`(**ADMIN 전용**). 각 파일 단위로 성공/실패 격리.

### 레거시/인프라 라우터

| 라우터 | prefix | 역할 | 인증 |
|---|---|---|---|
| `drive_router` | `/api/drive` | Drive 연결 테스트, 부서 폴더 동기화, dept_config.json 관리 | **없음** ⚠ |
| `departments_router` | `/api/departments` | 부서 트리(DB 기준), Drive→DB 동기화 | 없음 |
| `db_router` | `/api/db` | DB 헬스/테이블/카운트/코멘트 | 없음 |
| `jd_router` | `/api/jd` | 팀별 JD 조회/저장 + OpenAI 추천 | 저장만 권한 |
| `analyze_router` | `/api/analyze` | 부서+업로드ID 기준 배치 분석(구버전) | 권한 |
| `resume_router` | `/api/resume` | 단일 파일 분석(호환용) | 없음 |
| `upload_router` | `/api/uploads` | 부서 기준 로컬 파일 업로드(구버전) | 없음 |
| `dept_router` | `/api/depts` | 더미 부서 flat list | 없음 |

> ⚠ **보안 관찰**: `drive`·`departments`·`db` 등 인프라/관리 성격 엔드포인트가 인증 없이 노출됩니다. 특히 `PUT /api/drive/dept-config`(Drive 설정 변경)는 인증 없이 접근 가능 — 보안 검토 포인트.

---

## 5. 서비스 계층 (`app/services/`, 27개)

### 5.1 AI / LLM 파이프라인

- **`openai_llm_service.py`** — OpenAI 호출 단일 진입점. 모델 기본 **`gpt-4.1-mini`**(`OPENAI_MODEL` env). **Responses API 우선 → Chat Completions fallback**. `call_openai_json()`이 코드블록/잡텍스트 제거 후 `json.loads`. 예외를 step 코드(`openai_auth_failed`/`openai_model_invalid`/`openai_rate_limited`/`openai_network_failed`)로 분류. API 키는 로그/에러에서 마스킹.
  - **SSL 특이점**: 프로젝트가 사내 Fortinet CA로 `SSL_CERT_FILE`을 고정하므로, 공개 CA 서명인 `api.openai.com` 검증 실패를 피하려 OpenAI 전용 httpx 클라이언트를 **certifi 공개 CA 번들**로 별도 구성.
- **`ai_agent_service.py`** — 이력서 텍스트를 OpenAI로 분석(기존 LangGraph+Gemini에서 OpenAI로 교체, JSON 구조 유지). 반환: `candidate_summary`, `extracted_skills`, `career_summary`, `strengths`, `weaknesses`, `recommendation`, **`ai_judgment_score`(0~10)**.
- **`matching_service.py`** — 점수 산출(LLM 없는 순수 로직). **매칭 점수 = 100점 만점**:
  - 필수 기술 `matched/total × 70`
  - 우대 기술 `matched/total × 20`
  - AI 종합 판단 `ai_judgment_score`(0~10 가산)
  - 스킬 매칭은 **소문자+strip 후 exact set 매칭**(부분일치/유사도 없음).
- **`resume_parser_service.py`** — `pypdf`(PDF)/`python-docx`(DOCX) 텍스트 추출.
- **`resume_analysis_service.py`** — **분석 파이프라인 오케스트레이터(핵심)**. `analyze_pending`(부서 기준)/`analyze_posting`(공고 기준) 진입점. 파일 1건 처리(`_process_one_db`): `set_processing` → Drive 다운로드 → 텍스트 추출(최대 20,000자 절단) → `AiAgentService.analyze` → `MatchingService` 점수 → completed/failed 이동 → `save_result`(결과 insert + resume_files update 한 트랜잭션). 추천 문구: ≥80 "우선 검토 추천", ≥60 "추가 검토 필요", 그 외 "낮은 적합도"(탈락 표현 금지).
- **`jd_recommend_service.py`** — 부서명/포지션명으로 JD 초안(설명·필수·우대 기술) 생성. DB 저장 없이 입력란 채우기용.
- **`job_extract_service.py`** — 공고 URL → JD 자동 추출. **SSRF 방어**(http/https만, 해석된 IP가 공인인지 검사, private/loopback/link-local 차단, 리다이렉트 매 hop 재검증, 응답 2MB/LLM 15,000자 제한). **디딤(주) 공고로 검증된 경우에만** LLM 호출. JD 본문 수집 fallback: 정적 HTML → 사람인 상세 iframe → 동일 출처 iframe. 플랫폼은 URL 도메인 기준, 공고명은 `og:title`/`<title>` 우선. Playwright 미사용.

### 5.2 Google Drive 통합

- **`google_drive_service.py`** — Drive v3 래퍼. Desktop OAuth(token 재사용→refresh→최초 로그인, WSL 대응 URL 터미널 출력). `httplib2` CA 번들 명시로 사내망 검증. 폴더/파일 CRUD, `move_file_to_folder`(parent만 변경), 중복명 처리, `dept_config.json` 텍스트 read/write, 빈 폴더 정리.
- **`dept_config_service.py`** — Drive `config/dept_config.json`을 **부서 데이터 원천**으로 관리(조회/정규화/검증/저장, **규칙 기반·LLM 없음**). 화면 트리는 로컬 캐시(`dept_config_cache.json`) 사용.
- **`dept_folder_sync_service.py`** — inbox/completed/failed 아래 부서 폴더(`{id}_{name}`) 생성·재사용, `dept_drive_folders`에 upsert.
- **`job_posting_drive_service.py`** — 공고 폴더(`JP{id:06d}_{공고명}`)를 inbox/completed/failed에 생성.
- **`resume_drive_upload_service.py`** — 업로드 파일을 inbox 폴더에 저장(분석·이동 안 함, PENDING). 확장자 화이트리스트, ZIP 평탄화(중첩/traversal 차단), 실행파일 차단, 파일 20MB/전체 100MB/ZIP 100개 제한. 기준 저장소는 DB, `upload_records.json`은 fallback.

### 5.3 DB 서비스 계층 (`SessionLocal` + 트랜잭션 패턴, `resume_ai` 한정)

- **`resume_analysis_db_service.py`** — 분석 파이프라인 DB 액세스(PENDING 조회, `set_processing`, `save_result`, `update_batch_counts` 배치 상태 집계, 공고 분석 컨텍스트).
- **`resume_upload_db_service.py`** — `save_upload`(batch upsert + files N건, `on_conflict_do_update`로 중복 방지), 권한 부서 필터 pending 조회.
- **`resume_status_db_service.py`** — 이력서 현황 읽기 전용(페이징+권한/공고/키워드/날짜 필터, 상세, Excel용 전체).
- **`jd_db_service.py`** — `job_descriptions` 관리(dept당 active 1개, version+1, soft delete).
- **`department_db_service.py`** — dept_config → `departments` upsert, 트리 조회.
- **`dept_drive_folder_db_service.py`** — `dept_drive_folders` upsert/조회.

### 5.4 인증 / 권한 / 공고 / 기타

- **`auth_service.py`** — `users` 로그인/프로필. **bcrypt**(`app.core.password`)로 검증/저장. 세션엔 user_id만. 본인 email/password만 수정 가능.
- **`department_access_service.py`** — **RBAC 권한 계산 핵심**. ADMIN=전체, MANAGER/VIEWER=본인 부서+하위(**PostgreSQL recursive CTE**). `ensure_can_manage_jd`/`ensure_can_upload_resume`(leaf 부서), `ensure_can_run_analysis`/`ensure_can_download_resume`(VIEWER 불가), `ensure_department_access`(조회는 VIEWER 허용).
- **`admin_user_service.py`** — 사용자 CRUD, **마지막 활성 ADMIN 강등/비활성화 차단**, 본인 비활성화 차단, 임시 비밀번호 발급. password_hash 응답 제외.
- **`job_posting_service.py`** — 공고/JD 관리, **1공고=1 active JD 강제**. `upsert_jd`가 JD 저장 시점에 공고 Drive 폴더를 **같은 트랜잭션**으로 생성(Drive 실패 시 롤백).
- **`resume_status_excel_service.py`** — openpyxl로 현황 xlsx를 메모리(BytesIO) 생성.
- **`batch_service.py` / `upload_service.py`** — **레거시 로컬 파일시스템 경로**(`data/storage/...`). 현행 Drive+DB 파이프라인과 별개 구버전.

### 5.5 엔드투엔드 파이프라인 요약

```
[업로드]  resume_drive_upload_service.upload()
          → Drive inbox/{upload_id}_{label}/ 저장 (PENDING, 분석 안 함)
          → resume_upload_db_service.save_upload()  (batch + files DB)

[분석]    resume_analysis_service.analyze_posting()/analyze_pending()
          → active JD 확인, 폴더 매핑 조회
          → 파일별: download → parse(20k자) → OpenAI(gpt-4.1-mini) → 점수(필수70+우대20+AI10)
                   → completed/failed 이동(parent 변경) → save_result(1 트랜잭션)
          → update_batch_counts + 빈 inbox 폴더 정리

[조회]    resume_status_db_service → resume_status_excel_service(xlsx)
```

---

## 6. 데이터 모델 (`app/db/`)

- **엔진/세션**: `create_engine(pool_pre_ping=True)`(지연 연결 — DB 꺼져 있어도 기동), `connect`마다 `SET search_path TO resume_ai, public`. 서버 시작 시 **`create_all` 안 함** — 테이블은 Alembic + 수동 SQL로 관리.
- **스키마 이원 관리(중요)**:
  1. `alembic/versions/0001_create_resume_ai_tables.py` — 초기 6개 테이블(`departments`, `job_descriptions`, `dept_drive_folders`, `resume_upload_batches`, `resume_files`, `resume_analysis_results`). 이 시점엔 `posting_id`/`jd_id` 없음.
  2. `docs/sql/2026-06-12-posting-jd.sql`(수동, idempotent) — `job_postings`·`job_posting_jds` 생성 + `resume_files`/`resume_analysis_results`에 `posting_id`/`jd_id`/`jd_snapshot` ALTER. **실제 FK 3개가 여기서 정의**.
  3. `docs/sql/2026-06-12-job-postings-dept-nullable.sql` — `job_postings.department_id` NOT NULL 해제.
  4. `users` 테이블은 Alembic·docs/sql 어디에도 DDL이 없음 — **외부 선행 존재 전제**.

### 모델 10개

| 모델 / 테이블 | PK | 역할 |
|---|---|---|
| `departments` | `id` str (예: D00035) | Drive dept_config 동기화 부서 트리(권한/필터 기준) |
| `users` | `id` bigint | 로그인 계정 + role/부서 스코프 |
| `job_postings` | `id` bigint | **채용 단위(공고)**. platform/status/Drive 폴더 4종 |
| `job_posting_jds` | `id` bigint | 공고 active JD(현행). `required/preferred_skills` JSONB |
| `job_descriptions` ★legacy | `id` bigint | 부서별 JD(구조). count/신규 흐름에서 제외 |
| `dept_drive_folders` | `id` bigint | 부서별 Drive 폴더 매핑(dept_id UNIQUE) |
| `resume_upload_batches` | `upload_id` str (UPL…) | 업로드 1회 = 1 회차(batch) |
| `resume_files` | `id` bigint | 분석 대상 파일 1건 = 지원자 1명 |
| `resume_analysis_results` | `analysis_id` str (ANL…) | AI 분석 결과 상세 + `jd_snapshot` |

### ER 개요 (관계는 대부분 soft reference — 하드 FK는 posting-jd.sql의 3개뿐)

```
departments (id: str)
   ├─(department_id) job_postings ──FK created_by──► users
   │                     │ id
   │          posting_id │ (FK CASCADE)
   │                     ▼
   │             job_posting_jds ──FK created_by──► users
   ├─(department_id) users
   ├─(dept_id, UNIQUE) dept_drive_folders
   ├─(dept_id) job_descriptions  ★legacy
   └─(dept_id) resume_upload_batches (upload_id: str)
                     │ upload_id
                     ▼
              resume_files (posting_id/jd_id nullable → 공고/JD)
                     │ resume_file_id (nullable)
                     ▼
       resume_analysis_results (posting_id/jd_id nullable, jd_snapshot JSONB)
```

**하드 FK 3개**: `job_postings.created_by → users`(SET NULL), `job_posting_jds.posting_id → job_postings`(**CASCADE**), `job_posting_jds.created_by → users`(SET NULL). 나머지는 값 참조(문자열/정수), SQLAlchemy `relationship()` 미선언 — 조인은 서비스 계층에서 수동.

### 데이터 모델 주의사항
1. **ORM↔DB drift**: `JobPosting.department_id`가 ORM에선 `nullable=False`이나 실제 DB는 nullable(dept-nullable.sql 적용).
2. **Legacy 이중 JD**: `job_descriptions`(부서별)와 `job_posting_jds`(공고별)가 공존.
3. **NULL 미매핑**: 전환 후 추가된 `posting_id`/`jd_id`는 기존 데이터에서 NULL(공고명 '-' 로 안전 표시).
4. **분석 스냅샷**: `jd_snapshot`(JSONB)으로 분석 당시 JD를 동결 → 이후 JD 수정과 무관하게 근거 보존.

---

## 7. 프론트엔드 (`app/templates/`, `app/static/`)

- 서버 렌더 Jinja2 뼈대 + **Vanilla JS SPA**(프레임워크 없음). `app/static/app.js`(~3,048줄)가 `DOMContentLoaded → init()`에서 메뉴/이벤트 배선. 좌측 "업무 메뉴" 사이드바 + 우측 `<section class="view">` 전환.
- **메뉴/권한**: 각 메뉴는 `data-roles` 속성으로 프론트에서 숨김. 단, **모든 권한은 백엔드에서 403 재검증**(프론트 숨김은 UX용).
- **주요 화면**: 공고/JD 관리(`view-jobPostings`), 이력서 등록(`view-resume`), 분석 작업 관리(`view-analysisJobs`), 이력서 현황(`view-resumeStatus`, 필터·상세 모달·Excel), 관리자 Drive 설정(`view-driveSync`), 사용자 관리(`view-adminUsers`, ADMIN 전용), 미구현 안내(`view-todo`).
- **API 호출**: 순수 `fetch`(공통 래퍼 없이 함수별 직접 호출), `401` 응답 시 일괄 `/login` 리다이렉트. 정적 자원은 `?v=날짜` 캐시 버스팅.
- **페이징**: 백엔드 페이징(`{items, total, page, size}`), size select 20/30/50.

---

## 8. 설정 / 인증 코어 (`app/core/`)

- **`config.py`** — Pydantic Settings(`.env`, `extra=ignore`). DB 접속(`DB_*` 또는 `DATABASE_URL` 우선), `DB_SCHEMA=resume_ai`, `SESSION_SECRET_KEY`. `OPENAI_*`는 여기 미선언 — 코드에서 `os.getenv` 직접 사용.
- **`security.py`** — 서버 세션 인증(`request.session["user_id"]`). `get_current_user`/`require_admin`.
- **`password.py`** — **bcrypt** 해싱(`hash/verify_password`), `is_bcrypt_hash`(재실행 안전), `generate_temporary_password`(secrets 기반, 대/소/숫자/특수 보장).
- **`paths.py`** — Google OAuth 파일 경로(`GOOGLE_CREDENTIALS_PATH`/`GOOGLE_TOKEN_PATH`) 절대경로화, `PROJECT_ROOT` 기준 fallback.

---

## 9. 배포 & 실행

- **로컬**: `run.sh` → `uv sync` 후 `uv run uvicorn app.main:app --reload`. Python 3.12, 패키지 관리자 `uv`(`uv.lock`), build-backend `uv_build`.
- **Docker**: `python:3.12-slim` 기반. curl/ca-certificates/build-essential 설치, **회사 Root CA 등록** 후 `pip install uv` → `uv sync --frozen --no-dev --no-install-project`(의존성만). `CMD uvicorn app.main:app --host 0.0.0.0 --port 8000`(운영은 `--reload` 없음).
- **Compose**: 서비스 `resume-ai`, 포트 **`28080:8000`**, `restart: unless-stopped`, `env_file: .env`. 볼륨 `./secrets/google:/app/secrets/google`(OAuth 시크릿), `./data:/app/data`. Healthcheck `curl -f http://localhost:8000/`. NCP에 복사 후 `docker compose up -d --build`.
- **`.dockerignore`**: `.env*`(단 `.env.example` 예외)·`secrets`·`credentials.json`·`token.json`·`*.tar.gz` 제외 — **시크릿은 이미지 미포함, runtime 볼륨 주입**.
- **Google OAuth**: `credentials.json`(클라이언트) + `token.json`(토큰) — compose 볼륨(`/app/secrets/google/...`) 마운트.
- **사내 CA(Fortinet)**: `certs/company-root-ca.crt`(FortiGate SSL-inspection Root CA). Dockerfile이 시스템 번들에 병합(`update-ca-certificates`), `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE`(+`HTTPLIB2_CA_CERTS`)를 `/etc/ssl/certs/ca-certificates.crt`로 지정 → requests/httplib2/googleapiclient가 사내 CA 신뢰.
- **부트스트랩**: `scripts/hash_existing_dummy_passwords.py` — 더미 계정 평문 password_hash를 bcrypt로 일회성 전환(이미 bcrypt면 skip).

### 주요 환경변수

| 변수 | 용도 |
|---|---|
| `SESSION_SECRET_KEY` | 세션 쿠키 서명 (운영 필수 교체) |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | JD 추천/이력서 분석 LLM (기본 `gpt-4.1-mini`) |
| `DB_HOST/PORT/NAME/USER/PASSWORD/SCHEMA` 또는 `DATABASE_URL` | PostgreSQL 접속 (`DATABASE_URL` 우선) |
| `GOOGLE_CREDENTIALS_PATH`, `GOOGLE_TOKEN_PATH` | Google OAuth 파일 경로 |
| `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE` (+`HTTPLIB2_CA_CERTS`) | 사내 Root CA 번들 경로 |
| `DB_ECHO` | SQL 로그 on/off |

---

## 10. 관찰 사항 / 리스크 (사실 적시, 제안 성격)

1. **인증 없는 관리 엔드포인트**: `/api/drive`(특히 `PUT /dept-config`), `/api/departments`, `/api/db`, `/api/uploads`, `/api/resume` 등이 인증 의존성 없이 노출. 인프라/설정 변경 경로에 세션 인증 적용 검토 필요.
2. **`.env.example`에 실 크리덴셜로 보이는 값 커밋**: 형태상 유효한 `OPENAI_API_KEY`(sk-proj-…), DB 접속정보(IP/비밀번호), `DATABASE_URL`이 예시 파일에 포함. 노출/키 폐기·교체 검토 권장.
3. **세션 쿠키 `https_only=False`**: 운영이 HTTPS라면 `True` 권장.
4. **스키마 이원 관리**: Alembic이 전체 스키마를 담지 못함(`users`/`job_postings`/`job_posting_jds`는 수동 SQL/외부). 재현 시 적용 순서 문서화 필요 — Alembic → posting-jd.sql → dept-nullable.sql + users DDL.
5. **ORM↔DB drift**: `JobPosting.department_id` NOT NULL 선언과 실제 nullable 불일치.
6. **레거시 경로 공존**: 부서 중심 라우터/서비스(`dept`/`upload`/`resume`/`analyze`/`jd`, `batch_service`)와 공고 중심 현행 경로가 병존 — 정리 대상 후보.

---

## 11. 참고 문서

- 향후 개발 예정: [`docs/TODO.md`](TODO.md)
- 사용자 업무 흐름: [`docs/WORKFLOW.md`](WORKFLOW.md)
- 구조 전환 작업 기록: [`docs/work-log/`](work-log/) (`2026-06-posting-jd-*` 단계별)
- DB 변경 SQL: [`docs/sql/`](sql/)
