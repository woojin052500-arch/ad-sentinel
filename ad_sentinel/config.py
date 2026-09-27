from dataclasses import dataclass, field

OWN_SITE_LABEL = "내가 관리하는 사이트 점검 (robots.txt 무시)"
BOT_BLOCK_NOTICE = (
    "사이트의 봇 차단 장치 때문에 일부 화면을 점검하지 못했을 수 있습니다. "
    "관리하는 사이트라면 점검 도구를 허용 목록에 추가하세요."
)
CLOAKING_OFF, CLOAKING_SUSPECT, CLOAKING_ALL = "off", "suspect", "all"
CLOAKING_MODES = {
    CLOAKING_OFF: "끄기",
    CLOAKING_SUSPECT: "첫 페이지·의심 페이지만",
    CLOAKING_ALL: "모든 페이지",
}
ROBOTS_IGNORE_WARNING = (
    "robots.txt 제한을 무시하고 수집합니다. 본인이 관리하거나 점검 권한을 받은 사이트에만 사용하세요. "
    "권한 없이 사용하면 사이트 운영 정책 위반이나 법적 문제가 될 수 있습니다."
)


@dataclass
class CrawlConfig:
    start_url: str = ""
    url_list: list[str] = field(default_factory=list)
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
    delay_sec: float = 1.0
    throttle_backoff_min_sec: float = 2.0
    throttle_max_delay_sec: float = 30.0
    throttle_max_consecutive: int = 3
    enter_gate: bool = True
    gate_link_threshold: int = 3
    gate_wait_ms: int = 20000
    load_more: bool = True
    load_more_max_clicks: int = 30
    load_more_timeout_sec: float = 90.0
    use_sitemap: bool = True
    sitemap_urls: list[str] = field(default_factory=list)
    max_sitemap_urls: int = 5000
    respect_robots: bool = True
    max_elements_per_frame: int = 3000
    max_text_len: int = 500
    headless: bool = True
    screenshot_dir: str = ""
    cloaking_check: str = "off"
    browser_executable: str = ""
