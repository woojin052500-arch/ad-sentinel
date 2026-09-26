from dataclasses import dataclass

SECONDS_PER_PAGE = 5
SETTING_LABELS = ("무엇인가요", "언제 바꾸나요", "추천")
RESULT_LABELS = ("무엇인가요", "어떻게 활용하나요", "먼저 볼 것")
UNCHECKED_LABELS = ("무엇인가요", "왜 확인해야 하나요", "먼저 볼 것")


@dataclass(frozen=True)
class Help:
    title: str
    what: str
    when: str
    recommend: str
    labels: tuple[str, str, str] = SETTING_LABELS

    def lines(self) -> list[tuple[str, str]]:
        return [(label, value) for label, value in zip(self.labels, (self.what, self.when, self.recommend))
                if value and value != "-"]


def estimate_text(pages: int, seconds_per_page: int = SECONDS_PER_PAGE) -> str:
    minutes = pages * seconds_per_page / 60
    if minutes < 1:
        return "1분 이내"
    if minutes < 60:
        return f"약 {round(minutes)}분"
    hours, rest = divmod(round(minutes), 60)
    return f"약 {hours}시간" + (f" {rest}분" if rest else "")


SETTINGS: dict[str, Help] = {
    "max_pages": Help(
        "최대 페이지 수",
        "몇 페이지까지 점검할지 정하는 숫자입니다. 이 수에 닿으면 점검을 마칩니다.",
        "사이트 전체를 꼼꼼히 보려면 늘리고, 빨리 훑어보려면 줄이세요. 페이지가 많을수록 오래 걸립니다. "
        f"(한 페이지에 약 {SECONDS_PER_PAGE}초 기준: 30페이지 {estimate_text(30)}, 100페이지 {estimate_text(100)}, "
        f"500페이지 {estimate_text(500)})",
        "처음에는 30, 게시판이 많은 사이트는 100~300",
    ),
    "max_depth": Help(
        "링크 깊이",
        "첫 화면에서 링크를 몇 번까지 눌러 들어갈지 정합니다. "
        "예: 첫 화면 → 게시판 → 게시글 = 2단계",
        "게시글 속 댓글·첨부 화면처럼 더 안쪽까지 봐야 하면 늘리세요. 0이면 시작 주소 한 페이지만 봅니다.",
        "3 (대부분의 게시글까지 닿음)",
    ),
    "enter_gate": Help(
        "입장 버튼 자동 클릭",
        "첫 화면에 '입장하기', '시작하기' 같은 버튼이 있으면 한 번 눌러 본 화면으로 들어갑니다. "
        "로그인·회원가입·결제·삭제·신고·동의·구독·다운로드 버튼은 절대 누르지 않습니다.",
        "첫 화면이 소개 화면이고 버튼을 눌러야 게시판이 나오는 사이트에 필요합니다. "
        "첫 화면에 바로 게시판이 보이는 일반 기관 사이트는 켜 두어도 상관없습니다.",
        "켜 둠",
    ),
    "sitemap": Help(
        "sitemap 또는 RSS 주소",
        "sitemap은 사이트가 가진 페이지 주소를 모아 둔 목록 파일이고, RSS는 새 글 목록입니다. "
        "넣어 두면 링크로 찾기 어려운 게시글까지 점검 목록에 넣습니다.",
        "비워 두면 자동으로 찾습니다. 자동으로 못 찾는 위치(예: /all/sitemap.xml)에 있을 때만 주소를 넣으세요.",
        "비워 둠",
    ),
    "own_site": Help(
        "내가 관리하는 사이트 점검 (robots.txt 무시)",
        "robots.txt는 사이트가 '이 주소는 자동 프로그램이 가져가지 마세요'라고 적어 둔 안내 파일입니다. "
        "이 항목을 켜면 그 안내를 따르지 않고 모든 주소를 점검합니다.",
        "우리 기관이 관리하거나 점검 권한을 받은 사이트인데, robots.txt 때문에 점검하지 못한 주소가 있을 때만 켜세요. "
        "권한 없는 사이트에 쓰면 운영 정책 위반이나 법적 문제가 될 수 있습니다.",
        "꺼 둠",
    ),
    "delay": Help(
        "요청 간격",
        "한 페이지를 보고 다음 페이지로 넘어가기 전에 쉬는 시간입니다.",
        "너무 짧으면 사이트가 공격으로 오해해 접속을 막을 수 있습니다. "
        "'요청 제한' 안내가 뜨면 늘리세요. (막히면 도구가 스스로 간격을 늘리기도 합니다.)",
        "1~3초",
    ),
    "page_timeout": Help(
        "페이지당 제한 시간",
        "한 페이지를 여는 데 최대 몇 초까지 기다릴지 정합니다. 시간이 넘으면 그 페이지는 멈추고 다음으로 넘어갑니다.",
        "사이트가 느리거나, 결과에 '다 불러와지지 않았을 수 있습니다' 또는 '시간 초과' 안내가 뜨면 늘리세요.",
        "60초, 느린 사이트는 120초",
    ),
    "show_browser": Help(
        "브라우저 창 보이기(진단용)",
        "점검하는 동안 브라우저 창을 화면에 띄워, 도구가 실제로 보는 화면을 눈으로 확인합니다.",
        "평소에는 꺼 두세요. 결과가 이상하거나 '다 불러와지지 않았을 수 있습니다' 안내가 뜰 때, "
        "켜고 다시 점검해 화면이 어떻게 보이는지 비교하는 용도입니다.",
        "꺼 둠",
    ),
    "detail_log": Help(
        "상세 로그 보기",
        "페이지마다 걸린 시간, 누른 버튼 같은 기술 정보를 진행 상황에 함께 보여 줍니다. "
        "켜고 점검하면 입장 버튼을 누른 전후 화면도 output/screenshots 폴더에 저장합니다.",
        "점검이 멈추거나 결과가 이상할 때 켜고 다시 점검한 뒤, 그 로그와 화면 캡처를 개발자·담당자에게 보내세요.",
        "평소에는 꺼 둠",
    ),
}

COLUMNS: dict[str, Help] = {
    "level": Help(
        "판정",
        "발견한 내용이 얼마나 확실한지 나타냅니다.\n"
        "· 불법광고 의심: 증거가 충분해 바로 조치가 필요한 것\n"
        "· 검토 필요: 사람이 직접 보고 판단해야 하는 것",
        "'불법광고 의심'부터 먼저 확인하고 조치하세요.",
        "빨간 줄(불법광고 의심) → 노란 줄(검토 필요) 순서로 확인",
        RESULT_LABELS,
    ),
    "pattern": Help(
        "유형",
        "광고가 어떤 방식으로 들어 있는지 나타냅니다.\n"
        "· 노출 광고: 화면에 그대로 보이는 광고 글\n"
        "· 숨김 광고: 화면에는 안 보이게 숨겨 둔 광고\n"
        "· URL 파라미터 반사: 주소 뒤에 붙인 광고 문구가 화면에 그대로 찍혀 나오는 것\n"
        "· 자동 이동: 다른 사이트로 저절로 넘어가게 하는 코드\n"
        "· 악용 가능 지점: 지금 광고는 없지만, 주소에 적은 글이 화면에 그대로 나와 광고에 악용될 수 있는 곳",
        "유형마다 조치 방법이 다릅니다. 결과를 누르면 오른쪽 '조치 안내'에 할 일이 나옵니다.",
        "숨김 광고·자동 이동은 사이트 변조 가능성이 있으니 우선 확인",
        RESULT_LABELS,
    ),
    "category": Help(
        "분류",
        "광고 내용의 종류입니다. (도박, 성인, 불법금융, 불법의약품)",
        "관련 부서에 넘길 때 참고하세요.",
        "-",
        RESULT_LABELS,
    ),
    "score": Help(
        "점수",
        "불법광고 단어, 수상한 주소, 숨김 처리, 연락처 같은 증거마다 점수를 더한 값입니다. 높을수록 확실합니다.",
        "증거가 2개 이상이고 4점이면 '검토 필요', 5점 이상이면 '불법광고 의심'입니다. "
        "결과를 누르면 '판정 근거'에서 어떤 증거로 점수가 붙었는지 볼 수 있습니다.",
        "점수가 높은 것부터 확인",
        RESULT_LABELS,
    ),
    "content": Help(
        "내용",
        "발견한 광고 문구입니다. 게시글 안에서 찾았으면 괄호에 글 제목이 붙습니다.",
        "두 번 누르면 해당 페이지가 브라우저로 열립니다.",
        "-",
        RESULT_LABELS,
    ),
    "pages": Help(
        "페이지 수",
        "같은 광고가 발견된 페이지 개수입니다. 머리글·바닥글처럼 여러 페이지에 반복되면 하나로 묶어 보여 줍니다.",
        "숫자가 크면 사이트 공통 영역(머리글·바닥글 등)이 변조되었을 수 있습니다.",
        "-",
        RESULT_LABELS,
    ),
}

UNCHECKED = Help(
    "점검하지 못한 영역",
    "열리지 않았거나 시간이 넘은 페이지, 내용을 읽지 못한 iframe(페이지 안에 끼워 넣은 다른 화면), "
    "robots.txt 때문에 가져가지 않은 주소입니다.",
    "숨겨진 iframe은 불법광고를 몰래 넣는 대표적인 방법입니다. 결과가 0건이어도 이 목록이 있으면 "
    "주소를 직접 열어 광고가 없는지 확인하세요.",
    "특히 '신뢰 도메인 아님 - 주의'로 표시된 항목은 꼭 확인",
    UNCHECKED_LABELS,
)

QUICK_START_TITLE = "처음 사용하시나요? 3단계 사용법"
QUICK_START = [
    ("주소 입력", "'시작 주소'에 점검할 사이트 주소를 넣습니다. (예: https://www.example.go.kr) "
                  "다른 설정은 그대로 두어도 됩니다."),
    ("점검 시작", "[▶ 점검 시작]을 누르고 기다립니다. 30페이지 기준 몇 분 걸리며, 중간에 [■ 중지]로 멈출 수 있습니다."),
    ("결과 확인", "'4. 점검 결과' 표에서 빨간 줄(불법광고 의심)부터 눌러 오른쪽의 조치 안내를 확인하고, "
                  "[HTML 보고서로 저장]으로 보고서를 남깁니다."),
]
QUICK_START_FOOTER = "각 설정 옆의 ? 에 마우스를 올리면 설명이 나옵니다."



def tooltip_text(item: Help) -> str:
    return "\n".join(f"{label}: {value}" for label, value in item.lines())


def quick_start_text() -> str:
    steps = "\n".join(f"{i}. {name} - {text}" for i, (name, text) in enumerate(QUICK_START, 1))
    return f"{steps}\n\n{QUICK_START_FOOTER}"


def as_markdown() -> str:
    lines = [f"## {QUICK_START_TITLE}", ""]
    lines += [f"{i}. **{name}** - {text}" for i, (name, text) in enumerate(QUICK_START, 1)]
    for heading, items in (("설정 설명", SETTINGS.values()), ("결과 화면 설명", [*COLUMNS.values(), UNCHECKED])):
        lines += ["", f"## {heading}"]
        for h in items:
            lines += ["", f"### {h.title}", ""]
            lines += [f"- **{label}**: {value}".replace("\n", "\n  ") for label, value in h.lines()]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    print(as_markdown())
