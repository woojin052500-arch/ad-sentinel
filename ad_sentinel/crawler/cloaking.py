import re
from typing import Callable

from playwright.sync_api import Browser, Error as PlaywrightError

from ad_sentinel.crawler.url_utils import normalize_url

GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
MOBILE_UA = ("Mozilla/5.0 (Linux; Android 14; SM-S921N) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/126.0.0.0 Mobile Safari/537.36")
GOOGLE_REFERER = "https://www.google.com/"
MAX_TEXT = 20000
MAX_LINKS = 300
SETTLE_MS = 1500

PROFILES = [
    {"key": "pc", "label": "일반 PC", "only_in": "", "ua": None, "referer": None, "mobile": False},
    {"key": "googlebot", "label": "구글봇", "only_in": "구글봇으로 볼 때만 나타남", "ua": GOOGLEBOT_UA,
     "referer": None, "mobile": False},
    {"key": "google_referer", "label": "구글 검색 경유", "only_in": "구글 검색 결과를 눌러 들어올 때만 나타남",
     "ua": None, "referer": GOOGLE_REFERER, "mobile": False},
    {"key": "mobile", "label": "모바일", "only_in": "모바일로 접속할 때만 나타남", "ua": MOBILE_UA, "referer": None,
     "mobile": True},
]

SNAPSHOT_JS = r"""
(maxText) => {
    const links = [];
    for (const a of document.querySelectorAll('a[href], area[href]')) {
        if (/^https?:/i.test(a.href)) links.push(a.href);
        if (links.length >= 300) break;
    }
    const refresh = [];
    for (const m of document.querySelectorAll('meta[http-equiv]')) {
        if ((m.getAttribute('http-equiv') || '').toLowerCase() === 'refresh') refresh.push(m.getAttribute('content') || '');
    }
    const body = document.body;
    const text = body ? (body.innerText || body.textContent || '') : '';
    const hidden = [];
    for (const el of document.querySelectorAll('body *')) {
        if (hidden.length >= 50) break;
        const st = getComputedStyle(el);
        if ((st.display === 'none' || st.visibility === 'hidden') && (el.textContent || '').trim().length >= 2 &&
                !['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(el.tagName)) {
            hidden.push((el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 300));
        }
    }
    return { title: document.title || '', text: text.replace(/[ \t]+/g, ' ').slice(0, maxText), links, refresh,
             hidden, url: location.href };
}
"""

SCRIPT_REDIRECT = re.compile(
    r"(?:location(?:\.href)?\s*=|location\.(?:replace|assign)\(|window\.open\()\s*['\"](https?://[^'\"\s]+)",
    re.IGNORECASE)
REFRESH_URL = re.compile(r"url\s*=\s*['\"]?([^'\"\s;]+)", re.IGNORECASE)


def _context_options(profile: dict, default_ua: str) -> dict:
    options = {"user_agent": profile["ua"] or default_ua, "locale": "ko-KR", "ignore_https_errors": True,
               "bypass_csp": True}
    if profile["mobile"]:
        options.update(viewport={"width": 412, "height": 915}, is_mobile=True, has_touch=True, device_scale_factor=2)
    else:
        options["viewport"] = {"width": 1366, "height": 900}
    return options


def snapshot(browser: Browser, url: str, profile: dict, default_ua: str, timeout_ms: int,
             evaluate: Callable) -> dict:
    result = {"key": profile["key"], "label": profile["label"], "only_in": profile["only_in"], "status": None,
              "final_url": "", "title": "", "text": "", "links": [], "redirects": [], "hidden": [], "error": None}
    context = None
    try:
        context = browser.new_context(**_context_options(profile, default_ua))
        page = context.new_page()
        response = page.goto(url, referer=profile["referer"], wait_until="domcontentloaded", timeout=timeout_ms)
        result["status"] = response.status if response else None
        try:
            html = page.content()
        except PlaywrightError:
            html = ""
        page.wait_for_timeout(SETTLE_MS)
        data = evaluate(page.main_frame, SNAPSHOT_JS, MAX_TEXT, min(5000, timeout_ms))
        result.update(title=data["title"], text=data["text"], links=data["links"][:MAX_LINKS], hidden=data["hidden"],
                      final_url=normalize_url(page.url) or page.url)
        redirects = [m.group(1) for m in SCRIPT_REDIRECT.finditer(html)]
        for content in data["refresh"]:
            m = REFRESH_URL.search(content)
            if m:
                redirects.append(m.group(1))
        result["redirects"] = list(dict.fromkeys(r for r in redirects if r.startswith("http")))
    except PlaywrightError as e:
        result["error"] = str(e).strip().splitlines()[0] if str(e).strip() else "열기 실패"
    finally:
        if context:
            try:
                context.close()
            except PlaywrightError:
                pass
    return result


def check(browser: Browser, url: str, default_ua: str, timeout_ms: int, evaluate: Callable,
          stop: Callable[[], bool] = lambda: False) -> dict:
    snapshots = []
    for profile in PROFILES:
        if stop():
            break
        snapshots.append(snapshot(browser, url, profile, default_ua, timeout_ms, evaluate))
    return {"url": url, "profiles": snapshots}
