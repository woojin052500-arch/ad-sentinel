GATE_WORDS = [
    "입장", "입장하기", "사이트입장", "홈페이지입장", "지금입장", "들어가기", "시작", "시작하기",
    "확인", "계속", "계속하기", "메인으로", "메인바로가기", "홈으로", "홈페이지바로가기", "바로가기", "바로입장",
    "enter", "entersite", "entry", "start", "continue", "go", "gotomain", "ok",
]

DANGER_WORDS = [
    "로그인", "login", "log in", "signin", "sign in", "회원가입", "가입", "signup", "sign up", "register", "join",
    "결제", "구매", "주문", "pay", "checkout", "order", "buy", "삭제", "delete", "remove", "신고", "report",
    "탈퇴", "로그아웃", "logout", "비밀번호", "password", "다운로드", "download", "설치", "install",
    "구독", "subscribe", "후원", "donate", "전송", "submit", "send",
]

FIND_GATE_JS = r"""
(opts) => {
    const GATE = new Set(opts.gateWords);
    const DANGER = opts.dangerWords.map(w => w.toLowerCase()).map(w =>
        /^[a-z ]+$/.test(w) ? new RegExp('(^|[^a-z])' + w + '([^a-z]|$)') : w);
    const prefer = (opts.prefer || '').toLowerCase();
    const norm = s => (s || '').toLowerCase().replace(/[\s >»→▶▷►·.!,:~\-_\[\]()<«←◀◁]+/g, '');

    function labelOf(el) {
        let t = el.innerText || el.value || el.getAttribute('aria-label') || el.title || '';
        if (!t.trim()) {
            const img = el.querySelector && el.querySelector('img');
            t = img ? (img.alt || '') : '';
        }
        return t.trim();
    }

    function isDanger(el, label) {
        const hay = [label, el.getAttribute('href') || '', el.getAttribute('onclick') || '',
                     el.id || '', typeof el.className === 'string' ? el.className : '',
                     el.getAttribute('name') || '', el.getAttribute('formaction') || ''].join(' ').toLowerCase();
        if (DANGER.some(w => typeof w === 'string' ? hay.includes(w) : w.test(hay))) return true;
        const form = el.closest('form');
        if (form && (form.querySelector('input[type=password]') || (form.method || '').toLowerCase() === 'post'))
            return true;
        const href = el.getAttribute('href') || '';
        if (/^(mailto|tel|sms):/i.test(href)) return true;
        if (/^https?:/i.test(href)) {
            try { if (new URL(href).host !== location.host) return true; } catch (e) { return true; }
        }
        return false;
    }

    function visible(el) {
        const st = getComputedStyle(el);
        if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) < 0.1) return 0;
        const r = el.getBoundingClientRect();
        return r.width > 4 && r.height > 4 ? r.width * r.height : 0;
    }

    const candidates = document.querySelectorAll(
        'a, button, input[type=button], input[type=submit], input[type=image], [role=button], [onclick], area');
    let best = null;
    for (const el of candidates) {
        const label = labelOf(el);
        if (!label || label.length > 30) continue;
        const key = norm(label);
        let score = 0;
        if (prefer) score = key === prefer ? 3 : 0;
        else if (GATE.has(key)) score = 2;
        else if (key.includes('입장') || key.startsWith('enter')) score = 1;
        if (!score || isDanger(el, label)) continue;
        const area = visible(el);
        if (!area) continue;
        if (!best || score > best.score || (score === best.score && area > best.area))
            best = { el, score, area, label, key };
    }
    for (const old of document.querySelectorAll('[data-ad-sentinel-gate]')) old.removeAttribute('data-ad-sentinel-gate');
    if (!best) return null;
    best.el.setAttribute('data-ad-sentinel-gate', '1');
    if (best.el.getAttribute('target')) best.el.removeAttribute('target');
    return { text: best.label, key: best.key, tag: best.el.tagName.toLowerCase(),
             href: best.el.getAttribute('href') || '' };
}
"""
