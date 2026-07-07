// 로그인 화면 동작: /api/auth/login 호출 → 성공 시 / 로 이동, 실패 시 에러 메시지 표시.
document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('loginBtn');
    const idEl = document.getElementById('loginId');
    const pwEl = document.getElementById('loginPassword');
    const errorEl = document.getElementById('loginError');

    function showError(msg) {
        errorEl.textContent = msg;
        errorEl.classList.remove('hidden');
    }

    async function login() {
        errorEl.classList.add('hidden');
        const loginId = idEl.value.trim();
        const password = pwEl.value;
        if (!loginId || !password) {
            showError('아이디와 비밀번호를 입력해주세요.');
            return;
        }

        // 요청 중 버튼 중복 클릭 방지
        btn.disabled = true;
        btn.textContent = '로그인 중...';
        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ login_id: loginId, password }),
            });
            if (res.ok) {
                window.location.href = '/';
                return;
            }
            if (res.status === 403) {
                showError('비활성화된 계정입니다. 관리자에게 문의해주세요.');
            } else {
                showError('아이디 또는 비밀번호가 올바르지 않습니다.');
            }
        } catch (e) {
            showError('로그인 요청에 실패했습니다. 잠시 후 다시 시도해주세요.');
        } finally {
            btn.disabled = false;
            btn.textContent = '로그인';
        }
    }

    btn.addEventListener('click', login);
    // Enter 키로 로그인
    [idEl, pwEl].forEach(el => el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); login(); }
    }));
});
