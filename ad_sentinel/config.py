"""크롤링 설정값.

GUI(3단계)와 CLI가 같은 설정 객체를 쓰도록 한 곳에 모아 둔다.
"""

from dataclasses import dataclass


@dataclass
class CrawlConfig:
    # 탐색을 시작할 URL
    start_url: str

    # 최대 방문 페이지 수 (시작 페이지 포함)
    max_pages: int = 30

    # 시작 페이지로부터 링크를 몇 번까지 따라갈지 (0 = 시작 페이지만)
    max_depth: int = 3

    # True면 www.example.go.kr 에서 시작해도 board.example.go.kr 같은 하위 도메인까지 탐색
    include_subdomains: bool = True

    # 페이지 한 개를 여는 최대 대기 시간(밀리초)
    page_timeout_ms: int = 20000

    # 페이지 로딩 후 동적 콘텐츠(광고 스크립트 등)가 뜰 때까지 추가로 기다리는 시간(밀리초)
    render_wait_ms: int = 1500

    # 페이지 사이 요청 간격(초). 대상 서버에 부담을 주지 않기 위함
    delay_sec: float = 0.5

    # robots.txt 에서 금지한 경로는 방문하지 않음
    respect_robots: bool = True

    # 페이지 하나에서 수집할 요소 수 상한 (거대한 게시판 페이지 대비)
    max_elements_per_frame: int = 3000

    # 텍스트 한 덩어리의 최대 길이 (JSON 크기 제한용)
    max_text_len: int = 500

    # 브라우저 창을 띄우지 않고 실행
    headless: bool = True

    # 사용할 브라우저 실행 파일 경로 (비워 두면 자동 탐색, browser.py 참고)
    browser_executable: str = ""
