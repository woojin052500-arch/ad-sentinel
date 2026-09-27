import re
from dataclasses import dataclass

STRONG, MEDIUM, WEAK = 3, 2, 1

GAMBLING = "도박"
ADULT = "성인"
FINANCE = "불법금융"
DRUG = "불법의약품"
NARCOTIC = "마약"
ACCOUNT = "대포통장"
EXCHANGE = "불법환전"
LOAN = "작업대출"

HANGUL = "가-힣"
SEPARATOR = r"[\s·.\-_*|/]{0,2}"


@dataclass(frozen=True)
class Keyword:
    word: str
    category: str
    weight: int
    pattern: re.Pattern


def _compile(word: str, weight: int, strict: bool, not_after: str) -> re.Pattern:
    tokens = word.split()
    if weight == STRONG and len(word.replace(" ", "")) >= 3:
        body = SEPARATOR.join(re.escape(c) for c in word.replace(" ", ""))
    else:
        body = r"\s*".join(re.escape(t) for t in tokens)
    prefix = f"(?<![{HANGUL}])" if strict else ""
    suffix = f"(?!{not_after})" if not_after else ""
    return re.compile(prefix + body + suffix, re.IGNORECASE)


def _kw(word, category, weight, strict=False, not_after=""):
    return Keyword(word, category, weight, _compile(word, weight, strict, not_after))


def _en(word, category, weight):
    return Keyword(word, category, weight, re.compile(rf"(?<![a-z]){word}", re.IGNORECASE))


KEYWORDS = [
    _kw("카지노", GAMBLING, STRONG),
    _kw("바카라", GAMBLING, STRONG),
    _kw("토토사이트", GAMBLING, STRONG),
    _kw("사설토토", GAMBLING, STRONG),
    _kw("먹튀", GAMBLING, STRONG),
    _kw("슬롯사이트", GAMBLING, STRONG),
    _kw("메이저놀이터", GAMBLING, STRONG),
    _kw("꽁머니", GAMBLING, STRONG),
    _kw("첫충", GAMBLING, STRONG),
    _kw("매충", GAMBLING, STRONG),
    _kw("파워볼", GAMBLING, STRONG),
    _kw("안전놀이터", GAMBLING, MEDIUM),
    _kw("베팅", GAMBLING, MEDIUM),
    _kw("배팅", GAMBLING, MEDIUM),
    _kw("홀덤", GAMBLING, MEDIUM),
    _kw("가입코드", GAMBLING, MEDIUM),
    _kw("추천코드", GAMBLING, MEDIUM),
    _kw("입금 보너스", GAMBLING, MEDIUM),
    _kw("사다리게임", GAMBLING, MEDIUM),
    _kw("스포츠토토", GAMBLING, MEDIUM),
    _kw("토토", GAMBLING, WEAK, strict=True),
    _kw("슬롯", GAMBLING, WEAK, strict=True),
    _kw("룰렛", GAMBLING, WEAK),
    _kw("환전", GAMBLING, WEAK),

    _kw("야동", ADULT, STRONG),
    _kw("성인방송", ADULT, STRONG),
    _kw("조건만남", ADULT, STRONG),
    _kw("원조교제", ADULT, STRONG),
    _kw("출장안마", ADULT, STRONG),
    _kw("출장마사지", ADULT, STRONG),
    _kw("섹스", ADULT, STRONG),
    _kw("립카페", ADULT, STRONG),
    _kw("키스방", ADULT, STRONG),
    _kw("오피", ADULT, MEDIUM, strict=True, not_after="스|니|셜"),
    _kw("몰카", ADULT, MEDIUM),
    _kw("19금", ADULT, MEDIUM),
    _kw("룸살롱", ADULT, MEDIUM),
    _kw("룸싸롱", ADULT, MEDIUM),
    _kw("성인용품", ADULT, MEDIUM),
    _kw("성인", ADULT, WEAK, strict=True),
    _kw("무료 영상", ADULT, WEAK),
    _kw("유흥", ADULT, WEAK),

    _kw("카드깡", FINANCE, STRONG),
    _kw("휴대폰깡", FINANCE, STRONG),
    _kw("신용카드현금화", FINANCE, STRONG),
    _kw("소액결제현금화", FINANCE, STRONG),
    _kw("정보이용료현금화", FINANCE, STRONG),
    _kw("내구제", FINANCE, STRONG),

    _kw("작업대출", LOAN, STRONG),
    _kw("대출작업", LOAN, STRONG),
    _kw("서류작업", LOAN, STRONG),
    _kw("재직작업", LOAN, STRONG),
    _kw("무직자작업", LOAN, STRONG),
    _kw("무직자대출", LOAN, MEDIUM),
    _kw("신불자대출", LOAN, MEDIUM),
    _kw("연체자대출", LOAN, MEDIUM),
    _kw("당일대출", LOAN, MEDIUM),
    _kw("급전", LOAN, MEDIUM),
    _kw("대출", LOAN, WEAK),

    _kw("대포통장", ACCOUNT, STRONG),
    _kw("통장매입", ACCOUNT, STRONG),
    _kw("통장매매", ACCOUNT, STRONG),
    _kw("통장삽니다", ACCOUNT, STRONG),
    _kw("통장구매", ACCOUNT, STRONG),
    _kw("통장임대", ACCOUNT, STRONG),
    _kw("법인통장매입", ACCOUNT, STRONG),
    _kw("대포폰", ACCOUNT, STRONG),
    _kw("대포유심", ACCOUNT, STRONG),
    _kw("유심매입", ACCOUNT, STRONG),
    _kw("통장대여", ACCOUNT, MEDIUM),
    _kw("계좌대여", ACCOUNT, MEDIUM),
    _kw("명의대여", ACCOUNT, MEDIUM),
    _kw("체크카드매입", ACCOUNT, MEDIUM),
    _kw("법인통장", ACCOUNT, WEAK),

    _kw("환치기", EXCHANGE, STRONG),
    _kw("불법환전", EXCHANGE, STRONG),
    _kw("코인세탁", EXCHANGE, STRONG),
    _kw("자금세탁 대행", EXCHANGE, STRONG),
    _kw("테더매입", EXCHANGE, STRONG),
    _kw("테더판매", EXCHANGE, STRONG),
    _kw("환전대행", EXCHANGE, MEDIUM),
    _kw("코인환전", EXCHANGE, MEDIUM),
    _kw("테더환전", EXCHANGE, MEDIUM),
    _kw("상품권매입", EXCHANGE, MEDIUM),

    _kw("필로폰", NARCOTIC, STRONG),
    _kw("물뽕", NARCOTIC, STRONG),
    _kw("엑스터시", NARCOTIC, STRONG),
    _kw("케타민", NARCOTIC, STRONG),
    _kw("야바", NARCOTIC, STRONG, strict=True, not_after="바|위|간|구|외|채"),
    _kw("빙두", NARCOTIC, STRONG),
    _kw("떨액", NARCOTIC, STRONG),
    _kw("액상대마", NARCOTIC, STRONG),
    _kw("대마젤리", NARCOTIC, STRONG),
    _kw("대마쿠키", NARCOTIC, STRONG),
    _kw("아이스작대기", NARCOTIC, STRONG),
    _kw("마약판매", NARCOTIC, STRONG),
    _kw("마약구매", NARCOTIC, STRONG),
    _kw("마약구입", NARCOTIC, STRONG),
    _kw("대마초", NARCOTIC, MEDIUM),
    _kw("코카인", NARCOTIC, MEDIUM),
    _kw("헤로인", NARCOTIC, MEDIUM),
    _kw("사티바", NARCOTIC, MEDIUM),
    _kw("던지기 거래", NARCOTIC, MEDIUM),
    _kw("좌표 거래", NARCOTIC, MEDIUM),
    _kw("마약", NARCOTIC, WEAK, strict=True),
    _kw("대마", NARCOTIC, WEAK, strict=True, not_after="도|을|루|디|른"),

    _kw("비아그라", DRUG, STRONG),
    _kw("시알리스", DRUG, STRONG),
    _kw("레비트라", DRUG, STRONG),
    _kw("낙태약", DRUG, STRONG),
    _kw("미프진", DRUG, STRONG),
    _kw("발기부전", DRUG, WEAK),

    _en("casino", GAMBLING, STRONG),
    _en("baccarat", GAMBLING, STRONG),
    _en("powerball", GAMBLING, STRONG),
    _en("porn", ADULT, STRONG),
    _en("viagra", DRUG, STRONG),
    _en("cialis", DRUG, STRONG),
    _en("ketamine", NARCOTIC, STRONG),
    _en("meth", NARCOTIC, MEDIUM),
    _en("usdt", EXCHANGE, MEDIUM),
]

TELEGRAM_PATTERN = re.compile(
    r"(?:(?<![가-힣])(?:텔레그램|텔레|텔그|텔렘|텔)|(?<![a-z])telegram)"
    r"\s*(?:아이디|id|문의|주소|연락)?\s*[:：]?\s*@?[a-z][a-z0-9_]{3,31}(?![a-z0-9_])"
    r"|(?<![a-z])tg\s*(?:id\s*[:：]?|[:：@])\s*@?[a-z][a-z0-9_]{3,31}(?![a-z0-9_])"
    r"|(?<![a-z0-9])(?:t\.me|telegram\.me|telegram\.dog)/[a-z0-9_+]+",
    re.IGNORECASE,
)
CONTACT_PATTERN = re.compile(
    r"(?:카톡|카카오톡|카카오|라인|위챗|wechat|시그널|signal)\s*(?:아이디|id|문의)?\s*[:：]?\s*@?[a-z0-9_]{3,}"
    r"|(?<![\w@.])@[a-z][a-z0-9_]{4,31}(?![\w@]|\.[a-z])"
    r"|01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}",
    re.IGNORECASE,
)


def find_keyword_spans(text: str) -> list[tuple[Keyword, int, int]]:
    if not text:
        return []
    found = []
    covered: list[tuple[int, int]] = []
    for kw in sorted(KEYWORDS, key=lambda k: -len(k.word)):
        for m in kw.pattern.finditer(text):
            span = (m.start(), m.end())
            if any(s <= span[0] and span[1] <= e for s, e in covered):
                continue
            covered.append(span)
            found.append((kw, m.start(), m.end()))
    return found


def find_keywords(text: str) -> list[Keyword]:
    found = []
    for kw, _, _ in find_keyword_spans(text):
        if kw not in found:
            found.append(kw)
    return found


def has_contact(text: str) -> bool:
    return bool(find_contact(text))


def find_contact(text: str) -> tuple[str, str] | None:
    if not text:
        return None
    m = TELEGRAM_PATTERN.search(text)
    if m:
        return "telegram", " ".join(m.group().split())
    m = CONTACT_PATTERN.search(text)
    if m:
        return "contact", " ".join(m.group().split())
    return None


PREVENTION_PATTERN = re.compile(
    r"예방|중독|근절|단속|처벌|퇴치|경각심|캠페인|사행성|사행\s*행위|치유|사범|적발|검거|수사|피해\s*(?:예방|사례|주의|신고)"
    r"|불법\s*(?:\S+\s*)?(?:도박|사이트|마약|대출|금융|광고|사금융|거래)|불법(?:이며|입니다|이므로|이에요)"
    r"|신고\s*(?:센터|방법|하세요|해\s*주세요|전화|포상)|상담\s*(?:센터|전화)|치료\s*(?:센터|기관|보호)|유의\s*사항"
    r"|주의\s*(?:하세요|보|를\s*당부)")


def is_prevention_context(text: str) -> bool:
    return bool(text and PREVENTION_PATTERN.search(text))
