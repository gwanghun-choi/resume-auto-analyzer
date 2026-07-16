// 화면 구조 (업무 메뉴 기반):
//  - 왼쪽 사이드바: 업무 메뉴만 표시 (채용 관리 > JD 등록 / 이력서 등록)
//  - 오른쪽 메인: 선택한 메뉴에 따라 화면(view) 전환
//      * JD 등록   : 부서 트리 + JD 수정 폼            (팀장 / JD 관리자용)
//      * 이력서 등록: 부서 트리 + 업로드 + 분석 + 결과   (HR 담당자용, JD 는 보이지 않음)
//
// 부서 트리는 두 화면에서 동일한 renderDeptTree() 함수로 재사용합니다.
//
// 사용 API (기존 그대로):
//   GET  /api/depts
//   GET  /api/jd/{deptId}
//   POST /api/jd/{deptId}
//   POST /api/uploads/{deptId}
//   POST /api/analyze/{deptId}/{uploadId}

// 화면별로 따로 기억하는 선택 상태
let jdSelectedDeptId = null;        // JD 관리 화면(legacy)에서 선택한 팀
let analysisRunning = false;        // 분석 실행 중 여부 (중복/동시 실행 방지)

// 이력서 현황 화면 상태 (검색/필터/페이징)
let statusFilterDeptId = null;    // 부서 필터 (null = 전체)
let statusPage = 1;               // 현재 페이지
let statusPageSize = 20;          // 페이지당 건수 (20/30/50 select)
let statusTotal = 0;              // 전체 건수
let statusLoadedOnce = false;     // 화면 첫 진입 시 1회 자동 조회용

// 부서 트리는 한 번 받아서 모든 화면 트리에서 재사용합니다. (재호출 방지용 promise 캐시)
// 데이터 원천: GET /api/auth/me/departments (로그인 사용자가 접근 가능한 부서만 내려옴)
let deptTreePromise = null;
let currentUser = null;            // /api/auth/me/departments 의 user (role_code 등)
let accessibleDepartments = [];    // 권한 있는 부서 flat list (검색/트리 구성 원본)

document.addEventListener('DOMContentLoaded', init);

function init() {
    setupMenu();
    // 로그인 사용자 정보 표시 + 로그아웃 연결 (세션 만료 시 /login 으로 이동)
    loadCurrentUser();
    document.getElementById('logoutBtn').addEventListener('click', logout);
    // 관리자 > 사용자 관리 화면 UI 연결 (ADMIN 만 메뉴 노출)
    setupAdminUsersUI();
    // 내 정보 수정 UI 연결 (우측 상단 이름 클릭)
    setupProfileUI();
    // 공고/JD 관리 화면 UI 연결
    setupJobPostingsUI();
    // 부서 트리는 JD(legacy) / 이력서 현황 화면에서만 사용합니다. (이력서 등록/분석은 공고 기준으로 전환됨)
    renderDeptTree(document.getElementById('jdDeptTree'), onJdTeamSelected);
    renderDeptTree(document.getElementById('statusDeptTree'), onStatusTeamSelected);
    setupDeptSearch('jdDeptSearchInput', 'jdDeptSearchBtn', 'jdDeptTree', onJdTeamSelected, () => jdSelectedDeptId);
    setupDeptSearch('statusDeptSearchInput', 'statusDeptSearchBtn', 'statusDeptTree', onStatusTeamSelected, () => statusFilterDeptId);

    // 이력서 등록 / 분석 작업 관리 (공고 기준) UI 연결
    setupResumeUI();
    setupAnalysisJobsUI();

    document.getElementById('saveJdBtn').addEventListener('click', saveJd);
    document.getElementById('recommendJdBtn').addEventListener('click', recommendJd);
    // 분석 작업 관리 화면(공고 기준): 선택 공고 분석 / 헤더 전체선택 / 선택 항목 / 전체(ADMIN)
    document.getElementById('analyzePostingBtn').addEventListener('click', runPostingAnalyze);
    document.getElementById('pendingSelectAll').addEventListener('change', togglePendingSelectAll);
    document.getElementById('analyzeSelectedBtn').addEventListener('click', runSelectedAnalyze);
    document.getElementById('analyzeAllBtn').addEventListener('click', runAllAnalyze);
    // 행 체크박스 변경 → 헤더 전체선택 동기화 + '선택 항목 분석 실행' 버튼 상태 갱신 (이벤트 위임)
    document.getElementById('pendingTableBody').addEventListener('change', (e) => {
        if (!e.target.classList.contains('pending-row-check')) return;
        const all = document.querySelectorAll('#pendingTableBody .pending-row-check');
        const checked = document.querySelectorAll('#pendingTableBody .pending-row-check:checked');
        const selAll = document.getElementById('pendingSelectAll');
        if (selAll) selAll.checked = (all.length > 0 && checked.length === all.length);
        updateAnalyzeSelectedState();
    });
    document.getElementById('syncDeptFoldersBtn').addEventListener('click', syncDeptFolders);
    document.getElementById('loadDeptConfigBtn').addEventListener('click', loadDeptConfig);
    document.getElementById('uploadDeptConfigBtn').addEventListener('click', uploadNormalizeDeptConfig);
    document.getElementById('validateDeptConfigBtn').addEventListener('click', validateDeptConfig);
    document.getElementById('saveDeptConfigBtn').addEventListener('click', saveDeptConfig);
    document.getElementById('driveUploadBtn').addEventListener('click', uploadResumesToDrive);
    document.getElementById('syncDeptDbBtn').addEventListener('click', syncDeptDbFromDriveConfig);

    // 이력서 현황 화면
    document.getElementById('statusSearchBtn').addEventListener('click', () => { statusPage = 1; loadResumeStatusList(); });
    // 파일명 검색 input 에서 Enter -> 검색 실행 (page 1, form submit 새로고침 방지)
    document.getElementById('statusKeyword').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); statusPage = 1; loadResumeStatusList(); }
    });
    document.getElementById('statusPostingKeyword').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); statusPage = 1; loadResumeStatusList(); }
    });
    // 업로드일 시작/종료 input 에서도 Enter 검색
    wireEnterSearch(['statusDateFrom', 'statusDateTo'], () => { statusPage = 1; loadResumeStatusList(); });
    document.getElementById('statusSizeSelect').addEventListener('change', (e) => {
        statusPageSize = parseInt(e.target.value, 10) || 20;
        statusPage = 1;
        loadResumeStatusList();
    });
    document.getElementById('statusTodayBtn').addEventListener('click', setStatusToday);
    document.getElementById('statusResetBtn').addEventListener('click', resetStatusFilters);
    document.getElementById('statusExcelBtn').addEventListener('click', downloadStatusExcel);
    document.getElementById('statusDeptAllBtn').addEventListener('click', clearStatusDeptFilter);
    document.getElementById('statusPrevBtn').addEventListener('click', () => { if (statusPage > 1) { statusPage--; loadResumeStatusList(); } });
    document.getElementById('statusNextBtn').addEventListener('click', () => {
        if (statusPage * statusPageSize < statusTotal) { statusPage++; loadResumeStatusList(); }
    });

    // 상세 보기 모달: 닫기 버튼 / overlay 클릭 / ESC 로 닫기
    document.getElementById('statusModalCloseBtn').addEventListener('click', closeStatusModal);
    document.getElementById('statusModalOverlay').addEventListener('click', (e) => {
        if (e.target.id === 'statusModalOverlay') closeStatusModal();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { closeStatusModal(); }
    });
}

// ---------- 사이드바 메뉴 ----------

// 다른 그룹은 모두 닫고(collapsed) 지정 그룹만 펼칩니다. (accordion: 한 번에 하나만 열림)
function openOnlyGroup(group) {
    document.querySelectorAll('.menu-group').forEach(g => g.classList.add('collapsed'));
    if (group) group.classList.remove('collapsed');
}

function setupMenu() {
    // 초기 진입 시 모든 그룹은 닫힘 상태(HTML 에 collapsed). 그룹 제목 클릭 시 accordion 토글.
    document.querySelectorAll('.menu-group-title').forEach(title => {
        title.addEventListener('click', () => {
            const group = title.closest('.menu-group');
            const willOpen = group.classList.contains('collapsed'); // 현재 닫혀 있으면 클릭 시 열기
            // 한 번에 하나만 열리도록 모두 닫은 뒤, 닫혀 있던 그룹이면 펼칩니다.
            document.querySelectorAll('.menu-group').forEach(g => g.classList.add('collapsed'));
            if (willOpen) group.classList.remove('collapsed');
        });
    });

    // 메뉴 항목 클릭 -> 해당 view 표시 + 활성화 표시 + 부모 그룹은 열린 상태로 유지(다른 그룹은 닫힘)
    document.querySelectorAll('.menu-item').forEach(item => {
        item.addEventListener('click', () => {
            // 외부 링크 메뉴(data-external): 새 탭으로 열고 화면 전환/active 변경은 하지 않습니다.
            if (item.dataset.external) {
                window.open(item.dataset.external, '_blank', 'noopener,noreferrer');
                return;
            }
            // 권한 없는 메뉴는 화면 전환하지 않고 안내만 표시 (DOM 잔존/직접 호출 방어)
            if (!canAccessSection(item.dataset.view, item.dataset.todo)) {
                notifyNoAccess();
                return;
            }
            openOnlyGroup(item.closest('.menu-group'));
            showView(item.dataset.view, item);
        });
    });
}

function showView(view, menuItemEl) {
    // 방어적 권한 체크: 직접/프로그램 호출(콘솔, hash 조작 등)로 권한 없는 화면 전환을 막습니다.
    const todoKey = menuItemEl ? menuItemEl.dataset.todo : undefined;
    if (!canAccessSection(view, todoKey)) {
        notifyNoAccess();
        return;
    }

    // 활성 메뉴 강조
    document.querySelectorAll('.menu-item.active').forEach(el => el.classList.remove('active'));
    menuItemEl.classList.add('active');

    // 메뉴 선택 전 안내 숨김
    document.getElementById('menuEmpty').classList.add('hidden');

    // 모든 view 숨기고 선택한 것만 표시
    document.querySelectorAll('.view').forEach(el => el.classList.add('hidden'));
    document.getElementById(`view-${view}`).classList.remove('hidden');

    // 미구현 메뉴(data-view="todo")는 공통 안내 화면을 메뉴별 내용으로 채웁니다.
    if (view === 'todo') {
        renderTodo(menuItemEl.dataset.todo);
    }

    // 관리자 > Google Drive 동기화 화면 진입 시 최근 동기화 상태 + DB count 를 조회합니다.
    if (view === 'driveSync') {
        loadDriveSyncStatus();
        loadDeptDbCounts();
    }

    // 이력서 현황 화면 첫 진입 시 전체 목록을 1회 자동 조회합니다.
    if (view === 'resumeStatus' && !statusLoadedOnce) {
        statusLoadedOnce = true;
        loadResumeStatusList();
    }

    // 사용자 관리 화면 진입 시 사용자 목록을 조회합니다. (ADMIN 전용)
    if (view === 'adminUsers') {
        loadAdminUsers();
    }

    // 공고/JD 관리 화면 진입 시 공고 목록을 조회합니다.
    if (view === 'jobPostings') {
        loadJobPostings();
    }

    // 이력서 등록 화면(공고 기준): 공고 목록 조회 + 업로드 패널 숨김
    if (view === 'resume') {
        loadResumePostings();
    }

    // 분석 작업 관리 화면(공고 기준): 공고 목록 + 대기 건수 조회
    if (view === 'analysisJobs') {
        loadAnalysisPostings();
    }
}

// ---------- 미구현 메뉴 공통 안내(TODO) 화면 ----------
// 메뉴별 안내 내용. (실제 기능 없음 — API 호출하지 않습니다.)
const TODO_INFO = {
    dashboard: { title: '대시보드 > 홈', items: [
        '전체 이력서 수, 오늘 업로드 수, 분석 대기/완료/실패 수',
        '부서별 이력서 수',
        '최근 업로드 및 최근 실패 목록',
    ] },
    recommendations: { title: '추천 결과 관리', items: [
        'JD별 추천 후보자 조회',
        '기준 점수 충족/미달 필터',
        '점수순 정렬 및 엑셀 다운로드',
    ] },
    talentpool_all: { title: '전체 인재풀', items: [
        '후보자 단위 통합 조회',
        '이름, 이메일, 연락처, 기술스택, 출처 관리',
    ] },
    talentpool_manual: { title: '수동 등록 인재', items: [
        '관리자가 직접 후보자 정보를 등록',
        '이력서 파일 첨부 및 기본 정보 입력',
    ] },
    talentpool_platform: { title: '플랫폼 연동 인재', items: [
        '사람인/잡코리아/원티드 등 외부 출처에서 수집된 후보자 관리',
        '실제 API 연동 전까지는 예정 화면으로 표시',
    ] },
    talentpool_dup: { title: '중복 후보자 관리', items: [
        '이메일/전화번호/이름 기준 중복 후보자 식별',
        '후보자 병합 또는 보류 처리',
    ] },
    talentpool_archive: { title: '아카이브', items: [
        '더 이상 진행하지 않는 후보자 보관',
        '필요 시 복원',
    ] },
    integration_platform: { title: '채용 플랫폼 연동', items: [
        { label: '사람인 API', url: 'https://oapi.saramin.co.kr/' },
        { label: '잡코리아 API', url: 'https://www.jobkorea.co.kr/service/api' },
        { label: '원티드 API', url: 'https://openapi.wanted.jobs/' },
        { label: '공식 API/계약 조건 확인 후 구현 예정' },
    ] },
    integration_import: { title: 'CSV/ZIP 가져오기', items: [
        '플랫폼에서 다운로드한 CSV 또는 ZIP 파일을 업로드하여 후보자/이력서 가져오기',
        '기존 수동 업로드 기능과 연계 예정',
    ] },
    integration_history: { title: '연동 이력', items: [
        '외부 연동 실행 내역',
        '성공/실패 결과 및 실패 사유 확인',
    ] },
    admin_users: { title: '사용자 관리', items: [
        '로그인 사용자 목록',
        '사용자 생성/비활성화/비밀번호 초기화',
    ] },
    admin_roles: { title: '권한 관리', items: [
        'ADMIN, HR, REVIEWER, VIEWER 역할 관리',
        '메뉴/API 접근 권한 제어',
    ] },
    admin_audit: { title: '감사 로그', items: [
        '로그인, 이력서 조회, 분석 실행, Drive 동기화 이력 기록',
        '개인정보 접근 로그 조회',
    ] },
    admin_settings: { title: '시스템 설정', items: [
        'OpenAI 모델명, 기본 기준 점수, 분석 재시도 횟수 등 운영 설정 관리',
    ] },
};

// TODO item 은 문자열 또는 { label, url } 객체. url 이 있으면 새 탭 외부링크로 표시.
function renderTodoItem(item) {
    if (typeof item === 'string') return `<li>${escapeHtml(item)}</li>`;
    if (item.url) {
        return `<li><a class="todo-link" href="${escapeHtml(item.url)}" target="_blank" `
            + `rel="noopener noreferrer">${escapeHtml(item.label)} <span class="ext-icon">↗</span></a></li>`;
    }
    return `<li>${escapeHtml(item.label)}</li>`;
}

function renderTodo(key) {
    const info = TODO_INFO[key] || { title: '준비 중', items: [] };
    document.getElementById('todoTitle').textContent = info.title;
    document.getElementById('todoDescription').textContent = '이 기능은 향후 구현 예정입니다.';
    document.getElementById('todoList').innerHTML =
        (info.items || []).map(renderTodoItem).join('');
}

// ---------- 인증(로그인 사용자 표시 / 로그아웃) ----------
// /api/auth/me 로 현재 사용자를 받아 상단 user-bar 에 표시합니다. 세션이 없으면(401) /login 으로 이동.
async function loadCurrentUser() {
    try {
        const res = await fetch('/api/auth/me');
        if (res.status === 401) {
            window.location.href = '/login';
            return;
        }
        if (!res.ok) return;
        const user = await res.json();
        currentUser = user;   // 전역 저장: 메뉴/화면 권한 분기에서 role_code 사용
        document.getElementById('userName').textContent = `${user.name}님`;
        document.getElementById('userRole').textContent = user.role_code;
        document.getElementById('userBar').classList.remove('hidden');
        // role_code 기준으로 좌측 메뉴 표시 권한 적용 (department_id 가 아니라 role 로 판단)
        applyMenuPermissions(user.role_code);
    } catch (e) {
        // 네트워크 오류 시에는 화면을 막지 않습니다. (표시만 생략)
    }
}

// ----- 메뉴/화면 권한 분기 (프론트 UX) -----
// 백엔드 인가는 이미 적용되어 있으며, 이 분기는 접근 불필요한 메뉴/화면을 보이지 않게 하는 UX 정리입니다.
// section(view) 별 접근 가능 role. data-view 가 'todo' 면 'todo:<data-todo>' 키로 조회하고,
// 미지정 todo(인재풀/연동/관리자 하위)는 기본 ADMIN 전용으로 처리합니다.
const SECTION_ROLES = {
    jobPostings: ['ADMIN', 'MANAGER', 'VIEWER'],   // 공고/JD 관리(조회는 VIEWER 도, 등록/수정은 백엔드에서 차단)
    jd: ['ADMIN', 'MANAGER'],
    resume: ['ADMIN', 'MANAGER'],
    resumeStatus: ['ADMIN', 'MANAGER', 'VIEWER'],
    analysisJobs: ['ADMIN', 'MANAGER'],
    driveSync: ['ADMIN'],
    adminUsers: ['ADMIN'],
    'todo:dashboard': ['ADMIN', 'MANAGER', 'VIEWER'],
    'todo:recommendations': ['ADMIN', 'MANAGER', 'VIEWER'],
};

function canAccessSection(view, todoKey) {
    const role = currentUser && currentUser.role_code;
    if (!role) return false;
    const key = (view === 'todo') ? `todo:${todoKey}` : view;
    const allowed = SECTION_ROLES[key] || ['ADMIN'];  // 미지정(인재풀/연동/관리자 등)은 ADMIN 전용
    return allowed.includes(role);
}

// data-roles(메뉴 그룹/항목) 기준으로 표시/숨김을 적용합니다. 하위가 모두 숨겨진 그룹은 그룹도 숨깁니다.
function applyMenuPermissions(role) {
    document.querySelectorAll('.menu [data-roles]').forEach(el => {
        const allowed = el.dataset.roles.split(',').map(s => s.trim());
        el.style.display = allowed.includes(role) ? '' : 'none';
    });
    document.querySelectorAll('.menu .menu-group').forEach(group => {
        if (group.style.display === 'none') return;
        const items = group.querySelectorAll('.menu-item');
        const anyVisible = Array.from(items).some(it => it.style.display !== 'none');
        if (items.length && !anyVisible) group.style.display = 'none';
    });
}

// 권한 없는 메뉴/화면 접근 시 안내 (별도 toast 영역이 없어 alert 사용)
function notifyNoAccess() {
    alert('접근 권한이 없습니다.');
}

// 로그아웃: 세션 제거 후 /login 으로 이동.
async function logout() {
    const btn = document.getElementById('logoutBtn');
    btn.disabled = true;
    try {
        await fetch('/api/auth/logout', { method: 'POST' });
    } catch (e) {
        // 실패해도 로그인 화면으로 보냅니다.
    } finally {
        window.location.href = '/login';
    }
}

// ---------- 부서 트리 (재사용 컴포넌트) ----------
// 화면 트리는 GET /api/auth/me/departments 를 사용합니다. (로그인 사용자 권한 범위 부서만)
//  - ADMIN  : 전체 부서 (department_id 값과 무관하게 전체 — 백엔드에서 보장)
//  - MANAGER/VIEWER : 본인 department_id + 하위 부서만
// flat list(departments) 를 parent_id 기준 중첩 트리로 변환해 기존 렌더러에 그대로 넘깁니다.

// 권한 부서 flat list -> 중첩 트리(노드: {id, name, children, ...}).
// parent_id 가 응답 목록에 없으면(권한 범위의 최상위) root 로 처리합니다. (MANAGER 의 시작 부서가 중간 노드일 수 있음)
function buildDepartmentTree(departments) {
    const byId = new Map();
    departments.forEach(d => byId.set(d.id, { ...d, children: [] }));
    const roots = [];
    departments.forEach(d => {
        const node = byId.get(d.id);
        if (d.parent_id && byId.has(d.parent_id)) {
            byId.get(d.parent_id).children.push(node);
        } else {
            roots.push(node);
        }
    });
    return roots;
}

// /api/auth/me/departments 를 한 번만 호출해 모든 화면 트리에서 공유합니다.
// 401(세션 만료) 이면 /login 으로 이동합니다.
function getDeptTree() {
    if (!deptTreePromise) {
        deptTreePromise = fetch('/api/auth/me/departments')
            .then(res => {
                if (res.status === 401) {
                    window.location.href = '/login';
                    throw new Error('미인증');
                }
                return res.json();
            })
            .then(data => {
                if (data.status === 'ERROR' || data.detail) {
                    throw new Error(data.error_message || data.detail || '부서 트리 로드 실패');
                }
                currentUser = data.user || null;
                accessibleDepartments = data.departments || [];
                return buildDepartmentTree(accessibleDepartments);
            })
            .catch(err => {
                // 실패 시 다음 호출에서 다시 시도할 수 있도록 캐시를 비웁니다.
                deptTreePromise = null;
                throw err;
            });
    }
    return deptTreePromise;
}

// containerEl 안에 부서 트리를 그립니다.
// onSelect(deptId, deptName, labelEl) 는 팀(잎 노드) 선택 시 호출됩니다.
// selectedId 가 주어지면 그 부서로 가는 경로(상위 노드들)를 자동으로 펼치고 선택 표시합니다.
async function renderDeptTree(containerEl, onSelect, selectedId) {
    containerEl.textContent = '불러오는 중...';
    try {
        const tree = await getDeptTree();
        // 선택 부서가 있으면 그 조상들만 펼침. 없으면 빈 집합(루트만 펼침).
        const expandPath = selectedId ? new Set(findAncestorIds(tree, selectedId) || []) : new Set();
        containerEl.innerHTML = '';
        containerEl.appendChild(buildTreeFromNodes(tree, onSelect, { expandPath, selectedId }, 0));
    } catch (e) {
        containerEl.textContent = '부서 목록을 불러오지 못했습니다. (관리자 > Google Drive 동기화에서 Drive config → DB 부서 동기화를 실행하세요)';
    }
}

// targetId 부서로 가는 경로의 '상위 노드 id 목록'을 반환합니다. (자기 자신은 제외) 없으면 null.
function findAncestorIds(nodes, targetId, trail) {
    trail = trail || [];
    for (const n of nodes) {
        if (n.id === targetId) return trail;
        if (n.children && n.children.length) {
            const found = findAncestorIds(n.children, targetId, trail.concat(n.id));
            if (found) return found;
        }
    }
    return null;
}

// 부서명에 keyword(소문자) 가 포함된 노드 + 그 상위 경로만 남긴 트리를 반환합니다. (부서명만 대상)
function filterTreeByName(nodes, kwLower) {
    const out = [];
    for (const n of nodes) {
        const children = (n.children && n.children.length) ? filterTreeByName(n.children, kwLower) : [];
        const selfMatch = n.name && n.name.toLowerCase().includes(kwLower);
        if (selfMatch || children.length) {
            out.push({ ...n, children });
        }
    }
    return out;
}

// 트리의 모든 노드 id 를 set 에 모읍니다. (검색 결과를 전부 펼치기 위함)
function collectAllIds(nodes, set) {
    for (const n of nodes) {
        set.add(n.id);
        if (n.children && n.children.length) collectAllIds(n.children, set);
    }
    return set;
}

// keyword 로 부서 트리를 필터링해 다시 그립니다. keyword 가 비면 전체 트리로 복원합니다.
async function renderDeptTreeSearch(containerEl, onSelect, selectedId, keyword) {
    const kw = (keyword || '').trim().toLowerCase();
    if (!kw) return renderDeptTree(containerEl, onSelect, selectedId);
    try {
        const tree = await getDeptTree();
        const filtered = filterTreeByName(tree, kw);
        if (!filtered.length) {
            containerEl.innerHTML = '<p class="hint">검색 결과가 없습니다.</p>';
            return;
        }
        // 검색 결과는 모두 펼쳐서 보여줍니다. (부서명 매칭 노드 + 상위 경로)
        // matchKw 를 넘겨 매칭 노드에만 하이라이트(.search-matched)를 적용합니다.
        const expandPath = collectAllIds(filtered, new Set());
        containerEl.innerHTML = '';
        containerEl.appendChild(buildTreeFromNodes(filtered, onSelect, { expandPath, selectedId, matchKw: kw }, 0));
    } catch (e) {
        containerEl.textContent = '부서 목록을 불러오지 못했습니다.';
    }
}

// 부서명 검색 input/버튼을 트리 컨테이너에 연결합니다. (검색 버튼/Enter, 검색어를 지우면 복원)
function setupDeptSearch(inputId, btnId, containerId, onSelect, getSelectedId) {
    const input = document.getElementById(inputId);
    const run = () => renderDeptTreeSearch(
        document.getElementById(containerId), onSelect, getSelectedId(), input.value);
    document.getElementById(btnId).addEventListener('click', run);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); run(); } });
    input.addEventListener('input', () => { if (!input.value.trim()) run(); });
}

// 서버가 내려준 중첩 트리(노드: {id, name, children}) -> 중첩 <ul> 로 변환합니다.
// 내부 식별은 항상 dept_id 기준입니다. (부서명이 중복될 수 있음)
// 펼침/접힘: 그룹 노드는 행 클릭 시 toggle, leaf 노드는 클릭 시 선택. (기존 선택 정책 유지)
function buildTreeFromNodes(nodes, onSelect, opts, depth) {
    const ul = document.createElement('ul');
    nodes.forEach(node => {
        const li = document.createElement('li');
        const hasChildren = node.children && node.children.length > 0;

        const row = document.createElement('span');
        row.className = 'tree-row';
        const toggle = document.createElement('span');
        const label = document.createElement('span');
        label.textContent = node.name;
        label.className = hasChildren ? 'tree-group' : 'tree-team';
        // 검색 중이고 이 부서명에 검색어가 포함되면 강조합니다. (상위 경로 노드는 강조 안 함)
        if (opts.matchKw && node.name && node.name.toLowerCase().includes(opts.matchKw)) {
            label.classList.add('search-matched');
        }

        // 초기 선택 강조: 상위 부서(tree-group)/말단 부서(tree-team) 모두 선택 가능
        if (opts.selectedId && node.id === opts.selectedId) {
            label.classList.add('selected');
        }
        // 부서명(라벨) 클릭 = 해당 부서를 검색조건으로 선택 (상위/말단 공통). 펼침/접힘과 분리.
        label.addEventListener('click', (e) => {
            e.stopPropagation();
            const root = ul.closest('.dept-tree') || ul;
            root.querySelectorAll('.tree-group.selected, .tree-team.selected')
                .forEach(el => el.classList.remove('selected'));
            label.classList.add('selected');
            onSelect(node.id, node.name, label);
        });

        if (hasChildren) {
            // 초기 펼침: 루트(depth 0) 또는 선택 부서의 조상이면 펼침, 그 외는 접힘.
            const expanded = depth === 0 || opts.expandPath.has(node.id);
            li.className = 'tree-node';
            toggle.className = 'tree-toggle';
            toggle.textContent = expanded ? '▼' : '▶';
            row.appendChild(toggle);
            row.appendChild(label);
            li.appendChild(row);

            // children 은 '펼친 상태'일 때만 실제 DOM 으로 만들어 붙입니다.
            let childUl = expanded ? buildTreeFromNodes(node.children, onSelect, opts, depth + 1) : null;
            if (childUl) li.appendChild(childUl);

            // 화살표(아이콘) 클릭 시에만 펼침/접힘 (이름 클릭은 선택)
            toggle.addEventListener('click', (e) => {
                e.stopPropagation();
                if (childUl) {
                    li.removeChild(childUl);
                    childUl = null;
                    toggle.textContent = '▶';
                } else {
                    childUl = buildTreeFromNodes(node.children, onSelect, opts, depth + 1);
                    li.appendChild(childUl);
                    toggle.textContent = '▼';
                }
            });
        } else {
            // leaf(팀): 아이콘 공간만 맞추고, 라벨 클릭 시 부서 선택(위 공통 핸들러)
            toggle.className = 'tree-toggle-space';
            row.appendChild(toggle);
            row.appendChild(label);
            li.appendChild(row);
        }
        ul.appendChild(li);
    });
    return ul;
}

// ---------- JD 등록 화면 ----------

async function onJdTeamSelected(deptId, deptName) {
    jdSelectedDeptId = deptId;
    document.getElementById('jdEmpty').classList.add('hidden');
    document.getElementById('jdForm').classList.remove('hidden');
    document.getElementById('jdSelectedDeptName').textContent = deptName;
    await loadJd(deptId);
}

async function loadJd(deptId) {
    const res = await fetch(`/api/jd/${deptId}`);
    const jd = await res.json();
    document.getElementById('position_title').value = jd.position_title || '';
    document.getElementById('job_description').value = jd.job_description || '';
    document.getElementById('required_skills').value = (jd.required_skills || []).join('\n');
    document.getElementById('preferred_skills').value = (jd.preferred_skills || []).join('\n');
    document.getElementById('min_years').value = jd.min_years ?? 0;
    document.getElementById('manager_email').value = jd.manager_email || '';
    document.getElementById('jdVersion').textContent = jd.version > 0
        ? `현재 버전 v${jd.version} (마지막 수정: ${jd.update_date || '-'})`
        : '아직 저장된 JD 가 없습니다. (기본 템플릿)';
}

async function saveJd() {
    if (!jdSelectedDeptId) return;
    const payload = {
        position_title: document.getElementById('position_title').value,
        job_description: document.getElementById('job_description').value,
        required_skills: document.getElementById('required_skills').value,
        preferred_skills: document.getElementById('preferred_skills').value,
        min_years: parseInt(document.getElementById('min_years').value || '0', 10),
        manager_email: document.getElementById('manager_email').value,
    };
    try {
        const res = await fetch(`/api/jd/${jdSelectedDeptId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error((await res.json()).detail || 'JD 저장 실패');
        const jd = await res.json();
        document.getElementById('required_skills').value = (jd.required_skills || []).join('\n');
        document.getElementById('preferred_skills').value = (jd.preferred_skills || []).join('\n');
        document.getElementById('jdVersion').textContent =
            `현재 버전 v${jd.version} (마지막 수정: ${jd.update_date || '-'})`;
        alert('JD 를 저장했습니다.');
    } catch (e) {
        alert(e.message);
    }
}

// 추천JD: 선택 부서/포지션명을 기반으로 LLM 에게 JD 초안을 요청해 입력란을 채웁니다. (DB 저장 안 함)
async function recommendJd() {
    if (!jdSelectedDeptId) {
        alert('먼저 부서/팀을 선택해주세요.');
        return;
    }
    const deptName = document.getElementById('jdSelectedDeptName').textContent.trim();
    const positionEl = document.getElementById('position_title');
    const descEl = document.getElementById('job_description');
    const reqEl = document.getElementById('required_skills');
    const prefEl = document.getElementById('preferred_skills');

    // 포지션명이 비어 있으면 '{부서명} 채용 포지션' 으로 구성합니다.
    const positionTitle = positionEl.value.trim() || `${deptName} 채용 포지션`;

    // 기존 입력값이 하나라도 있으면 덮어쓰기 확인
    if (descEl.value.trim() || reqEl.value.trim() || prefEl.value.trim()) {
        if (!confirm('이미 입력된 JD 내용이 있습니다. 추천 JD로 덮어쓰시겠습니까?')) return;
    }

    const btn = document.getElementById('recommendJdBtn');
    btn.disabled = true;
    const originalText = btn.textContent;
    btn.textContent = '추천 중...';
    try {
        const res = await fetch('/api/jd/recommend', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                dept_id: jdSelectedDeptId,
                dept_name: deptName,
                position_title: positionTitle,
                current_description: descEl.value,
                current_required_skills: reqEl.value,
                current_preferred_skills: prefEl.value,
            }),
        });
        const result = await res.json();
        if (!res.ok || result.status === 'ERROR') {
            alert(`추천 JD 생성에 실패했습니다.\nstep: ${result.step || '-'}\n${result.error_message || ''}\n${result.hint || ''}`.trim());
            return;
        }
        const d = result.data || {};
        positionEl.value = d.position_title || positionTitle;
        descEl.value = d.description || '';
        reqEl.value = (d.required_skills || []).join('\n');
        prefEl.value = (d.preferred_skills || []).join('\n');
    } catch (e) {
        alert(`추천 JD 생성에 실패했습니다.\n${e.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

// ---------- 관리자 > Google Drive 동기화 ----------
// TODO: 관리자 권한 적용 예정 (현재는 권한 제한 없이 누구나 실행 가능)
//
// 사용 API (기존 그대로):
//   GET  /api/drive/sync-dept-folders/status
//   POST /api/drive/sync-dept-folders

// 화면 진입 시 최근 동기화 상태를 표시합니다.
async function loadDriveSyncStatus() {
    const el = document.getElementById('driveSyncStatus');
    el.textContent = '불러오는 중...';
    try {
        const res = await fetch('/api/drive/sync-dept-folders/status');
        const s = await res.json();
        if (!s.exists) {
            el.innerHTML = '<div class="empty-state">아직 동기화 이력이 없습니다. 부서 폴더 동기화를 먼저 실행해주세요.</div>';
            return;
        }
        el.innerHTML = `
            <table class="kv-table"><tbody>
                <tr><th>매핑 파일 존재 여부</th><td>있음</td></tr>
                <tr><th>map_file</th><td>${escapeHtml(s.map_file)}</td></tr>
                <tr><th>folder_count</th><td>${s.folder_count}</td></tr>
                <tr><th>last_synced_at</th><td>${escapeHtml(s.last_synced_at || '-')}</td></tr>
            </tbody></table>`;
    } catch (e) {
        el.innerHTML = '<p class="text-danger">동기화 상태를 불러오지 못했습니다.</p>';
    }
}

// "부서 폴더 동기화 실행" 버튼 동작
async function syncDeptFolders() {
    const btn = document.getElementById('syncDeptFoldersBtn');
    const resultSection = document.getElementById('driveSyncResultSection');
    const errorSection = document.getElementById('driveSyncErrorSection');
    const resultEl = document.getElementById('driveSyncResult');
    const errorEl = document.getElementById('driveSyncError');

    // 1~3) 호출 중 버튼 비활성화 + 문구 변경 + 중복 클릭 방지
    btn.disabled = true;
    btn.textContent = '동기화 중입니다...';
    resultSection.classList.add('hidden');
    errorSection.classList.add('hidden');

    try {
        const res = await fetch('/api/drive/sync-dept-folders', { method: 'POST' });
        const data = await res.json();

        // 5) 실패 시 alert 대신 화면에 에러 영역 표시 (status/step/error_message/hint)
        if (!res.ok || data.status === 'ERROR') {
            errorEl.innerHTML = `
                <p><strong>status:</strong> ${escapeHtml(String(data.status || 'ERROR'))}</p>
                <p><strong>step:</strong> ${escapeHtml(String(data.step || '-'))}</p>
                <p><strong>error_message:</strong> ${escapeHtml(String(data.error_message || '-'))}</p>
                <p><strong>hint:</strong> ${escapeHtml(String(data.hint || '-'))}</p>`;
            errorSection.classList.remove('hidden');
            return;
        }

        // 4) 성공 시 결과 영역에 응답 내용 표시
        resultEl.innerHTML = `
            <p><strong>status:</strong> ${escapeHtml(String(data.status))}</p>
            <p><strong>source:</strong> ${escapeHtml(String(data.source || '-'))}</p>
            <p><strong>target:</strong> ${escapeHtml(String(data.target || '-'))}</p>
            <p><strong>total_depts:</strong> ${data.total_depts}</p>
            <p><strong>active_depts:</strong> ${data.active_depts}</p>
            <p><strong>created:</strong> ${data.created} / <strong>reused:</strong> ${data.reused} / <strong>updated:</strong> ${data.updated} / <strong>failed:</strong> ${data.failed}</p>
            <p><strong>synced_at:</strong> ${escapeHtml(String(data.synced_at || '-'))}</p>`;
        resultSection.classList.remove('hidden');

        // 6) 완료 후 최근 동기화 상태 + DB count 갱신
        await loadDriveSyncStatus();
        loadDeptDbCounts();
    } catch (e) {
        errorEl.innerHTML = `<p class="text-danger">동기화 요청 실패: ${escapeHtml(e.message)}</p>`;
        errorSection.classList.remove('hidden');
    } finally {
        // 버튼 원래 상태로 복구
        btn.disabled = false;
        btn.textContent = '부서 폴더 동기화 실행 (DB 기준)';
    }
}

// ---------- 관리자 > 부서 DB 동기화 (resume_ai) ----------

async function loadDeptDbCounts() {
    const el = document.getElementById('deptDbCounts');
    try {
        const res = await fetch('/api/db/counts');
        const data = await res.json();
        if (data.status === 'ERROR' || !data.counts) {
            el.innerHTML = '<span class="text-danger">DB count 조회 실패</span>';
            return;
        }
        const c = data.counts;
        // 공고/JD 중심 전환: job_descriptions(legacy) 카드는 제거. 부서/Drive 폴더 매핑 중심으로만 표시.
        el.innerHTML = `
            <div class="stat-row">
                <div class="stat-card"><span class="stat-label">departments</span><span class="stat-value">${c.departments}</span></div>
                <div class="stat-card"><span class="stat-label">dept_drive_folders</span><span class="stat-value">${c.dept_drive_folders}</span></div>
            </div>`;
    } catch (e) {
        el.innerHTML = '<span class="text-danger">DB count 조회 실패</span>';
    }
}

// (legacy 제거) 부서별 JD 등록 현황 팝업(job_descriptions 카드)은 공고/JD 중심 전환으로 삭제되었습니다.
// 공고/JD 현황은 '공고/JD 관리' 화면에서 확인합니다.

// Drive config/dept_config.json → resume_ai.departments upsert
async function syncDeptDbFromDriveConfig() {
    const btn = document.getElementById('syncDeptDbBtn');
    const resultEl = document.getElementById('deptDbResult');
    const errorEl = document.getElementById('deptDbError');
    resultEl.innerHTML = '';
    errorEl.innerHTML = '';
    btn.disabled = true;
    btn.textContent = '동기화 중입니다...';
    try {
        const res = await fetch('/api/departments/sync-from-drive-config', { method: 'POST' });
        const data = await res.json();
        if (!res.ok || data.status === 'ERROR') {
            errorEl.innerHTML = `
                <p class="text-danger">[${escapeHtml(String(data.step || '-'))}] ${escapeHtml(String(data.error_message || '실패'))}</p>
                <p class="hint">${escapeHtml(String(data.hint || ''))}</p>`;
            return;
        }
        resultEl.innerHTML = `
            <p class="text-success">DB 부서 동기화 완료 (${escapeHtml(String(data.table))})</p>
            <p><strong>inserted:</strong> ${data.inserted} / <strong>updated:</strong> ${data.updated} / <strong>skipped:</strong> ${data.skipped} / <strong>total:</strong> ${data.total}</p>`;
        loadDeptDbCounts();
        // 화면 트리 기준이 DB 이므로, 트리 캐시 무효화 후 다시 그립니다. (트리 사용 화면: JD(legacy)/이력서 현황)
        deptTreePromise = null;
        renderDeptTree(document.getElementById('jdDeptTree'), onJdTeamSelected, jdSelectedDeptId);
        renderDeptTree(document.getElementById('statusDeptTree'), onStatusTeamSelected, statusFilterDeptId);
    } catch (e) {
        errorEl.innerHTML = `<p class="text-danger">동기화 요청 실패: ${escapeHtml(e.message)}</p>`;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Drive config → DB 부서 동기화';
    }
}

// ---------- 관리자 > 부서 설정 JSON 관리 ----------
// TODO: 관리자 권한 적용 예정 (현재는 권한 제한 없이 누구나 실행 가능)
//
// 사용 API:
//   GET  /api/drive/dept-config                    : Drive dept_config.json 불러오기
//   POST /api/drive/dept-config/normalize-upload   : 업로드 JSON 자동 정규화 (저장 안 함)
//   POST /api/drive/dept-config/validate           : departments 검증
//   PUT  /api/drive/dept-config                    : Drive dept_config.json 저장

function renderDeptConfigMeta(d) {
    const el = document.getElementById('deptConfigMeta');
    const rows = [
        ['source', d.source],
        ['file_id', d.file_id],
        ['dept_count', d.dept_count],
        ['active_dept_count', d.active_dept_count],
        ['detected_format', d.detected_format],
        ['normalize_rule', d.normalize_rule],
        ['warnings', (d.warnings && d.warnings.length) ? d.warnings.join(' / ') : '없음'],
        ['modified_time', d.modified_time],
        ['created_from_local_dummy', d.created_from_local_dummy],
    ];
    el.innerHTML = rows
        .filter(([, v]) => v !== undefined)
        .map(([k, v]) => `<span class="tag">${k}: ${escapeHtml(String(v))}</span>`)
        .join(' ');
}

function showDeptConfigResult(msg) {
    document.getElementById('deptConfigError').innerHTML = '';
    document.getElementById('deptConfigResult').innerHTML =
        `<p class="text-success">${escapeHtml(msg)}</p>`;
}

function showDeptConfigError(data) {
    document.getElementById('deptConfigResult').innerHTML = '';
    const step = data.step || '-';
    const msg = data.error_message || data.message || '알 수 없는 오류';
    const hint = data.hint || '';
    document.getElementById('deptConfigError').innerHTML = `
        <p class="text-danger">[${escapeHtml(String(step))}] ${escapeHtml(String(msg))}</p>
        <p class="hint">${escapeHtml(String(hint))}</p>`;
}

// Drive 의 dept_config.json 을 불러와 textarea(pretty print)에 표시합니다.
async function loadDeptConfig() {
    const btn = document.getElementById('loadDeptConfigBtn');
    btn.disabled = true;
    document.getElementById('deptConfigResult').innerHTML = '';
    document.getElementById('deptConfigError').innerHTML = '';
    document.getElementById('deptConfigMeta').textContent = '불러오는 중...';
    try {
        const res = await fetch('/api/drive/dept-config');
        const data = await res.json();
        if (!res.ok || data.status === 'ERROR') {
            showDeptConfigError(data);
            document.getElementById('deptConfigMeta').textContent = '';
            return;
        }
        document.getElementById('deptConfigText').value = JSON.stringify(data.departments, null, 2);
        renderDeptConfigMeta(data);
        showDeptConfigResult('Drive 부서 JSON 을 불러왔습니다.');
    } catch (e) {
        showDeptConfigError({ step: 'network', error_message: e.message });
        document.getElementById('deptConfigMeta').textContent = '';
    } finally {
        btn.disabled = false;
    }
}

// 업로드 파일을 정규화해 textarea 에 표시합니다. (아직 Drive 저장 안 함)
async function uploadNormalizeDeptConfig() {
    const input = document.getElementById('deptConfigFile');
    if (!input.files.length) {
        alert('업로드할 JSON 파일을 선택하세요.');
        return;
    }
    const btn = document.getElementById('uploadDeptConfigBtn');
    btn.disabled = true;
    document.getElementById('deptConfigResult').innerHTML = '';
    document.getElementById('deptConfigError').innerHTML = '';
    try {
        const formData = new FormData();
        formData.append('file', input.files[0]);
        const res = await fetch('/api/drive/dept-config/normalize-upload', { method: 'POST', body: formData });
        const data = await res.json();
        if (!res.ok || data.status === 'ERROR') {
            showDeptConfigError(data);
            return;
        }
        document.getElementById('deptConfigText').value = JSON.stringify(data.departments, null, 2);
        renderDeptConfigMeta(data);
        showDeptConfigResult('업로드 JSON 을 정규화했습니다. (아직 Drive에 저장되지 않았습니다. 검토 후 저장하세요.)');
    } catch (e) {
        showDeptConfigError({ step: 'normalize_upload', error_message: e.message });
    } finally {
        btn.disabled = false;
    }
}

// textarea 내용을 파싱하고 프론트 1차 검증(배열/id·name/중복 id)을 수행합니다.
function parseDeptConfigText() {
    let parsed;
    try {
        parsed = JSON.parse(document.getElementById('deptConfigText').value);
    } catch (e) {
        throw new Error('JSON 파싱 실패: ' + e.message);
    }
    if (!Array.isArray(parsed)) throw new Error('부서 JSON 은 배열이어야 합니다.');
    const seen = new Set();
    parsed.forEach((d, i) => {
        if (!d || typeof d !== 'object') throw new Error(`${i}번째 항목이 객체가 아닙니다.`);
        if (!d.id) throw new Error(`${i}번째 부서에 id가 없습니다.`);
        if (!d.name) throw new Error(`${i}번째 부서에 name이 없습니다.`);
        if (seen.has(d.id)) throw new Error(`중복된 부서 id: ${d.id}`);
        seen.add(d.id);
    });
    return parsed;
}

// 프론트 1차 검증 후 서버 검증(POST validate)을 수행합니다.
async function validateDeptConfig() {
    document.getElementById('deptConfigResult').innerHTML = '';
    document.getElementById('deptConfigError').innerHTML = '';
    let departments;
    try {
        departments = parseDeptConfigText();
    } catch (e) {
        showDeptConfigError({ step: 'validate(front)', error_message: e.message,
            hint: '배열 JSON, 각 부서 id/name, 중복 id 를 확인하세요.' });
        return;
    }
    const btn = document.getElementById('validateDeptConfigBtn');
    btn.disabled = true;
    try {
        const res = await fetch('/api/drive/dept-config/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ departments }),
        });
        const data = await res.json();
        if (!res.ok || data.status === 'ERROR') {
            showDeptConfigError(data);
            return;
        }
        showDeptConfigResult(`검증 성공 (dept_count=${data.dept_count}, active=${data.active_dept_count})`);
    } catch (e) {
        showDeptConfigError({ step: 'validate_dept_config', error_message: e.message });
    } finally {
        btn.disabled = false;
    }
}

// 저장: 프론트 검증 후 PUT /api/drive/dept-config 로 전송합니다.
async function saveDeptConfig() {
    document.getElementById('deptConfigResult').innerHTML = '';
    document.getElementById('deptConfigError').innerHTML = '';
    let departments;
    try {
        departments = parseDeptConfigText();
    } catch (e) {
        showDeptConfigError({ step: 'validate(front)', error_message: e.message,
            hint: '배열 JSON, 각 부서 id/name, 중복 id 를 확인하세요.' });
        return;
    }
    const btn = document.getElementById('saveDeptConfigBtn');
    btn.disabled = true;
    btn.textContent = '저장 중입니다...';
    try {
        const res = await fetch('/api/drive/dept-config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ departments }),
        });
        const data = await res.json();
        if (!res.ok || data.status === 'ERROR') {
            showDeptConfigError(data);
            return;
        }
        document.getElementById('deptConfigText').value = JSON.stringify(data.departments, null, 2);
        renderDeptConfigMeta(data);
        showDeptConfigResult(`${data.message} (dept_count=${data.dept_count}, modified_time=${data.modified_time})`);
    } catch (e) {
        showDeptConfigError({ step: 'dept_config_save', error_message: e.message });
    } finally {
        btn.disabled = false;
        btn.textContent = 'Drive에 부서 JSON 저장';
    }
}

// ---------- 이력서 등록 (공고 기준) ----------
// 공고 목록을 보여주고, JD가 등록된 공고를 선택해 해당 공고의 Drive inbox 폴더에 업로드합니다.
let resumeSelectedPosting = null;   // {id, title} 업로드 대상 공고
let resumePostingPage = 1, resumePostingSize = 20;   // 이력서 등록 공고 목록 페이징

// 공고 필터 바(이력서 등록/분석 공용) 에서 URLSearchParams 를 만듭니다.
function buildPostingFilterParams(prefix) {
    const params = new URLSearchParams();
    const g = (id) => document.getElementById(prefix + id);
    const kw = g('Keyword') ? g('Keyword').value.trim() : '';
    const platform = g('Platform') ? g('Platform').value : '';
    const status = g('Status') ? g('Status').value : '';
    const jd = g('Jd') ? g('Jd').value : '';
    const dateFrom = g('DateFrom') ? g('DateFrom').value : '';
    const dateTo = g('DateTo') ? g('DateTo').value : '';
    if (kw) params.set('keyword', kw);
    if (platform) params.set('platform_code', platform);
    if (status) params.set('status', status);
    if (jd) params.set('jd_status', jd);
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    return params;
}

async function loadResumePostings() {
    const body = document.getElementById('resumePostingTableBody');
    const errorEl = document.getElementById('resumePostingError');
    errorEl.innerHTML = '';
    closeResumeUpload();
    body.innerHTML = '<tr><td colspan="7" class="empty-cell">불러오는 중...</td></tr>';
    const params = buildPostingFilterParams('resumePosting');
    params.set('page', String(resumePostingPage));
    params.set('size', String(resumePostingSize));
    const { _redirect, ok, data } = await adminFetchJson(`/api/job-postings?${params.toString()}`);
    if (_redirect) return;
    if (!ok) {
        body.innerHTML = '';
        errorEl.innerHTML = `<p class="text-danger">${escapeHtml((data && data.detail) || '공고 목록을 불러오지 못했습니다.')}</p>`;
        return;
    }
    renderResumePostingsTable(data.items || []);
    renderPager('resumePosting', data.page || resumePostingPage, data.size || resumePostingSize, data.total || 0);
}

function renderResumePostingsTable(postings) {
    const body = document.getElementById('resumePostingTableBody');
    if (!postings.length) {
        body.innerHTML = '<tr><td colspan="7" class="empty-cell">등록된 공고가 없습니다.</td></tr>';
        return;
    }
    body.innerHTML = postings.map(p => {
        const dept = p.department_name
            ? `${escapeHtml(p.department_name)} <span class="dept-code">(${escapeHtml(p.department_id)})</span>`
            : escapeHtml(p.department_id || '-');
        const uploadBtn = p.has_jd
            ? `<button type="button" class="btn-small resume-upload-open" data-id="${p.id}" data-title="${escapeHtml(p.title)}">업로드</button>`
            : `<button type="button" class="btn-small" disabled title="JD가 등록된 공고에만 이력서를 업로드할 수 있습니다.">업로드</button>`;
        return `<tr>
            <td class="cell-filename" title="${escapeHtml(p.title)}">${escapeHtml(p.title)}</td>
            <td>${dept}</td>
            <td>${escapeHtml(p.platform_label || '-')}</td>
            <td>${postingStatusBadge(p.status)}</td>
            <td>${postingJdBadge(p.has_jd)}</td>
            <td>${escapeHtml(formatDateTime(p.created_at))}</td>
            <td>${uploadBtn}</td>
        </tr>`;
    }).join('');
    body.querySelectorAll('.resume-upload-open').forEach(btn => {
        btn.addEventListener('click', () => openResumeUpload(btn.dataset.id, btn.dataset.title));
    });
}

function openResumeUpload(postingId, title) {
    resumeSelectedPosting = { id: postingId, title: title };
    document.getElementById('resumeUploadPostingName').textContent = title || `공고 #${postingId}`;
    document.getElementById('driveResumeFiles').value = '';
    document.getElementById('driveUploadMsg').textContent = '';
    document.getElementById('driveUploadResultSection').classList.add('hidden');
    document.getElementById('driveUploadErrorSection').classList.add('hidden');
    document.getElementById('resumeUploadPanel').classList.remove('hidden');
    document.getElementById('resumeUploadPanel').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    loadUploadPendingSummary(postingId);
}

// 해당 공고의 기존 미처리(분석 대기) 이력서 요약. (기존 posting-pending API 재사용 — 파일명/건수만)
async function loadUploadPendingSummary(postingId) {
    const el = document.getElementById('resumeUploadPending');
    el.classList.add('hidden');
    el.innerHTML = '';
    const { _redirect, ok, data } = await adminFetchJson(`/api/resumes/posting-pending/${postingId}?page=1&size=5`);
    if (_redirect || !ok || !data) return;
    const total = data.total || 0;
    if (!total) {
        el.classList.remove('hidden');
        el.innerHTML = '<span class="hint">미처리(분석 대기) 이력서가 없습니다.</span>';
        return;
    }
    const names = (data.files || []).map(f => escapeHtml(f.original_file_name || '-'));
    const shown = names.slice(0, 5);
    const more = total > shown.length ? ` 외 ${total - shown.length}건` : '';
    el.classList.remove('hidden');
    el.innerHTML =
        `<strong>기존 미처리 이력서 ${total}건</strong>`
        + `<ul class="upload-pending-list">${shown.map(n => `<li>${n}</li>`).join('')}</ul>`
        + (more ? `<span class="hint">${more.trim()}</span>` : '');
}

function closeResumeUpload() {
    resumeSelectedPosting = null;
    document.getElementById('resumeUploadPanel').classList.add('hidden');
}

// 선택한 공고의 inbox 폴더에 파일을 업로드합니다. (posting_id 기준, AI 분석은 하지 않음)
async function uploadResumesToDrive() {
    const msg = document.getElementById('driveUploadMsg');
    const resultSection = document.getElementById('driveUploadResultSection');
    const errorSection = document.getElementById('driveUploadErrorSection');
    msg.textContent = '';
    resultSection.classList.add('hidden');
    errorSection.classList.add('hidden');

    if (!resumeSelectedPosting) { msg.textContent = '먼저 공고를 선택해주세요.'; return; }
    const input = document.getElementById('driveResumeFiles');
    if (!input.files.length) { msg.textContent = '업로드할 이력서 파일을 선택해주세요.'; return; }

    const btn = document.getElementById('driveUploadBtn');
    btn.disabled = true;
    btn.textContent = '업로드 중입니다...';
    try {
        const formData = new FormData();
        formData.append('posting_id', resumeSelectedPosting.id);
        for (const f of input.files) formData.append('files', f);

        const res = await fetch('/api/resumes/upload-to-drive', { method: 'POST', body: formData });
        if (res.status === 401) { window.location.href = '/login'; return; }
        const data = await res.json();
        if (!res.ok || data.status === 'ERROR') {
            // 권한 오류(403 등)는 detail 로 내려오므로 error_message 로 매핑해 표시합니다.
            if (data.detail && !data.error_message) data.error_message = data.detail;
            renderDriveUploadError(data);
            errorSection.classList.remove('hidden');
            return;
        }
        renderDriveUploadResult(data);
        resultSection.classList.remove('hidden');
        input.value = '';   // 성공 후 파일 input 초기화
    } catch (e) {
        renderDriveUploadError({ error_message: e.message });
        errorSection.classList.remove('hidden');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Google Drive에 업로드';
    }
}

function setupResumeUI() {
    const searchBtn = document.getElementById('resumePostingSearchBtn');
    if (!searchBtn) return;
    const search = () => { resumePostingPage = 1; loadResumePostings(); };
    searchBtn.addEventListener('click', search);
    wireEnterSearch(['resumePostingKeyword', 'resumePostingDateFrom', 'resumePostingDateTo'], search);
    document.getElementById('resumePostingTodayBtn').addEventListener('click', () => {
        const iso = todayIso();
        document.getElementById('resumePostingDateFrom').value = iso;
        document.getElementById('resumePostingDateTo').value = iso;
        search();
    });
    document.getElementById('resumePostingResetBtn').addEventListener('click', () => {
        ['Keyword', 'Platform', 'Status', 'Jd', 'DateFrom', 'DateTo'].forEach(s => {
            const el = document.getElementById('resumePosting' + s);
            if (el) el.value = '';
        });
        resumePostingSize = 20;
        document.getElementById('resumePostingSizeSelect').value = '20';
        search();
    });
    document.getElementById('resumePostingSizeSelect').addEventListener('change', (e) => {
        resumePostingSize = parseInt(e.target.value, 10) || 20;
        resumePostingPage = 1;
        loadResumePostings();
    });
    document.getElementById('resumePostingPrevBtn').addEventListener('click', () => {
        if (resumePostingPage > 1) { resumePostingPage--; loadResumePostings(); }
    });
    document.getElementById('resumePostingNextBtn').addEventListener('click', () => {
        resumePostingPage++; loadResumePostings();
    });
    document.getElementById('resumeUploadCancelBtn').addEventListener('click', closeResumeUpload);
}

// 바이트를 사람이 읽기 쉬운 크기 문자열로 (예: 19.5 KB)
function formatBytes(bytes) {
    if (bytes == null || isNaN(bytes)) return '-';
    if (bytes < 1024) return `${bytes} B`;
    const kb = bytes / 1024;
    if (kb < 1024) return `${kb.toFixed(1)} KB`;
    return `${(kb / 1024).toFixed(1)} MB`;
}

// 업로드 제외 사유 코드 -> 운영자용 한글 문구
const SKIP_REASON_LABEL = {
    unsupported_extension: '허용되지 않은 파일 형식',
    file_too_large: '파일 크기 초과',
    total_size_limit_exceeded: '총 용량 초과',
    invalid_zip: '잘못된 ZIP 파일',
    zip_entry_limit_exceeded: 'ZIP 내 파일 수 초과',
    path_traversal_blocked: '잘못된 파일 경로',
};
function skipReasonLabel(reason) {
    if (!reason) return '-';
    if (SKIP_REASON_LABEL[reason]) return SKIP_REASON_LABEL[reason];
    if (String(reason).startsWith('drive_upload_failed')) return 'Drive 업로드 실패';
    return String(reason);
}

// 업로드 결과를 운영자 친화적으로 표시합니다. (요약 + 파일 테이블 + 제외 목록 + 다음 단계 + 접힌 상세)
// 내부 식별/경로값(upload_id, drive 경로, DB 상태 등)은 '상세 정보 보기'(기본 닫힘)에만 둡니다.
function renderDriveUploadResult(d) {
    const deptName = d.dept_name || '선택한 부서';
    const okCount = d.uploaded_count || 0;
    const skippedCount = d.skipped_count || 0;
    // 분석 대기 등록 = DB 에 저장된 파일 수(= PENDING 으로 등록된 수). DB 저장 실패 시 0.
    const pendingRegistered = (d.db_saved && d.db_saved.resume_files != null) ? d.db_saved.resume_files : 0;

    const uploadedRows = (d.uploaded_files || []).map(f => {
        const name = f.original_file_name || f.stored_file_name || '-';
        return `<tr>
            <td class="cell-filename" title="${escapeHtml(name)}">${escapeHtml(name)}</td>
            <td>${escapeHtml(formatBytes(f.file_size))}</td>
            <td>${escapeHtml(f.extension || '-')}</td>
            <td>${fileStatusBadge(f.status || 'UPLOADED')}</td>
        </tr>`;
    }).join('');

    let skippedBlock;
    if (!(d.skipped_files || []).length) {
        skippedBlock = '<p class="hint">제외된 파일이 없습니다.</p>';
    } else {
        const rows = d.skipped_files.map(f => {
            const name = f.original_file_name || '-';
            return `<tr>
                <td class="cell-filename" title="${escapeHtml(name)}">${escapeHtml(name)}</td>
                <td>${escapeHtml(skipReasonLabel(f.reason))}</td>
            </tr>`;
        }).join('');
        skippedBlock = `<div class="table-scroll"><table class="data-table">
            <colgroup><col style="width:60%"><col style="width:40%"></colgroup>
            <thead><tr><th>파일명</th><th>사유</th></tr></thead>
            <tbody>${rows}</tbody></table></div>`;
    }

    // PARTIAL_SUCCESS: Drive 업로드는 됐지만 DB 저장이 실패한 경우 경고
    const partialWarn = (d.status === 'PARTIAL_SUCCESS')
        ? `<p class="text-danger">일부 처리에 실패했습니다: ${escapeHtml(d.error_message || 'DB 저장 실패')}</p>
           <p class="hint">${escapeHtml(d.hint || '')}</p>`
        : '';

    const details = `
        <details class="upload-detail">
            <summary>상세 정보 보기</summary>
            <table class="upload-detail-table"><tbody>
                <tr><th>업로드 ID</th><td>${escapeHtml(d.upload_id || '-')}</td></tr>
                <tr><th>업로드 폴더명</th><td>${escapeHtml(d.upload_folder_name || '-')}</td></tr>
                <tr><th>원본 파일</th><td>${escapeHtml(d.source_upload_file_name || d.source_label || '-')}</td></tr>
                <tr><th>업로드 유형</th><td>${escapeHtml(d.upload_type || '-')}</td></tr>
                <tr><th>Drive 저장 경로</th><td>${escapeHtml(d.drive_path_display || '-')}</td></tr>
                <tr><th>업로드 상태</th><td>${escapeHtml(d.upload_status || '-')}</td></tr>
                <tr><th>DB 저장 상태</th><td>${escapeHtml(d.db_save_status || '-')}${d.db_saved ? ` (batches ${d.db_saved.resume_upload_batches}, files ${d.db_saved.resume_files})` : ''}</td></tr>
            </tbody></table>
        </details>`;

    document.getElementById('driveUploadResult').innerHTML = `
        <div class="upload-summary">
            <p class="upload-done">✅ <strong>업로드 완료</strong> — ${escapeHtml(deptName)}에 이력서 ${okCount}건이 업로드되었습니다.</p>
            ${partialWarn}
            <div class="upload-badges">
                <span class="badge badge-blue">부서/팀: ${escapeHtml(deptName)}</span>
                <span class="badge badge-green">업로드 성공: ${okCount}건</span>
                <span class="badge badge-gray">제외: ${skippedCount}건</span>
                <span class="badge badge-amber">분석 대기 등록: ${pendingRegistered}건</span>
            </div>
        </div>

        <h4 class="upload-section-title">업로드된 파일</h4>
        <div class="table-scroll"><table class="data-table">
            <colgroup><col style="width:46%"><col style="width:18%"><col style="width:14%"><col style="width:22%"></colgroup>
            <thead><tr><th>파일명</th><th>크기</th><th>형식</th><th>상태</th></tr></thead>
            <tbody>${uploadedRows || '<tr><td colspan="4" class="empty-cell">업로드된 파일이 없습니다.</td></tr>'}</tbody>
        </table></div>

        <h4 class="upload-section-title">제외된 파일</h4>
        ${skippedBlock}

        <h4 class="upload-section-title">다음 단계</h4>
        <p class="hint">분석 작업 관리 화면에서 업로드된 이력서를 분석할 수 있고, 이력서 현황에서 업로드/분석 상태를 확인할 수 있습니다.</p>
        <div class="btn-row">
            <button type="button" id="goAnalysisJobsBtn" class="btn-small">분석 작업 관리로 이동</button>
            <button type="button" id="goResumeStatusBtn" class="btn-small btn-secondary">이력서 현황 보기</button>
        </div>

        ${details}`;

    // 다음 단계 버튼 → 기존 좌측 메뉴 클릭 핸들러 재사용(권한 체크 + 화면 전환 포함)
    const goA = document.getElementById('goAnalysisJobsBtn');
    const goS = document.getElementById('goResumeStatusBtn');
    if (goA) goA.addEventListener('click', () => {
        const el = document.querySelector('.menu-item[data-view="analysisJobs"]');
        if (el) el.click();
    });
    if (goS) goS.addEventListener('click', () => {
        const el = document.querySelector('.menu-item[data-view="resumeStatus"]');
        if (el) el.click();
    });
}

// ---------- 분석 작업 관리 (공고 기준) ----------
// 부서/팀(검색조건) → 공고/JD 리스트(대기 건수 포함) → 공고 선택 → 분석 대기 파일(체크박스) → 분석 실행.
let analysisSelectedPostingId = null;     // 선택한 공고 id
let analysisSelectedPostingTitle = '';    // 선택한 공고명(대기 테이블 표시용)
let analysisSelectedDeptId = null;        // 부서/팀 검색조건 (null = 전체 부서)
let analysisPostingPage = 1, analysisPostingSize = 5;   // 공고/JD 리스트 페이징 (한 페이지 5개 고정)
let pendingPage = 1, pendingSize = 20;    // 분석 대기 파일 페이징

async function loadAnalysisPostings() {
    const list = document.getElementById('analysisPostingList');
    const errorEl = document.getElementById('analysisPostingError');
    errorEl.innerHTML = '';
    // 전체 분석 실행 버튼은 ADMIN 에게만 노출 (백엔드에서도 403 재검증)
    const allBtn = document.getElementById('analyzeAllBtn');
    if (allBtn) allBtn.classList.toggle('hidden', !(currentUser && currentUser.role_code === 'ADMIN'));
    list.innerHTML = '<p class="hint">불러오는 중...</p>';
    const params = buildPostingFilterParams('analysisPosting');
    if (analysisSelectedDeptId) params.set('department_id', analysisSelectedDeptId);
    params.set('page', String(analysisPostingPage));
    params.set('size', String(analysisPostingSize));
    // 공고 목록과 공고별 대기 건수를 함께 조회
    const [listRes, countRes] = await Promise.all([
        adminFetchJson(`/api/job-postings?${params.toString()}`),
        adminFetchJson('/api/resumes/posting-pending-counts'),
    ]);
    if (listRes._redirect || countRes._redirect) return;
    if (!listRes.ok) {
        list.innerHTML = '';
        errorEl.innerHTML = `<p class="text-danger">${escapeHtml((listRes.data && listRes.data.detail) || '공고 목록을 불러오지 못했습니다.')}</p>`;
        return;
    }
    const counts = countRes.ok ? (countRes.data || {}) : {};
    const d = listRes.data || {};
    renderAnalysisPostingsTable(d.items || [], counts);
    renderPager('analysisPosting', d.page || analysisPostingPage, d.size || analysisPostingSize, d.total || 0);
}

function renderAnalysisPostingsTable(postings, counts) {
    const list = document.getElementById('analysisPostingList');
    if (!postings.length) {
        list.innerHTML = '<p class="hint">등록된 공고가 없습니다.</p>';
        return;
    }
    list.innerHTML = postings.map(p => {
        const dept = p.department_name
            ? `${escapeHtml(p.department_name)} (${escapeHtml(p.department_id)})`
            : escapeHtml(p.department_id || '-');
        const pending = counts[p.id] || 0;
        const pendingBadge = pending > 0
            ? `<span class="badge badge-amber">대기 ${pending}건</span>`
            : '<span class="badge badge-gray">대기 0건</span>';
        const platform = p.platform_label ? `<span class="pc-platform">${escapeHtml(p.platform_label)}</span>` : '';
        return `<div class="posting-card" data-id="${p.id}" data-title="${escapeHtml(p.title)}">
            <div class="pc-title" title="${escapeHtml(p.title)}">${escapeHtml(p.title)}</div>
            <div class="pc-meta">${dept}${platform}</div>
            <div class="pc-badges">${postingJdBadge(p.has_jd)} ${pendingBadge}</div>
        </div>`;
    }).join('');
    list.querySelectorAll('.posting-card').forEach(card => {
        card.addEventListener('click', () => {
            list.querySelectorAll('.posting-card').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            selectAnalysisPosting(card.dataset.id, card.dataset.title);
        });
    });
}

function selectAnalysisPosting(postingId, title) {
    analysisSelectedPostingId = postingId;
    analysisSelectedPostingTitle = title || '';
    pendingPage = 1;   // 새 공고 선택 시 대기 파일 1페이지부터
    document.getElementById('driveAnalysisResultSection').classList.add('hidden');
    loadPostingPending(postingId);
}

// 선택 공고의 분석 대기 파일 목록 조회 (페이징)
async function loadPostingPending(postingId) {
    const meta = document.getElementById('pendingMeta');
    const body = document.getElementById('pendingTableBody');
    meta.textContent = '불러오는 중...';
    body.innerHTML = '<tr><td colspan="5" class="empty-cell">불러오는 중...</td></tr>';
    updatePostingAnalyzeState(null);
    const qs = `page=${pendingPage}&size=${pendingSize}`;
    const { _redirect, ok, data } = await adminFetchJson(`/api/resumes/posting-pending/${postingId}?${qs}`);
    if (_redirect) return;
    if (!ok) {
        meta.textContent = '';
        body.innerHTML = `<tr><td colspan="5" class="empty-cell text-danger">${escapeHtml((data && data.detail) || '분석 대기 파일을 불러오지 못했습니다.')}</td></tr>`;
        updatePostingAnalyzeState(0);
        return;
    }
    renderPostingPending(data);
    renderPager('pending', data.page || pendingPage, data.size || pendingSize, data.total || 0);
    updatePostingAnalyzeState(data.total || 0);   // 선택 공고 분석 버튼은 '전체 대기 건수' 기준
}

function renderPostingPending(data) {
    const meta = document.getElementById('pendingMeta');
    const body = document.getElementById('pendingTableBody');
    const selAll = document.getElementById('pendingSelectAll');
    const files = data.files || [];
    meta.textContent = `[${analysisSelectedPostingTitle || '선택 공고'}]의 분석 대기 파일 ${data.total || 0}건`;
    if (!files.length) {
        body.innerHTML = '<tr><td colspan="5" class="empty-cell">분석 대기 파일이 없습니다.</td></tr>';
        if (selAll) { selAll.checked = false; selAll.disabled = true; }
        updateAnalyzeSelectedState();
        return;
    }
    body.innerHTML = files.map(f => `
        <tr>
            <td class="cell-check"><input type="checkbox" class="pending-row-check" data-id="${f.resume_file_id}"></td>
            <td class="cell-filename" title="${escapeHtml(analysisSelectedPostingTitle)}">${escapeHtml(analysisSelectedPostingTitle)}</td>
            <td>${escapeHtml(f.dept_name || f.dept_id || '-')}</td>
            <td class="cell-filename" title="${escapeHtml(f.original_file_name || '-')}">${escapeHtml(f.original_file_name || '-')}</td>
            <td>${escapeHtml(formatDateTime(f.uploaded_at))}</td>
        </tr>`).join('');
    if (selAll) { selAll.checked = false; selAll.disabled = false; }
    updateAnalyzeSelectedState();
}

// 선택 공고/대기 파일 영역 초기화 (부서 변경 시)
function resetAnalysisSelection() {
    analysisSelectedPostingId = null;
    analysisSelectedPostingTitle = '';
    pendingPage = 1;
    document.getElementById('pendingTableBody').innerHTML =
        '<tr><td colspan="5" class="empty-cell">왼쪽에서 공고를 선택하세요.</td></tr>';
    document.getElementById('pendingMeta').textContent = '왼쪽에서 공고를 선택하세요.';
    renderPager('pending', 1, pendingSize, 0);
    updatePostingAnalyzeState(null);
    document.getElementById('driveAnalysisResultSection').classList.add('hidden');
}

// 부서/팀 선택(검색조건) → 공고 목록 1페이지부터 재조회
function onAnalysisDeptSelected(deptId) {
    analysisSelectedDeptId = deptId;
    analysisPostingPage = 1;
    resetAnalysisSelection();
    loadAnalysisPostings();
}

// '전체 부서' : 부서 검색조건 해제
function clearAnalysisDeptFilter() {
    analysisSelectedDeptId = null;
    document.querySelectorAll('#analysisDeptTree .tree-group.selected, #analysisDeptTree .tree-team.selected')
        .forEach(el => el.classList.remove('selected'));
    const search = document.getElementById('analysisDeptSearchInput');
    if (search) search.value = '';
    analysisPostingPage = 1;
    resetAnalysisSelection();
    loadAnalysisPostings();
}

function setupAnalysisJobsUI() {
    const searchBtn = document.getElementById('analysisPostingSearchBtn');
    if (!searchBtn) return;
    // 부서/팀 트리(검색조건) — 이력서 현황과 동일 컴포넌트 재사용
    renderDeptTree(document.getElementById('analysisDeptTree'), onAnalysisDeptSelected);
    setupDeptSearch('analysisDeptSearchInput', 'analysisDeptSearchBtn', 'analysisDeptTree',
        onAnalysisDeptSelected, () => analysisSelectedDeptId);
    document.getElementById('analysisDeptAllBtn').addEventListener('click', clearAnalysisDeptFilter);

    const search = () => { analysisPostingPage = 1; resetAnalysisSelection(); loadAnalysisPostings(); };
    searchBtn.addEventListener('click', search);
    wireEnterSearch(['analysisPostingKeyword', 'analysisPostingDateFrom', 'analysisPostingDateTo'], search);
    document.getElementById('analysisPostingTodayBtn').addEventListener('click', () => {
        const iso = todayIso();
        document.getElementById('analysisPostingDateFrom').value = iso;
        document.getElementById('analysisPostingDateTo').value = iso;
        search();
    });
    document.getElementById('analysisPostingResetBtn').addEventListener('click', () => {
        ['Keyword', 'Platform', 'DateFrom', 'DateTo'].forEach(s => {
            const el = document.getElementById('analysisPosting' + s);
            if (el) el.value = '';
        });
        search();
    });
    // 공고/JD 리스트 페이징 (size=5 고정, 이전/다음만)
    document.getElementById('analysisPostingPrevBtn').addEventListener('click', () => {
        if (analysisPostingPage > 1) { analysisPostingPage--; loadAnalysisPostings(); }
    });
    document.getElementById('analysisPostingNextBtn').addEventListener('click', () => {
        analysisPostingPage++; loadAnalysisPostings();
    });
    // 분석 대기 파일 페이징 (페이지 변경 시 체크박스는 재렌더로 초기화됨)
    document.getElementById('pendingSizeSelect').addEventListener('change', (e) => {
        pendingSize = parseInt(e.target.value, 10) || 20;
        pendingPage = 1;
        if (analysisSelectedPostingId) loadPostingPending(analysisSelectedPostingId);
    });
    document.getElementById('pendingPrevBtn').addEventListener('click', () => {
        if (pendingPage > 1 && analysisSelectedPostingId) { pendingPage--; loadPostingPending(analysisSelectedPostingId); }
    });
    document.getElementById('pendingNextBtn').addEventListener('click', () => {
        if (analysisSelectedPostingId) { pendingPage++; loadPostingPending(analysisSelectedPostingId); }
    });
}

// 헤더 '전체 선택' 체크박스: 현재 표시된 모든 행 체크박스를 토글하고 버튼 상태를 갱신합니다.
function togglePendingSelectAll() {
    const checked = document.getElementById('pendingSelectAll').checked;
    document.querySelectorAll('#pendingTableBody .pending-row-check')
        .forEach(cb => { cb.checked = checked; });
    updateAnalyzeSelectedState();
}

// 체크된 항목 수에 따라 '선택 항목 분석 실행' 버튼 활성/비활성을 갱신합니다.
function updateAnalyzeSelectedState() {
    const btn = document.getElementById('analyzeSelectedBtn');
    if (!btn) return;
    const checkedCount = document.querySelectorAll('#pendingTableBody .pending-row-check:checked').length;
    btn.disabled = (checkedCount === 0) || analysisRunning;
}

// 분석 결과 요약(total/success/failed) 을 결과 영역에 표시합니다. (선택 공고/선택 항목/전체 분석 공용)
function showAnalysisSummary(data) {
    const el = document.getElementById('driveAnalysisResult');
    let html;
    // 비동기(Celery) 전환: 분석은 큐에 등록되고 worker 가 처리합니다. 결과는 현황/대기목록 새로고침으로 확인.
    if (data.status === 'QUEUED' || data.task_id || Array.isArray(data.tasks)) {
        const cnt = Array.isArray(data.tasks)
            ? data.tasks.reduce((s, t) => s + (t.resume_file_count || t.pending_count || 0), 0)
            : (data.pending_count != null ? data.pending_count : null);
        html = `<p>${escapeHtml(data.message || '분석 작업이 큐에 등록되었습니다.')}</p>
            <p class="hint">${cnt != null ? '대상 ' + cnt + '건 · ' : ''}잠시 후 '이력서 현황' 또는 대기 목록 새로고침으로 결과를 확인하세요.</p>`;
    } else if (data.status === 'ALREADY_PROCESSING' || data.status === 'NO_PENDING') {
        html = `<p>${escapeHtml(data.message || '')}</p>`;
    } else {
        html = `<p>${escapeHtml(data.message || '분석이 완료되었습니다.')}</p>
            <p class="hint">총 ${data.total || 0}건 · 성공 ${data.success || 0}건 · 실패 ${data.failed || 0}건</p>`;
        const errs = (data.posting_errors || []).map(e => ({ id: e.posting_id, msg: e.message || e.step }))
            .concat((data.dept_errors || []).map(e => ({ id: e.dept_id, msg: e.message || e.step })));
        if (errs.length) {
            html += '<p class="text-danger">일부 공고는 실행하지 못했습니다:</p><ul>' +
                errs.map(e => `<li class="hint">${escapeHtml(String(e.id))}: ${escapeHtml(String(e.msg || '-'))}</li>`).join('') +
                '</ul>';
        }
    }
    el.innerHTML = html;
    document.getElementById('driveAnalysisResultSection').classList.remove('hidden');
}

// 분석 실행 오류를 결과 영역에 표시합니다. (HTTP status 별로 사용자 친화적 문구)
function showAnalysisError(data, status) {
    data = data || {};
    let msg;
    if (status === 404) {
        msg = '분석 API를 찾을 수 없습니다. 서버가 최신 코드로 재시작되었는지 확인하거나 관리자에게 문의하세요.';
    } else if (status === 403) {
        msg = data.detail || '해당 항목을 분석할 권한이 없습니다.';
    } else if (status === 500) {
        msg = data.detail || data.error_message || '분석 실행 중 오류가 발생했습니다.';
    } else {
        // 400 등 서버가 구체 메시지를 준 경우는 그대로 사용
        msg = data.detail || data.error_message || '분석 실행 중 오류가 발생했습니다.';
    }
    const step = data.step ? `[${data.step}] ` : '';
    document.getElementById('driveAnalysisResult').innerHTML =
        `<p class="text-danger">${escapeHtml(step)}${escapeHtml(String(msg))}</p>
         <p class="hint">${escapeHtml(String(data.hint || ''))}</p>`;
    document.getElementById('driveAnalysisResultSection').classList.remove('hidden');
}

// 선택 항목 분석 실행: 체크된 resume_file_id 만 분석합니다. (백엔드에서 권한/PENDING 재검증)
async function runSelectedAnalyze() {
    if (analysisRunning) return;
    const ids = Array.from(document.querySelectorAll('#pendingTableBody .pending-row-check:checked'))
        .map(cb => parseInt(cb.dataset.id, 10)).filter(n => !Number.isNaN(n));
    if (!ids.length) return;   // 버튼이 disabled 라 보통 도달 안 함(방어)
    if (!confirm('선택한 항목을 분석하시겠습니까?')) return;

    const btn = document.getElementById('analyzeSelectedBtn');
    analysisRunning = true;
    btn.disabled = true;
    const orig = btn.textContent;
    btn.textContent = '분석 중...';
    document.getElementById('driveAnalysisResultSection').classList.add('hidden');
    try {
        const res = await fetch('/api/resumes/analyze-selected', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ resume_file_ids: ids }),
        });
        if (res.status === 401) { window.location.href = '/login'; return; }
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.status === 'ERROR') { showAnalysisError(data, res.status); return; }
        showAnalysisSummary(data);
    } catch (e) {
        showAnalysisError({ error_message: '분석 요청 실패: ' + e.message });
    } finally {
        analysisRunning = false;
        btn.textContent = orig;
        // 목록 새로고침(선택 초기화 + 분석된 항목 제거) + 좌측 공고 대기 건수 갱신.
        if (analysisSelectedPostingId) loadPostingPending(analysisSelectedPostingId);
        refreshAnalysisPostingCounts();
    }
}

// 전체 분석 실행: 공고 기준 전체 분석 대기 파일을 분석합니다. (ADMIN 전용 — 백엔드에서 403 재검증)
async function runAllAnalyze() {
    if (analysisRunning) return;
    if (!confirm('전체 공고의 분석 대기 파일을 분석하시겠습니까? (관리자 전용)')) return;

    const btn = document.getElementById('analyzeAllBtn');
    analysisRunning = true;
    btn.disabled = true;
    const orig = btn.textContent;
    btn.textContent = '분석 중...';
    document.getElementById('driveAnalysisResultSection').classList.add('hidden');
    try {
        const res = await fetch('/api/resumes/analyze-all', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
        });
        if (res.status === 401) { window.location.href = '/login'; return; }
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.status === 'ERROR') { showAnalysisError(data, res.status); return; }
        showAnalysisSummary(data);
    } catch (e) {
        showAnalysisError({ error_message: '분석 요청 실패: ' + e.message });
    } finally {
        analysisRunning = false;
        btn.disabled = false;
        btn.textContent = orig;
        if (analysisSelectedPostingId) loadPostingPending(analysisSelectedPostingId);
        refreshAnalysisPostingCounts();
    }
}

// 좌측 공고 리스트의 분석 대기 건수만 가볍게 다시 그립니다. (분석 실행 후 카운트 반영)
async function refreshAnalysisPostingCounts() {
    if (document.getElementById('view-analysisJobs').classList.contains('hidden')) return;
    loadAnalysisPostings();
}

// count: null = 공고 선택 전/로딩 중, 0 = 대기 없음, N = 대기 N건
function updatePostingAnalyzeState(count) {
    const btn = document.getElementById('analyzePostingBtn');
    const msg = document.getElementById('analyzeStatusMsg');
    if (!analysisSelectedPostingId) {
        btn.disabled = true;
        msg.textContent = '왼쪽에서 공고를 선택해주세요.';
    } else if (count === null) {
        btn.disabled = true;
        msg.textContent = '분석 대기 파일을 확인하는 중입니다...';
    } else if (count === 0) {
        btn.disabled = true;
        msg.textContent = '선택한 공고에 분석 대기 파일이 없습니다.';
    } else {
        btn.disabled = analysisRunning;
        msg.textContent = `분석 대기 파일 ${count}개가 있습니다. 분석을 실행할 수 있습니다.`;
    }
}

// '선택 공고 분석 실행': 선택 공고의 분석 대기 파일을 공고 JD 기준으로 분석합니다.
// 성공 파일은 completed, 실패 파일은 failed 로 이동되고 결과를 화면에 표시합니다.
async function runPostingAnalyze() {
    const btn = document.getElementById('analyzePostingBtn');
    const note = document.getElementById('analyzeNote');
    const resultSection = document.getElementById('driveAnalysisResultSection');
    if (analysisRunning) return;
    if (!analysisSelectedPostingId || btn.disabled) return;
    if (!confirm('선택한 공고의 분석 대기 파일을 분석하시겠습니까?')) return;

    analysisRunning = true;
    btn.disabled = true;
    btn.textContent = '분석 요청 중...';
    note.textContent = '분석 작업을 큐에 등록하는 중입니다...';
    resultSection.classList.add('hidden');
    try {
        const res = await fetch('/api/resumes/analyze-posting', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ posting_id: parseInt(analysisSelectedPostingId, 10) }),
        });
        if (res.status === 401) { window.location.href = '/login'; return; }
        const data = await res.json();
        if (!res.ok || data.status === 'ERROR') {
            document.getElementById('driveAnalysisResult').innerHTML =
                `<p class="text-danger">[${escapeHtml(String(data.step || '-'))}] ${escapeHtml(String(data.detail || data.error_message || '분석 실패'))}</p>
                 <p class="hint">${escapeHtml(String(data.hint || ''))}</p>`;
            resultSection.classList.remove('hidden');
            return;
        }
        // 비동기 전환: 분석 결과가 아니라 큐 등록 상태를 안내합니다. (결과는 현황/대기목록 새로고침)
        showAnalysisSummary(data);
    } catch (e) {
        document.getElementById('driveAnalysisResult').innerHTML =
            `<p class="text-danger">분석 요청 실패: ${escapeHtml(e.message)}</p>`;
        resultSection.classList.remove('hidden');
    } finally {
        analysisRunning = false;
        btn.textContent = '선택 공고 분석 실행';
        note.textContent = '';
        loadPostingPending(analysisSelectedPostingId);
        refreshAnalysisPostingCounts();
    }
}

function renderAnalysisResults(data) {
    const el = document.getElementById('driveAnalysisResult');
    if (data.message && (!data.results || !data.results.length)) {
        el.innerHTML = `<p class="hint">${escapeHtml(data.message)}</p>`;
        return;
    }
    const cards = (data.results || []).map(r => {
        if (r.analysis_status === 'COMPLETED') {
            return `<div class="card">
                <p><strong>${escapeHtml(r.original_file_name)}</strong> — 점수 <strong>${r.score}</strong> / 추천: ${escapeHtml(r.recommendation || '-')}</p>
                <p><strong>요약:</strong> ${escapeHtml(r.summary || '')}</p>
                <p><strong>강점:</strong> ${escapeHtml((r.strengths || []).join(', ') || '-')}</p>
                <p><strong>보완점:</strong> ${escapeHtml((r.weaknesses || []).join(', ') || '-')}</p>
                <p><strong>매칭 기술:</strong> ${escapeHtml((r.matched_skills || []).join(', ') || '-')}</p>
                <p><strong>부족 기술:</strong> ${escapeHtml((r.missing_skills || []).join(', ') || '-')}</p>
                <p class="hint">상태: ${escapeHtml(r.analysis_status)} · 이동: ${escapeHtml(r.moved_to || '-')} (${escapeHtml(r.move_status || '-')})</p>
            </div>`;
        }
        return `<div class="card result-error">
            <p><strong>${escapeHtml(r.original_file_name)}</strong> — 분석 실패</p>
            <p><strong>실패 사유:</strong> ${escapeHtml(r.error_message || r.error_code || '-')}</p>
            <p class="hint">상태: ${escapeHtml(r.analysis_status)} · 이동: ${escapeHtml(r.moved_to || '-')} (${escapeHtml(r.move_status || '-')})</p>
        </div>`;
    }).join('');

    // 빈 inbox upload 폴더 정리 결과 (실패는 warning 으로만 표시)
    const cleanups = (data.empty_inbox_folder_cleanups || []).map(c => {
        const warn = c.cleanup_status === 'CLEANUP_FAILED' ? ' class="text-danger"' : '';
        return `<li${warn}>${escapeHtml(c.upload_folder_name || '-')}: ${escapeHtml(c.cleanup_status)}</li>`;
    }).join('');
    const cleanupBlock = cleanups
        ? `<p class="hint">빈 inbox 폴더 정리</p><ul>${cleanups}</ul>`
        : '';

    // DB 저장 상태 (PARTIAL/FAILED 면 빨간색으로 명확히 표시)
    const dbStatus = data.db_save_status || 'OK';
    const dbLine = `<p class="${dbStatus === 'OK' ? 'hint' : 'text-danger'}">DB 저장 상태: ${escapeHtml(dbStatus)} (기준 저장소: resume_ai.resume_analysis_results)</p>`;

    el.innerHTML = `<p class="hint">전체 ${data.total_pending_files}건 · 성공 ${data.completed_count} · 실패 ${data.failed_count}</p>${dbLine}${cards}${cleanupBlock}`;
}

function renderDriveUploadError(d) {
    let html = `
        <p><strong>step:</strong> ${escapeHtml(String(d.step || '-'))}</p>
        <p><strong>error_message:</strong> ${escapeHtml(String(d.error_message || '업로드 실패'))}</p>
        <p><strong>hint:</strong> ${escapeHtml(String(d.hint || ''))}</p>`;
    // 업로드 가능한 파일이 0개인 경우 제외 사유도 함께 표시
    if (d.skipped_files && d.skipped_files.length) {
        const skipped = d.skipped_files.map(f =>
            `<li>${escapeHtml(f.original_file_name)} <span class="hint">(${escapeHtml(f.reason)})</span></li>`).join('');
        html += `<p><strong>제외된 파일</strong></p><ul>${skipped}</ul>`;
    }
    document.getElementById('driveUploadError').innerHTML = html;
}

function escapeHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ---------- 이력서 현황 (채용 관리) ----------
// DB(resume_ai) 기준으로 업로드된 이력서 파일 목록/상세/Excel 을 조회합니다.

// 분석 상태 코드 -> 한글 표시
const ANALYSIS_STATUS_LABEL = {
    PENDING: '분석 대기', PROCESSING: '분석 중',
    COMPLETED: '분석 완료', FAILED: '분석 실패',
};

function statusAnalysisLabel(code) {
    if (!code) return '-';
    return ANALYSIS_STATUS_LABEL[code] || code;
}

// ISO 문자열을 "YYYY-MM-DD HH:mm" 로 표시합니다. (없으면 '-')
function formatDateTime(s) {
    if (!s) return '-';
    return String(s).replace('T', ' ').slice(0, 16);
}

// 부서 트리에서 팀 선택 -> 해당 부서로 필터 (선택 강조는 트리 노드 하이라이트로 표시)
function onStatusTeamSelected(deptId, deptName) {
    statusFilterDeptId = deptId;
    statusPage = 1;
    loadResumeStatusList();
}

// '전체 부서' : 부서 필터 해제
function clearStatusDeptFilter() {
    statusFilterDeptId = null;
    document.querySelectorAll('#statusDeptTree .tree-group.selected, #statusDeptTree .tree-team.selected')
        .forEach(el => el.classList.remove('selected'));
    statusPage = 1;
    loadResumeStatusList();
}

// 현재 필터 상태 -> URLSearchParams (page/size 제외, Excel 과 목록 공용)
function buildStatusFilterParams() {
    const params = new URLSearchParams();
    if (statusFilterDeptId) params.set('dept_id', statusFilterDeptId);
    const analysis = document.getElementById('statusAnalysisFilter').value;
    const recommendation = document.getElementById('statusRecommendationFilter').value;
    const keyword = document.getElementById('statusKeyword').value.trim();
    const postingKeyword = document.getElementById('statusPostingKeyword').value.trim();
    const dateFrom = document.getElementById('statusDateFrom').value;
    const dateTo = document.getElementById('statusDateTo').value;
    if (analysis) params.set('analysis_status', analysis);
    if (recommendation) params.set('recommendation', recommendation);
    if (keyword) params.set('keyword', keyword);
    if (postingKeyword) params.set('posting_keyword', postingKeyword);
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    return params;
}

async function loadResumeStatusList() {
    const errorEl = document.getElementById('statusError');
    const metaEl = document.getElementById('statusListMeta');
    const bodyEl = document.getElementById('statusTableBody');
    errorEl.innerHTML = '';
    metaEl.textContent = '이력서 목록을 불러오는 중입니다.';
    bodyEl.innerHTML = '';
    try {
        const params = buildStatusFilterParams();
        params.set('page', String(statusPage));
        params.set('size', String(statusPageSize));
        const res = await fetch(`/api/resumes/status?${params.toString()}`);
        if (res.status === 401) { window.location.href = '/login'; return; }
        const data = await res.json();
        if (!res.ok || data.status === 'ERROR') {
            metaEl.textContent = '';
            // 권한 오류(403 등)는 detail, 기존 서비스 오류는 error_message 로 내려옵니다.
            errorEl.innerHTML = `<p class="text-danger">${escapeHtml(data.detail || data.error_message || '조회 실패')}</p>
                <p class="hint">${escapeHtml(data.hint || '')}</p>`;
            return;
        }
        statusTotal = data.total;
        renderStatusTable(data);
    } catch (e) {
        metaEl.textContent = '';
        errorEl.innerHTML = `<p class="text-danger">이력서 현황 조회 요청 실패: ${escapeHtml(e.message)}</p>`;
    }
}

function renderStatusTable(data) {
    const bodyEl = document.getElementById('statusTableBody');
    const metaEl = document.getElementById('statusListMeta');
    metaEl.textContent = `총 ${data.total}건`;

    if (!data.items.length) {
        // 필터가 걸려 있으면 '조회된 이력서가 없습니다.', 아니면 '데이터가 없습니다.'
        const emptyMsg = [...buildStatusFilterParams().keys()].length
            ? '조회된 이력서가 없습니다.' : '데이터가 없습니다.';
        bodyEl.innerHTML = `<tr><td colspan="9" class="empty-cell">${emptyMsg}</td></tr>`;
    } else {
        // '상세' 컬럼 제거 -> row 클릭으로 상세 팝업을 엽니다. (유형은 상세 팝업에서만 확인)
        bodyEl.innerHTML = data.items.map(it => {
            const fileName = it.original_file_name || it.stored_file_name || '-';
            const score = (it.score === null || it.score === undefined) ? '-' : it.score;
            // 공고 미매핑(legacy) 데이터는 '-' 로 표시
            const postingTitle = it.posting_title || '-';
            return `<tr class="clickable-row" data-id="${it.resume_file_id}">
                <td class="cell-filename" title="${escapeHtml(postingTitle)}">${escapeHtml(postingTitle)}</td>
                <td>${escapeHtml(it.dept_name || it.dept_id || '-')}</td>
                <td class="cell-filename" title="${escapeHtml(fileName)}">${escapeHtml(fileName)}</td>
                <td>${fileStatusBadge(it.file_status)}</td>
                <td>${statusBadge(it.analysis_status)}</td>
                <td class="cell-score">${escapeHtml(String(score))}</td>
                <td>${recommendationBadge(it.recommendation)}</td>
                <td>${escapeHtml(formatDateTime(it.uploaded_at))}</td>
                <td>${escapeHtml(formatDateTime(it.analyzed_at))}</td>
            </tr>`;
        }).join('');
        bodyEl.querySelectorAll('tr.clickable-row').forEach(row => {
            row.addEventListener('click', () => openStatusDetail(row.dataset.id));
        });
    }

    // 페이징 표시
    const totalPages = Math.max(1, Math.ceil(data.total / data.size));
    document.getElementById('statusPageInfo').textContent = `${data.page} / ${totalPages} 페이지`;
    document.getElementById('statusPrevBtn').disabled = data.page <= 1;
    document.getElementById('statusNextBtn').disabled = data.page >= totalPages;
}

// ----- 상태/추천/이동 badge -----
function statusBadge(code) {
    if (!code) return '-';
    const cls = { PENDING: 'badge-gray', PROCESSING: 'badge-blue',
                  COMPLETED: 'badge-green', FAILED: 'badge-red' }[code] || 'badge-gray';
    return `<span class="badge ${cls}">${escapeHtml(statusAnalysisLabel(code))}</span>`;
}

// 파일 상태: UPLOADED -> 업로드 완료
const FILE_STATUS_LABEL = { UPLOADED: '업로드 완료' };
function fileStatusBadge(code) {
    if (!code) return '-';
    const cls = code === 'UPLOADED' ? 'badge-blue' : 'badge-gray';
    return `<span class="badge ${cls}">${escapeHtml(FILE_STATUS_LABEL[code] || code)}</span>`;
}

function recommendationBadge(rec) {
    if (!rec) return '-';
    const cls = { '우선 검토 추천': 'badge-green', '추가 검토 필요': 'badge-amber',
                  '낮은 적합도': 'badge-gray' }[rec] || 'badge-gray';
    return `<span class="badge ${cls}">${escapeHtml(rec)}</span>`;
}

function moveBadge(mv) {
    if (!mv) return '-';
    const cls = { MOVED_TO_COMPLETED: 'badge-green', MOVED_TO_FAILED: 'badge-red',
                  MOVE_FAILED: 'badge-red' }[mv] || 'badge-gray';
    return `<span class="badge ${cls}">${escapeHtml(mv)}</span>`;
}

// ----- 상세 보기 모달 -----
function openStatusModal() {
    document.getElementById('statusModalOverlay').classList.remove('hidden');
}

function closeStatusModal() {
    const overlay = document.getElementById('statusModalOverlay');
    overlay.classList.add('hidden');
    // 다음에 열 때 이전 내용이 잠깐 보이지 않도록 초기화합니다.
    document.getElementById('statusModalFileName').textContent = '';
    document.getElementById('statusModalBody').innerHTML = '';
}

async function openStatusDetail(resumeFileId) {
    // resume_file_id 가 없으면 모달을 열지 않고 로그만 남깁니다.
    if (!resumeFileId) {
        console.error('openStatusDetail: resume_file_id 가 없습니다.');
        return;
    }
    const body = document.getElementById('statusModalBody');
    document.getElementById('statusModalFileName').textContent = '';
    body.innerHTML = '<p class="hint">상세 정보를 불러오는 중입니다.</p>';
    openStatusModal();
    try {
        const res = await fetch(`/api/resumes/status/${resumeFileId}`);
        if (res.status === 401) { window.location.href = '/login'; return; }
        const data = await res.json();
        if (!res.ok || data.status === 'ERROR') {
            body.innerHTML = `<p class="text-danger">${escapeHtml(data.detail || data.error_message || '상세 조회 실패')}</p>
                <p class="hint">${escapeHtml(data.hint || '')}</p>`;
            return;
        }
        renderStatusDetail(data);
    } catch (e) {
        body.innerHTML = `<p class="text-danger">상세 조회 요청 실패: ${escapeHtml(e.message)}</p>`;
    }
}

// key-value 한 줄 (값은 escape)
function kv(label, value) {
    const v = (value === null || value === undefined || value === '') ? '-' : value;
    return `<p class="kv"><strong>${escapeHtml(label)}:</strong> ${escapeHtml(String(v))}</p>`;
}

// key-value 한 줄 (값이 이미 HTML 인 경우: badge 등)
function kvRaw(label, htmlValue) {
    return `<p class="kv"><strong>${escapeHtml(label)}:</strong> ${htmlValue}</p>`;
}

// 긴 문자열(경로/근거 등): 줄바꿈 가능하게 별도 줄에 표시
function kvLong(label, value) {
    const v = (value === null || value === undefined || value === '') ? '-' : value;
    return `<p class="kv"><strong>${escapeHtml(label)}:</strong></p><p class="long-text">${escapeHtml(String(v))}</p>`;
}

// 리스트(강점/보완점/기술) -> bullet 또는 '-'
function statusList(label, arr) {
    if (!arr || !arr.length) return `<p class="kv"><strong>${escapeHtml(label)}:</strong> -</p>`;
    const items = arr.map(x => `<li>${escapeHtml(String(x))}</li>`).join('');
    return `<p class="kv"><strong>${escapeHtml(label)}:</strong></p><ul>${items}</ul>`;
}

function renderStatusDetail(data) {
    const f = data.resume_file;
    const a = data.analysis_result;
    document.getElementById('statusModalFileName').textContent =
        f.original_file_name || f.stored_file_name || '';

    // 7-1. 기본 정보 (공고명/부서/파일명/업로드ID/업로드 일시)
    const dept = `${f.dept_name || ''} (${f.dept_id})`.trim();
    const postingTitle = f.posting_title || '-';   // 공고 미매핑(legacy)은 '-'
    let html = '<section class="modal-section"><h4>기본 정보</h4>';
    html += '<table class="resume-detail-table"><tbody>';
    html += `<tr>
        <th>공고명/JD명</th><td>${escapeHtml(postingTitle)}</td>
        <th>부서</th><td>${escapeHtml(dept)}</td>
    </tr>`;
    html += `<tr>
        <th>파일명</th><td>${fileNameCellHtml(f)}</td>
        <th>업로드 일시</th><td>${escapeHtml(formatDateTime(f.created_at))}</td>
    </tr>`;
    html += `<tr>
        <th>업로드ID</th><td colspan="3">${escapeHtml(f.upload_id || '-')}</td>
    </tr>`;
    html += '</tbody></table></section>';

    // 7-2. 분석 상태 (핵심 항목만 2/2 table 로 표시, 기존 badge 유지)
    html += '<section class="modal-section"><h4>분석 상태</h4>';
    html += '<table class="resume-detail-table"><tbody>';
    html += `<tr>
        <th>파일 상태</th><td>${fileStatusBadge(f.file_status)}</td>
        <th>분석 상태</th><td>${statusBadge(f.analysis_status)}</td>
    </tr>`;
    html += `<tr>
        <th>이동 상태</th><td>${moveBadge(f.move_status)}</td>
        <th>분석 일시</th><td>${escapeHtml(formatDateTime(f.analyzed_at))}</td>
    </tr>`;
    html += '</tbody></table></section>';

    // 7-3. 분석 결과
    html += '<section class="modal-section"><h4>분석 결과</h4>';
    if (!a) {
        html += `<p class="hint">아직 분석 결과가 없습니다.</p>`;
    } else if (a.analysis_status === 'FAILED') {
        html += `<p class="hint">분석에 실패하여 결과가 없습니다. (아래 오류 정보 참고)</p>`;
    } else {
        const score = (a.score === null || a.score === undefined) ? '-' : String(a.score);
        html += kvRaw('점수', escapeHtml(score));
        html += kvRaw('추천', recommendationBadge(a.recommendation));
        html += kvLong('요약', a.summary);
        html += statusList('강점', a.strengths);
        html += statusList('보완점', a.weaknesses);
        html += statusList('매칭 기술', a.matched_skills);
        html += statusList('부족 기술', a.missing_skills);
        html += kvLong('분석 근거', a.reasoning);
    }
    html += '</section>';

    // 7-4. 오류 정보
    const errCode = (a && a.error_code) || f.error_code;
    const errMsg = (a && a.error_message) || f.error_message;
    html += '<section class="modal-section"><h4>오류 정보</h4>';
    if (errCode || errMsg || f.analysis_status === 'FAILED') {
        html += kv('error_code', errCode);
        html += kvLong('error_message', errMsg);
    } else {
        html += `<p class="hint">오류 없음</p>`;
    }
    html += '</section>';

    document.getElementById('statusModalBody').innerHTML = html;

    // 파일명 다운로드 링크 클릭 → 원본 파일 다운로드 (ADMIN/MANAGER 만 링크 렌더됨)
    const dlEl = document.querySelector('#statusModalBody .file-download-link');
    if (dlEl) dlEl.addEventListener('click', () => downloadResumeFile(dlEl.dataset.rfid));
}

// 상세 팝업 파일명 셀: ADMIN/MANAGER 는 클릭 시 원본 다운로드 링크, VIEWER 는 일반 텍스트.
function fileNameCellHtml(f) {
    const name = f.original_file_name || f.stored_file_name || '-';
    const canDownload = currentUser && currentUser.role_code !== 'VIEWER' && f.id != null;
    if (!canDownload) return escapeHtml(name);
    return `<a class="file-download-link" data-rfid="${f.id}" title="원본 파일 다운로드">${escapeHtml(name)} <span class="dl-icon">⬇</span></a>`;
}

// 이력서 원본 파일 다운로드. 백엔드가 권한 검증 후 attachment 로 내려줍니다. (세션 쿠키 자동 포함)
async function downloadResumeFile(resumeFileId) {
    if (!resumeFileId) return;
    try {
        const res = await fetch(`/api/resumes/${resumeFileId}/download`);
        if (res.status === 401) { window.location.href = '/login'; return; }
        if (!res.ok) {
            let msg = '파일 다운로드 중 오류가 발생했습니다.';
            if (res.status === 403) msg = '파일을 다운로드할 권한이 없습니다.';
            else if (res.status === 404) msg = '다운로드할 원본 파일을 찾을 수 없습니다.';
            try { const j = await res.json(); msg = j.detail || j.error_message || msg; } catch (_) {}
            alert(msg);
            return;
        }
        const blob = await res.blob();
        // 서버 Content-Disposition(filename*=UTF-8'') 에서 원본 파일명 추출
        let filename = 'resume';
        const disp = res.headers.get('Content-Disposition') || '';
        const m = disp.match(/filename\*=UTF-8''([^;]+)/i);
        if (m) { try { filename = decodeURIComponent(m[1]); } catch (_) { filename = m[1]; } }
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    } catch (e) {
        alert('파일 다운로드 중 오류가 발생했습니다.');
    }
}

// '오늘' 버튼: 업로드일 시작/종료를 오늘 날짜로 설정하고 조회합니다.
function setStatusToday() {
    const d = new Date();
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    document.getElementById('statusDateFrom').value = iso;
    document.getElementById('statusDateTo').value = iso;
    statusPage = 1;
    loadResumeStatusList();
}

function resetStatusFilters() {
    document.getElementById('statusAnalysisFilter').value = '';
    document.getElementById('statusRecommendationFilter').value = '';
    document.getElementById('statusKeyword').value = '';
    document.getElementById('statusPostingKeyword').value = '';
    document.getElementById('statusDateFrom').value = '';
    document.getElementById('statusDateTo').value = '';
    statusPageSize = 20;
    document.getElementById('statusSizeSelect').value = '20';
    clearStatusDeptFilter(); // 부서 필터 해제 + 목록 재조회(page=1)
}

async function downloadStatusExcel() {
    const btn = document.getElementById('statusExcelBtn');
    const errorEl = document.getElementById('statusError');
    errorEl.innerHTML = '';
    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = '다운로드 중...';
    try {
        const res = await fetch(`/api/resumes/status/export-excel?${buildStatusFilterParams().toString()}`);
        if (res.status === 401) { window.location.href = '/login'; return; }
        if (!res.ok) {
            // 에러는 JSON 으로 내려옵니다. (권한 오류는 detail)
            let msg = 'Excel 다운로드 실패';
            try { const j = await res.json(); msg = j.detail || j.error_message || msg; } catch (_) {}
            errorEl.innerHTML = `<p class="text-danger">${escapeHtml(msg)}</p>`;
            return;
        }
        const blob = await res.blob();
        // 서버 Content-Disposition 의 파일명을 우선 사용합니다.
        let filename = 'resume_status.xlsx';
        const disp = res.headers.get('Content-Disposition') || '';
        const m = disp.match(/filename="?([^"]+)"?/);
        if (m) filename = m[1];
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    } catch (e) {
        errorEl.innerHTML = `<p class="text-danger">Excel 다운로드 요청 실패: ${escapeHtml(e.message)}</p>`;
    } finally {
        btn.disabled = false;
        btn.textContent = original;
    }
}

// ============ 관리자 > 사용자 관리 (ADMIN 전용) ============
// 사용자 목록/추가/수정/비밀번호초기화/활성화·비활성화 + 부서 검색 선택.
// 보안: password_hash 는 서버가 내려주지 않으며 화면에도 표시하지 않습니다.
let adminUserEditingId = null;        // null = 추가 모드, 값 = 수정 모드(user_id)
let adminUserSelectedDept = null;     // {id, name, path}
let adminUserCurrentActive = true;    // 수정 대상의 현재 활성 상태

// 401 → 로그인, 403/기타 → 메시지 반환. (사용자 관리 fetch 공통 처리)
async function adminFetchJson(url, options) {
    const res = await fetch(url, options);
    if (res.status === 401) { window.location.href = '/login'; return { _redirect: true }; }
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    return { ok: res.ok, status: res.status, data };
}

function userStatusBadge(active) {
    return active
        ? '<span class="badge badge-green">활성</span>'
        : '<span class="badge badge-gray">비활성</span>';
}
function userRoleBadge(role) {
    const cls = { ADMIN: 'badge-blue', MANAGER: 'badge-amber', VIEWER: 'badge-gray' }[role] || 'badge-gray';
    return `<span class="badge ${cls}">${escapeHtml(role || '-')}</span>`;
}

async function loadAdminUsers() {
    const body = document.getElementById('adminUsersBody');
    const errorEl = document.getElementById('adminUsersError');
    errorEl.innerHTML = '';
    body.innerHTML = '<tr><td colspan="9" class="empty-cell">불러오는 중...</td></tr>';
    const { _redirect, ok, data } = await adminFetchJson('/api/admin/users');
    if (_redirect) return;
    if (!ok) {
        body.innerHTML = '';
        errorEl.innerHTML = `<p class="text-danger">${escapeHtml((data && data.detail) || '사용자 목록을 불러오지 못했습니다.')}</p>`;
        return;
    }
    renderAdminUsersTable(data);
}

function renderAdminUsersTable(users) {
    const body = document.getElementById('adminUsersBody');
    if (!users.length) {
        body.innerHTML = '<tr><td colspan="9" class="empty-cell">사용자가 없습니다.</td></tr>';
        return;
    }
    body.innerHTML = users.map(u => {
        const dept = u.department_name
            ? `${escapeHtml(u.department_name)} <span class="dept-code">(${escapeHtml(u.department_id)})</span>`
            : '-';
        return `<tr class="clickable-row" data-id="${u.id}">
            <td>${userStatusBadge(u.is_active)}</td>
            <td>${escapeHtml(u.login_id)}</td>
            <td>${escapeHtml(u.name)}</td>
            <td>${escapeHtml(u.email)}</td>
            <td>${userRoleBadge(u.role_code)}</td>
            <td>${dept}</td>
            <td>${escapeHtml(formatDateTime(u.last_login_at))}</td>
            <td>${escapeHtml(formatDateTime(u.created_at))}</td>
            <td><span class="row-action">상세</span></td>
        </tr>`;
    }).join('');
    body.querySelectorAll('tr.clickable-row').forEach(row => {
        row.addEventListener('click', () => openEditUserModal(row.dataset.id));
    });
}

// ----- 부서/팀 검색 선택 -----
function updateUserRoleDeptHint() {
    const role = document.getElementById('userRole').value;
    const hint = document.getElementById('userRoleDeptHint');
    if (role === 'ADMIN') hint.textContent = 'ADMIN은 부서와 관계없이 전체 접근 가능합니다. (부서 선택 사항)';
    else if (role === 'MANAGER') hint.textContent = '선택한 부서 및 하위 부서에 접근합니다. (부서 필수)';
    else hint.textContent = '선택한 부서 및 하위 부서를 조회할 수 있습니다. (부서 필수)';
}

function renderSelectedDept() {
    const box = document.getElementById('userSelectedDept');
    if (!adminUserSelectedDept) { box.classList.add('hidden'); box.innerHTML = ''; return; }
    box.classList.remove('hidden');
    box.innerHTML = `<strong>${escapeHtml(adminUserSelectedDept.name)}</strong> (${escapeHtml(adminUserSelectedDept.id)})
        <br><span class="hint">${escapeHtml(adminUserSelectedDept.path || '')}</span>
        <button type="button" id="userDeptClearBtn" class="btn-small" style="margin-left:8px;">선택 해제</button>`;
    document.getElementById('userDeptClearBtn').addEventListener('click', () => {
        adminUserSelectedDept = null; renderSelectedDept();
    });
}

async function searchUserDept() {
    const kw = document.getElementById('userDeptSearchInput').value.trim();
    const resultsEl = document.getElementById('userDeptSearchResults');
    resultsEl.innerHTML = '<p class="hint">검색 중...</p>';
    const { _redirect, ok, data } = await adminFetchJson(`/api/admin/departments/search?keyword=${encodeURIComponent(kw)}`);
    if (_redirect) return;
    if (!ok) { resultsEl.innerHTML = `<p class="text-danger">${escapeHtml((data && data.detail) || '부서 검색 실패')}</p>`; return; }
    if (!data.length) { resultsEl.innerHTML = '<p class="hint">검색 결과가 없습니다.</p>'; return; }
    resultsEl.innerHTML = data.map(d => `
        <div class="dept-search-result" data-id="${escapeHtml(d.id)}" data-name="${escapeHtml(d.name)}" data-path="${escapeHtml(d.path || '')}">
            <div class="name">${escapeHtml(d.name)} ${d.is_leaf ? '' : '<span class="hint">(상위 조직)</span>'}</div>
            <div class="meta">${escapeHtml(d.id)} · ${escapeHtml(d.path || '')}</div>
        </div>`).join('');
    resultsEl.querySelectorAll('.dept-search-result').forEach(el => {
        el.addEventListener('click', () => {
            adminUserSelectedDept = { id: el.dataset.id, name: el.dataset.name, path: el.dataset.path };
            resultsEl.innerHTML = '';
            document.getElementById('userDeptSearchInput').value = '';
            renderSelectedDept();
        });
    });
}

// ----- 팝업 열기/닫기 -----
function openAdminUserModal() { document.getElementById('adminUserModalOverlay').classList.remove('hidden'); }
function closeAdminUserModal() { document.getElementById('adminUserModalOverlay').classList.add('hidden'); }

function resetAdminUserForm() {
    document.getElementById('adminUserNotice').classList.add('hidden');
    document.getElementById('adminUserNotice').innerHTML = '';
    document.getElementById('userDeptSearchResults').innerHTML = '';
    document.getElementById('userDeptSearchInput').value = '';
    document.getElementById('userMeta').textContent = '';
    adminUserSelectedDept = null;
    renderSelectedDept();
}

function openAddUserModal() {
    adminUserEditingId = null;
    resetAdminUserForm();
    document.getElementById('adminUserModalTitle').textContent = '사용자 추가';
    document.getElementById('userLoginId').value = '';
    document.getElementById('userLoginId').readOnly = false;
    document.getElementById('userName2').value = '';
    document.getElementById('userEmail').value = '';
    document.getElementById('userRole').value = 'MANAGER';
    document.getElementById('adminUserForm').classList.remove('hidden');
    document.getElementById('userSaveBtn').classList.remove('hidden');
    document.getElementById('userSaveBtn').textContent = '추가';
    document.getElementById('userResetPwBtn').classList.add('hidden');
    document.getElementById('userToggleActiveBtn').classList.add('hidden');
    updateUserRoleDeptHint();
    openAdminUserModal();
}

async function openEditUserModal(userId) {
    adminUserEditingId = userId;
    resetAdminUserForm();
    document.getElementById('adminUserModalTitle').textContent = '사용자 상세/수정';
    const { _redirect, ok, data } = await adminFetchJson(`/api/admin/users/${userId}`);
    if (_redirect) return;
    if (!ok) { alert((data && data.detail) || '사용자 조회 실패'); return; }
    document.getElementById('userLoginId').value = data.login_id;
    document.getElementById('userLoginId').readOnly = true;   // login_id 수정 불가
    document.getElementById('userName2').value = data.name || '';
    document.getElementById('userEmail').value = data.email || '';
    document.getElementById('userRole').value = data.role_code || 'MANAGER';
    adminUserCurrentActive = data.is_active;
    if (data.department_id) {
        adminUserSelectedDept = { id: data.department_id, name: data.department_name || data.department_id, path: data.department_path || '' };
    }
    renderSelectedDept();
    updateUserRoleDeptHint();
    document.getElementById('userMeta').textContent =
        `상태: ${data.is_active ? '활성' : '비활성'}\n최근 로그인: ${formatDateTime(data.last_login_at)}\n생성일: ${formatDateTime(data.created_at)}\n수정일: ${formatDateTime(data.updated_at)}`;
    document.getElementById('userSaveBtn').classList.remove('hidden');
    document.getElementById('userSaveBtn').textContent = '저장';
    document.getElementById('userResetPwBtn').classList.remove('hidden');
    const toggleBtn = document.getElementById('userToggleActiveBtn');
    toggleBtn.classList.remove('hidden');
    toggleBtn.textContent = data.is_active ? '비활성화' : '활성화';
    openAdminUserModal();
}

function showUserNotice(html) {
    const el = document.getElementById('adminUserNotice');
    el.innerHTML = html;
    el.classList.remove('hidden');
}

// ----- 저장(추가/수정) -----
async function saveAdminUser() {
    const role = document.getElementById('userRole').value;
    const name = document.getElementById('userName2').value.trim();
    const email = document.getElementById('userEmail').value.trim();
    const deptId = adminUserSelectedDept ? adminUserSelectedDept.id : null;
    if ((role === 'MANAGER' || role === 'VIEWER') && !deptId) {
        alert('MANAGER/VIEWER 는 담당 부서를 선택해야 합니다.');
        return;
    }
    const btn = document.getElementById('userSaveBtn');
    btn.disabled = true;
    try {
        if (adminUserEditingId === null) {
            // 추가
            const loginId = document.getElementById('userLoginId').value.trim();
            if (!loginId || !name || !email) { alert('로그인ID, 이름, 이메일을 입력해주세요.'); return; }
            const { _redirect, ok, data } = await adminFetchJson('/api/admin/users', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ login_id: loginId, name, email, role_code: role, department_id: deptId }),
            });
            if (_redirect) return;
            if (!ok) { alert((data && data.detail) || '사용자 추가 실패'); return; }
            // 임시 비밀번호 1회 표시 + 폼 비활성(추가 완료)
            document.getElementById('adminUserForm').classList.add('hidden');
            document.getElementById('userSaveBtn').classList.add('hidden');
            showUserNotice(`<p>사용자가 추가되었습니다.</p>
                <p>초기 비밀번호: <span class="temp-pw">${escapeHtml(data.temporary_password)}</span></p>
                <p class="hint">이 비밀번호는 다시 확인할 수 없습니다. 사용자에게 전달 후 창을 닫아주세요.</p>`);
            loadAdminUsers();
        } else {
            // 수정
            const { _redirect, ok, data } = await adminFetchJson(`/api/admin/users/${adminUserEditingId}`, {
                method: 'PUT', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, email, role_code: role, department_id: deptId }),
            });
            if (_redirect) return;
            if (!ok) { alert((data && data.detail) || '사용자 수정 실패'); return; }
            closeAdminUserModal();
            loadAdminUsers();
        }
    } finally {
        btn.disabled = false;
    }
}

// ----- 비밀번호 초기화 -----
async function resetAdminUserPassword() {
    if (adminUserEditingId === null) return;
    if (!confirm('비밀번호를 초기화하시겠습니까?\n기존 비밀번호로는 더 이상 로그인할 수 없습니다.')) return;
    const { _redirect, ok, data } = await adminFetchJson(`/api/admin/users/${adminUserEditingId}/reset-password`, { method: 'PATCH' });
    if (_redirect) return;
    if (!ok) { alert((data && data.detail) || '비밀번호 초기화 실패'); return; }
    showUserNotice(`<p>비밀번호가 초기화되었습니다.</p>
        <p>임시 비밀번호: <span class="temp-pw">${escapeHtml(data.temporary_password)}</span></p>
        <p class="hint">이 값은 다시 확인할 수 없습니다.</p>`);
}

// ----- 활성/비활성 -----
async function toggleAdminUserActive() {
    if (adminUserEditingId === null) return;
    const willDeactivate = adminUserCurrentActive;
    if (willDeactivate && !confirm('이 사용자를 비활성화하시겠습니까?\n비활성화된 사용자는 로그인할 수 없습니다.')) return;
    const action = willDeactivate ? 'deactivate' : 'activate';
    const { _redirect, ok, data } = await adminFetchJson(`/api/admin/users/${adminUserEditingId}/${action}`, { method: 'PATCH' });
    if (_redirect) return;
    if (!ok) { alert((data && data.detail) || '상태 변경 실패'); return; }
    adminUserCurrentActive = data.is_active;
    document.getElementById('userToggleActiveBtn').textContent = data.is_active ? '비활성화' : '활성화';
    loadAdminUsers();
    // 메타 갱신
    document.getElementById('userMeta').textContent =
        `상태: ${data.is_active ? '활성' : '비활성'}\n최근 로그인: ${formatDateTime(data.last_login_at)}\n생성일: ${formatDateTime(data.created_at)}\n수정일: ${formatDateTime(data.updated_at)}`;
}

function setupAdminUsersUI() {
    const addBtn = document.getElementById('addUserBtn');
    if (!addBtn) return;   // 사용자 관리 화면이 없는 경우 방어
    addBtn.addEventListener('click', openAddUserModal);
    document.getElementById('userDeptSearchBtn').addEventListener('click', searchUserDept);
    document.getElementById('userDeptSearchInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); searchUserDept(); }
    });
    document.getElementById('userRole').addEventListener('change', updateUserRoleDeptHint);
    document.getElementById('userSaveBtn').addEventListener('click', saveAdminUser);
    document.getElementById('userResetPwBtn').addEventListener('click', resetAdminUserPassword);
    document.getElementById('userToggleActiveBtn').addEventListener('click', toggleAdminUserActive);
    document.getElementById('userModalCancelBtn').addEventListener('click', closeAdminUserModal);
    document.getElementById('adminUserModalCloseBtn').addEventListener('click', closeAdminUserModal);
    document.getElementById('adminUserModalOverlay').addEventListener('click', (e) => {
        if (e.target.id === 'adminUserModalOverlay') closeAdminUserModal();
    });
}

// ============ 내 정보 수정 (우측 상단 이름 클릭 → 본인 확인 → 이메일/비밀번호 수정) ============
// 모든 로그인 사용자(ADMIN/MANAGER/VIEWER) 가 본인 정보(이메일/비밀번호)만 수정합니다.
function openVerifyPwModal() {
    const err = document.getElementById('verifyPwError');
    err.classList.add('hidden'); err.textContent = '';
    document.getElementById('verifyPwInput').value = '';
    document.getElementById('verifyPwModalOverlay').classList.remove('hidden');
    document.getElementById('verifyPwInput').focus();
}
function closeVerifyPwModal() {
    document.getElementById('verifyPwModalOverlay').classList.add('hidden');
}

async function doVerifyPassword() {
    const pw = document.getElementById('verifyPwInput').value;
    const err = document.getElementById('verifyPwError');
    if (!pw) { err.textContent = '현재 비밀번호를 입력해주세요.'; err.classList.remove('hidden'); return; }
    const btn = document.getElementById('verifyPwConfirmBtn');
    btn.disabled = true;
    try {
        const res = await fetch('/api/auth/verify-password', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: pw }),
        });
        if (res.status === 401) {
            // 세션 만료가 아니라 비밀번호 불일치(본인 확인 실패)를 팝업 안에 표시
            const data = await res.json().catch(() => ({}));
            err.textContent = data.detail || '비밀번호가 일치하지 않습니다.';
            err.classList.remove('hidden');
            return;
        }
        if (!res.ok) { err.textContent = '본인 확인에 실패했습니다.'; err.classList.remove('hidden'); return; }
        closeVerifyPwModal();
        openProfileModal();
    } catch (e) {
        err.textContent = '요청에 실패했습니다. 잠시 후 다시 시도해주세요.';
        err.classList.remove('hidden');
    } finally {
        btn.disabled = false;
    }
}

function openProfileModal() {
    const u = currentUser || {};
    document.getElementById('profileNotice').classList.add('hidden');
    document.getElementById('profileNotice').innerHTML = '';
    document.getElementById('profileError').classList.add('hidden');
    document.getElementById('profileError').textContent = '';
    document.getElementById('profileLoginId').value = u.login_id || '';
    document.getElementById('profileName').value = u.name || '';
    document.getElementById('profileRole').value = u.role_code || '';
    document.getElementById('profileEmail').value = u.email || '';
    document.getElementById('profileNewPw').value = '';
    document.getElementById('profileNewPwConfirm').value = '';
    document.getElementById('profileModalOverlay').classList.remove('hidden');
}
function closeProfileModal() {
    document.getElementById('profileModalOverlay').classList.add('hidden');
}

async function saveProfile() {
    const email = document.getElementById('profileEmail').value.trim();
    const newPw = document.getElementById('profileNewPw').value;
    const newPwConfirm = document.getElementById('profileNewPwConfirm').value;
    const err = document.getElementById('profileError');
    err.classList.add('hidden'); err.textContent = '';
    // 프론트 1차 검증 (백엔드에서도 검증)
    if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
        err.textContent = '올바른 이메일 형식이 아닙니다.'; err.classList.remove('hidden'); return;
    }
    if (newPw && newPw !== newPwConfirm) {
        err.textContent = '새 비밀번호와 확인 값이 일치하지 않습니다.'; err.classList.remove('hidden'); return;
    }
    const btn = document.getElementById('profileSaveBtn');
    btn.disabled = true;
    try {
        const res = await fetch('/api/auth/me/profile', {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, new_password: newPw, new_password_confirm: newPwConfirm }),
        });
        if (res.status === 401) { window.location.href = '/login'; return; }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            err.textContent = data.detail || '저장에 실패했습니다.'; err.classList.remove('hidden'); return;
        }
        // currentUser + 우측 상단 헤더 갱신
        currentUser = data;
        document.getElementById('userName').textContent = `${data.name}님`;
        document.getElementById('userRole').textContent = data.role_code;
        const msg = newPw
            ? '내 정보가 수정되었습니다. 비밀번호가 변경되었습니다. 다음 로그인부터 새 비밀번호를 사용하세요.'
            : '내 정보가 수정되었습니다.';
        const notice = document.getElementById('profileNotice');
        notice.textContent = msg;
        notice.classList.remove('hidden');
        document.getElementById('profileNewPw').value = '';
        document.getElementById('profileNewPwConfirm').value = '';
    } catch (e) {
        err.textContent = '요청에 실패했습니다. 잠시 후 다시 시도해주세요.'; err.classList.remove('hidden');
    } finally {
        btn.disabled = false;
    }
}

function setupProfileUI() {
    const nameEl = document.getElementById('userName');
    if (!nameEl) return;
    // 우측 상단 이름 클릭 → 본인 확인 팝업 (로그인 사용자만)
    nameEl.addEventListener('click', () => { if (currentUser) openVerifyPwModal(); });
    document.getElementById('verifyPwConfirmBtn').addEventListener('click', doVerifyPassword);
    document.getElementById('verifyPwCancelBtn').addEventListener('click', closeVerifyPwModal);
    document.getElementById('verifyPwCloseBtn').addEventListener('click', closeVerifyPwModal);
    document.getElementById('verifyPwInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); doVerifyPassword(); }
    });
    document.getElementById('profileSaveBtn').addEventListener('click', saveProfile);
    document.getElementById('profileCancelBtn').addEventListener('click', closeProfileModal);
    document.getElementById('profileCloseBtn').addEventListener('click', closeProfileModal);
    [document.getElementById('verifyPwModalOverlay'), document.getElementById('profileModalOverlay')].forEach(ov => {
        ov.addEventListener('click', (e) => { if (e.target === ov) ov.classList.add('hidden'); });
    });
}

// ============ 공고/JD 관리 (공고 중심 전환) ============
// 조회는 ADMIN/MANAGER/VIEWER, 등록/수정은 ADMIN/MANAGER(백엔드에서 재검증). 현재 1공고=1 active JD.
let postingEditingId = null;          // null = 신규 등록, 값 = 수정 중인 posting id
let postingPage = 1, postingSize = 20;   // 공고/JD 관리 목록 페이징
let postingSelectedDept = null;       // {id, name, path}

// 오늘 날짜를 YYYY-MM-DD 로 (로컬 기준). 여러 화면의 [오늘] 버튼/날짜필터 공용.
function todayIso() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// 지정 input 들에서 Enter 키 입력 시 검색 함수를 실행합니다. (공고명 검색/날짜 input 공용)
function wireEnterSearch(ids, fn) {
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); fn(); }
        });
    });
}

// 페이징 컨트롤 공통 렌더러. prefix 로 {prefix}Total/{prefix}PageInfo/{prefix}PrevBtn/{prefix}NextBtn 를 갱신합니다.
// 반환: 현재 페이지가 총 페이지 수보다 크면 보정한 page(없으면 그대로).
function renderPager(prefix, page, size, total) {
    const totalPages = Math.max(1, Math.ceil((total || 0) / size));
    const totalEl = document.getElementById(prefix + 'Total');
    if (totalEl) totalEl.textContent = `총 ${total || 0}건`;
    const infoEl = document.getElementById(prefix + 'PageInfo');
    if (infoEl) infoEl.textContent = `${Math.min(page, totalPages)} / ${totalPages} 페이지`;
    const prev = document.getElementById(prefix + 'PrevBtn');
    const next = document.getElementById(prefix + 'NextBtn');
    if (prev) prev.disabled = page <= 1;
    if (next) next.disabled = page >= totalPages;
    return totalPages;
}

function postingCanManage() {
    return currentUser && (currentUser.role_code === 'ADMIN' || currentUser.role_code === 'MANAGER');
}
function postingStatusBadge(status) {
    const cls = { OPEN: 'badge-green', CLOSED: 'badge-gray', INACTIVE: 'badge-gray', DRAFT: 'badge-amber' }[status] || 'badge-gray';
    return `<span class="badge ${cls}">${escapeHtml(status || '-')}</span>`;
}
function postingJdBadge(hasJd) {
    return hasJd ? '<span class="badge badge-blue">JD 등록 완료</span>' : '<span class="badge badge-gray">JD 미등록</span>';
}
// 콤마/줄바꿈 구분 텍스트 → 문자열 배열 (JD 필수/우대 기술)
function parseSkillsInput(text) {
    return (text || '').split(/[,\n]/).map(s => s.trim()).filter(Boolean);
}

async function loadJobPostings() {
    const body = document.getElementById('postingTableBody');
    const errorEl = document.getElementById('postingError');
    errorEl.innerHTML = '';
    // VIEWER 면 [+ 공고 등록] 숨김
    const addBtn = document.getElementById('addPostingBtn');
    if (addBtn) addBtn.style.display = postingCanManage() ? '' : 'none';
    body.innerHTML = '<tr><td colspan="7" class="empty-cell">불러오는 중...</td></tr>';
    const params = new URLSearchParams();
    const kw = document.getElementById('postingKeyword').value.trim();
    const platform = document.getElementById('postingPlatformFilter').value;
    const status = document.getElementById('postingStatusFilter').value;
    const jd = document.getElementById('postingJdFilter').value;
    const dateFrom = document.getElementById('postingDateFrom').value;
    const dateTo = document.getElementById('postingDateTo').value;
    if (kw) params.set('keyword', kw);
    if (platform) params.set('platform_code', platform);
    if (status) params.set('status', status);
    if (jd) params.set('jd_status', jd);
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    params.set('page', String(postingPage));
    params.set('size', String(postingSize));
    const { _redirect, ok, data } = await adminFetchJson(`/api/job-postings?${params.toString()}`);
    if (_redirect) return;
    if (!ok) {
        body.innerHTML = '';
        errorEl.innerHTML = `<p class="text-danger">${escapeHtml((data && data.detail) || '공고 목록을 불러오지 못했습니다.')}</p>`;
        return;
    }
    renderPostingsTable(data.items || []);
    renderPager('posting', data.page || postingPage, data.size || postingSize, data.total || 0);
}

function renderPostingsTable(postings) {
    const body = document.getElementById('postingTableBody');
    if (!postings.length) {
        body.innerHTML = '<tr><td colspan="7" class="empty-cell">등록된 공고가 없습니다.</td></tr>';
        return;
    }
    const manageLabel = postingCanManage() ? '상세/수정' : '상세';
    body.innerHTML = postings.map(p => {
        const dept = p.department_name
            ? `${escapeHtml(p.department_name)} <span class="dept-code">(${escapeHtml(p.department_id)})</span>`
            : escapeHtml(p.department_id || '-');
        return `<tr class="clickable-row" data-id="${p.id}">
            <td class="cell-title" title="${escapeHtml(p.title)}">${escapeHtml(p.title)}</td>
            <td class="cell-title" title="${escapeHtml(p.department_name || p.department_id || '')}">${dept}</td>
            <td>${escapeHtml(p.platform_label || '-')}</td>
            <td>${postingStatusBadge(p.status)}</td>
            <td>${postingJdBadge(p.has_jd)}</td>
            <td>${escapeHtml(formatDateTime(p.created_at))}</td>
            <td><span class="row-action">${manageLabel}</span></td>
        </tr>`;
    }).join('');
    body.querySelectorAll('tr.clickable-row').forEach(row => {
        row.addEventListener('click', () => openEditPosting(row.dataset.id));
    });
}

// ----- 부서 검색 (권한 범위 API: /api/job-postings/dept-search — 사용자 관리 부서검색과 동일 응답) -----
function renderPostingSelectedDept() {
    const box = document.getElementById('postingSelectedDept');
    if (!postingSelectedDept) { box.classList.add('hidden'); box.innerHTML = ''; return; }
    box.classList.remove('hidden');
    box.innerHTML = `<strong>${escapeHtml(postingSelectedDept.name)}</strong> (${escapeHtml(postingSelectedDept.id)})
        <br><span class="hint">${escapeHtml(postingSelectedDept.path || '')}</span>
        <button type="button" id="postingDeptClearBtn" class="btn-small btn-secondary">선택 해제</button>`;
    const clearBtn = document.getElementById('postingDeptClearBtn');
    if (clearBtn) clearBtn.addEventListener('click', () => { postingSelectedDept = null; renderPostingSelectedDept(); });
}
async function searchPostingDept() {
    const kw = document.getElementById('postingDeptSearchInput').value.trim();
    const resultsEl = document.getElementById('postingDeptSearchResults');
    resultsEl.innerHTML = '<p class="hint">검색 중...</p>';
    const { _redirect, ok, data } = await adminFetchJson(
        `/api/job-postings/dept-search?keyword=${encodeURIComponent(kw)}`);
    if (_redirect) return;
    if (!ok) { resultsEl.innerHTML = `<p class="hint text-danger">${escapeHtml((data && data.detail) || '부서 검색 실패')}</p>`; return; }
    const list = (data || []).slice(0, 30);
    if (!list.length) { resultsEl.innerHTML = '<p class="hint">검색 결과가 없습니다.</p>'; return; }
    resultsEl.innerHTML = list.map(d => `
        <div class="dept-search-result" data-id="${escapeHtml(d.id)}" data-name="${escapeHtml(d.name)}" data-path="${escapeHtml(d.path || '')}">
            <div class="name">${escapeHtml(d.name)}${d.is_leaf ? '' : ' <span class="hint">(상위 조직)</span>'}</div>
            <div class="meta">${escapeHtml(d.id)} · ${escapeHtml(d.path || '')}</div>
        </div>`).join('');
    resultsEl.querySelectorAll('.dept-search-result').forEach(el => {
        el.addEventListener('click', () => {
            postingSelectedDept = { id: el.dataset.id, name: el.dataset.name, path: el.dataset.path };
            resultsEl.innerHTML = '';
            document.getElementById('postingDeptSearchInput').value = '';
            renderPostingSelectedDept();
        });
    });
}

// ----- 팝업 열기/닫기 -----
function openPostingModal() { document.getElementById('postingModalOverlay').classList.remove('hidden'); }
function closePostingModal() { document.getElementById('postingModalOverlay').classList.add('hidden'); }

function resetPostingForm() {
    document.getElementById('postingNotice').classList.add('hidden');
    document.getElementById('postingNotice').innerHTML = '';
    document.getElementById('postingError2').classList.add('hidden');
    document.getElementById('postingError2').textContent = '';
    document.getElementById('postingDeptSearchResults').innerHTML = '';
    document.getElementById('postingDeptSearchInput').value = '';
    const extractMsg = document.getElementById('postingExtractMsg');
    extractMsg.className = 'hint';
    extractMsg.textContent = '';
    postingSelectedDept = null;
    renderPostingSelectedDept();
    ['jdTitle', 'jdRequired', 'jdPreferred', 'jdContent'].forEach(id => { document.getElementById(id).value = ''; });
}

function setPostingFormReadonly(readonly) {
    ['postingTitle', 'postingUrl', 'jdTitle', 'jdRequired', 'jdPreferred', 'jdContent'].forEach(id => {
        document.getElementById(id).readOnly = readonly;
    });
    ['postingPlatform', 'postingStatus'].forEach(id => { document.getElementById(id).disabled = readonly; });
    document.getElementById('postingDeptSearchBtn').disabled = readonly;
    document.getElementById('postingSaveBtn').style.display = readonly ? 'none' : '';
    // 추천 JD / 공고 내용 가져오기: VIEWER(readonly) 는 숨김 (백엔드에서도 403 재검증)
    document.getElementById('postingJdRecommendBtn').style.display = readonly ? 'none' : '';
    document.getElementById('postingExtractBtn').style.display = readonly ? 'none' : '';
}

function openCreatePosting() {
    if (!postingCanManage()) { notifyNoAccess(); return; }
    postingEditingId = null;
    resetPostingForm();
    document.getElementById('postingModalTitle').textContent = '공고 등록';
    document.getElementById('postingTitle').value = '';
    document.getElementById('postingPlatform').value = '';
    document.getElementById('postingUrl').value = '';
    document.getElementById('postingStatus').value = 'OPEN';
    document.getElementById('postingSaveBtn').textContent = '공고 등록';
    // JD 카드는 처음부터 표시(통합 입력). 신규는 JD 미등록 badge.
    document.getElementById('postingJdStatusBadge').innerHTML = postingJdBadge(false);
    setPostingFormReadonly(false);
    openPostingModal();
}

async function openEditPosting(postingId) {
    postingEditingId = postingId;
    resetPostingForm();
    document.getElementById('postingModalTitle').textContent = postingCanManage() ? '공고 상세/수정' : '공고 상세';
    const { _redirect, ok, data } = await adminFetchJson(`/api/job-postings/${postingId}`);
    if (_redirect) return;
    if (!ok) { alert((data && data.detail) || '공고 조회 실패'); return; }
    document.getElementById('postingTitle').value = data.title || '';
    document.getElementById('postingPlatform').value = data.platform_code || '';
    document.getElementById('postingUrl').value = data.platform_posting_url || '';
    document.getElementById('postingStatus').value = data.status || 'OPEN';
    if (data.department_id) {
        postingSelectedDept = { id: data.department_id, name: data.department_name || data.department_id, path: data.department_path || '' };
    }
    renderPostingSelectedDept();
    document.getElementById('postingSaveBtn').textContent = '공고 수정';
    // JD 카드 표시(항상) + 현재 JD 로드
    document.getElementById('postingJdStatusBadge').innerHTML = postingJdBadge(data.has_jd);
    await loadPostingJd(postingId);
    setPostingFormReadonly(!postingCanManage());
    openPostingModal();
}

function showPostingNotice(html) {
    const el = document.getElementById('postingNotice');
    el.innerHTML = html; el.classList.remove('hidden');
}
function showPostingError(msg) {
    const el = document.getElementById('postingError2');
    el.textContent = msg; el.classList.remove('hidden');
}

// ----- 공고 + JD 통합 저장 (단일 버튼: 신규=공고 등록 / 수정=공고 수정) -----
async function savePosting() {
    if (!postingCanManage()) { notifyNoAccess(); return; }
    document.getElementById('postingError2').classList.add('hidden');
    const title = document.getElementById('postingTitle').value.trim();
    if (!title) { showPostingError('공고명을 입력해주세요.'); return; }
    const deptId = postingSelectedDept ? postingSelectedDept.id : '';   // 부서/팀은 선택사항
    const payload = {
        title,
        department_id: deptId,   // 빈 값이면 백엔드에서 부서 미지정 처리
        platform_code: document.getElementById('postingPlatform').value || null,
        platform_posting_url: document.getElementById('postingUrl').value.trim() || null,
        status: document.getElementById('postingStatus').value,
    };
    const btn = document.getElementById('postingSaveBtn');
    btn.disabled = true;
    btn.textContent = '저장 중...';
    try {
        const isCreate = (postingEditingId === null);
        const url = isCreate ? '/api/job-postings' : `/api/job-postings/${postingEditingId}`;
        // 1) 공고 기본 정보 저장
        const res = await adminFetchJson(url, {
            method: isCreate ? 'POST' : 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (res._redirect) return;
        if (!res.ok) { showPostingError((res.data && res.data.detail) || '공고 저장 실패'); return; }
        const postingId = isCreate ? res.data.id : postingEditingId;
        if (isCreate) {
            // 등록 직후 수정 모드로 전환 (이후 클릭은 '공고 수정')
            postingEditingId = postingId;
            document.getElementById('postingModalTitle').textContent = '공고 상세/수정';
        }
        // 2) JD 저장 (JD 입력 내용이 있을 때만 — 기존 upsert 로직/Drive 폴더 생성 재사용)
        const jd = await _savePostingJdIfPresent(postingId);
        document.getElementById('postingJdStatusBadge').innerHTML = postingJdBadge(jd.attempted && jd.ok);
        loadJobPostings();   // 목록 갱신(JD 등록 완료/수정 내용 반영)
        if (jd.attempted && !jd.ok) {
            // 공고는 저장됐지만 JD 저장 실패 → 팝업 유지하고 오류 안내
            showPostingError('공고는 저장되었으나 JD 저장에 실패했습니다: ' + (jd.error || ''));
        } else {
            // 전체 성공 → 안내 후 팝업 닫기
            showPostingNotice(isCreate ? '공고가 등록되었습니다.' : '공고가 수정되었습니다.');
            closePostingModal();
        }
    } finally {
        btn.disabled = false;
        // 신규 저장 후에는 수정 모드이므로 버튼명을 모드에 맞춤
        btn.textContent = (postingEditingId === null) ? '공고 등록' : '공고 수정';
    }
}

// JD 입력 내용이 있으면 upsert. 반환 {attempted, ok, error}. (내용 없으면 attempted=false → 공고만 저장)
async function _savePostingJdIfPresent(postingId) {
    const jdTitle = document.getElementById('jdTitle').value.trim();
    const req = document.getElementById('jdRequired').value;
    const pref = document.getElementById('jdPreferred').value;
    const content = document.getElementById('jdContent').value.trim();
    if (!jdTitle && !req.trim() && !pref.trim() && !content) {
        return { attempted: false, ok: true };
    }
    const payload = {
        title: jdTitle || null,
        required_skills: parseSkillsInput(req),     // 줄바꿈/콤마 → 배열 (기존 로직, JSONB 저장)
        preferred_skills: parseSkillsInput(pref),
        jd_content: content || null,
    };
    const { _redirect, ok, data } = await adminFetchJson(`/api/job-postings/${postingId}/jd`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (_redirect) return { attempted: true, ok: false, error: '세션이 만료되었습니다.' };
    if (!ok) return { attempted: true, ok: false, error: (data && (data.detail || data.error_message)) || 'JD 저장 실패' };
    return { attempted: true, ok: true };
}

// ----- JD 로드 (수정 모드 진입 시 현재 active JD 를 입력란에 채움) -----
async function loadPostingJd(postingId) {
    const { _redirect, ok, data } = await adminFetchJson(`/api/job-postings/${postingId}/jd`);
    if (_redirect || !ok) return;
    const jd = data && data.jd;
    document.getElementById('jdTitle').value = jd ? (jd.title || '') : '';
    document.getElementById('jdRequired').value = jd ? (jd.required_skills || []).join('\n') : '';
    document.getElementById('jdPreferred').value = jd ? (jd.preferred_skills || []).join('\n') : '';
    document.getElementById('jdContent').value = jd ? (jd.jd_content || '') : '';
    document.getElementById('postingJdStatusBadge').innerHTML = postingJdBadge(!!jd);
}

// 추천 JD: 공고명/부서명 기반 LLM JD 초안을 받아 JD 입력란을 채웁니다. (DB 저장은 [JD 저장] 시)
async function recommendPostingJd() {
    if (!postingCanManage() || postingEditingId === null) { notifyNoAccess(); return; }
    const titleEl = document.getElementById('jdTitle');
    const reqEl = document.getElementById('jdRequired');
    const prefEl = document.getElementById('jdPreferred');
    const contentEl = document.getElementById('jdContent');
    // 기존 입력값이 있으면 덮어쓰기 확인
    if (reqEl.value.trim() || prefEl.value.trim() || contentEl.value.trim()) {
        if (!confirm('현재 입력된 JD 내용이 있습니다. 추천 JD로 덮어쓰시겠습니까?')) return;
    }
    const btn = document.getElementById('postingJdRecommendBtn');
    btn.disabled = true;
    const orig = btn.textContent;
    btn.textContent = '추천 중...';
    try {
        const { _redirect, ok, data } = await adminFetchJson(
            `/api/job-postings/${postingEditingId}/jd/recommend`, { method: 'POST' });
        if (_redirect) return;
        if (!ok || (data && data.status === 'ERROR')) {
            showPostingError((data && (data.detail || data.error_message)) || '추천 JD 생성에 실패했습니다.');
            return;
        }
        const d = (data && data.data) || {};
        titleEl.value = d.title || titleEl.value;
        reqEl.value = (d.required_skills || []).join('\n');
        prefEl.value = (d.preferred_skills || []).join('\n');
        contentEl.value = d.jd_content || '';
        showPostingNotice('추천 JD를 입력란에 채웠습니다. 확인 후 [JD 저장]을 눌러주세요.');
    } finally {
        btn.disabled = false;
        btn.textContent = orig;
    }
}

// ----- 공고 URL 기반 자동 채우기 (대상 회사 공고만) -----
// 덮어쓰기/자동 채우기 대상(부서/팀·상태는 제외). 값 존재 여부 검사 + 교체에 사용.
const EXTRACT_TARGET_IDS = ['postingTitle', 'postingPlatform', 'jdContent', 'jdRequired', 'jdPreferred'];

// 자동 추출 결과로 대상 필드를 '교체'합니다. (비어 있는 추출값은 기존 값 유지, 부서/팀·상태는 절대 변경 안 함)
function applyExtractResult(d) {
    const set = (id, v) => { if (v && String(v).trim()) document.getElementById(id).value = v; };
    set('postingTitle', d.job_title);     // 공고명/JD명
    set('jdContent', d.main_tasks);        // 주요 업무
    set('jdRequired', d.qualifications);   // 자격 요건
    set('jdPreferred', d.preferred);       // 우대 사항
    // 플랫폼: URL 도메인 기준 코드(d.platform)가 select option 에 존재할 때만 선택
    const platSel = document.getElementById('postingPlatform');
    if (platSel && d.platform && [...platSel.options].some(o => o.value === d.platform)) {
        platSel.value = d.platform;
    }
    // 부서/팀(postingSelectedDept)·상태(postingStatus)는 자동 입력/변경하지 않습니다.
}

async function extractFromUrl() {
    if (!postingCanManage()) { notifyNoAccess(); return; }
    const url = document.getElementById('postingUrl').value.trim();
    const msg = document.getElementById('postingExtractMsg');
    msg.className = 'hint';
    if (!url) { msg.textContent = '공고 URL을 입력해주세요.'; return; }

    // 덮어쓰기 확인(API 호출 전): 대상 필드 중 하나라도 값이 있으면 confirm
    const hasValue = EXTRACT_TARGET_IDS.some(id => (document.getElementById(id).value || '').trim());
    if (hasValue && !confirm('이미 입력된 공고/JD 내용이 있습니다. 가져온 공고 내용으로 덮어쓸까요?')) {
        return;   // 취소 → 화면 값 유지
    }

    const btn = document.getElementById('postingExtractBtn');
    btn.disabled = true;
    const orig = btn.textContent;
    btn.textContent = '가져오는 중...';
    msg.textContent = '공고 내용을 가져오는 중입니다...';
    try {
        const { _redirect, ok, data } = await adminFetchJson('/api/jobs/extract-from-url', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
        });
        if (_redirect) return;
        if (!ok || (data && data.status === 'ERROR')) {
            msg.className = 'hint text-danger';
            msg.textContent = (data && (data.error_message || data.detail))
                || '공고 내용을 가져오지 못했습니다. URL을 확인하거나 직접 입력해주세요.';
            return;
        }
        if (!data.company_verified) {
            // 대상 회사 공고가 아니면 어떤 필드도 덮어쓰지 않음
            msg.className = 'hint text-danger';
            msg.textContent = data.warning
                || '대상 회사 공고로 확인되지 않아 자동 입력을 중단했습니다. 공고 URL을 다시 확인해주세요.';
            return;
        }
        applyExtractResult(data);
        // 추출한 JD 영역으로 스크롤 (URL 입력은 상단이라 하단 JD 가 화면 밖일 수 있음)
        const jdSec = document.getElementById('postingJdSection');
        if (jdSec) jdSec.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        if (data.warning) {
            // 일부 항목(주요 업무/자격 요건/우대 사항)을 추출하지 못함 → 성공이 아닌 '경고'로 안내
            msg.className = 'hint text-warning';
            msg.textContent = data.warning + ' 직접 입력 후 저장해주세요.';
        } else {
            msg.className = 'hint';
            msg.textContent = '공고 내용을 가져왔습니다. 자격 요건/우대 사항/주요 업무까지 채워졌는지 확인 후 저장해주세요.';
        }
    } catch (e) {
        msg.className = 'hint text-danger';
        msg.textContent = '공고 내용을 가져오지 못했습니다. URL을 확인하거나 직접 입력해주세요.';
    } finally {
        btn.disabled = false;
        btn.textContent = orig;
    }
}

function setupJobPostingsUI() {
    const addBtn = document.getElementById('addPostingBtn');
    if (!addBtn) return;   // 화면 없으면 방어
    addBtn.addEventListener('click', openCreatePosting);
    const search = () => { postingPage = 1; loadJobPostings(); };
    document.getElementById('postingSearchBtn').addEventListener('click', search);
    wireEnterSearch(['postingKeyword', 'postingDateFrom', 'postingDateTo'], search);
    document.getElementById('postingTodayBtn').addEventListener('click', () => {
        const iso = todayIso();
        document.getElementById('postingDateFrom').value = iso;
        document.getElementById('postingDateTo').value = iso;
        search();
    });
    document.getElementById('postingResetBtn').addEventListener('click', () => {
        document.getElementById('postingKeyword').value = '';
        document.getElementById('postingPlatformFilter').value = '';
        document.getElementById('postingStatusFilter').value = '';
        document.getElementById('postingJdFilter').value = '';
        document.getElementById('postingDateFrom').value = '';
        document.getElementById('postingDateTo').value = '';
        postingSize = 20;
        document.getElementById('postingSizeSelect').value = '20';
        search();
    });
    document.getElementById('postingSizeSelect').addEventListener('change', (e) => {
        postingSize = parseInt(e.target.value, 10) || 20;
        postingPage = 1;
        loadJobPostings();
    });
    document.getElementById('postingPrevBtn').addEventListener('click', () => {
        if (postingPage > 1) { postingPage--; loadJobPostings(); }
    });
    document.getElementById('postingNextBtn').addEventListener('click', () => {
        postingPage++; loadJobPostings();
    });
    document.getElementById('postingDeptSearchBtn').addEventListener('click', searchPostingDept);
    document.getElementById('postingDeptSearchInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); searchPostingDept(); }
    });
    document.getElementById('postingSaveBtn').addEventListener('click', savePosting);
    document.getElementById('postingJdRecommendBtn').addEventListener('click', recommendPostingJd);
    document.getElementById('postingExtractBtn').addEventListener('click', extractFromUrl);
    document.getElementById('postingModalCancelBtn').addEventListener('click', closePostingModal);
    document.getElementById('postingModalCloseBtn').addEventListener('click', closePostingModal);
    document.getElementById('postingModalOverlay').addEventListener('click', (e) => {
        if (e.target.id === 'postingModalOverlay') closePostingModal();
    });
}
