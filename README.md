# AD Sentinel — 공공 웹사이트 불법광고 탐지 도구

공공 웹사이트의 하위 페이지·게시글·댓글·iframe에 게시되거나 숨겨진 불법광고(도박·성인물 등)를
자동으로 찾아 분류하고, 위치(페이지 URL + CSS 선택자)를 알려주는 도구입니다.

> 행정안전부·NIA 「공공 웹사이트 불법광고 탐지 도구 개발 공모전」 출품작

## 진행 현황

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | 크롤러 (Playwright 렌더링, iframe·숨김 요소 수집) | ✅ |
| 2 | 탐지·분류 (키워드·숨김·도메인 점수, 화이트리스트, 페이지 간 묶기) | ✅ |
| 3 | GUI (사이트 점검, URL 목록 점검, 결과 상세, 보고서 내보내기) | ✅ |
| 4 | Windows exe 빌드 (PyInstaller) | ⏳ |
| 5 | 문서 (매뉴얼, 사용설명서, 기획서) | ⏳ |

## 폴더 구조

```
ad-sentinel/
├── main.py                    # 실행 진입점 (인자 없이 실행하면 GUI, 인자가 있으면 CLI)
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
│   │   ├── domains.py         #   정상 도메인 화이트리스트, 의심 도메인 판별
│   │   └── reflection.py      #   URL 파라미터 반사 판별 (UTF-8·EUC-KR 디코딩)
│   ├── gui/app.py             # [3단계] GUI (Tkinter)
│   ├── url_list.py            # URL 목록 파일 읽기 (txt, csv, 서치 콘솔 내보내기 zip)
│   └── report.py              # 결과 내보내기 (JSON, CSV, HTML 보고서)
├── tests/
│   ├── fixtures/mois_sample.json  # 행정안전부 누리집 실제 크롤링 결과 일부 (오탐 회귀 테스트)
│   ├── fixtures/reflect/      # 주소 파라미터를 화면에 그대로 출력하는 페이지 (파라미터 반사형 스팸 재현)
│   ├── fixtures/site/         # 불법광고가 숨겨진 샘플 사이트 (테스트·시연용)
│   ├── test_url_utils.py
│   ├── fixtures/heavy/        # 요소 1만 개 이상 페이지, 응답 없는 iframe (성능·제한 시간 테스트)
│   ├── test_crawler.py
│   ├── test_heavy.py
│   ├── test_detector.py
│   └── test_reflection.py
├── packaging/                 # [4단계] PyInstaller 설정 (예정)
└── docs/                      # [5단계] 매뉴얼·사용설명서·기획서 (예정)
```

## 화면 사용법 (GUI)

`python main.py` (인자 없이) 또는 exe를 실행합니다.

1. **점검 방식** 선택
   - **사이트 점검**: 시작 주소를 넣으면 같은 사이트 안의 링크를 따라가며 하위 페이지를 점검합니다. 최대 페이지 수와 링크 깊이를 정할 수 있습니다.
   - **URL 목록 점검**: 주소 목록 파일에 있는 주소만 점검합니다. 링크는 따라가지 않습니다.
     txt(한 줄에 주소 하나), CSV(첫 번째 열), 구글 서치 콘솔에서 내보낸 파일(csv 또는 zip)을 그대로 읽습니다.
2. 필요하면 **내가 관리하는 사이트 점검 (robots.txt 무시)** 체크 → 확인 창에서 한 번 더 확인
3. **▶ 점검 시작** → 진행 상황(현재 페이지, N/M, 진행 바, 실시간 로그) 표시, **■ 중지**로 멈추면 그때까지 점검한 결과로 탐지
4. **점검 결과** 목록에서 항목을 누르면 오른쪽에 조치 안내, 근거, 발견 페이지, 위치(선택자), iframe 경로, 숨김 이유, 반사된 파라미터 표시.
   두 번 누르거나 **페이지 열기**를 누르면 브라우저로 엽니다.
5. **HTML 보고서 / CSV / JSON으로 저장**. CSV는 한글 엑셀에서 바로 열립니다.

그 밖의 기능
- **저장된 점검 결과 불러오기**: `output/crawl_*.json`을 고르면 다시 크롤링하지 않고 탐지만 다시 실행합니다. `detect_*.json`은 결과만 표시합니다.
- **신뢰 도메인 관리**: 기본 신뢰 도메인 외에 추가할 도메인을 입력합니다. 저장하면 `whitelist.txt`에 기록되고 현재 결과를 다시 탐지합니다.
- 점검할 때마다 `output/` 폴더에 `crawl_날짜_시간.json`(수집 원본)과 `detect_날짜_시간.json`(탐지 결과)이 자동 저장됩니다.

### 서치 콘솔 연계 흐름 (사용설명서용)

구글 서치 콘솔 → 실적 → 페이지 탭 → 내보내기(CSV 다운로드) → 이 도구에서 **URL 목록 점검** → **목록 파일 불러오기**로 받은 zip 또는 `페이지.csv` 선택 → 점검 시작.
검색엔진에 노출된 주소 중 파라미터 반사형 스팸 주소처럼 사이트 안에서는 링크로 연결되지 않는 주소를 점검할 수 있습니다.

### GUI 라이브러리: Tkinter를 쓴 이유

- **파이썬 표준 라이브러리**라 추가 설치가 없고, PyInstaller로 묶을 때 exe 크기가 PySide6(Qt)보다 수십 MB 작습니다.
- 필요한 화면 요소(입력칸, 표, 진행 바, 파일 선택 창)가 모두 있어 이 도구 규모에 충분합니다.
- 라이선스 확인(LGPL)이나 Qt 플러그인 동봉 같은 배포 문제가 없습니다.
- 코드가 단순해서 심사 때 구조를 설명하기 쉽습니다.

## 설치 및 실행 (개발 환경)

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements-dev.txt
playwright install chromium       # 생략 시 Windows 기본 Edge를 자동 사용

python main.py https://www.example.go.kr --max-pages 20
python main.py --url-list 페이지.csv                            # URL 목록 점검
python main.py --from-json output/crawl_20260926_185056.json   # 기존 크롤링 결과로 탐지만 다시 실행
```

주요 옵션: `--max-pages`, `--depth`, `--delay`, `--page-timeout`, `--out`, `--report`, `--whitelist <도메인...>`, `--same-host-only`,
`--ignore-robots`, `--show-browser`, `--browser <브라우저 경로>`

### robots.txt 무시 (`--ignore-robots`, GUI: "내가 관리하는 사이트 점검")

기본값은 robots.txt 준수입니다. 켜면 실행 시 아래 경고를 표시하고, 결과 JSON의 `meta.robots_ignored`에 `true`로 기록합니다.

> robots.txt 제한을 무시하고 수집합니다. 본인이 관리하거나 점검 권한을 받은 사이트에만 사용하세요.
> 권한 없이 사용하면 사이트 운영 정책 위반이나 법적 문제가 될 수 있습니다.

문구는 `ad_sentinel/config.py`의 `OWN_SITE_LABEL`, `ROBOTS_IGNORE_WARNING`에 있으며 GUI에서도 같은 문구를 씁니다.

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
| URL 파라미터 반사 | 2 | 주소의 `?play=바카라분석` 값이 화면·제목에 그대로 출력됨 |

숨김·외부 도메인·연락처·파라미터 반사는 키워드나 의심 도메인이 있을 때만 더합니다. 그래서 스크린리더용 문구, 메뉴, 빈 요소처럼
광고 내용이 없는 숨김 요소는 결과에 나오지 않습니다.

- **단어 경계**: 약한 키워드(성인, 토토, 슬롯, 오피)는 앞에 한글이 붙어 있으면 제외합니다. 예: "웹 접근성인증"
- **난독화**: 3글자 이상 강한 키워드는 글자 사이 공백·점을 허용합니다. 예: "카 지 노", "꽁.머.니"
- **화이트리스트(신뢰 도메인)**: 기본값은 정부 도메인(`*.go.kr`, `gov.kr`, `mil.kr`, `korea.kr`, `korea.net`)과 공식 SNS뿐입니다.
  해킹된 협회·학교·연구기관 사이트가 광고 호스팅에 악용되는 경우를 대비해 `*.or.kr`, `*.ac.kr`, `*.re.kr`은 기본에서 뺐습니다.
  GUI의 **신뢰 도메인 관리** 또는 exe(프로젝트) 폴더의 `whitelist.txt`에 한 줄에 하나씩 추가할 수 있습니다.
- **문단과 링크 합산**: 문단 텍스트의 키워드 근거와 그 안 링크의 의심 도메인 근거를 합쳐 한 건으로 판정합니다.
  예: `<p>스포츠 베팅 <a href="http://bet...">바로가기</a></p>` → 키워드 2 + 의심 도메인 3 + 외부 1 = 6점 한 건
- **페이지 간 묶기**: 같은 프레임 경로·선택자·내용은 한 건으로 묶고 `"3개 페이지에서 발견"`처럼 표시합니다.
  숨김 요소 안의 링크처럼 이미 찾은 요소의 하위 요소는 따로 표시하지 않습니다.

### 탐지 유형 (`pattern`)

| 유형 | 조건 |
|---|---|
| URL 파라미터 반사 | 반사 근거가 있음. `reflected_params`에 반사된 파라미터 이름과 값 표시 → 불법광고 의심 |
| 악용 가능 지점 | 검색 파라미터(q, query, keyword, searchWrd 등)의 반사만으로 잡히고 다른 광고 근거가 없음 → 항상 **검토 필요** |
| 자동 이동 | meta refresh 또는 다른 사이트로 이동 |
| 숨김 광고 | 숨김 근거가 있음 |
| 노출 광고 | 그 밖의 경우 |

**URL 파라미터 반사**: 주소 파라미터를 화면에 그대로 출력하는 페이지를 악용한 스팸입니다.
예: `http://old.gongdan.go.kr/home.jsp?play=바카라분석`. 페이지 주소의 쿼리 파라미터 값(UTF-8, 실패 시 EUC-KR로 해석)이
요소 내용이나 페이지 제목에 들어 있고, **그 값 자체에 광고 키워드나 의심 도메인이 있을 때만** 근거로 인정합니다.
`?menu=공지사항`, `?q=주민등록`처럼 평범한 값의 반사는 무시합니다. 검색 페이지가 `?q=카지노 규제`를 출력하는 것처럼
의도가 정상이어도 구조가 같으면 잡히지만, 다음 조건을 모두 만족하면 **악용 가능 지점(검토 필요)**으로 따로 분류하고
"입력값을 그대로 출력하지 않도록 조치 권장" 안내를 붙입니다.

- 반사된 파라미터가 모두 검색용 이름(q, query, keyword, searchWrd 등)
- 반사된 값 밖의 텍스트에 광고 키워드·연락처가 없고, 숨김·의심 도메인·자동 이동 근거도 없음
- 반사된 값 자체도 광고 문구로 보기 어려움 (키워드 1개뿐이고 연락처 없음)

gongdan 사례(`play`는 검색 파라미터가 아님)나 `?q=바카라사이트 텔레그램 @xxx`처럼 값 자체가 광고 문구인 경우는
**URL 파라미터 반사(불법광고 의심)**입니다.

### 실제 사이트 검증 (www.mois.go.kr, 10페이지)

| 항목 | 결과 |
|---|---|
| 숨김 요소 326개 (skipnav, "새창으로 열기", 메뉴, 빈 요소) | 탐지 0건 |
| 외부 도메인 72개 | 광고 판정 0건 (`*.or.kr`·`*.re.kr` 등 19개는 신뢰 목록 밖으로 표시만 됨) |
| "놀이터 안전", "웹 접근성인증" | 키워드로 인식하지 않음 |
| "맹세문 성인남자.mp3" (숨김 목록) | 약한 키워드 1 + 숨김 2 = 3점 → 판정 안 함 |

## 테스트

```bash
python -m pytest
```

`test_crawler.py`는 `tests/fixtures/site`를 로컬 서버로 띄워 실제 브라우저로 크롤링합니다.
`test_heavy.py`는 요소가 1만 개 넘는 페이지와 응답 없는 iframe에서 제한 시간 안에 끝나는지 검증합니다.
`test_detector.py`는 실제 mois 결과(`mois_sample.json`)의 오탐 사례가 광고로 판정되지 않는지, 숨긴 광고는 찾는지 검증합니다.
`test_reflection.py`는 파라미터 반사형 스팸 페이지를 크롤링해 `URL 파라미터 반사` 유형으로 분류되는지 검증합니다.
`test_url_list.py`는 txt·CSV(서치 콘솔 한글 헤더, 엑셀 cp949·UTF-16)·zip 목록 읽기와 목록 모드(링크 미추적)를 검증합니다.
`test_report.py`는 CSV(엑셀용 BOM)·HTML(특수문자 이스케이프)·JSON 내보내기를 검증합니다.
`test_gui.py`는 화면이 있는 환경에서 결과 표·상세 화면·입력 검증·robots 확인 창을 검증합니다. (화면이 없으면 건너뜀)

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
