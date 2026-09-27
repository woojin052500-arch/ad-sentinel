FRAME_ELEMENT_JS = r"""
(el) => {
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1) {
        if (cur.id && cur.ownerDocument.querySelectorAll('#' + CSS.escape(cur.id)).length === 1) {
            parts.unshift('#' + CSS.escape(cur.id));
            break;
        }
        let part = cur.tagName.toLowerCase();
        const parent = cur.parentElement;
        if (!parent) { parts.unshift(part); break; }
        let index = 1, count = 0;
        for (const c of parent.children) {
            if (c.tagName === cur.tagName) {
                count++;
                if (c === cur) index = count;
            }
        }
        if (count > 1) part += ':nth-of-type(' + index + ')';
        parts.unshift(part);
        cur = parent;
    }
    return { selector: parts.join(' > '), src: el.src || el.getAttribute('src') || '' };
}
"""

EXTRACT_JS = r"""
(opts) => {
    const MAX_RECORDS = opts.maxRecords;
    const MAX_SCAN = opts.maxScan;
    const MAX_TEXT = opts.maxTextLen;
    const TIME_BUDGET = opts.timeBudgetMs;
    const FOOTER = opts.footerSelector || 'footer';
    const inFooter = el => { try { return !!el.closest(FOOTER); } catch (e) { return false; } };
    const t0 = performance.now();

    const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'META', 'LINK',
                               'BR', 'HR', 'OPTION', 'WBR']);

    const records = [];
    let truncated = false;
    let timedOut = false;
    let scanned = 0;
    const PRIORITY = new Set(['hidden', 'iframe', 'redirect', 'meta', 'noscript']);
    let priorityCount = 0, normalCount = 0;

    const ITEM_SEL = 'article, li, [class*=post i], [class*=item i], [class*=card i], [class*=article i], ' +
                     '[class*=entry i], [class*=comment i]';
    const TITLE_SEL = 'h1, h2, h3, h4, h5, [class*=title i], [class*=subject i]';
    const titleCache = new Map();
    function contextTitle(el) {
        let item = el.closest(ITEM_SEL);
        for (let depth = 0; item && depth < 4; depth++) {
            if (!titleCache.has(item)) {
                const h = item.querySelector(TITLE_SEL);
                titleCache.set(item, h ? (h.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80) : '');
            }
            const t = titleCache.get(item);
            if (t) return t;
            item = item.parentElement ? item.parentElement.closest(ITEM_SEL) : null;
        }
        return '';
    }

    const SEARCH_HEAD = /인기\s*검색어|최근\s*검색어|실시간\s*검색어|검색어\s*순위|추천\s*검색어|급상승\s*검색어|많이\s*찾(?:는|은)\s*검색어|인기\s*키워드|popular\s*(?:search|keyword)|trending\s*search|hot\s*keyword|top\s*searches/i;
    const SEARCH_ATTR = /(?:popular|hot|rank|recent|best|trend)[-_]?(?:keyword|search|word|query)|(?:keyword|search|query)[-_]?(?:rank|popular|hot|recent|best|trend|list)/i;
    const searchRoots = [];
    function listRoot(el) {
        let cur = el;
        for (let depth = 0; cur && depth < 4; depth++) {
            if (cur.querySelectorAll('li, a').length >= 2) return cur;
            cur = cur.parentElement;
        }
        return null;
    }
    function addSearchRoot(root, label) {
        if (root && root !== document.body && root !== document.documentElement &&
                !searchRoots.some(([r]) => r === root || r.contains(root))) {
            searchRoots.push([root, label]);
        }
    }
    try {
        for (const el of document.querySelectorAll('[class], [id]')) {
            if (searchRoots.length >= 10) break;
            const attrs = (el.getAttribute('class') || '') + ' ' + (el.id || '');
            if (SEARCH_ATTR.test(attrs) && el.querySelectorAll('li, a').length >= 2) {
                const head = (el.textContent || '').match(SEARCH_HEAD);
                addSearchRoot(el, head ? head[0].replace(/\s+/g, ' ') : '검색어 목록');
            }
        }
        const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
        let node, seen = 0;
        while ((node = walker.nextNode()) && seen++ < 20000 && searchRoots.length < 10) {
            const t = node.nodeValue;
            if (t.length > 40) continue;
            const m = t.match(SEARCH_HEAD);
            if (m && node.parentElement) addSearchRoot(listRoot(node.parentElement), m[0].replace(/\s+/g, ' '));
        }
    } catch (e) {}
    function searchWidgetOf(el) {
        for (const [root, label] of searchRoots) {
            if (root.contains(el)) return label;
        }
        return '';
    }

    function pushEl(el, rec) {
        try { rec.context_title = contextTitle(el); } catch (e) { rec.context_title = ''; }
        if (searchRoots.length) {
            const label = searchWidgetOf(el);
            if (label) rec.search_widget = label;
        }
        push(rec);
    }

    function push(rec) {
        if (PRIORITY.has(rec.type)) {
            if (priorityCount >= MAX_RECORDS) { truncated = true; return; }
            priorityCount++;
        } else {
            if (normalCount >= MAX_RECORDS) { truncated = true; return; }
            normalCount++;
        }
        records.push(rec);
    }

    function clip(s) {
        s = (s || '').replace(/\s+/g, ' ').trim();
        return s.length > MAX_TEXT ? s.slice(0, MAX_TEXT) + '…' : s;
    }

    const idCount = new Map();
    for (const e of document.querySelectorAll('[id]')) idCount.set(e.id, (idCount.get(e.id) || 0) + 1);

    const selectorCache = new Map();
    function cssSelector(el) {
        if (!el || el.nodeType !== 1) return '';
        const cached = selectorCache.get(el);
        if (cached !== undefined) return cached;
        let sel;
        if (el.id && idCount.get(el.id) === 1) {
            sel = '#' + CSS.escape(el.id);
        } else {
            let part = el.tagName.toLowerCase();
            const parent = el.parentElement;
            if (!parent) {
                sel = part;
            } else {
                let index = 1, count = 0;
                for (const c of parent.children) {
                    if (c.tagName === el.tagName) {
                        count++;
                        if (c === el) index = count;
                    }
                }
                if (count > 1) part += ':nth-of-type(' + index + ')';
                sel = cssSelector(parent) + ' > ' + part;
            }
        }
        selectorCache.set(el, sel);
        return sel;
    }

    const scrollX = window.scrollX, scrollY = window.scrollY;
    const docW = Math.max(document.documentElement.scrollWidth, window.innerWidth);

    function rectOf(r) {
        return { x: Math.round(r.left + scrollX), y: Math.round(r.top + scrollY),
                 w: Math.round(r.width), h: Math.round(r.height) };
    }

    function ownText(el) {
        let s = '';
        for (let n = el.firstChild; n; n = n.nextSibling) if (n.nodeType === 3) s += n.nodeValue;
        return s.replace(/\s+/g, ' ').trim();
    }

    const colorCache = new Map();
    function parseColor(c) {
        if (colorCache.has(c)) return colorCache.get(c);
        const m = (c || '').match(/rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+%?))?/);
        let v = null;
        if (m) {
            let a = m[4] === undefined ? 1 : parseFloat(m[4]);
            if (m[4] && m[4].endsWith('%')) a = a / 100;
            v = [parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3]), a];
        }
        colorCache.set(c, v);
        return v;
    }

    const styleCache = new Map();
    function styleOf(el) {
        let st = styleCache.get(el);
        if (!st) { st = getComputedStyle(el); styleCache.set(el, st); }
        return st;
    }

    const WHITE = [255, 255, 255, 1];
    const bgCache = new Map();
    function effectiveBackground(el) {
        if (!el || el.nodeType !== 1) return WHITE;
        if (bgCache.has(el)) return bgCache.get(el);
        const st = styleOf(el);
        let bg;
        if (st.backgroundImage && st.backgroundImage !== 'none') {
            bg = null;
        } else {
            const c = parseColor(st.backgroundColor);
            bg = c && c[3] > 0.1 ? c : effectiveBackground(el.parentElement);
        }
        bgCache.set(el, bg);
        return bg;
    }

    function hiddenReasons(el, st, r, hasOwnText) {
        const reasons = [];
        const none = st.display === 'none';
        if (none) reasons.push('display:none');
        if (st.visibility === 'hidden' || st.visibility === 'collapse') reasons.push('visibility:hidden');
        if (parseFloat(st.opacity) <= 0.05) reasons.push('opacity:0');
        if (st.clip === 'rect(0px, 0px, 0px, 0px)' || /inset\(\s*(50|100)%/.test(st.clipPath))
            reasons.push('clip');
        if (none) return reasons;

        const left = r.left + scrollX, top = r.top + scrollY;
        if ((r.width > 0 || r.height > 0) && (left + r.width <= 0 || top + r.height <= 0 || left >= docW + 100))
            reasons.push('off-screen');
        if ((r.width <= 1 || r.height <= 1) && /hidden|clip/.test(st.overflow))
            reasons.push('zero-size');
        if (parseFloat(st.textIndent) <= -999) reasons.push('text-indent');

        if (hasOwnText) {
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
        const out = [];
        for (const a of el.querySelectorAll('a[href], area[href]')) {
            out.push(a.href);
            if (out.length >= 20) break;
        }
        return out;
    }

    const body = document.body;
    if (!body) {
        return { title: document.title || '', text: '', records: [], truncated: false,
                 timed_out: false, scanned: 0, total_elements: 0, elapsed_ms: 0 };
    }

    for (const m of document.querySelectorAll('meta[http-equiv]')) {
        if ((m.getAttribute('http-equiv') || '').toLowerCase() === 'refresh') {
            push({ type: 'redirect', selector: cssSelector(m), content: clip(m.getAttribute('content')) });
        }
    }

    const META_FIELDS = new Set(['description', 'keywords', 'og:title', 'og:description', 'og:site_name',
                                 'twitter:title', 'twitter:description', 'subject', 'abstract']);
    for (const m of document.querySelectorAll('meta[name], meta[property]')) {
        const field = (m.getAttribute('property') || m.getAttribute('name') || '').toLowerCase();
        const content = clip(m.getAttribute('content'));
        if (META_FIELDS.has(field) && content.length >= 2) {
            push({ type: 'meta', field, selector: 'meta[' + (m.hasAttribute('property') ? 'property' : 'name') +
                   '="' + field + '"]', content });
        }
    }

    for (const ns of document.querySelectorAll('noscript')) {
        try {
            const doc = new DOMParser().parseFromString(ns.textContent || '', 'text/html');
            const content = clip(doc.body ? Array.from(doc.body.childNodes, n => n.textContent).join(' ') : '');
            const links = [];
            for (const a of doc.querySelectorAll('a[href]')) {
                const u = resolveUrl(a.getAttribute('href'));
                if (u) links.push(u);
                if (links.length >= 20) break;
            }
            if (content.length >= 2 || links.length) {
                push({ type: 'noscript', selector: cssSelector(ns), content, links });
            }
        } catch (e) {}
    }

    const hiddenOf = new Map();
    function isHidden(el) {
        if (!el || el === body) return false;
        const v = hiddenOf.get(el);
        if (v !== undefined) return v;
        const h = isHidden(el.parentElement);
        hiddenOf.set(el, h);
        return h;
    }

    const NAV_ATTRS = ['data-href', 'data-url', 'data-link', 'data-route', 'data-path', 'routerlink',
                       'ng-reflect-router-link'];
    const NAV_CALL = /(?:location(?:\.href)?\s*=\s*|location\.(?:assign|replace)\(\s*|window\.open\(\s*|\b(?:navigate|push|goto|go[A-Z_]\w*|go|move\w*|fn\w*|link\w*)\(\s*|path\s*:\s*)['"`]([^'"`\s]+)['"`]/g;

    function looksLikeUrl(t) {
        return /^(https?:\/\/|\/|\.\.?\/)/i.test(t) || /\.(html?|do|jsp|php|aspx?)(\?|#|$)/i.test(t) || /^[\w-]+\?[\w-]+=/.test(t);
    }

    function navTarget(el, tag) {
        for (const name of NAV_ATTRS) {
            const v = el.getAttribute(name);
            if (v && looksLikeUrl(v.trim())) return { url: v.trim(), source: name };
        }
        const code = el.getAttribute('onclick');
        if (code) {
            NAV_CALL.lastIndex = 0;
            let m;
            while ((m = NAV_CALL.exec(code)) !== null) {
                if (looksLikeUrl(m[1])) return { url: m[1], source: 'onclick' };
            }
        }
        return null;
    }

    function resolveUrl(u) {
        try { return new URL(u, document.baseURI).href; } catch (e) { return ''; }
    }

    function navRecord(el, nav, hidden, r) {
        return { type: 'link', source: nav.source, selector: cssSelector(el), href: resolveUrl(nav.url),
                 raw_href: nav.url, content: clip(el.textContent || el.getAttribute('aria-label') || el.title || ''),
                 target: '', hidden, footer: inFooter(el), rect: r ? rectOf(r) : null };
    }

    const all = body.getElementsByTagName('*');
    const total = all.length;

    for (let i = 0; i < total; i++) {
        if (i >= MAX_SCAN) { truncated = true; break; }
        if ((i & 127) === 0 && performance.now() - t0 > TIME_BUDGET) { timedOut = true; break; }
        const el = all[i];
        scanned++;

        const tag = el.tagName.toUpperCase();
        if (SKIP_TAGS.has(tag)) continue;
        if (el instanceof SVGElement && tag !== 'SVG') { hiddenOf.set(el, isHidden(el.parentElement)); continue; }

        const parentHidden = isHidden(el.parentElement);
        const text = parentHidden ? '' : ownText(el);
        const isLink = tag === 'A' || tag === 'AREA' ? el.hasAttribute('href') : false;
        const isFrame = tag === 'IFRAME' || tag === 'FRAME';
        const href = isLink ? (el.getAttribute('href') || '').trim() : '';
        const nav = (!isLink || href === '' || href.startsWith('#') || /^javascript:/i.test(href))
            ? navTarget(el, tag) : null;

        if (parentHidden) {
            hiddenOf.set(el, true);
            if (nav) pushEl(el, navRecord(el, nav, true, null));
            if (isLink) {
                pushEl(el, { type: 'link', selector: cssSelector(el), href: el.href,
                       raw_href: el.getAttribute('href'), content: clip(el.textContent || el.title || ''),
                       target: el.getAttribute('target') || '', hidden: true, footer: inFooter(el), rect: null });
            }
            if (isFrame) {
                pushEl(el, { type: 'iframe', selector: cssSelector(el), src: el.src || '',
                       raw_src: el.getAttribute('src') || '', content: clip(el.title || el.name || ''),
                       hidden: true, hidden_reasons: ['inside-hidden-element'], rect: null });
            }
            continue;
        }

        const needsStyle = text.length > 0 || el.firstElementChild || isLink || isFrame || nav || tag === 'IMG';
        if (!needsStyle) { hiddenOf.set(el, false); continue; }

        const st = styleOf(el);
        const r = el.getBoundingClientRect();
        const reasons = hiddenReasons(el, st, r, text.length > 0);
        const selfHidden = reasons.length > 0;
        hiddenOf.set(el, selfHidden);

        if (selfHidden) {
            const content = clip(el.textContent);
            const links = linksInside(el);
            if (isLink) links.unshift(el.href);
            if (content || links.length || el.querySelector('iframe, img')) {
                pushEl(el, { type: 'hidden', tag: tag.toLowerCase(), selector: cssSelector(el),
                       content, hidden_reasons: reasons, links, rect: rectOf(r) });
            }
        }

        if (isLink) {
            let label = el.textContent || el.title || '';
            if (!label.trim()) {
                const img = el.querySelector('img');
                label = img ? img.alt : '';
            }
            pushEl(el, { type: 'link', selector: cssSelector(el), href: el.href,
                   raw_href: el.getAttribute('href'), content: clip(label),
                   target: el.getAttribute('target') || '', hidden: selfHidden, footer: inFooter(el),
                   rect: rectOf(r) });
        }

        if (nav) pushEl(el, navRecord(el, nav, selfHidden, r));

        if (isFrame) {
            const fr = selfHidden ? reasons.slice() : [];
            if (st.display !== 'none' && (r.width <= 2 || r.height <= 2)) fr.push('tiny-size');
            pushEl(el, { type: 'iframe', selector: cssSelector(el), src: el.src || '',
                   raw_src: el.getAttribute('src') || '', content: clip(el.title || el.name || ''),
                   hidden: fr.length > 0, hidden_reasons: fr, rect: rectOf(r) });
        }

        if (tag === 'IMG' && !el.closest('a[href]')) {
            const alt = clip(el.getAttribute('alt') || el.getAttribute('title') || '');
            if (alt.length >= 2 && selfHidden) {
                pushEl(el, { type: 'hidden', tag: 'img', selector: cssSelector(el), content: alt,
                       hidden_reasons: reasons, links: [], rect: rectOf(r) });
            } else if (alt.length >= 2) {
                pushEl(el, { type: 'alt', selector: cssSelector(el), content: alt, src: el.currentSrc || el.src || '',
                       rect: rectOf(r) });
            }
        }

        if (!selfHidden && text.length >= 2) {
            let content = clip(text);
            if (el.childElementCount > 0 && el.childElementCount <= 10) {
                const full = el.textContent;
                if (full.length <= MAX_TEXT * 2) content = clip(el.innerText || full);
            }
            pushEl(el, { type: 'text', tag: tag.toLowerCase(), selector: cssSelector(el),
                   content, rect: rectOf(r) });
        }
    }

    let pageText = '';
    if (performance.now() - t0 <= TIME_BUDGET) {
        pageText = (body.innerText || '');
    } else {
        pageText = (body.textContent || '');
    }

    return {
        title: document.title || '',
        text: pageText.replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim().slice(0, 50000),
        records,
        truncated,
        timed_out: timedOut,
        scanned,
        total_elements: total,
        elapsed_ms: Math.round(performance.now() - t0),
    };
}
"""
