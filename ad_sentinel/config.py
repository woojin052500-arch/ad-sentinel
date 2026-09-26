from dataclasses import dataclass

OWN_SITE_LABEL = "내가 관리하는 사이트 점검 (robots.txt 무시)"
ROBOTS_IGNORE_WARNING = (
    "robots.txt 제한을 무시하고 수집합니다. 본인이 관리하거나 점검 권한을 받은 사이트에만 사용하세요. "
    "권한 없이 사용하면 사이트 운영 정책 위반이나 법적 문제가 될 수 있습니다."
)


@dataclass
class CrawlConfig:
    start_url: str
    max_pages: int = 30
    max_depth: int = 3
    include_subdomains: bool = True
    page_timeout_ms: int = 20000
    page_total_timeout_sec: float = 60.0
    networkidle_timeout_ms: int = 5000
    render_wait_ms: int = 1500
    frame_eval_timeout_ms: int = 15000
    iframe_eval_timeout_ms: int = 5000
    extract_time_budget_ms: int = 10000
    max_frames_per_page: int = 20
    max_scan_elements: int = 20000
    delay_sec: float = 0.5
    respect_robots: bool = True
    max_elements_per_frame: int = 3000
    max_text_len: int = 500
    headless: bool = True
    browser_executable: str = ""
