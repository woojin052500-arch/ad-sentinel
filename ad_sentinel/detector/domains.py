import re
from pathlib import Path

from ad_sentinel.detector.keywords import ADULT, GAMBLING
from ad_sentinel.paths import data_dir

DEFAULT_WHITELIST = (
    "go.kr", "gov.kr", "mil.kr", "korea.kr", "korea.net",
    "youtube.com", "youtu.be", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "blog.naver.com", "post.naver.com", "tv.naver.com", "pf.kakao.com",
)

WHITELIST_FILE = "whitelist.txt"

SUSPICIOUS_SUBSTRINGS = {
    "casino": GAMBLING, "baccarat": GAMBLING, "holdem": GAMBLING, "powerball": GAMBLING,
    "gamble": GAMBLING, "porn": ADULT,
}
SUSPICIOUS_TOKENS = {
    "toto": GAMBLING, "bet": GAMBLING, "betting": GAMBLING, "slot": GAMBLING, "slots": GAMBLING,
    "poker": GAMBLING, "sportsbet": GAMBLING,
    "xxx": ADULT, "sex": ADULT, "sexy": ADULT, "adult": ADULT, "av": ADULT, "jav": ADULT,
}


def load_whitelist(extra: list[str] | None = None, path: Path | None = None) -> set[str]:
    domains = set(DEFAULT_WHITELIST)
    domains.update(d.strip().lower() for d in (extra or []) if d.strip())
    path = path or data_dir() / WHITELIST_FILE
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip().lower()
            if line and not line.startswith("#"):
                domains.add(line)
    return domains


def is_whitelisted(host: str, whitelist: set[str]) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in whitelist)


def suspicious_domain(host: str) -> str | None:
    host = (host or "").lower()
    if not host:
        return None
    for word, category in SUSPICIOUS_SUBSTRINGS.items():
        if word in host:
            return category
    for token in re.split(r"[.\-_]", host):
        token = re.sub(r"\d+", "", token)
        if token in SUSPICIOUS_TOKENS:
            return SUSPICIOUS_TOKENS[token]
    return None


def user_whitelist_path() -> Path:
    return data_dir() / WHITELIST_FILE


def read_user_whitelist() -> list[str]:
    path = user_whitelist_path()
    if not path.is_file():
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.strip().startswith("#")]


def save_user_whitelist(domains: list[str]) -> Path:
    path = user_whitelist_path()
    cleaned = []
    for d in domains:
        d = d.strip().lower().removeprefix("http://").removeprefix("https://").removeprefix("*.").strip("/")
        if d and not d.startswith("#") and d not in cleaned:
            cleaned.append(d)
    path.write_text("\n".join(cleaned) + ("\n" if cleaned else ""), encoding="utf-8")
    return path
