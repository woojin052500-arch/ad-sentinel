from dataclasses import dataclass


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
