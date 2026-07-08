# TODO (향후 개발 항목)

현재 코드에는 **구현되어 있지 않은** 기능들의 개발 계획입니다.
실제 구현된 기능은 [`../README.md`](../README.md) 의 "현재 구현된 기능" 을 참고하세요.

각 항목은 다음 형식으로 정리합니다: **목적 / 필요한 이유 / 주요 작업 / DB 변경 / API 변경 / 화면 변경 / 우선순위 / 선행 조건 / 주의사항**.

---

## 1) 로그인

- **목적**: 인증된 사용자만 시스템을 사용하도록 사용자 로그인 기능 추가.
- **필요한 이유**: 현재는 누구나 접근 가능. 이력서(개인정보)를 다루므로 최소한의 인증이 필요.
- **주요 작업**
  - 인증 방식 검토: **JWT(stateless)** vs **세션(server-side)** — MVP 규모면 세션 또는 단순 JWT 권장.
  - `users` 테이블(아이디, 이메일, 비밀번호 해시, 활성 여부, 생성/수정일).
  - 비밀번호 **해시 저장**(bcrypt/argon2). 평문 저장 금지.
  - 로그인/로그아웃 API, 토큰/세션 발급·만료 처리.
  - 프론트 로그인 화면, 미인증 시 리다이렉트.
  - 보호가 필요한 API 에 인증 의존성(Depends) 적용.
  - **초기 관리자 계정 생성**: 시드 스크립트 또는 최초 부팅 시 env 기반 1회 생성.
- **DB 변경**: `users` 테이블 신규(예정).
- **API 변경**: `/api/auth/login`, `/api/auth/logout`, `/api/auth/me` 신규. 기존 보호 대상 API 에 인증 적용.
- **화면 변경**: 로그인 화면 신규, 헤더에 로그인 상태/로그아웃.
- **우선순위**: **높음** (권한관리·감사 로그의 선행).
- **선행 조건**: 없음(가장 먼저 도입).
- **주의사항**: 비밀번호/토큰 로그 출력 금지. 토큰 만료/갱신 정책 명확화. HTTPS 전제(운영).

---

## 2) 권한관리 (RBAC)

- **목적**: 역할별로 메뉴/API/데이터 접근을 제어.
- **필요한 이유**: 관리자만 Drive 동기화, HR/부서 담당자별 이력서 접근 범위 분리 필요.
- **주요 작업**
  - 역할 정의: **관리자 / HR 담당자 / 부서 담당자 / 면접관·검토자 / 읽기 전용**.
  - 역할별 **메뉴 노출** 제어(프론트), **API 접근** 제어(백엔드 의존성).
  - **부서별 이력서 조회 권한**(부서 담당자는 본인 부서만).
  - **Google Drive 동기화/부서 설정 변경은 관리자만**.
  - 권한 구조: `roles`, `user_roles`(사용자-역할 매핑) 또는 사용자에 role 컬럼(단순) 검토.
- **DB 변경**: `roles`, `user_roles`(또는 `users.role`) (예정).
- **API 변경**: 보호 API 에 역할 검사 추가. 부서 스코프 필터 추가.
- **화면 변경**: 역할별 메뉴/버튼 노출 분기.
- **우선순위**: **높음**.
- **선행 조건**: **1) 로그인** 완료.
- **주의사항**: 백엔드에서도 반드시 권한 검사(프론트 숨김만으로 불충분). 부서 스코프 누락 시 정보 노출 위험.

---

## 3) 이력서 분석 배치/큐 구조

- **목적**: 현재 "요청 시 즉시 동기 분석" 을 **배치/큐 기반 비동기** 로 전환.
- **필요한 이유**: 다건 분석 시 요청 타임아웃/중복 실행/실패 복구 어려움. LLM 호출은 느리고 실패 가능.
- **주요 작업**
  - **분석 Job 테이블**(작업 큐). 상태값: `PENDING / RUNNING / SUCCESS / FAILED / RETRY / CANCELED`.
  - **재시도 횟수** 관리, **실패 사유** 저장.
  - **서버 재시작 시 복구 정책**(RUNNING 중단 작업을 PENDING/RETRY 로 회수).
  - 실패 케이스 분리: **LLM 호출 실패 / Google Drive 실패 / DB 저장 실패**.
  - **수동 재분석** 트리거(버튼).
  - 배치 실행 주기(스케줄러) / **동시 실행 제한**(워커 수, 분당 호출 제한).
  - **OpenAI 토큰/비용 사용량 기록** 검토(요청별 토큰 수 저장).
- **DB 변경**: `analysis_jobs`(또는 기존 `resume_files.analysis_status` 확장) 신규/확장.
- **API 변경**: 큐 등록/조회/재시도/취소 API. 기존 `analyze-pending` 을 큐 enqueue 로 전환(또는 병행).
- **화면 변경**: 작업 상태/진행률, 재분석 버튼, 실패 사유 표시.
- **우선순위**: **중간~높음**.
- **선행 조건**: 큐/워커 인프라 선택(내장 백그라운드/Redis+RQ/Celery 등). 동시성·비용 정책 합의.
- **주의사항**: 중복 실행 방지(락/유니크 제약). 부분 실패(파일 단위) 정책 유지. 비용 모니터링.

---

## 4) 이력서 상태값에 따른 재처리

- **목적**: 이력서 생애주기 상태를 명확히 하고, 상태별 가능한 액션/재처리를 정의.
- **필요한 이유**: 실패 이력서 재처리, 상태별 버튼 노출 제어가 필요.
- **주요 작업**
  - 상태 흐름 정리: `UPLOADED → QUEUED → ANALYZING → ANALYZED → (FAILED) → MOVED → ARCHIVED`.
  - **실패 이력서 재처리**(FAILED → QUEUED).
  - 특정 상태에서만 가능한 **버튼/액션** 정의(예: ANALYZED 만 결과 보기, FAILED 만 재분석).
  - **상태 변경 이력** 저장 여부 검토(상태 전이 로그).
  - 사용자 화면에 **실패 사유** 표시.
  - 관리자 **재처리** 기능.
- **DB 변경**: 상태 enum 정리, (선택) `resume_status_history` 신규.
- **API 변경**: 재처리/상태 전이 API.
- **화면 변경**: 현황 화면에 상태별 버튼/실패 사유.
- **우선순위**: **중간**.
- **선행 조건**: **3) 배치/큐** 와 연계(재처리 = 큐 재등록).
- **주의사항**: 상태 전이 규칙을 한 곳에서 관리(임의 전이 방지).

---

## 5) 대시보드

- **목적**: 운영 현황을 한눈에 보는 통계 화면.
- **필요한 이유**: 업로드/분석/실패 추이, 부서·JD별 분포 파악.
- **주요 작업**(표시 지표)
  - 전체 이력서 수, 오늘 업로드 수, 분석 대기/완료/실패 수.
  - 부서별 이력서 수, JD별 후보자 수, 평균 매칭 점수.
  - 최근 분석 실패 목록, 최근 업로드 목록.
  - OpenAI 사용량/비용 요약(3) 의 토큰 기록 연계).
  - **대시보드 API 후보**: `GET /api/dashboard/summary`, `/api/dashboard/by-dept`, `/api/dashboard/recent`.
- **DB 변경**: 원칙적으로 집계 쿼리로 가능(스키마 변경 최소). 비용 지표는 3) 의 토큰 기록 필요.
- **API 변경**: 대시보드 집계 API 신규.
- **화면 변경**: 대시보드 메뉴/화면 신규.
- **우선순위**: **중간**.
- **선행 조건**: 데이터 누적, (비용 지표는) 3) 토큰 기록.
- **주의사항**: 무거운 집계는 인덱스/캐시 고려. 권한별 노출 범위(2) 연계).

---

## 6) 감사 로그 (Audit Log)

- **목적**: "누가, 언제, 무엇을 했는지" 기록(개인정보 접근 추적 포함).
- **필요한 이유**: 개인정보(이력서) 처리 책임성/규제 대응.
- **주요 작업**(기록 대상)
  - 로그인/로그아웃, 이력서 조회/다운로드, 분석/재분석 실행.
  - Google Drive 동기화, 부서 설정 변경, 권한 변경.
  - **개인정보 접근 로그**(누가 어떤 이력서를 열람/다운로드).
  - **`audit_logs` 테이블 후보**: `id, user_id, action, target_type, target_id, detail(JSON), ip, created_at`.
- **DB 변경**: `audit_logs` 신규(예정).
- **API 변경**: 내부 기록(미들웨어/서비스 훅) + 관리자 조회 API.
- **화면 변경**: (관리자) 감사 로그 조회 화면(후순위).
- **우선순위**: **중간** (로그인/권한 이후).
- **선행 조건**: **1) 로그인**, **2) 권한관리**.
- **주의사항**: 로그 자체에 민감정보(비밀번호/토큰/이력서 본문) 저장 금지. 보존 기간 정책.

---

## 7) 채용 플랫폼 연동

- **목적**: 사람인/잡코리아/원티드 등 외부 채용 플랫폼의 공고/지원자/이력서를 연동.
- **필요한 이유**: 수동 업로드를 줄이고 지원자 데이터 자동 수집.
- **주요 작업 (사전 조사 중심)**
  - 플랫폼별 **공식 API 제공 여부** 조사: 사람인 / 잡코리아 / 원티드 / 기타.
  - **기업회원/파트너 API** 여부, 공고 등록·수정 가능 여부.
  - **지원자/이력서 조회**, **첨부파일 다운로드** 가능 여부.
  - **개인정보 처리 동의 범위**, **API 계약 필요 여부** 확인.
  - **API 가 없을 경우 대안**(우선순위 순):
    1. CSV 업로드
    2. 플랫폼에서 받은 **ZIP 업로드**(현재 업로드 기능 재사용 가능)
    3. 이메일 수신함 연동
    4. 수동 업로드
    5. **RPA 는 최후 수단**
- **DB 변경**: 연동 소스 메타(출처/외부ID) 컬럼 검토.
- **API 변경**: 연동 어댑터/수집 API(플랫폼별).
- **화면 변경**: 연동 설정/가져오기 화면(후순위).
- **우선순위**: **낮음** (조사 우선, 계약/법무 의존).
- **선행 조건**: 각 플랫폼 **공식 문서/계약 조건** 확인.
- **주의사항**: **플랫폼별 연동 가능성은 반드시 추후 공식 문서/계약 조건 기반으로 확인**해야 합니다(추측 금지). 개인정보 동의 범위를 벗어난 수집/저장 금지. 무단 스크래핑/약관 위반 금지.

---

## 8) 배포 / 운영 개선

- **목적**: 현재 수동 배포를 안정화하고 운영 절차를 표준화.
- **필요한 이유**: 현재 Git 없이 tar.gz + scp 수동 배포라 재현성/롤백이 약함.
- **주요 작업**
  - 현재 방식(**tar.gz + scp + docker compose**) 절차 문서화(README 7장 반영 완료).
  - **`deploy.sh`** 작성 검토(압축 → 전송 → 원격 해제 → compose up).
  - Docker Compose 운영 명령 정리(build/up/down/logs/restart).
  - **`.env` / `credentials.json` / `token.json` 보안 관리**(권한 제한, 서버 외 노출 금지).
  - **DB 백업/복구** 절차(pg_dump/restore, 주기).
  - **로그 관리**(컨테이너 로그 로테이션/수집).
  - **장애 대응** 순서(Drive/DB/OpenAI 연결 점검 → 컨테이너 재시작).
  - **NCP ACG/방화벽 관리**(SSH/28080/5432 IP 제한).
  - 추후 **Git/GHCR/Jenkins/ArgoCD** 도입 가능성 검토(CI/CD).
- **DB 변경**: 없음.
- **API 변경**: 없음(운영 영역). 헬스체크는 `/api/db/health`, `/` 활용.
- **화면 변경**: 없음.
- **우선순위**: **중간**(운영 안정화 관점).
- **선행 조건**: 없음(점진 도입).
- **주의사항**: 비밀/키 파일을 배포 산출물/이미지에 포함하지 않기. 롤백 가능하도록 버전 보관.

---

## JD 기준 점수 기반 추천 판단 로직 개선

제거

현재 JD의 `threshold_score`는 참고용으로만 저장되고 실제 추천 판단에는 사용되지 않는다.

향후에는 JD별 기준 점수를 실제 추천 판단 로직에 반영해야 한다.

개선 방향 예시:

- 단순 합격/불합격 표현은 개인정보/채용 리스크가 있으므로 신중하게 사용
- 추천 문구는 "합격/불합격"보다는 "우선 검토 추천", "추가 검토 필요", "기준 점수 미달" 같은 보조 판단 문구를 우선 고려
- JD별 기준 점수를 화면, API 응답, 분석 결과 저장값과 연동
- 기존 고정 구간 80/60 기반 추천 로직을 JD 기준 점수 기반으로 대체하거나 병행할지 정책 결정 필요

---

## [2026-06] 공고/JD 중심 구조 전환 — 남은 TODO

> 배경: 채용 단위를 부서/팀 → 공고(job_posting)/JD 로 전환. Step01~04(DB SQL·공고/JD 백엔드·공고/JD 관리 화면)는 완료(코드), DB SQL은 적용 대기. 아래는 남은 작업.

### 즉시 필요 (전환 완료 핵심)
- [ ] **DB SQL 적용**: `docs/sql/2026-06-12-posting-jd.sql` 을 resume_ai 대상으로 실행(신규 테이블/컬럼/인덱스). 적용 전까지 공고/JD 기능 동작 불가.
- [ ] **이력서 등록 공고 전환(Step05)**: 업로드 API `posting_id` 기반화, `resume_files.posting_id/jd_id/dept_id(=공고부서)` 저장, JD 미등록 공고 업로드 차단, 공고 Drive 폴더(없으면 생성) 사용.
- [ ] **분석 공고 전환(Step06)**: pending/분석을 `posting_id`→active JD 기준으로. `analysis_results.posting_id/jd_id/jd_snapshot` 저장. `POST /api/analysis/run/posting`. 전체분석 ADMIN 전용 유지. (산식/프롬프트 불변)
- [ ] **현황 공고 전환(Step07)**: `GET /api/resumes/status` 에 `posting_id` 필터 + 응답 `posting_title/jd_id`, 목록 공고명 컬럼, 상세 공고명/JD명. 미매핑(`posting_id IS NULL`) "-" 방어.

### Drive
- [ ] 공고별 Drive 폴더 구조 `postings/{부서}/{공고}/inbox|completed|failed` 동기화/재동기화 기능(기존 부서 동기화 유지하며 추가).
- [ ] `job_postings.drive_*_folder_id` 채우는 시점 정책(공고 등록 시 vs 업로드 시 lazy 생성) 확정.

### 감사 로그
- [ ] `audit_logs` 모델 + `AuditLogService.log(...)`(실패 무시) 추가. 이벤트: 공고 등록/수정, JD 등록/수정, 업로드, 분석 실행, 전체 분석(ADMIN). 상세조회/다운로드 로그는 기존 정책과 통합.

### 확장/고도화
- [ ] **1공고 N JD** 확장(현재 service 에서 1 active 강제 → 다중 active/버전 정책).
- [ ] JD 변경 이력/snapshot 관리(분석 시 jd_snapshot 활용 + 화면 표시).
- [ ] 외부 플랫폼 API 자동 연동(사람인/잡코리아/원티드 공고 자동 수집·등록).
- [ ] 공고별 대시보드, 공고별 추천 결과 화면.
- [ ] 분석 job/queue 구조 전환(동기 분석 → 비동기 큐).
- [ ] 기존 부서 중심 legacy 데이터 → posting 매핑 마이그레이션(또는 "미매핑" 유지 정책).

### 정리 대상 (영향도 확인 후)
- [ ] legacy 부서 중심 JD 화면(`view-jd`)·`jd_router`/`jd_service`/`jds_router`·관련 JS(saveJd/recommendJd) — 공고/JD 로 완전 흡수 후 제거 여부 결정. (현재는 호환 위해 유지)

---

## [2026-06-12] 공고/JD 중심 UI 전환 — 완료 및 남은 TODO

> 이전 "[2026-06] 공고/JD 중심 구조 전환" 섹션의 항목 중 아래가 **완료**되었습니다(코드 + 라이브 DB/Drive 검증):
> DB SQL 적용 / Drive 공고 폴더 자동 생성 / 이력서 등록·분석·현황 공고 기준 전환(Step05~07) /
> 공고 목록 날짜·jd_status 필터 / 권한범위 부서검색 API / 공고 검색바(오늘·날짜) / 분석 작업 관리 공고 리스트+체크박스 / 전체 분석 ADMIN 전용.

### 남은 TODO
- [ ] **추천 결과 관리** 화면을 공고/JD 단위로 구현(현재 미구현 안내 화면).
- [ ] **audit_logs** 테이블/서비스 추가 후 공고 등록·JD 등록·업로드·분석·전체분석 이벤트 기록(실패 무시). *(현재 audit 인프라 없음 → 본 전환에서는 미적용)*
- [ ] **1공고 N JD** 확장(현재 service 에서 1 active 강제) + JD 변경 이력/`jd_snapshot` 활용 화면.
- [ ] 공고 폴더 **재동기화/이름변경** 기능(현재 등록 시 생성만). 공고 삭제 시 Drive 폴더 정리 정책.
- [ ] 외부 플랫폼 API 자동 연동(사람인/잡코리아/원티드 공고 자동 수집·등록).
- [ ] 분석 **비동기 job/queue** 전환(현재 동기). 공고별 대시보드.
- [ ] legacy 정리(영향도 확인 후): 부서 트리 기반 JD 화면(`view-jd`)·`jd_router`/`jds_router`, 부서 기준 `analyze-pending`(legacy) 엔드포인트, 업로드 `dept_id` 폼 파라미터.
- [ ] 이력서 등록 결과의 `drive_path_display` 를 공고 폴더 경로로 정확히 표기(현재 cosmetic).
- [ ] 기존 부서 중심 legacy 데이터의 공고 매핑 마이그레이션(또는 "미매핑" 유지 정책 확정).

---

## [2026-06-12] 공고 Drive 정책/UX 보정 — 완료 및 남은 TODO

> 완료: Drive 공고 폴더 생성 시점 = **JD 등록 완료 시점**(멱등), 폴더 구조에서 **부서 폴더 제거**(`inbox|completed|failed/{JP코드_공고명}`),
> 검색바 한 줄 정리(공고명 검색 input 폭 버그 수정)·Enter 검색(공고명/날짜), 공고/JD 목록 테이블 가독성 개선,
> 분석 작업 관리 공고 리스트 compact 카드화.

### 남은 TODO
- [ ] **기존 `postings/{부서id_부서명}/{공고}/...` 폴더 구조 정리/마이그레이션**(현재 신규는 새 구조, 기존은 삭제 안 함). 이미 그 구조로 만들어진 공고의 folder id 는 그대로 동작.
- [ ] **Drive 폴더 재생성/복구 버튼**(공고 상세에서 폴더 누락 시 수동 재생성).
- [ ] **JD 저장 성공 후 Drive 생성 실패 시 재시도 UX**(현재는 한 트랜잭션 롤백 = JD 저장 실패 처리. 사용자 재시도로 충분하나, "JD는 저장 + Drive만 재생성" 분리 옵션 검토).
- [ ] **공고명 변경 시 Drive 폴더명 변경 여부 정책**(현재 폴더명은 생성 시점 공고명 고정, rename 안 함).
- [ ] **1공고 N JD** 확장(현재 1 active 강제).

---

## [2026-06-12] 공고/JD UI 정리 + 추천 JD 복구 — 완료 및 남은 TODO

> 완료: 검색/초기화 버튼 한 줄 그룹화(`toolbar-actions`)·날짜 Enter 검색, 이력서 현황 Excel 우상단 이동,
> 이력서 현황 부서 트리 카드 max-height+내부 스크롤(페이지 스크롤 방지), **상위 부서 이름 클릭 선택**(화살표=펼치기/접기),
> 공고 모달 공고/JD 카드 분리·버튼 우측 정렬, **추천 JD 기능 복구**(`POST /api/job-postings/{id}/jd/recommend`).

### 남은 TODO
- [ ] 추천 JD 프롬프트에 **플랫폼/공고 URL/기존 입력값** 반영(현재는 공고명+부서명 기반으로 레거시 `recommend_jd` 재사용). 필요 시 공고 전용 프롬프트 분리.
- [ ] 부서 트리 패널 `max-height: calc(100vh - 230px)` 상수의 화면별 미세조정(작은 화면 대응).
- [ ] 추천 결과 관리 화면(공고/JD 단위) 구현.
- [ ] (이전 누적) 기존 `postings/{부서}/...` Drive 폴더 마이그레이션, Drive 폴더 재생성/복구 버튼, 1공고 N JD, audit_logs 서비스.

---

## [2026-06-12] 화면 레이아웃 보정 — 완료 및 남은 TODO

> 완료: 검색 필터 한 줄 정리(select/input 폭 축소 + `toolbar-actions` 그룹), 이력서 현황 부서 트리
> 카드 `overflow:hidden` + `max-height` 로 페이지 스크롤 제거(트리 내부 스크롤), 분석 작업 관리 본문
> width 확대(`analysis-split`: 좌 400px / 우 남은 폭 전부). HTML/CSS만 변경(기능/DB/분석 로직 불변).

### 남은 TODO
- [ ] 부서 트리 패널 `max-height: calc(100vh - 240px)` 상수의 화면별 미세조정(작은/큰 화면).
- [ ] 초대형 모니터에서 분석 좌측 공고 카드 400px 고정 비율 재검토(반응형 grid 고려).
- [ ] 매우 좁은 화면에서 toolbar 2줄 wrap 시 그룹 정렬/여백 점검.

---

## [2026-07-07] Alembic 마이그레이션 정리 (수동 SQL 편입) — 완료 및 남은 TODO

> 배경: DB 스키마가 Alembic `0001`(초기 6테이블) + 수동 SQL(`docs/sql/2026-06-12-*.sql`) + 외부 `users` DDL 로 분산되어 있어, 빈 DB 를 `alembic upgrade head` 한 번으로 재현할 수 없었음. 이를 마이그레이션으로 일원화.

### 완료
- [x] **users DDL 편입**: `0002_create_users_table`(모델 기준 신규 — 기존엔 "이미 생성되어 있다고 가정"이던 테이블).
- [x] **공고/JD 편입**: `0003_create_job_postings_and_jds`(`job_postings` + `job_posting_jds`, FK/인덱스 포함) — `docs/sql/2026-06-12-posting-jd.sql` (1·2).
- [x] **resume 테이블 컬럼 편입**: `0004_add_posting_jd_columns`(`resume_files`/`resume_analysis_results` 의 `posting_id`/`jd_id`/`jd_snapshot` + 인덱스) — 같은 SQL (3·4).
- [x] **부서 nullable 편입**: `0005_job_posting_dept_nullable`(`job_postings.department_id` NOT NULL 해제) — `docs/sql/2026-06-12-job-postings-dept-nullable.sql`.
- [x] **ORM drift 보정**: `JobPosting.department_id` `nullable=False → True`, `resume_files`/`resume_analysis_results` 모델에 `posting_id`/`jd_id` 인덱스 선언 추가(마이그레이션과 정합).
- [x] **idempotent 작성**: 모든 신규 리비전을 `IF NOT EXISTS`/`DROP NOT NULL` 로 작성 → 기존 DB 에서도 `upgrade head` 무충돌(빈 DB / 기존 DB 시뮬레이션 양쪽 검증 완료).
- [x] **문서화**: README "DB 초기화 / 마이그레이션 (Alembic)" 섹션, WORKFLOW 초기 설정 플로우, 작업 로그(`docs/work-log/2026-07-07-alembic-schema-sync.md`).
- [x] **수동 SQL 선실행 불필요화**: `docs/sql/*.sql` 은 참고용(원본 기록)으로만 유지.

### 남은 TODO
- [ ] **운영 DB 반영**: 운영/개발 DB 에서 `alembic upgrade head`(권장, idempotent) 또는 스키마 확인 후 `alembic stamp head`. *(실제 운영 DB 접속은 이번 작업 범위 밖 — 반영 담당자가 수행)*
- [ ] **soft-reference FK/인덱스 정책 확정**: 현재 FK(`fk_job_postings_created_by` 등)와 `ix_job_postings_created_at`(DESC)·중복 `ix_analysis_results_resume_file_id` 는 DB(마이그레이션)에만 있고 ORM 에는 없음 → `alembic revision --autogenerate` 사용 금지(제거 제안됨), **손으로 리비전 작성** 유지. ORM 에 FK 를 넣을지 여부는 별도 결정.
- [ ] **중복 인덱스 정리 여부**: `resume_analysis_results.resume_file_id` 에 `ix_resume_analysis_results_resume_file_id`(0001) + `ix_analysis_results_resume_file_id`(수동 SQL) 2개 존재. 프로덕션 재현 위해 유지 중 — 후속에서 하나로 정리 검토.
- [ ] **보안(이번 범위 밖)**: `.env.example` 에 실제 키/비밀번호로 보이는 값 커밋 여부 점검·교체, 인증 없는 관리 API(`/api/drive`,`/api/db`,`/api/departments` 등) 인증 적용 검토.

---

## [2026-07-07] 사람인 디딤(주) 신규 공고 자동 수집 배치 — 완료 및 남은 TODO

> 배경: 수동 공고 URL 분석/등록은 이미 가능. 사람인 '디딤' 검색 결과를 주기적으로 확인해 디딤(주) 신규 공고를 자동 등록하는 배치 구조 추가. 상세 분석/JD 저장/Drive 폴더는 기존 로직 재사용.

### 완료
- [x] **검색 결과 수집기**: `app/services/saramin_job_collect_service.py`(정적 fetch 재사용 + 카드 파싱 + 회사명 normalize + rec_idx/detail_url 정규화).
- [x] **회사명 필터**: 디딤(주)/디딤 (주)/디딤 주식회사 만 exact(normalize 후) 통과, 다른 '디딤' 계열 제외(단위 검증 완료).
- [x] **발견/중복/등록 서비스**: `app/services/job_posting_discovery_service.py`(detail_url·rec_idx 중복 확인 → 신규만 insert → `job_extract_service.extract_from_url` 재사용 → `job_posting_service.create_posting`/`upsert_jd`). 공고 단위 try/except 격리.
- [x] **수동 실행 API**: `POST /api/jobs/discover/saramin/didim`(ADMIN/MANAGER). 카운트/항목별 상태 요약 반환.
- [x] **스케줄러 코드**: `app/services/scheduler_service.py`(진입점 `run_saramin_didim_discovery()` + 1시간 interval 등록) — **실제 등록은 주석 처리**(startup 자동 실행 안 함).
- [x] **설정 분리**: `SARAMIN_DIDIM_SEARCH_URL`/`_KEYWORD`/`_COMPANY_NAME`/`SARAMIN_DISCOVERY_ENABLED`(config + .env.example).
- [x] **검증**: 순수 함수(회사명/URL/파싱) + DB 통합(신규 insert→재실행 duplicate skip) + 실패 격리(하나 실패해도 배치 계속) 일회용 Postgres 로 확인.
- [x] **문서화**: README/WORKFLOW/작업 로그(`docs/work-log/2026-07-07-saramin-job-discovery-batch.md`).

### 남은 TODO (후속 작업)
- [ ] **실제 운영 스케줄러 활성화**: `apscheduler` 의존성 추가(`uv sync`) → `scheduler_service.start_scheduler()` 주석 해제 → `SARAMIN_DISCOVERY_ENABLED=true` 일 때 startup 에서 단일 프로세스로 호출. (다중 워커 중복 실행 주의)
- [ ] **관리자 화면에서 수집 결과 확인**: 현재는 API 응답/로그로만 확인. 수동 실행 버튼 + 결과 요약 화면(공고/JD 관리) 추가 검토.
- [x] **플랫폼 확장(잡코리아)**: `jobkorea_job_collect_service` 추가(2026-07-08). 원티드 등은 후속. external_id 컬럼은 계속 미추가(URL 컬럼 + 플랫폼 스코프로 중복 판단).

### [2026-07-07] 3차 — URL 수집 파서 fallback 보강
- [x] **사람인 공고 URL 수집 fallback 보강**: 정적 HTML 파싱을 3단계로 견고화 — 1차 `item_recruit` 카드, 2차 `corp_name` 세그먼트 + `a.str_tit`/`a[id^=rec_link_]`/`relay/view href` 결속(카드 클래스 변경 대응), 3차 링크 전체 스캔(감지/로깅). rec_idx dedupe(1차 우선, 제목 비면 2차 보강), 회사명 결속 없는 링크는 미등록. mock 8케이스 검증.
- [ ] **브라우저 렌더링 DOM fallback(Playwright/Selenium) 검토**: **라이브 검증 결과, 대상 검색 URL 의 결과 목록이 JS 렌더링**이라 정적 HTML 에 상세 링크(`str_tit`/`rec_link_`/`relay/view`/`rec_idx`)가 전혀 없어 **정적 수집 0건**(HTML 1.99MB, title "총 387건"은 서버렌더, 목록은 클라이언트 렌더). 실제 라이브 수집은 렌더링 DOM fallback 필요(이번 범위 제외). 도입 시 Docker chromium/이미지 크기/실행 검토.
- [ ] **사람인 HTML 구조 변경 모니터링**: 파서는 정규식 기반 — `parser_missed`/`link_scan`/`rec_fail` 로그로 구조 변화 감지, 필요 시 파서 수정.

---

## [2026-07-07] Celery/Redis 도입 1차 — 공고 JD 분석 비동기화 — 완료 및 남은 TODO

> 배경: 사람인 신규 공고 발견 후 JD 분석(상세 URL 분석 + JD 저장 + Drive 폴더)을 Celery worker 로 분리(1차). 이력서 분석 비동기화는 2차. (근거: `docs/work-log/2026-07-07-celery-redis-job-posting-jd-analysis.md`)

### 완료 (1차)
- [x] Redis/Celery 연결 구조 추가(`celery`/`redis` 의존성, `config.py` `CELERY_*` 설정, `.env.example` 섹션).
- [x] Celery app 추가(`app/core/celery_app.py`, 큐 `job_discovery`).
- [x] JD 분석 task 추가(`app/tasks/job_posting_tasks.py` `analyze_job_posting_jd_task(posting_id, requested_by_user_id)`): SessionLocal 신규 개설/close, idempotent skip, 상태 전이 JD_PROCESSING→JD_READY/JD_FAILED, 기존 `job_extract_service`/`job_posting_service` 재사용, 제한 재시도.
- [x] 사람인 배치를 **동기 분석 → enqueue** 로 전환(`job_posting_discovery_service`): 신규 공고 insert 후 `posting_id` 만 큐에 넣고 status=JD_QUEUED. 수동 API 응답에 `queued_count`/`status: JD_QUEUED` 반영.
- [x] Celery worker 서비스 + Redis 서비스 compose 추가(`docker-compose.yml`, worker 는 app 과 동일 이미지/.env/볼륨).
- [x] JD 생명주기 상태(JD_QUEUED/JD_PROCESSING/JD_READY/JD_FAILED)를 사용자 편집 `VALID_STATUS` 와 분리(전용 헬퍼 `mark_jd_lifecycle_status` — UI 상태 목록 불변).
- [x] 검증: compileall / celery app import / redis PONG / worker 기동(broker 연결·task 등록·ready) / eager 모드 통합(enqueue→JD_READY, 중복 skip, 멱등 skip, 실패 JD_FAILED).

### 남은 TODO (2차 이후)
- [x] **이력서 분석 `analyze_posting` Celery 전환**(`/api/resumes/analyze-posting`·`analyze-selected`·`analyze-all`) — 2026-07-07 완료([2차] 섹션 참고).
- [ ] **작업 상태 조회 API + 화면 polling**(analysis job 상태), 필요 시 `analysis_jobs` 테이블 신설 검토.
- [ ] **`resume_analysis` 전용 큐 분리** + worker scale/동시성 정책.
- [ ] 운영 스케줄러 주석 해제(사람인 1시간 주기, `apscheduler` 도입 시).
- [ ] Redis 운영 보안(비밀번호/네트워크 제한), worker 모니터링/실패 알림, task 결과 보존 정책.
- [ ] 레거시 부서 중심 `analyze_pending`/`batch_service` 는 **큐 전환 대상 아님**(공고 중심만).

---

## [2026-07-07] Celery/Redis 2차 — 이력서 분석 비동기화 — 완료 및 남은 TODO

> 배경: 공고 기준 이력서 분석(`/api/resumes/analyze-posting`·`analyze-selected`·`analyze-all`)을 요청 스레드 직접 실행 → Celery `resume_analysis` 큐 비동기로 전환. 기존 `resume_analysis_service.analyze_posting` 재사용. (근거: `docs/work-log/2026-07-07-celery-resume-analysis-phase2.md`)

### 완료 (2차)
- [x] `resume_analysis` 전용 큐 추가(celery_app `task_routes`로 모듈별 라우팅, worker `-Q job_discovery,resume_analysis`).
- [x] 이력서 분석 task 추가(`app/tasks/resume_analysis_tasks.py` `analyze_resume_posting_task(posting_id, resume_file_ids, requested_by_user_id)`) — 기존 `analyze_posting` 재사용, 파일 단위 격리 유지, 상태 매핑 COMPLETED/PARTIAL_FAILED/FAILED, no-pending skip(멱등), Drive 인증 실패만 제한 재시도.
- [x] `analyze-posting`/`analyze-selected`/`analyze-all` 모두 enqueue 전환(즉시 `QUEUED` 응답 + task_id/queue). `analyze-all`은 공고 단위 task 로 분할 enqueue(타임아웃 회피).
- [x] 중복 enqueue 방지: 공고에 PROCESSING 있으면 `ALREADY_PROCESSING`, PENDING 없으면 `NO_PENDING`(신규 헬퍼 `get_posting_analysis_status_counts`). 선택 분석은 PENDING 파일만 대상.
- [x] 권한 검사 API 진입 시점 유지(ADMIN/MANAGER, 공고 권한 범위; analyze-all ADMIN 전용). worker 는 `requested_by_user_id` 기록용.
- [x] 프론트 최소 수정: 분석 요청 성공 시 "큐에 등록되었습니다" 안내 + 기존 목록/현황 새로고침(`showAnalysisSummary` queue-aware). 자동 polling 미도입.
- [x] compose worker 두 큐 처리로 수정. 문서(README/WORKFLOW/work-log) 갱신.
- [x] 검증: compileall / celery import(두 task·라우팅) / worker 두 큐 기동 / eager 통합(QUEUED·중복가드·selected·상태매핑·no-pending) — 일회용 Postgres+Redis.

### 남은 TODO (3차 이후)
- [ ] **작업 상태 조회 API + 화면 polling**(현재는 이력서 현황 새로고침으로 확인). 필요 시 `analysis_jobs`(task_id/status/counts) 테이블 신설 검토.
- [ ] **worker 분리/scale**: `resume_analysis` 전용 worker, 동시성/prefetch 정책, 대량 `analyze-all` 부하 분산.
- [ ] 미사용 코드 정리: `_run_analysis_over_depts`(legacy), 프론트 `renderAnalysisResults`(비동기 전환으로 미호출) 제거 여부.
- [ ] task 결과 보존/모니터링, 실패 재처리 UX(부분 실패 파일 재분석).

---

## [2026-07-07] 공고 중심 플로우 확정 + 레거시 부서 중심 정리 — 완료 및 남은 TODO

> 배경: 부서 중심 → 공고 중심 전환 과도기. 실제 프론트/라우터/서비스 사용처를 확인해 공고 중심을 공식 주력 플로우로 확정하고, 레거시 부서 중심 경로를 삭제하지 않고 `LEGACY` 표시 + 문서화. (근거: `docs/work-log/2026-07-07-job-posting-flow-consolidation.md`)

### 완료
- [x] **사용처 확인**: 프론트 런타임 fetch 기준 분류. 프론트는 공고 중심 API(job-postings/resumes analyze-posting·selected·all)만 호출. 레거시 `/api/depts`·`/api/uploads`·`/api/analyze`·`/api/resume` 는 런타임 호출 없음(app.js 헤더 주석에만 존재). `view-jd`(→`/api/jd`) 화면은 메뉴 미연결로 도달 불가(orphaned).
- [x] **LEGACY 표시(동작 불변)**: 라우터 `dept_router`/`upload_router`/`resume_router`/`analyze_router`/`jd_router`/`jds_router`, 서비스 `batch_service`/`upload_service`/`jd_service`/`jd_db_service`/`dept_service`, 모델 `job_description`, KEEP 모듈 내 레거시 경로(`resume_analysis_service.analyze_pending`, resumes_router `/analyze-pending`·미사용 `_run_analysis_over_depts`)에 주석 추가. `app/main.py` include 블록에 KEEP/INFRA/LEGACY 분류 주석.
- [x] **신규 배치 레거시 결합 제거**: `job_posting_discovery_service` 가 legacy `jd_service.parse_skill_text` 를 import 하던 것을 로컬 `_parse_skills` 로 대체(공고 중심 배치가 legacy 모듈에 의존하지 않도록).
- [x] **문서화**: README(공식 주력/레거시 표), WORKFLOW(공식 9단계 + Legacy 섹션), work-log.

### 남은 TODO (후속)
- [ ] 레거시 부서 중심 라우터 **실제 사용 여부 최종 확인**(로그/모니터링) 후 제거 여부 결정.
- [ ] **LEGACY_USED → 공고 중심 전환**: 현재 프론트가 쓰는 레거시는 없음. 만약 남은 참조가 발견되면 공고 중심 API 로 전환.
- [ ] 사용 중단 확정 후 `dept`/`upload`/`resume`/`analyze`/`jd`/`jds` legacy router **제거**(그때 `app/main.py` include 및 관련 서비스/스키마 정리).
- [ ] `job_descriptions` 테이블 **신규 사용 중단 확인** 후 정리(테이블/데이터는 임의 삭제 금지 — 별도 마이그레이션 검토).
- [ ] `resume_analysis_service.analyze_pending` **신규 사용 금지** 유지(공고 기준 `analyze_posting` 로 일원화). 미사용 `_run_analysis_over_depts` 헬퍼 제거 검토.
- [ ] **Celery 도입 시** `analyze_posting`(+`job_extract_service`/`job_posting_service`)만 큐에 태우기. `analyze_pending`/`batch_service` 는 대상 아님.
- [ ] **인증 없는 legacy/admin API 정리**: `resume_router`(/api/resume, 인증 없음), `drive_router`/`departments_router`/`db_router`/`dept_router`/`upload_router` 인증 적용 검토(이전 보안 이슈와 통합).
- [ ] legacy 화면 코드(`view-jd` 섹션 + app.js `loadJd`/`saveJd`/`recommendJd`) 제거 여부 결정(현재 메뉴 미연결로 비활성 — 프론트 변경은 별도 작업).

---

## [2026-07-08] 잡코리아 수집 배치 + platform_code 자동 매핑 + 테이블 리스트업 — 완료 및 남은 TODO

> 배경: 사람인 배치에 더해 잡코리아 신규 공고 수집을 추가하고, URL→platform_code 자동 매핑을 확정. 미사용 테이블은 삭제 없이 리스트업만. (근거: `docs/work-log/2026-07-08-jobkorea-collector-and-table-usage.md`, `docs/db-table-usage-analysis.md`)

### 완료
- [x] **잡코리아 수집기**: `app/services/jobkorea_job_collect_service.py`(정적 SSR 파싱, `GI_Read/{gno}` canonical, `㈜→(주)` 후 사람인 `is_didim_company` 재사용). 라이브 read-only: cards=20 / 디딤(주) 12건 / parser_missed=0.
- [x] **배치 통합**: `job_posting_discovery_service` 를 플랫폼 공통 코어로 일반화(`discover_saramin_didim`/`discover_jobkorea_didim`), 중복 판단 플랫폼 스코프, **dry-run** 추가. `POST /api/jobs/discover/jobkorea/didim`(+`dry_run`), 사람인도 `dry_run` 지원. 스케줄러 `run_jobkorea_didim_discovery()`(등록은 주석 유지).
- [x] **platform_code 자동 매핑**: `job_extract_service.platform_code_for_url` 단일 진입점. `create_posting`/`update_posting` 이 URL 도메인으로 자동 채움(사용자 선택 존중, 미지원 도메인 None). saramin→SARAMIN / jobkorea→JOBKOREA / 기타→기존 기본값.
- [x] **테이블 사용 분석**: `docs/db-table-usage-analysis.md`(분류표 + 근거/선행작업/cleanup 초안). REMOVE_CANDIDATE(코드 미사용)=없음. legacy 제거 후보=`job_descriptions`/`dept_drive_folders`(삭제 미실행).
- [x] **테스트**: `tests/test_job_collectors.py`(plain-assert, pytest 미도입) ALL PASSED + 일회용 Postgres DB 통합(자동매핑/중복/ dry-run/사람인 회귀). 운영 DB 미접근.

### 남은 TODO (후속)
- [ ] **JobKorea collector fallback 안정화**: 잡코리아가 `data-sentry-component="Title"`/`GI_Read` 구조를 바꾸면 파서 수정 필요 → `parser_missed` 로그 감지, 속성 변경 대비 2차 파서 검토.
- [ ] **JobKorea 라이브 dry-run 정기 검증**: 실제 검색 URL 정기 점검(수집 0건/구조 변경 조기 감지).
- [ ] **platform_code enum/constraint 정리 필요 여부**: 현재 `VALID_PLATFORM`(SARAMIN/JOBKOREA/WANTED/ETC)은 서비스 레벨 검증만, DB check constraint 없음. 점핏/인크루트/커리어 등 확장 시 enum/제약 정식화 검토.
- [ ] **레거시 테이블 삭제 전 API/UI 호출 제거 확인**: `job_descriptions`/`dept_drive_folders` — `docs/db-table-usage-analysis.md` 6장 선행 작업(프론트 호출 제거·deprecated·백업·승인) 후에만 cleanup.
- [ ] **`analysis_jobs` 테이블 도입 검토**: 수집/분석 작업 상태 조회·재처리(사람인·잡코리아 배치 결과 포함).
- [ ] **Playwright 기반 collector fallback 검토**: 잡코리아는 현재 SSR 이라 불필요하나, 향후 JS 렌더링 전환/타 플랫폼 대비(도입 시 Docker chromium 검토).

---

## [2026-06-12] 목록 페이징 + 분석 작업 관리 3컬럼 — 완료 및 남은 TODO

> 완료: 공고/JD 관리·이력서 등록 공고 목록·분석 대기 파일 목록 **백엔드 페이징**(총 N건 + 20/30/50 select + 이전/다음),
> `GET /api/job-postings` page/size/`department_id`(subtree) + `{items,total,page,size}` 응답, posting-pending page/size,
> 분석 작업 관리 **3컬럼**(부서/팀 검색조건 → 공고/JD → 대기 파일) + 부서 트리 재사용 + 페이지 변경 시 체크 초기화.

### 남은 TODO
- [ ] 공고 목록 페이징이 현재 application-level slice(필터 후 전체 빌드 → slice). 공고 수가 매우 커지면 DB-level limit/offset + active JD 조인 최적화 검토.
- [ ] 분석 대기 파일 페이지 변경 시 선택 유지 옵션(현재는 안전하게 초기화).
- [ ] 대형 화면에서 분석 3컬럼 비율 반응형(부서 240 / 공고 320 고정 → 가변 검토).
- [ ] (이전 누적) postings/{부서} legacy 폴더 마이그레이션, Drive 폴더 재생성 버튼, 1공고 N JD, audit_logs, 추천 JD 프롬프트 고도화.

---

## [2026-06-12] 페이징 UI 보정 — 완료 및 남은 TODO

> 완료: 분석 작업 관리 공고/JD 목록 size select 제거 + **한 페이지 5개 고정**(이전/다음만),
> 이력서 현황 목록에 **20/30/50 page size select 추가**(기본 20, 백엔드 페이징 `GET /api/resumes/status?page&size` 연동, total 권한 필터 적용).

### 남은 TODO
- [ ] 분석 공고 목록 5개 고정값을 상수/설정으로 분리(추후 조정 대비).
- [ ] 이력서 현황 선택 size 를 세션/로컬에 기억(새로고침 후 유지) 검토.

---

## [2026-06-12] Drive 설정/동기화 legacy job_descriptions 카드 제거 — 완료 및 남은 TODO

> 완료: `관리자 > Drive 설정/동기화 > 부서 DB 동기화` 의 **`job_descriptions` 카드 제거**(카드/클릭 팝업/`GET /api/jds/status-by-department`/`jd_db_service.status_by_department`/관련 JS·CSS),
> `/api/db/counts` 에서 `job_descriptions` 카운트 제외. 부서/Drive 폴더 동기화 기능은 유지. 카운트는 departments/dept_drive_folders 2개만 표시.

### 남은 TODO
- [ ] legacy JD 시스템 전체 정리 여부 결정: `job_descriptions` 테이블 모델, `jds_router`(JD CRUD), `jd_router`(`/api/jd`), `jd_service`, `jd_db_service`, `resume_analysis_service` 의 부서 기준 분석 fallback. 공고/JD 전환이 완전히 끝나고 legacy 데이터 의존이 없을 때 일괄 제거.
- [ ] legacy `view-jd`(부서 중심 JD 관리 화면) DOM/JS(saveJd/recommendJd 등) 제거 여부 검토.

---

## [2026-06-12] 공고 URL LLM 자동 채우기 + JD 라벨 변경 — 완료 및 남은 TODO

> 완료: 공고 모달 JD 라벨(자격 요건/우대 사항/주요 업무, UI만), `POST /api/jobs/extract-from-url`(SSRF 방어 + 디딤(주) 검증 + LLM 추출),
> [공고 내용 가져오기] 버튼으로 비어 있는 입력값만 자동 채움(부서/팀 제외, 저장 안 함). 권한 ADMIN/MANAGER. 새 라이브러리 미추가.

### 남은 TODO
- [ ] 외부 채용 플랫폼별 크롤링/공식 API 정책 확인(robots/이용약관). 현재는 단순 GET + 평문 추출.
- [ ] 로그인 필요한 공고 페이지 처리 여부(현재 미우회 — 공개 페이지만).
- [ ] LLM 추출 정확도 개선 + 플랫폼별 HTML 구조 대응(사람인/잡코리아/원티드/점핏 등).
- [ ] **JD 필드명/DB 컬럼명 정식 리팩토링**: 화면은 자격요건/우대사항/주요업무이나 내부는 `required_skills`/`preferred_skills`(스킬 배열, 콤마·줄바꿈 split)/`jd_content` 유지 중 → free-text 분리 + 점수 산식 영향 검토.
- [ ] 자동 추출 결과 검수 UX 개선(추출된 항목 강조/되돌리기 등).
- [ ] 부서/팀 자동 매칭 정책 검토(현재 의도적으로 자동선택 안 함).
- [ ] 점핏(jumpit) 등 플랫폼 옵션 추가 여부 검토(현재 select 에 없으면 자동 선택 안 함).

---

## [2026-06-12] 공고/JD 통합 폼 + 부서 선택사항 + URL 자동채우기(JD 포함) — 완료 및 남은 TODO

> 완료: 부서/팀 선택사항(`job_postings.department_id` DROP NOT NULL), JD 카드 처음부터 표시(통합 입력),
> 저장 버튼 단일화(공고 등록/수정이 공고+JD 함께 저장), [공고 내용 가져오기]가 JD(주요업무/자격요건/우대사항)+플랫폼까지 채움,
> 이미 값 있으면 confirm 후 덮어쓰기(부서/상태 제외), LLM bullet 정리(`- `/빈줄 제거), platform 코드+라벨 응답.

### 남은 TODO
- [ ] **부서 미지정 공고의 이력서 업로드 처리**: `resume_files.dept_id` 가 NOT NULL 이라 부서 미지정 공고는 업로드 시 dept 복사가 불가 → 정책 결정(업로드 시 부서 요구 or dept_id nullable화).
- [ ] **공고+JD 저장 단일 트랜잭션화**: 현재 프론트가 공고 저장 → JD 저장 순차 2-API 호출(공고 성공·JD 실패 가능). 서비스 레벨 통합 저장 엔드포인트 검토.
- [ ] 플랫폼 select option 확장(점핏/인크루트/커리어 등 — 현재 option 없으면 자동 선택 안 함).
- [ ] 외부 플랫폼별 크롤링/API 정책, 로그인 공고 처리, LLM 추출 정확도/HTML 구조 대응.
- [ ] JD 필드/DB 컬럼 정식 리팩토링(자격요건/우대사항이 required_skills/preferred_skills 배열에 bullet 문자열로 저장 중).
- [ ] 자동추출 검수 UX(되돌리기/항목 강조), LLM 결과 줄바꿈/배열 변환 품질 개선.

---

## [2026-06-12] 공고 URL 자동채우기 → JD 영역/통합 저장 검증·보정 — 완료 및 남은 TODO

> 완료: [공고 내용 가져오기]가 JD(자격 요건/우대 사항/주요 업무)+플랫폼까지 채우고, 단일 저장 버튼이 공고+JD를 함께 저장함을 라이브 E2E로 검증.
> 공고 JD 저장 테이블은 **`resume_ai.job_posting_jds`**(job_descriptions 아님) 명확화. 추출 성공 후 JD 카드 자동 스크롤 + 메시지 보정, 캐시버스트 v49.

### 남은 TODO
- [ ] **공고 저장/JD 저장 트랜잭션 고도화**: 현재 프론트 순차 2-API(공고 성공·JD 실패 가능) → 서비스 레벨 통합 저장 엔드포인트(단일 트랜잭션) 검토.
- [ ] 부서 미지정 공고의 이력서 업로드(resume_files.dept_id NOT NULL) 처리 정책.
- [ ] 플랫폼별 크롤링/공식 API 정책, 로그인 필요 공고 처리.
- [ ] LLM 추출 정확도 개선 + 플랫폼별 HTML 구조 대응 + 줄바꿈/JSONB 배열 변환 품질.
- [ ] JD 필드/DB 컬럼 정식 리팩토링(자격요건/우대사항이 required_skills/preferred_skills 배열에 bullet 문자열로 저장 중).
- [ ] 자동추출 검수 UX 개선(되돌리기/항목 강조 등).

---

## [2026-06-12] 공고 수정 팝업닫기/안내문구/미처리요약/JD추출 정확도 — 완료 및 남은 TODO

> 완료: 공고 수정(및 등록) 전체 성공 시 팝업 자동 닫힘+목록 갱신, 통합 폼 안내문구 교체, 이력서 업로드 영역에 공고별 미처리(분석대기) 이력서 요약(posting-pending 재사용),
> JD 추출 정확도 개선(_html_to_text 섹션/표 구조 보존 + _build_prompt 섹션 라벨 동의어 분류). JD 저장 테이블은 `job_posting_jds`(주요 업무=jd_content).

### 남은 TODO
- [ ] **iframe/JS 렌더링 공고 본문 추출**: 사람인 등 일부 공고는 JD 본문이 iframe/스크립트로 로드되어 정적 GET HTML 에 없음 → 정적 추출 시 빈 값. 브라우저 자동화/플랫폼 전용 크롤러 없이 가능한 대안(공개 iframe URL 추적 등) 정책 검토.
- [ ] LLM 추출 정확도/플랫폼별 HTML 구조 대응 지속 개선.
- [ ] 공고 저장/JD 저장 단일 트랜잭션화(현재 프론트 순차 2-API).
- [ ] 주요 업무/자격 요건/우대 사항 DB 컬럼 정식 리팩토링 여부(현재 required_skills/preferred_skills 배열 + jd_content).
- [ ] 미처리 이력서 요약 UI 고도화(상태 badge/업로드일 등) + 업로드 영역 개인정보 노출 범위 검토.
- [ ] 자동추출 검수 UX(되돌리기/항목 강조), 줄바꿈/JSONB 배열 변환 품질.

---

## [2026-06-12] 사람인 JD 상세 iframe fallback 수집 — 완료 및 남은 TODO

> 완료: 사람인 공고 JD 가 JS 로드 iframe 에 있어 메인 정적 HTML 에 없던 문제를, 상세 URL(`relay/view-detail?rec_idx=`) **정적 fetch fallback**으로 해결(테스트 URL `rec_idx=53886522` 에서 collector_method=SARAMIN_DETAIL 로 주요 업무/자격요건/우대사항 3개 모두 채움). **Playwright 미도입**(정적 수집으로 충족 → pyproject/Dockerfile 변경 없음). 수집 fallback 구조(STATIC_HTML→SARAMIN_DETAIL→IFRAME) + 수집 실패 reason code + 부분 추출 시 경고 처리.

### 남은 TODO
- [ ] **순수 JS 렌더링 전용 공고 대응(Playwright/Selenium fallback)**: 정적·iframe 모두 본문이 없는 사이트는 현재 수집 불가. 도입 시 **Docker 이미지 크기/빌드시간/메모리 + chromium 설치(Dockerfile) + 로컬/Docker 실행** 검토 필요. (현재 사람인은 정적 상세 fetch 로 충족하므로 미도입)
- [ ] **플랫폼별 상세 URL/HTML 구조 대응**: 잡코리아/원티드/점핏 등 각 플랫폼의 JD 본문 위치(iframe/상세 endpoint) 매핑 추가.
- [ ] LLM 추출 정확도 개선 + 수집 실패 reason code 고도화(단계별 텍스트 길이/섹션 매칭 메트릭).
- [ ] 공고 저장/JD 저장 단일 트랜잭션화(현재 프론트 순차 2-API).
- [ ] 주요 업무/자격 요건/우대 사항 DB 컬럼 정식 리팩토링 여부(현재 required_skills/preferred_skills 배열 + jd_content).
- [ ] 자동추출 검수 UX 개선(추출 항목 강조/되돌리기, 수집 단계 표시).

---

## [2026-06-15] 공고명/JD명 추출 우선순위 수정 (모집분야 → 공고 상단 제목) — 완료 및 남은 TODO

> 완료: 공고명/JD명에 "모집분야"(`IDC 인프라 엔지니어`) 대신 공고 상단 제목(`og:title`/`<title>` 정적 추출, suffix 정리)을 우선 사용. `job_title = posting_title or llm_title`, 응답에 `posting_title`/`recruit_field` 분리. 테스트 URL `rec_idx=53886522` 에서 `job_title='IDC 인프라 운영 엔지니어 채용'`, JD 3개 영향 없음.

### 남은 TODO
- [ ] **플랫폼별 공고 제목 DOM selector 고도화**: 사이트별 상단 제목 영역(h1/제목 class) 매핑, og:title 부재/형식 상이 사이트 대응.
- [ ] **모집분야와 공고 제목 분리 저장 여부 검토**: 현재 `recruit_field` 는 응답 참고용만 — DB 컬럼 분리 저장 필요성 검토.
- [ ] **공고 제목 추출 실패 시 fallback 정책 개선**: 상단 제목/LLM 모두 빈 경우 사용자 입력 유도/경고 표기 정책.
