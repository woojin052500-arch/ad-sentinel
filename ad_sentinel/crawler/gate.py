import re

GATE_WORDS = [
    "입장", "입장하기", "사이트입장", "홈페이지입장", "지금입장", "들어가기", "시작", "시작하기",
    "확인", "계속", "계속하기", "바로가기", "바로입장",
    "enter", "entersite", "entry", "start", "continue", "go", "ok",
]

GATE_PARTS = ["입장", "들어가기", "시작하기", "시작", "계속하기", "둘러보기",
              "enter", "start", "continue", "getstarted"]

EXIT_PATTERN = (r"홈으로|홈페이지로|홈화면|메인으로|메인화면|메인페이지|돌아가|뒤로|이전|처음으로|첫화면|"
                r"home|back|return|previous|prev")

STRONG_GATE_WORDS = [
    "입장", "입장하기", "사이트입장", "홈페이지입장", "지금입장", "바로입장", "들어가기", "enter", "entersite", "entry",
]

FOOTER_SELECTOR = ("footer, [role=contentinfo], [id*=footer i], [class*=footer i], [id*=foot i], "
                   "[class*=copyright i]")

DANGER_WORDS = [
    "로그인", "login", "log in", "signin", "sign in", "회원가입", "가입", "signup", "sign up", "register", "join",
    "결제", "구매", "주문", "pay", "checkout", "order", "buy", "삭제", "delete", "remove", "신고", "report",
    "탈퇴", "로그아웃", "logout", "비밀번호", "password", "다운로드", "download", "설치", "install",
    "구독", "subscribe", "후원", "donate", "전송", "submit", "send",
    "동의", "agree", "accept", "허용", "allow", "consent", "수락", "쿠키", "cookie", "디스코드", "discord",
]

MAX_GATE_CANDIDATES = 3

DANGER_CHECK_JS = r"""
    const DANGER = opts.dangerWords.map(w => w.toLowerCase()).map(w =>
        /^[a-z ]+$/.test(w) ? new RegExp('(^|[^a-z])' + w + '([^a-z]|$)') : w);

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

    function visibleArea(el) {
        const st = getComputedStyle(el);
        if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) < 0.1) return 0;
        const r = el.getBoundingClientRect();
        return r.width > 4 && r.height > 4 ? r.width * r.height : 0;
    }
"""

FIND_GATE_JS = r"""
(opts) => {
""" + DANGER_CHECK_JS + r"""
    const GATE = new Set(opts.gateWords);
    const STRONG = new Set(opts.strongWords);
    const EXIT = new RegExp(opts.exitPattern, 'i');
    const prefer = (opts.prefer || '').toLowerCase();
    const norm = s => (s || '').toLowerCase().replace(/[\s >»→▶▷►·.!,:~\-_\[\]()<«←◀◁]+/g, '');
    const hasPart = key => opts.gateParts.some(w => /^[a-z]+$/.test(w)
        ? new RegExp('(^|[^a-z])' + w + '([^a-z]|$)').test(key) : key.includes(w));

    const candidates = document.querySelectorAll(
        'a, button, input[type=button], input[type=submit], input[type=image], [role=button], [onclick], area');
    const found = [];
    for (const el of candidates) {
        if (el.closest(opts.footerSelector)) continue;
        const href = (el.getAttribute('href') || '').trim();
        if (href.startsWith('#') && !el.getAttribute('onclick')) continue;
        const label = labelOf(el);
        if (!label || label.length > 30) continue;
        const key = norm(label);
        let score = 0;
        if (prefer) score = key === prefer ? 3 : 0;
        else if (GATE.has(key)) score = 2;
        else if (hasPart(key)) score = 1;
        if (!score || isDanger(el, label) || EXIT.test(key)) continue;
        const area = visibleArea(el);
        if (!area) continue;
        const strong = STRONG.has(key) || key.includes('입장') || key.includes('들어가기');
        const rank = area * (strong ? 2 : 1) * (score >= 2 ? 1.2 : 1);
        const weak = score === 2 && !strong && !hasPart(key);
        found.push({ el, label, key, score, strong, weak, area, rank, href });
    }
    for (const old of document.querySelectorAll('[data-ad-sentinel-gate]')) old.removeAttribute('data-ad-sentinel-gate');
    found.sort((a, b) => b.rank - a.rank);
    return found.slice(0, opts.maxCandidates).map((c, i) => {
        c.el.setAttribute('data-ad-sentinel-gate', String(i + 1));
        if (c.el.getAttribute('target')) c.el.removeAttribute('target');
        const rect = c.el.getBoundingClientRect();
        return { index: i + 1, text: c.label, key: c.key, tag: c.el.tagName.toLowerCase(), href: c.href,
                 strong: c.strong, weak: c.weak, viewport_ratio: c.area / Math.max(1, window.innerWidth * window.innerHeight),
                 first_screen: rect.top + window.scrollY < window.innerHeight };
    });
}
"""

FIND_MORE_JS = r"""
(opts) => {
""" + DANGER_CHECK_JS + r"""
    const MORE = /^\+?\s*(클릭\s*(하여|해서)\s*)?(글\s*|게시글\s*|게시물\s*)?(더\s*보기|더\s*불러오기|더\s*읽기)(\s*[+▼⌄∨v>]*)?\s*(\(\d+\))?$|^(load|show|view|see)\s+more(\s+posts?)?$|^more$/i;
    const norm = s => s.replace(/\s+/g, '');
    for (const old of document.querySelectorAll('[data-ad-sentinel-more]')) old.removeAttribute('data-ad-sentinel-more');

    function nearMedia(el) {
        let cur = el;
        for (let i = 0; i < 3 && cur; i++, cur = cur.parentElement) {
            if (cur.querySelector && cur.querySelector('img, video, canvas, picture')) return true;
            if (/blur/.test(getComputedStyle(cur).filter)) return true;
        }
        return false;
    }

    const matches = [];
    for (const el of document.querySelectorAll('a, button, [role=button], [onclick], div, span, li, p')) {
        const label = labelOf(el);
        if (!label || label.length > 20 || !MORE.test(label)) continue;
        if (el.querySelector('a, button, [role=button], [onclick]') && !el.matches('a, button, [role=button], [onclick]'))
            continue;
        matches.push({ el, label });
    }
    const outer = matches.filter(m => !matches.some(o => o.el !== m.el && o.el.contains(m.el)));
    matches.length = 0;
    matches.push(...outer);
    const counts = {};
    for (const m of matches) counts[norm(m.label)] = (counts[norm(m.label)] || 0) + 1;

    let best = null, reveal = 0;
    for (const m of matches) {
        const el = m.el;
        if (isDanger(el, m.label)) continue;
        const href = (el.getAttribute('href') || '').trim();
        if (href && !href.startsWith('#') && !/^javascript:/i.test(href)) continue;
        const pos = getComputedStyle(el).position;
        if (counts[norm(m.label)] >= 2 || ((pos === 'absolute' || pos === 'fixed') && nearMedia(el))) {
            reveal++;
            continue;
        }
        if (!visibleArea(el)) continue;
        const y = el.getBoundingClientRect().top + window.scrollY;
        if (!best || y > best.y) best = { el, label: m.label, y };
    }
    if (!best) return { found: false, reveal };
    best.el.setAttribute('data-ad-sentinel-more', '1');
    return { found: true, text: best.label, reveal };
}
"""

PAGE_METRICS_JS = r"""
() => {
    const text = document.body ? (document.body.innerText || '').replace(/\s+/g, '') : '';
    let hash = 0;
    for (let i = 0; i < text.length; i++) hash = (hash * 31 + text.charCodeAt(i)) | 0;
    let busy = false;
    if (text.length < 400) {
        for (const el of document.querySelectorAll('progress, [role=progressbar], [aria-busy=true], ' +
                '[class*=loading i], [class*=loader i], [class*=spinner i], [class*=progress i], [class*=bar i], ' +
                '[id*=loading i], [id*=loader i], [id*=progress i]')) {
            const st = getComputedStyle(el);
            const r = el.getBoundingClientRect();
            if (st.display !== 'none' && st.visibility !== 'hidden' && r.width > 0 && r.height > 0) { busy = true; break; }
        }
    }
    const loading = text.length < 400 &&
        (busy || /로딩|로드중|다운로드중|불러오는중|준비중|잠시만|loading|pleasewait/i.test(text));
    return {
        loading,
        text: text.length,
        hash,
        nodes: document.body ? document.body.getElementsByTagName('*').length : 0,
        height: document.documentElement.scrollHeight,
        url: location.href,
    };
}
"""

JS_CLICK = r"""
(selector) => {
    const el = document.querySelector(selector);
    if (!el) return false;
    el.click();
    return true;
}
"""

BOT_BLOCK_HINT = re.compile(
    r"브라우저\s*보안|VPN\s*(사용\s*)?(제한|차단|금지)|봇\s*(차단|탐지|감지|방지)|자동화\s*(프로그램|도구|브라우저)|"
    r"(비정상|자동)\s*(적인\s*)?(접근|접속|트래픽)|캡[차챠]|로봇이\s*아닙니다|사람인지\s*확인|"
    r"captcha|checking\s+your\s+browser|verify\s+(that\s+)?you\s+are\s+(a\s+)?human|are\s+you\s+a\s+robot|"
    r"bot\s+(detection|protection)|unusual\s+traffic",
    re.IGNORECASE,
)

SCREEN_TEXT_JS = r"""
() => (document.body ? document.body.innerText || '' : '').slice(0, 3000)
"""

BOILERPLATE_LINK = re.compile(
    r"개인\s*정보|처리\s*방침|이용\s*약관|약관|서비스\s*(안내|소개)|이용\s*안내|저작권|이메일\s*(무단)?\s*수집|"
    r"청소년\s*보호|사이트\s*맵|오시는\s*길|찾아\s*오시는|제휴|광고\s*문의|고객\s*센터|회사\s*소개|통계|책임\s*한계|"
    r"privacy|terms|policy|copyright|sitemap|contact|about\s*us|disclaimer",
    re.IGNORECASE,
)


def is_boilerplate_link(record: dict) -> bool:
    if record.get("footer") or (record.get("raw_href") or "").strip().startswith("#"):
        return True
    return bool(BOILERPLATE_LINK.search(record.get("content") or ""))


def content_grew(before: dict, after: dict) -> bool:
    if after.get("hash") == before.get("hash"):
        return False
    return (after["text"] - before["text"] >= 30 or after["nodes"] - before["nodes"] >= 5
            or after.get("height", 0) - before.get("height", 0) >= 100)


def content_changed(before: dict, after: dict) -> bool:
    if after["url"].split("#")[0] != before["url"].split("#")[0] and after["text"] > 0:
        return True
    if after.get("hash") == before.get("hash"):
        return False
    text_diff = abs(after["text"] - before["text"])
    node_diff = abs(after["nodes"] - before["nodes"])
    return ((text_diff >= 10 and text_diff >= before["text"] * 0.3)
            or (node_diff >= 3 and node_diff >= before["nodes"] * 0.3)
            or text_diff >= 1000 or node_diff >= 100)
