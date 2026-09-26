"""브라우저 안에서 실행되는 요소 추출 스크립트.

JS 코드를 별도 .js 파일로 두지 않고 파이썬 문자열로 둔 이유:
PyInstaller로 패키징할 때 데이터 파일을 따로 포함시키는 설정이 필요 없어서 단순하다.

추출하는 레코드 종류(type)
- text     : 화면에 보이는 텍스트 덩어리
- link     : <a href>, <area href> 링크 (숨김 영역 안에 있으면 hidden=true)
- iframe   : <iframe>/<frame> 의 src (1px 이하 크기 등 숨김 여부 포함)
- hidden   : 숨김 처리된 요소 (숨김 이유 hidden_reasons 포함)
- redirect : <meta http-equiv="refresh"> 자동 이동
"""

# CSS 선택자(selector)를 만드는 함수. 요소의 위치를 사람이 개발자도구에서 바로 찾을 수 있게 한다.
# 예: "#content > div:nth-of-type(2) > p"
CSS_SELECTOR_FN = r"""
function cssSelector(el) {
    if (!el || el.nodeType !== 1) return '';
    const doc = el.ownerDocument;
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1) {
        // 문서 안에서 유일한 id가 있으면 거기서 멈춘다 (가장 짧고 안정적인 경로)
        if (cur.id && doc.querySelectorAll('#' + CSS.escape(cur.id)).length === 1) {
            parts.unshift('#' + CSS.escape(cur.id));
            break;
        }
        let part = cur.tagName.toLowerCase();
        const parent = cur.parentElement;
        if (!parent) { parts.unshift(part); break; }
        // 같은 태그 형제가 여러 개면 몇 번째인지 표시
        const same = Array.from(parent.children).filter(c => c.tagName === cur.tagName);
        if (same.length > 1) part += ':nth-of-type(' + (same.indexOf(cur) + 1) + ')';
        parts.unshift(part);
        cur = parent;
    }
    return parts.join(' > ');
}
"""

# iframe 요소 하나의 선택자만 구할 때 쓰는 스크립트 (frame_path 계산용)
SELECTOR_JS = "(el) => {" + CSS_SELECTOR_FN + " return cssSelector(el); }"

# 프레임(메인 문서 또는 iframe 내부 문서) 하나에서 모든 레코드를 뽑는 스크립트
EXTRACT_JS = "(opts) => {" + CSS_SELECTOR_FN + r"""
    const MAX_ELEMENTS = opts.maxElements;
    const MAX_TEXT = opts.maxTextLen;
    // 내용이 아닌 태그는 건너뛴다
    const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'META', 'LINK',
                               'BR', 'HR', 'OPTION', 'PATH', 'DEFS', 'SYMBOL', 'USE']);

    const records = [];
    let truncated = false;

    function push(rec) {
        if (records.length >= MAX_ELEMENTS) { truncated = true; return; }
        records.push(rec);
    }

    // 공백 정리 + 길이 제한
    function clip(s) {
        s = (s || '').replace(/\s+/g, ' ').trim();
        return s.length > MAX_TEXT ? s.slice(0, MAX_TEXT) + '…' : s;
    }

    // 문서 기준 좌표 (스크롤 위치와 무관하게 비교 가능)
    function rectOf(el) {
        const r = el.getBoundingClientRect();
        return { x: Math.round(r.left + window.scrollX), y: Math.round(r.top + window.scrollY),
                 w: Math.round(r.width), h: Math.round(r.height) };
    }

    // 요소가 직접 가진 텍스트 (자식 요소의 텍스트는 제외)
    function ownText(el) {
        let s = '';
        for (const n of el.childNodes) if (n.nodeType === 3) s += n.nodeValue;
        return s.replace(/\s+/g, ' ').trim();
    }

    // "rgb(1, 2, 3)" / "rgba(1, 2, 3, 0.5)" → [r, g, b, a]
    function parseColor(c) {
        const m = (c || '').match(/rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+%?))?/);
        if (!m) return null;
        let a = m[4] === undefined ? 1 : parseFloat(m[4]);
        if (m[4] && m[4].endsWith('%')) a = a / 100;
        return [parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3]), a];
    }

    // 실제로 글자 뒤에 깔린 배경색: 투명하면 부모로 올라가며 찾는다. 배경 이미지가 있으면 판단 불가(null)
    function effectiveBackground(el) {
        for (let cur = el; cur && cur.nodeType === 1; cur = cur.parentElement) {
            const st = getComputedStyle(cur);
            if (st.backgroundImage && st.backgroundImage !== 'none') return null;
            const c = parseColor(st.backgroundColor);
            if (c && c[3] > 0.1) return c;
        }
        return [255, 255, 255, 1];  // 아무 배경도 없으면 브라우저 기본값(흰색)
    }

    // 요소가 숨김 처리되었는지 검사하고, 숨김 이유 목록을 돌려준다
    function hiddenReasons(el, st, hasOwnText) {
        const reasons = [];
        if (st.display === 'none') reasons.push('display:none');
        if (st.visibility === 'hidden' || st.visibility === 'collapse') reasons.push('visibility:hidden');
        if (parseFloat(st.opacity) <= 0.05) reasons.push('opacity:0');

        if (st.clip === 'rect(0px, 0px, 0px, 0px)' || /inset\(\s*(50|100)%/.test(st.clipPath))
            reasons.push('clip');

        // display:none 인 요소는 크기·위치가 0이라 아래 검사는 의미가 없다
        if (st.display !== 'none') {
            const r = el.getBoundingClientRect();
            const left = r.left + window.scrollX, top = r.top + window.scrollY;
            const docW = Math.max(document.documentElement.scrollWidth, window.innerWidth);
            if (r.width > 0 || r.height > 0) {
                if (left + r.width <= 0 || top + r.height <= 0 || left >= docW + 100)
                    reasons.push('off-screen');
            }
            if ((r.width <= 1 || r.height <= 1) && /hidden|clip/.test(st.overflow))
                reasons.push('zero-size');
            if (parseFloat(st.textIndent) <= -999) reasons.push('text-indent');
        }

        // 아래는 글자에 대한 검사라서 글자를 직접 가진 요소만 본다
        if (hasOwnText && st.display !== 'none') {
            if (parseFloat(st.fontSize) < 2) reasons.push('tiny-font');
            const fg = parseColor(st.color);
            if (fg && fg[3] <= 0.05) {
                reasons.push('transparent-text');
            } else if (fg) {
                const bg = effectiveBackground(el);
                if (bg) {
                    const dist = Math.sqrt((fg[0]-bg[0])**2 + (fg[1]-bg[1])**2 + (fg[2]-bg[2])**2);
                    if (dist < 20) reasons.push('same-color-as-background');
                }
            }
        }
        return reasons;
    }

    // 숨김 요소 안에 든 링크 주소 모으기 (숨겨진 광고 링크 확인용)
    function linksInside(el) {
        return Array.from(el.querySelectorAll('a[href], area[href]')).slice(0, 20).map(a => a.href);
    }

    const body = document.body;
    if (!body) return { title: document.title || '', text: '', records: [], truncated: false };

    const hiddenSet = new Set();   // 숨김으로 판정된 요소들
    function insideHidden(el) {
        for (let p = el; p; p = p.parentElement) if (hiddenSet.has(p)) return true;
        return false;
    }

    // 1) 자동 이동(meta refresh) - 게시판 해킹 시 도박 사이트로 넘기는 수법에 쓰임
    for (const m of document.querySelectorAll('meta[http-equiv]')) {
        if ((m.getAttribute('http-equiv') || '').toLowerCase() === 'refresh') {
            push({ type: 'redirect', selector: cssSelector(m), content: clip(m.getAttribute('content')) });
        }
    }

    // 2) 모든 요소를 문서 순서대로 훑는다 (부모가 자식보다 먼저 나온다)
    for (const el of body.querySelectorAll('*')) {
        if (SKIP_TAGS.has(el.tagName.toUpperCase())) continue;
        if (el.closest('svg') && el.tagName.toLowerCase() !== 'svg') continue;

        const st = getComputedStyle(el);
        const text = ownText(el);
        const parentHidden = insideHidden(el.parentElement);

        // 2-1) 숨김 요소: 가장 바깥쪽 숨김 요소만 기록 (안쪽 요소는 중복이므로 생략)
        if (!parentHidden) {
            const reasons = hiddenReasons(el, st, text.length > 0);
            if (reasons.length > 0) {
                hiddenSet.add(el);
                const content = clip(el.textContent);
                const links = linksInside(el);
                if (el.matches('a[href], area[href]')) links.unshift(el.href);
                // 내용도 링크도 없는 빈 숨김 요소(레이아웃용)는 기록하지 않는다
                if (content || links.length || el.querySelector('iframe, img')) {
                    push({ type: 'hidden', tag: el.tagName.toLowerCase(), selector: cssSelector(el),
                           content, hidden_reasons: reasons, links, rect: rectOf(el) });
                }
            }
        }
        const hidden = parentHidden || hiddenSet.has(el);

        // 2-2) 링크
        if (el.matches('a[href], area[href]')) {
            const label = clip(el.innerText || el.textContent || el.title ||
                               (el.querySelector('img') && el.querySelector('img').alt) || '');
            push({ type: 'link', selector: cssSelector(el), href: el.href,
                   raw_href: el.getAttribute('href'), content: label,
                   target: el.getAttribute('target') || '', hidden, rect: rectOf(el) });
        }

        // 2-3) iframe / frame
        if (el.tagName === 'IFRAME' || el.tagName === 'FRAME') {
            const r = el.getBoundingClientRect();
            const reasons = hidden ? ['inside-hidden-element'] : [];
            if (st.display !== 'none' && (r.width <= 2 || r.height <= 2)) reasons.push('tiny-size');
            push({ type: 'iframe', selector: cssSelector(el), src: el.src || '',
                   raw_src: el.getAttribute('src') || '',
                   content: clip(el.title || el.name || ''),
                   hidden: hidden || reasons.length > 0, hidden_reasons: reasons, rect: rectOf(el) });
        }

        // 2-4) 화면에 보이는 텍스트 (숨김 텍스트는 2-1에서 이미 기록)
        if (!hidden && text.length >= 2) {
            // 문장이 <b>, <span> 등으로 쪼개져도 문맥이 유지되도록 요소 전체 텍스트를 쓴다.
            // 단, body처럼 너무 큰 요소는 자기 텍스트만 쓴다.
            const full = (el.innerText || '').replace(/\s+/g, ' ').trim();
            const content = full.length > 0 && full.length <= MAX_TEXT * 2 ? clip(full) : clip(text);
            push({ type: 'text', tag: el.tagName.toLowerCase(), selector: cssSelector(el),
                   content, rect: rectOf(el) });
        }
    }

    return {
        title: document.title || '',
        text: (body.innerText || '').replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim().slice(0, 50000),
        records,
        truncated,
    };
}
"""
