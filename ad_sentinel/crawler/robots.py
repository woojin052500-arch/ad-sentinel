"""robots.txt 확인.

기관 사이트 운영 정책을 존중하기 위해 robots.txt 에서 막아 둔 경로는 방문하지 않는다.
robots.txt 를 읽지 못하면(없음, 네트워크 오류) 방문을 허용한다.
"""

import logging
import urllib.request
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

log = logging.getLogger(__name__)

USER_AGENT = "AD-Sentinel"


class RobotsChecker:
    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout
        self._cache: dict[str, RobotFileParser | None] = {}  # 호스트별로 한 번만 내려받는다

    def _load(self, origin: str) -> RobotFileParser | None:
        robots_url = origin + "/robots.txt"
        try:
            req = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
        except Exception as e:  # 404, 타임아웃, 인증서 오류 등 → 제한 없음으로 간주
            log.debug("robots.txt 읽기 실패 (%s): %s", robots_url, e)
            return None
        parser = RobotFileParser()
        parser.parse(body.splitlines())
        return parser

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._cache:
            self._cache[origin] = self._load(origin)
        parser = self._cache[origin]
        return parser is None or parser.can_fetch(USER_AGENT, url)
