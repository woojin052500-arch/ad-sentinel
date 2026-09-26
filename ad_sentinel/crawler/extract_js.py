CSS_SELECTOR_FN = r"""
function cssSelector(el) {
    if (!el || el.nodeType !== 1) return '';
    const doc = el.ownerDocument;
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1) {
        if (cur.id && doc.querySelectorAll('#' + CSS.escape(cur.id)).length === 1) {
            parts.unshift('#' + CSS.escape(cur.id));
            break;
        }
        let part = cur.tagName.toLowerCase();
        const parent = cur.parentElement;
        if (!parent) { parts.unshift(part); break; }
        const same = Array.from(parent.children).filter(c => c.tagName === cur.tagName);
        if (same.length > 1) part += ':nth-of-type(' + (same.indexOf(cur) + 1) + ')';
        parts.unshift(part);
        cur = parent;
    }
    return parts.join(' > ');
}
"""

SELECTOR_JS = "(el) => {" + CSS_SELECTOR_FN + " return cssSelector(el); }"

EXTRACT_JS = "(opts) => {" + CSS_SELECTOR_FN + r"""
    const MAX_ELEMENTS = opts.maxElements;
    const MAX_TEXT = opts.maxTextLen;
    const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'META', 'LINK',
                               'BR', 'HR', 'OPTION', 'PATH', 'DEFS', 'SYMBOL', 'USE']);

    const records = [];
    let truncated = false;

    function push(rec) {
        if (records.length >= MAX_ELEMENTS) { truncated = true; return; }
        records.push(rec);
    }

    function clip(s) {
        s = (s || '').replace(/\s+/g, ' ').trim();
        return s.length > MAX_TEXT ? s.slice(0, MAX_TEXT) + '…' : s;
    }

    function rectOf(el) {
        const r = el.getBoundingClientRect();
        return { x: Math.round(r.left + window.scrollX), y: Math.round(r.top + window.scrollY),
                 w: Math.round(r.width), h: Math.round(r.height) };
    }

    function ownText(el) {
        let s = '';
        for (const n of el.childNodes) if (n.nodeType === 3) s += n.nodeValue;
        return s.replace(/\s+/g, ' ').trim();
    }

    function parseColor(c) {
        const m = (c || '').match(/rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+%?))?/);
        if (!m) return null;
        let a = m[4] === undefined ? 1 : parseFloat(m[4]);
        if (m[4] && m[4].endsWith('%')) a = a / 100;
        return [parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3]), a];
    }

    function effectiveBackground(el) {
        for (let cur = el; cur && cur.nodeType === 1; cur = cur.parentElement) {
            const st = getComputedStyle(cur);
            if (st.backgroundImage && st.backgroundImage !== 'none') return null;
            const c = parseColor(st.backgroundColor);
            if (c && c[3] > 0.1) return c;
        }
        return [255, 255, 255, 1];
    }

    function hiddenReasons(el, st, hasOwnText) {
        const reasons = [];
        if (st.display === 'none') reasons.push('display:none');
        if (st.visibility === 'hidden' || st.visibility === 'collapse') reasons.push('visibility:hidden');
        if (parseFloat(st.opacity) <= 0.05) reasons.push('opacity:0');

        if (st.clip === 'rect(0px, 0px, 0px, 0px)' || /inset\(\s*(50|100)%/.test(st.clipPath))
            reasons.push('clip');

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

    function linksInside(el) {
        return Array.from(el.querySelectorAll('a[href], area[href]')).slice(0, 20).map(a => a.href);
    }

    const body = document.body;
    if (!body) return { title: document.title || '', text: '', records: [], truncated: false };

    const hiddenSet = new Set();
    function insideHidden(el) {
        for (let p = el; p; p = p.parentElement) if (hiddenSet.has(p)) return true;
        return false;
    }

    for (const m of document.querySelectorAll('meta[http-equiv]')) {
        if ((m.getAttribute('http-equiv') || '').toLowerCase() === 'refresh') {
            push({ type: 'redirect', selector: cssSelector(m), content: clip(m.getAttribute('content')) });
        }
    }

    for (const el of body.querySelectorAll('*')) {
        if (SKIP_TAGS.has(el.tagName.toUpperCase())) continue;
        if (el.closest('svg') && el.tagName.toLowerCase() !== 'svg') continue;

        const st = getComputedStyle(el);
        const text = ownText(el);
        const parentHidden = insideHidden(el.parentElement);

        if (!parentHidden) {
            const reasons = hiddenReasons(el, st, text.length > 0);
            if (reasons.length > 0) {
                hiddenSet.add(el);
                const content = clip(el.textContent);
                const links = linksInside(el);
                if (el.matches('a[href], area[href]')) links.unshift(el.href);
                if (content || links.length || el.querySelector('iframe, img')) {
                    push({ type: 'hidden', tag: el.tagName.toLowerCase(), selector: cssSelector(el),
                           content, hidden_reasons: reasons, links, rect: rectOf(el) });
                }
            }
        }
        const hidden = parentHidden || hiddenSet.has(el);

        if (el.matches('a[href], area[href]')) {
            const label = clip(el.innerText || el.textContent || el.title ||
                               (el.querySelector('img') && el.querySelector('img').alt) || '');
            push({ type: 'link', selector: cssSelector(el), href: el.href,
                   raw_href: el.getAttribute('href'), content: label,
                   target: el.getAttribute('target') || '', hidden, rect: rectOf(el) });
        }

        if (el.tagName === 'IFRAME' || el.tagName === 'FRAME') {
            const r = el.getBoundingClientRect();
            const reasons = hidden ? ['inside-hidden-element'] : [];
            if (st.display !== 'none' && (r.width <= 2 || r.height <= 2)) reasons.push('tiny-size');
            push({ type: 'iframe', selector: cssSelector(el), src: el.src || '',
                   raw_src: el.getAttribute('src') || '',
                   content: clip(el.title || el.name || ''),
                   hidden: hidden || reasons.length > 0, hidden_reasons: reasons, rect: rectOf(el) });
        }

        if (!hidden && text.length >= 2) {
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
