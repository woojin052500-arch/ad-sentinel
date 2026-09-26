"""1단계: 크롤러 패키지.

외부에서는 Crawler 클래스와 CrawlConfig만 가져다 쓰면 된다.
"""

from ad_sentinel.config import CrawlConfig
from ad_sentinel.crawler.crawler import Crawler

__all__ = ["Crawler", "CrawlConfig"]
