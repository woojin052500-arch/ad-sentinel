import logging
import urllib.request
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

log = logging.getLogger(__name__)

USER_AGENT = "AD-Sentinel"


class RobotsChecker:
    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout
        self._cache: dict[str, RobotFileParser | None] = {}

    def _load(self, origin: str) -> RobotFileParser | None:
        robots_url = origin + "/robots.txt"
        try:
            req = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            log.debug("robots.txt 읽기 실패 (%s): %s", robots_url, e)
            return None
        parser = RobotFileParser()
        parser.parse(body.splitlines())
        return parser

    def preload(self, origin: str, robots_txt: str) -> None:
        if origin in self._cache:
            return
        if not robots_txt.strip():
            self._cache[origin] = None
            return
        parser = RobotFileParser()
        parser.parse(robots_txt.splitlines())
        self._cache[origin] = parser

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._cache:
            self._cache[origin] = self._load(origin)
        parser = self._cache[origin]
        return parser is None or parser.can_fetch(USER_AGENT, url)
