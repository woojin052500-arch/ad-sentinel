import re
from dataclasses import dataclass

STRONG, MEDIUM, WEAK = 3, 2, 1

GAMBLING = "도박"
ADULT = "성인"
FINANCE = "불법금융"
DRUG = "불법의약품"

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

    _kw("작업대출", FINANCE, STRONG),
    _kw("대포통장", FINANCE, STRONG),
    _kw("카드깡", FINANCE, STRONG),
    _kw("신용카드현금화", FINANCE, STRONG),
    _kw("소액결제현금화", FINANCE, STRONG),
    _kw("내구제", FINANCE, STRONG),
    _kw("무직자대출", FINANCE, MEDIUM),
    _kw("당일대출", FINANCE, MEDIUM),
    _kw("급전", FINANCE, MEDIUM),
    _kw("대출", FINANCE, WEAK),

    _kw("비아그라", DRUG, STRONG),
    _kw("시알리스", DRUG, STRONG),
    _kw("레비트라", DRUG, STRONG),
    _kw("낙태약", DRUG, STRONG),
    _kw("미프진", DRUG, STRONG),
    _kw("발기부전", DRUG, WEAK),
]

CONTACT_PATTERN = re.compile(
    r"(텔레그램|텔레|telegram|카톡|카카오톡|라인)\s*(아이디|id)?\s*[:：]?\s*@?[a-z0-9_]{3,}"
    r"|t\.me/[a-z0-9_]+"
    r"|01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}",
    re.IGNORECASE,
)


def find_keywords(text: str) -> list[Keyword]:
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
            if kw not in found:
                found.append(kw)
    return found


def has_contact(text: str) -> bool:
    return bool(text and CONTACT_PATTERN.search(text))
