import argparse
import functools
import http.server
import socket
from pathlib import Path

from ad_sentinel.paths import output_dir

FIXTURES = Path(__file__).resolve().parent / "tests" / "fixtures"
SITE_DIR = FIXTURES / "site"
OLD_DIR = FIXTURES / "reflect"
OLD_PREFIX = "/old/"


class DemoHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        if path.startswith(OLD_PREFIX):
            return str(OLD_DIR / path[len(OLD_PREFIX):].split("?")[0].split("#")[0])
        return super().translate_path(path)

    def log_message(self, fmt, *args):
        print("  요청:", self.path)


def write_url_list(base: str) -> Path:
    urls = [
        base + "old/home.html?play=%EB%B0%94%EC%B9%B4%EB%9D%BC%EB%B6%84%EC%84%9D",
        base + "old/search.html?q=%EC%B9%B4%EC%A7%80%EB%85%B8+%EA%B7%9C%EC%A0%9C",
        base + "old/search.html?q=%EC%A3%BC%EB%AF%BC%EB%93%B1%EB%A1%9D",
        base + "page2.html",
    ]
    path = output_dir() / "demo_urls.csv"
    path.write_text("상위 페이지,클릭수,노출수\n" + "".join(f"{u},0,10\n" for u in urls), encoding="utf-8-sig")
    return path


def main():
    parser = argparse.ArgumentParser(description="AD Sentinel 시연용 샘플 사이트 서버")
    parser.add_argument("--port", type=int, default=8000, help="포트 번호 (기본 8000)")
    args = parser.parse_args()

    handler = functools.partial(DemoHandler, directory=str(SITE_DIR))
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    except OSError:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        print(f"포트 {args.port}을(를) 쓸 수 없어 {port}번으로 엽니다.")
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    base = f"http://127.0.0.1:{server.server_port}/"
    url_list = write_url_list(base)

    print("=" * 70)
    print(" AD Sentinel 시연용 샘플 사이트가 열렸습니다. (불법광고를 일부러 숨겨 둔 가짜 기관 사이트)")
    print("=" * 70)
    print(f" ① 사이트 점검 시연 : 시작 주소에 {base}index.html 입력 → 점검 시작")
    print("    - 숨김 광고 6건, 노출 광고 2건이 발견됩니다. (display:none, 글자색=배경색, 화면 밖, 1px iframe 등)")
    print("    - robots.txt로 막힌 관리자 페이지 1곳은 '점검하지 못한 영역'으로 표시됩니다.")
    print(" ② URL 목록 점검 시연: '목록 파일 불러오기'에서 아래 파일 선택 → 점검 시작")
    print(f"    {url_list}")
    print("    - URL 파라미터 반사 2건·노출 광고 1건(불법광고 의심), 악용 가능 지점 1건(검토 필요)이 발견됩니다.")
    print(f" ③ 브라우저로 직접 보기: {base}index.html , {base}old/home.html?play=바카라분석")
    print("-" * 70)
    print(" 종료하려면 이 창에서 Ctrl+C 를 누르세요.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n시연 서버를 종료합니다.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
