# AD Sentinel — 공공 웹사이트 불법광고 탐지 도구

공공 웹사이트의 하위 페이지·게시글·댓글·iframe에 게시되거나 숨겨진 불법광고(도박·성인물 등)를
자동으로 찾아 분류하고, 위치(페이지 URL + CSS 선택자)를 알려주는 도구입니다.

> 행정안전부·NIA 「공공 웹사이트 불법광고 탐지 도구 개발 공모전」 출품작

## 진행 현황

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | 크롤러 (Playwright 렌더링, iframe·숨김 요소 수집) | ✅ |
| 2 | 탐지·분류 (키워드·숨김·도메인 점수, 화이트리스트, 페이지 간 묶기) | ✅ |
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
│   ├── detector/              # [2단계] 탐지·분류
│   │   ├── detector.py        #   근거별 점수 합산, 판정, 페이지 간 묶기
│   │   ├── keywords.py        #   분야별 키워드 사전 (단어 경계·난독화 대응)
│   │   └── domains.py         #   정상 도메인 화이트리스트, 의심 도메인 판별
│   └── gui/                   # [3단계] GUI (예정)
├── tests/
│   ├── fixtures/mois_sample.json  # 행정안전부 누리집 실제 크롤링 결과 일부 (오탐 회귀 테스트)
│   ├── fixtures/site/         # 불법광고가 숨겨진 샘플 사이트 (테스트·시연용)
│   ├── test_url_utils.py
│   ├── fixtures/heavy/        # 요소 1만 개 이상 페이지, 응답 없는 iframe (성능·제한 시간 테스트)
│   ├── test_crawler.py
│   ├── test_heavy.py
│   └── test_detector.py
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
python main.py --from-json output/crawl_20260926_185056.json   # 기존 크롤링 결과로 탐지만 다시 실행
```

주요 옵션: `--max-pages`, `--depth`, `--delay`, `--page-timeout`, `--out`, `--report`, `--whitelist <도메인...>`, `--same-host-only`,
`--ignore-robots`, `--show-browser`, `--browser <브라우저 경로>`

크롤링 결과는 `output/crawl_날짜_시간.json`, 탐지 결과는 `output/detect_날짜_시간.json`에 저장됩니다.

### 제한 시간·상한 (`ad_sentinel/config.py`)

| 설정 | 기본값 | 설명 |
|---|---|---|
| `page_timeout_ms` | 20000 | 페이지 로딩(`goto`) 제한 시간 |
| `page_total_timeout_sec` | 60 | 페이지 하나의 전체 제한 시간. 넘으면 남은 프레임을 건너뛰고 다음 페이지로 |
| `networkidle_timeout_ms` | 5000 | 네트워크가 잠잠해질 때까지 기다리는 최대 시간 |
| `render_wait_ms` | 1500 | 스크롤 후 동적 콘텐츠 대기 시간 |
| `frame_eval_timeout_ms` | 15000 | 메인 문서 추출 제한 시간 |
| `iframe_eval_timeout_ms` | 5000 | iframe 하나의 추출 제한 시간 (응답 없는 iframe은 이 시간 후 건너뜀) |
| `extract_time_budget_ms` | 10000 | 추출 스크립트가 브라우저 안에서 쓰는 최대 시간. 넘으면 검사한 부분까지만 돌려줌 |
| `max_frames_per_page` | 20 | 페이지당 추출할 최대 프레임 수 |
| `max_scan_elements` | 20000 | 프레임당 검사할 최대 요소 수 |
| `max_elements_per_frame` | 3000 | 프레임당 텍스트·링크 레코드 상한 (숨김·iframe 레코드는 별도로 3000개까지 유지) |

실행 중 로그에 단계별 소요 시간이 표시됩니다.

```
[1/10] https://www.example.go.kr/
  로딩 0.84s (HTTP 200)
  렌더링 대기·스크롤 1.59s
  프레임 1/3 메인 1.51s (스크립트 0.46s) 요소 14429개 중 14429개 검사, 레코드 3401개
  프레임 2/3 iframe  → 건너뜀: 추출 시간 초과 (5.0s)
  페이지 완료 9.58s (프레임 3개, 레코드 3420개)
```

## 탐지 방식 (2단계)

요소마다 근거를 모아 점수를 더합니다. **키워드 하나만으로는 판정하지 않습니다.**
근거가 2개 이상이고 합계가 4점 이상이면 `검토 필요`, 5점 이상이면 `불법광고 의심`입니다.

| 근거 | 점수 | 예시 |
|---|---|---|
| 강한 키워드 | 3 | 카지노, 바카라, 토토사이트, 먹튀, 야동, 작업대출, 비아그라 |
| 중간 키워드 | 2 | 안전놀이터, 베팅, 홀덤, 가입코드, 오피(오피스·오피니언 제외) |
| 약한 키워드 | 1 | 성인, 토토, 슬롯, 대출, 환전 |
| 의심 도메인 | 3 | casino, toto, bet, slot, porn 등이 들어간 외부 도메인 |
| 숨김 처리 | 2 | 숨김 요소, 숨겨진 iframe 내부 |
| 화이트리스트 밖 외부 도메인 | 1 | 링크·iframe 주소 |
| 연락처·메신저 ID | 1 | 텔레그램 ID, 010 번호 |

숨김·외부 도메인·연락처는 키워드나 의심 도메인이 있을 때만 더합니다. 그래서 스크린리더용 문구, 메뉴, 빈 요소처럼
광고 내용이 없는 숨김 요소는 결과에 나오지 않습니다.

- **단어 경계**: 약한 키워드(성인, 토토, 슬롯, 오피)는 앞에 한글이 붙어 있으면 제외합니다. 예: "웹 접근성인증"
- **난독화**: 3글자 이상 강한 키워드는 글자 사이 공백·점을 허용합니다. 예: "카 지 노", "꽁.머.니"
- **화이트리스트**: `*.go.kr`, `*.or.kr`, `*.re.kr`, `*.ac.kr`, `korea.kr`, 공식 SNS 등. exe(또는 프로젝트) 폴더에
  `whitelist.txt`를 두면 한 줄에 도메인 하나씩 추가할 수 있습니다.
- **페이지 간 묶기**: 같은 프레임 경로·선택자·내용은 한 건으로 묶고 `"3개 페이지에서 발견"`처럼 표시합니다.
  숨김 요소 안의 링크처럼 이미 찾은 요소의 하위 요소는 따로 표시하지 않습니다.

### 실제 사이트 검증 (www.mois.go.kr, 10페이지)

| 항목 | 결과 |
|---|---|
| 숨김 요소 326개 (skipnav, "새창으로 열기", 메뉴, 빈 요소) | 탐지 0건 |
| 외부 도메인 72개 | 모두 화이트리스트 |
| "놀이터 안전", "웹 접근성인증" | 키워드로 인식하지 않음 |
| "맹세문 성인남자.mp3" (숨김 목록) | 약한 키워드 1 + 숨김 2 = 3점 → 판정 안 함 |

## 테스트

```bash
python -m pytest
```

`test_crawler.py`는 `tests/fixtures/site`를 로컬 서버로 띄워 실제 브라우저로 크롤링합니다.
`test_heavy.py`는 요소가 1만 개 넘는 페이지와 응답 없는 iframe에서 제한 시간 안에 끝나는지 검증합니다.
`test_detector.py`는 실제 mois 결과(`mois_sample.json`)의 오탐 사례가 광고로 판정되지 않는지, 숨긴 광고는 찾는지 검증합니다.

## 크롤링 결과 JSON 형식

```jsonc
{
  "meta": { "start_url": "...", "started_at": "...", "finished_at": "...", "page_count": 3, "config": {...} },
  "skipped": [ { "url": ".../private/secret.html", "reason": "robots.txt" } ],
  "pages": [
    {
      "url": "http://.../index.html", "final_url": "...", "status": 200, "title": "...",
      "depth": 0, "found_on": "", "error": null, "timed_out": false,
      "timings": { "load": 0.84, "render": 1.59, "extract": 1.51, "total": 4.25 },
      "offsite_redirect": false,               // 다른 사이트로 강제 이동되었는지
      "frames": [                              // 메인 문서 + 모든 iframe 문서
        { "frame_url": "...", "src": "", "loaded": true, "frame_path": [], "is_main": true, "title": "...", "text": "페이지 전체 텍스트",
          "total_elements": 14429, "scanned": 14429, "elapsed_ms": 1510, "truncated": false, "timed_out": false, "error": null }
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
- `frames[].src`: iframe 요소의 src 속성. 로드되지 않았거나 추출에 실패한 iframe도 기록되며, 이때 `loaded`는 `false`이고 `frame_url`에 src가 들어갑니다

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
