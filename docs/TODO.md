# TODO (남은 작업)

이 문서는 **아직 남아 있는 개발 항목**만 주제별로 통합해 정리합니다.
- 이미 **구현된 기능**은 [`../README.md`](../README.md) 의 "현재 구현된 기능" 을 참고하세요.
- **완료 내역**(날짜별 변경 이력)은 하단 [완료 아카이브](#완료-아카이브-요약) + 세부는 [`work-log/`](work-log/) 를 참고하세요.
- 정리 이력: 2026-07-08 기준으로 완료 항목/중복 항목을 압축(이전 날짜별 "완료 및 남은 TODO" 섹션 → 아카이브 1줄 요약).

---

## 미완료 (Open TODO)

### A. 채용 플랫폼 수집 / platform_code

- [ ] **JobKorea collector fallback 안정화 + 라이브 dry-run 정기 검증**: 잡코리아가 `data-sentry-component="Title"`/`GI_Read` 구조를 바꾸면 파서 수정 필요 → `parser_missed` 로그로 감지, 속성 변경 대비 2차 파서.
- [ ] **사람인 라이브 수집 한계 대응(Playwright/Selenium)**: 사람인 검색 목록은 JS 렌더링이라 정적 HTML 에 상세 링크가 없어 라이브 정적 수집 0건(파서는 마크업 존재 시 정확). 렌더링 DOM fallback 도입 시 Docker chromium/이미지 크기/실행 검토. 사람인 HTML 구조 모니터링(`parser_missed`/`link_scan`/`rec_fail`).
- [ ] **외부 플랫폼 공식 API 연동(원티드 등) 조사**: robots/이용약관/계약, 개인정보 동의 범위 확인(추측 금지). 무단 스크래핑 금지. API 없으면 CSV/ZIP 업로드 등 대안.
- [ ] **platform_code enum/DB constraint 정식화 여부**: 현재 서비스 레벨 `VALID_PLATFORM`(SARAMIN/JOBKOREA/WANTED/ETC)만 검증, DB check constraint 없음. 플랫폼 select 옵션 확장(점핏/인크루트/커리어) 시 함께 정식화.
- [ ] **운영 스케줄러 활성화**: `apscheduler` 도입(`uv sync`) → `scheduler_service.start_scheduler()` 주석 해제 → 사람인/잡코리아 1시간 주기 등록. `*_DISCOVERY_ENABLED=true` 일 때만, 단일 프로세스에서(다중 워커 중복 실행 주의).
- [ ] **관리자 화면에서 수집 결과 확인**: 현재 API 응답/로그로만 확인 → 수동 실행 버튼 + 결과 요약(공고/JD 관리) 화면.

### B. 비동기 작업 / 큐 (Celery)

- [ ] **`analysis_jobs` 테이블 + 작업 상태 조회 API/화면 polling**: 수집·분석 작업 상태(task_id/status/counts) 저장·조회(현재는 이력서 현황 새로고침으로만 확인).
- [ ] **worker 분리/scale**: `resume_analysis` 전용 worker, 동시성/prefetch 정책, 대량 `analyze-all` 부하 분산.
- [ ] **Redis 운영 보안 + 모니터링**: 비밀번호/네트워크 제한, worker 모니터링/실패 알림, task 결과 보존 정책.
- [ ] **실패 재처리 UX**: 부분 실패 파일 재분석, 이력서 상태값 재처리(FAILED→QUEUED) + 상태별 버튼/액션.
- [ ] (원칙 유지) 레거시 `analyze_pending`/`batch_service` 는 **큐 전환 대상 아님**(공고 중심 `analyze_posting` 만).

### C. 공고 / JD

- [ ] **1공고 N JD 확장**(현재 service 에서 1 active 강제) + JD 변경 이력/`jd_snapshot` 활용 화면.
- [ ] **공고+JD 저장 단일 트랜잭션화**: 현재 프론트 순차 2-API(공고 성공·JD 실패 가능) → 서비스 레벨 통합 저장 엔드포인트.
- [ ] **JD 필드/DB 컬럼 정식 리팩토링**: 화면 자격요건/우대사항/주요업무 ↔ 내부 `required_skills`/`preferred_skills`(배열) / `jd_content` → free-text 분리 + 점수 산식 영향 검토.
- [ ] **추천 JD 프롬프트 고도화**: 플랫폼/공고 URL/기존 입력값 반영(현재 공고명+부서명 기반 legacy `recommend_jd` 재사용).
- [ ] **추천 결과 관리 화면**(공고/JD 단위) 구현(현재 미구현 안내 화면).
- [ ] **부서 미지정 공고의 이력서 업로드 처리**: `resume_files.dept_id` NOT NULL → 정책 결정(업로드 시 부서 요구 or `dept_id` nullable화).

### D. URL / JD 추출 품질

- [ ] **LLM 추출 정확도 + 플랫폼별 HTML 구조 대응**: 플랫폼별 JD 본문 위치(iframe/상세 endpoint) 매핑, 줄바꿈/JSONB 배열 변환 품질, 수집 실패 reason code 고도화.
- [ ] **공고 상단 제목 추출 고도화**: 사이트별 DOM selector(h1/제목 class), `og:title` 부재/형식 상이 대응, 추출 실패 시 fallback 정책. `recruit_field`(모집분야) 분리 저장 여부 검토.
- [ ] **자동추출 검수 UX**: 추출 항목 강조/되돌리기, 수집 단계 표시.
- [ ] **기타**: 로그인 필요 공고 페이지 처리(현재 공개 페이지만), 부서/팀 자동 매칭 정책(현재 의도적으로 자동선택 안 함).

### E. Drive 폴더

- [ ] **공고 Drive 폴더 재동기화/재생성·복구 버튼**(현재 JD 저장 시점 생성만), 공고 삭제 시 폴더 정리 정책.
- [ ] **공고명 변경 시 Drive 폴더명 rename 정책**(현재 생성 시점 공고명 고정).
- [ ] **JD 저장 성공 후 Drive 생성 실패 재시도 UX**(현재 한 트랜잭션 롤백 = JD 저장도 실패). "JD 저장 + Drive만 재생성" 분리 옵션 검토.
- [ ] **기존 `postings/{부서}/...` legacy 폴더 마이그레이션**(신규는 새 구조, 기존 folder id 는 동작 유지), 이력서 등록 `drive_path_display` 공고 폴더 경로 정확 표기.

### F. 레거시 정리 (삭제 전 승인·백업 필수)

> 근거/선행 작업 체크리스트: [`db-table-usage-analysis.md`](db-table-usage-analysis.md) 6장. **임의 DROP/삭제 금지.**

- [ ] **레거시 부서 중심 라우터 제거**(실제 사용 여부 최종 확인 후): `dept`/`upload`/`resume`/`analyze`/`jd`/`jds` (+ `app/main.py` include, 관련 서비스/스키마 정리).
- [ ] **legacy 테이블 은퇴**: `job_descriptions`/`dept_drive_folders` — 프론트/API 호출 제거·deprecated·백업·승인 후 Alembic cleanup(제거 후보, 자세한 근거 = db-table-usage-analysis).
- [ ] **legacy 화면 코드 제거**: `view-jd` 섹션 + app.js `loadJd`/`saveJd`/`recommendJd`(현재 메뉴 미연결 orphaned).
- [ ] **미사용 코드 정리**: `resume_analysis_service._run_analysis_over_depts`(legacy), 프론트 `renderAnalysisResults`(비동기 전환으로 미호출).
- [ ] **legacy 데이터 → posting 매핑 마이그레이션**(또는 "미매핑" 유지 정책 확정).

### G. DB / 마이그레이션

- [ ] **운영/개발 DB 반영**: `alembic upgrade head`(권장, idempotent) 또는 스키마 확인 후 `alembic stamp head`. *(운영 DB 접속은 반영 담당자)*
- [ ] **soft-reference FK/인덱스 정책 확정**: DB 에만 있고 ORM 에 없는 FK/인덱스(`fk_job_postings_created_by`, `ix_job_postings_created_at` 등) → `--autogenerate` 금지, 손으로 리비전. 중복 인덱스(`resume_analysis_results.resume_file_id` 2개) 정리 여부.

### H. 대시보드 / 감사 로그 / 보안

- [ ] **대시보드**: 공고/부서/JD별 통계, 업로드/분석/실패 추이, OpenAI 사용량 — `GET /api/dashboard/*`.
- [ ] **`audit_logs` 테이블 + AuditLogService(실패 무시)**: 공고/JD 등록·수정, 업로드, 분석/전체분석, 상세조회/다운로드. (로그에 민감정보 저장 금지)
- [ ] **인증 없는 관리 API 정리**: `/api/drive`·`/api/db`·`/api/departments`·legacy(`resume`/`dept`/`upload`) 인증 적용 + `.env.example` 실제 키/비번 점검.

### I. UI / 페이징 미세조정

- [ ] 부서 트리 패널 `max-height` 화면별 미세조정, 분석 3컬럼 비율 반응형(부서/공고 고정폭 → 가변), 좁은 화면 toolbar wrap 정렬.
- [ ] 공고 목록 페이징 DB-level limit/offset 최적화(현재 app-level slice + active JD 조인), 분석 대기 파일 페이지 변경 시 선택 유지, 현황 page size 세션 기억, 분석 공고 목록 5개 고정값 상수화.
- [ ] 미처리 이력서 요약 UI 고도화(상태 badge/업로드일) + 업로드 영역 개인정보 노출 범위 검토.

### J. 배포 / 운영

- [ ] `deploy.sh`(압축→전송→원격 해제→compose up), compose 운영 명령 정리, DB 백업/복구(pg_dump), 로그 로테이션/수집, NCP ACG/방화벽, 장애 대응 순서. 추후 Git/GHCR/Jenkins/ArgoCD(CI/CD) 검토.
- [ ] 향후 권한 기반 플로우(역할별 메뉴/기능 노출) — WORKFLOW 7장 초안(미구현).

---

## 완료 아카이브 (요약)

> 세부 구현/검증 내역은 각 [`work-log/`](work-log/) 파일 참조. 아래는 완료된 큰 흐름의 1줄 요약입니다.

- [x] **2026-07-08 — 잡코리아 수집 배치 + platform_code 자동 매핑 + 테이블 사용 리스트업**: 잡코리아 SSR 수집기, 플랫폼 공통 discovery + dry-run, URL→platform_code 자동 매핑, `db-table-usage-analysis.md`. · [work-log](work-log/2026-07-08-jobkorea-collector-and-table-usage.md)
- [x] **2026-07-07 — 공고 중심 플로우 확정 + 레거시 LEGACY 표시**: 공고 중심을 공식 주력으로 확정, 부서 중심 경로 `LEGACY` 주석(삭제 안 함). · [work-log](work-log/2026-07-07-job-posting-flow-consolidation.md)
- [x] **2026-07-07 — Celery/Redis 2차(이력서 분석 비동기)**: `resume_analysis` 큐, `analyze-posting/selected/all` enqueue, 중복 가드, 파일 단위 격리. · [work-log](work-log/2026-07-07-celery-resume-analysis-phase2.md)
- [x] **2026-07-07 — Celery/Redis 1차(공고 JD 분석 비동기)**: `job_discovery` 큐, `analyze_job_posting_jd_task`, JD 생명주기 상태(JD_QUEUED→READY/FAILED). · [work-log](work-log/2026-07-07-celery-redis-job-posting-jd-analysis.md)
- [x] **2026-07-07 — 사람인 디딤(주) 수집 배치 + 파서 fallback**: 정적 수집기/회사명 필터/중복 판단, 파서 1·2·3차 견고화. · [batch](work-log/2026-07-07-saramin-job-discovery-batch.md) · [fallback](work-log/2026-07-07-saramin-url-collector-fallback.md)
- [x] **2026-07-07 — Alembic 마이그레이션 정리**: 수동 SQL/users DDL 편입(0002~0005), 빈 DB `upgrade head` 일원화, ORM drift 보정. · [work-log](work-log/2026-07-07-alembic-schema-sync.md)
- [x] **2026-06-15 — 공고명/JD명 추출 우선순위**(모집분야 → 공고 상단 제목 `og:title`/`<title>`). · [work-log](work-log/step-06-job-title-extraction-priority-fix.md)
- [x] **2026-06-12 — 공고/JD 중심 구조·UI 전환(Step01~07)**: DB SQL 적용, 공고 Drive 폴더 정책(JD 저장 시점 생성, 부서 폴더 제거), 공고+JD 통합 폼/부서 선택사항, URL LLM 자동채우기(JD 포함), 사람인 상세 iframe fallback, 목록 페이징/필터, 분석 작업 관리 3컬럼, legacy `job_descriptions` 카드 제거 등. · [work-log 2026-06-*](work-log/)
- [x] **(기반) 로그인(세션 인증) · RBAC(ADMIN/MANAGER/VIEWER + 부서 subtree) · 부서 트리/권한**: 구현 완료(이전 "1) 로그인" · "2) 권한관리" 계획 항목).
