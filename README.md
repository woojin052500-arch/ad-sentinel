# AD Sentinel — 공공 웹사이트 불법광고 탐지 도구

공공 웹사이트의 하위 페이지·게시글·댓글·iframe에 게시되거나 숨겨진 불법광고(도박·성인물 등)를
자동으로 찾아 분류하고, 위치(페이지 URL + CSS 선택자)를 알려주는 도구입니다.

> 행정안전부·NIA 「공공 웹사이트 불법광고 탐지 도구 개발 공모전」 출품작

## 진행 현황

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | 크롤러 (Playwright 렌더링, iframe·숨김 요소 수집) | ✅ |
| 2 | 탐지·분류 | ⏳ |
| 3 | GUI | ⏳ |
| 4 | Windows exe 빌드 (PyInstaller) | ⏳ |
| 5 | 문서 (매뉴얼, 사용설명서, 기획서) | ⏳ |

## 폴더 구조

```
ad-sentinel/
├── main.py                    # 실행 진입점 (지금은 CLI, 3단계에서 GUI 실행)
├── requirements.txt           # 실행용 패키지
├── requirements-dev.txt       # 개발·테스트·빌드용 패키지
├── ad_sentinel/
│   ├── config.py              # 크롤링 설정값 (CrawlConfig)
│   ├── paths.py               # exe/소스 실행 경로 차이 처리 (PyInstaller 대응)
│   ├── storage.py             # 결과 JSON 저장·읽기
│   ├── crawler/               # [1단계] 크롤러
│   │   ├── crawler.py         #   BFS 탐색, 페이지·프레임별 수집
│   │   ├── extract_js.py      #   브라우저 안에서 실행되는 추출 스크립트 (숨김 판정 포함)
│   │   ├── browser.py         #   브라우저 자동 탐색 (Chromium → Edge → Chrome)
│   │   ├── robots.py          #   robots.txt 준수
│   │   └── url_utils.py       #   URL 정규화, 같은 사이트 판정
│   ├── detector/              # [2단계] 탐지·분류 (예정)
│   └── gui/                   # [3단계] GUI (예정)
├── tests/
│   ├── fixtures/site/         # 불법광고가 숨겨진 샘플 사이트 (테스트·시연용)
│   ├── test_url_utils.py
│   └── test_crawler.py
├── packaging/                 # [4단계] PyInstaller 설정 (예정)
└── docs/                      # [5단계] 매뉴얼·사용설명서·기획서 (예정)
```

## 설치 및 실행 (개발 환경)

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements-dev.txt
playwright install chromium       # 생략 시 Windows 기본 Edge를 자동 사용

python main.py https://www.example.go.kr --max-pages 20
```

주요 옵션: `--max-pages`, `--depth`, `--delay`, `--out`, `--same-host-only`,
`--ignore-robots`, `--show-browser`, `--browser <브라우저 경로>`

결과는 `output/crawl_날짜_시간.json`에 저장됩니다.

## 테스트

```bash
python -m pytest
```

`test_crawler.py`는 `tests/fixtures/site`를 로컬 서버로 띄워 실제 브라우저로 크롤링합니다.

## 크롤링 결과 JSON 형식

```jsonc
{
  "meta": { "start_url": "...", "started_at": "...", "finished_at": "...", "page_count": 3, "config": {...} },
  "skipped": [ { "url": ".../private/secret.html", "reason": "robots.txt" } ],
  "pages": [
    {
      "url": "http://.../index.html", "final_url": "...", "status": 200, "title": "...",
      "depth": 0, "found_on": "", "error": null,
      "offsite_redirect": false,               // 다른 사이트로 강제 이동되었는지
      "frames": [                              // 메인 문서 + 모든 iframe 문서
        { "frame_url": "...", "frame_path": [], "is_main": true, "title": "...", "text": "페이지 전체 텍스트" }
      ],
      "elements": [
        { "type": "hidden", "selector": "#content > div:nth-of-type(1)", "content": "온라인 카지노 바로가기",
          "hidden_reasons": ["display:none"], "links": ["http://casino.invalid/"],
          "frame_url": "...", "frame_path": [], "rect": { "x": 0, "y": 0, "w": 0, "h": 0 } },
        { "type": "link",   "selector": "...", "href": "...", "content": "링크 글자", "hidden": false, ... },
        { "type": "iframe", "selector": "...", "src": "...", "hidden": true, "hidden_reasons": ["tiny-size"], ... },
        { "type": "text",   "selector": "#comments > li:nth-of-type(2)", "content": "먹튀 없는 안전놀이터 ...", ... }
      ]
    }
  ]
}
```

- `selector`: 해당 프레임 문서 안에서의 CSS 선택자
- `frame_path`: 메인 문서에서 그 프레임까지 거치는 `<iframe>`들의 선택자 (메인 문서면 `[]`)

### 숨김 판정 기준 (`hidden_reasons`)

| 값 | 의미 |
|---|---|
| `display:none` / `visibility:hidden` / `opacity:0` | CSS로 감춤 |
| `off-screen` | 화면 밖 좌표(예: `left:-9999px`)로 밀어냄 |
| `text-indent` | `text-indent:-9999px` 로 글자를 밀어냄 |
| `zero-size` / `clip` | 크기 0·잘라내기로 감춤 |
| `tiny-font` | 글자 크기 2px 미만 |
| `same-color-as-background` / `transparent-text` | 글자색이 배경색과 같거나 투명 |
| `tiny-size` (iframe) | 2px 이하 크기의 iframe |

> 참고: 드롭다운 메뉴, 팝업, 스크린리더용 문구(`.blind`, `.sr-only`)도 숨김 요소로 수집됩니다.
> 크롤러는 **빠짐없이 수집**하는 역할이고, 광고 여부 판단은 2단계 탐지기에서 내용으로 합니다.
