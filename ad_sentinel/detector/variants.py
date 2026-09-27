import re
import unicodedata
from dataclasses import dataclass

from ad_sentinel.detector.keywords import KEYWORDS, MEDIUM, Keyword, find_keyword_spans

INVISIBLE = re.compile("[­͏؜ᅟᅠ឴឵᠎​-‏‪-‮"
                       "⁠-⁤⁦-⁯ㅤ﻿ﾠ]")

HOMOGLYPHS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    "ԁ": "d", "ԛ": "q", "ӏ": "l", "ԝ": "w", "һ": "h", "к": "k", "м": "m", "т": "t", "в": "b", "н": "h",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
    "Х": "X", "У": "Y", "І": "I", "Ј": "J", "Ѕ": "S",
    "α": "a", "ο": "o", "ρ": "p", "ν": "v", "ι": "i", "κ": "k", "τ": "t", "υ": "u", "χ": "x", "ε": "e",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O",
    "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
})

CHOSUNG = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
CONJOINING_CHOSUNG = str.maketrans({chr(0x1100 + i): c for i, c in enumerate(CHOSUNG)})

ENCLOSED, STYLED = "enclosed", "styled"
ENCLOSED_TAGS = {"<circle>", "<square>"}
STYLED_TAGS = {"<font>", "<super>", "<sub>"}
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _extra_letters() -> dict[str, tuple[str, str]]:
    table = {}
    for base in (0x1F150, 0x1F170, 0x1F1E6):
        for i, letter in enumerate(ALPHABET):
            table[chr(base + i)] = (letter, ENCLOSED)
    for base in (0x2776, 0x2780, 0x278A):
        for i in range(10):
            table[chr(base + i)] = (str(i + 1), ENCLOSED)
    for i in range(10):
        table[chr(0x24EB + i)] = (str(i + 11), ENCLOSED)
    for ch in ("⓿", "\U0001F10B", "\U0001F10C"):
        table[ch] = ("0", ENCLOSED)
    for letter in ALPHABET:
        try:
            table[unicodedata.lookup(f"LATIN LETTER SMALL CAPITAL {letter}")] = (letter.lower(), STYLED)
        except KeyError:
            pass
    return table


EXTRA_LETTERS = _extra_letters()


def letter_style(ch: str) -> str:
    if ch in EXTRA_LETTERS:
        return EXTRA_LETTERS[ch][1]
    tag, _, rest = unicodedata.decomposition(ch).partition(" ")
    if tag in ENCLOSED_TAGS or (tag == "<compat>" and rest.startswith("0028 ") and rest.endswith(" 0029")):
        return ENCLOSED
    if tag in STYLED_TAGS:
        return STYLED
    return ""


def _plain(ch: str) -> str:
    if ch in EXTRA_LETTERS:
        return EXTRA_LETTERS[ch][0]
    plain = unicodedata.normalize("NFKC", ch)
    if len(plain) > 2 and plain[0] == "(" and plain[-1] == ")" and letter_style(ch) == ENCLOSED:
        plain = plain[1:-1]
    return plain.translate(CONJOINING_CHOSUNG)
JUNGSUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
JONGSUNG = ["", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ",
            "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]

CONSONANT_GROUP = {"ㄲ": "ㄱ", "ㅋ": "ㄱ", "ㄸ": "ㄷ", "ㅌ": "ㄷ", "ㅃ": "ㅂ", "ㅍ": "ㅂ", "ㅆ": "ㅅ",
                   "ㅉ": "ㅈ", "ㅊ": "ㅈ"}
VOWEL_GROUP = {"ㅑ": "ㅏ", "ㅘ": "ㅏ", "ㅕ": "ㅓ", "ㅝ": "ㅓ", "ㅛ": "ㅗ", "ㅠ": "ㅜ", "ㅟ": "ㅣ", "ㅢ": "ㅣ",
               "ㅔ": "ㅐ", "ㅒ": "ㅐ", "ㅖ": "ㅐ", "ㅙ": "ㅐ", "ㅚ": "ㅐ", "ㅞ": "ㅐ"}

FUZZY_EXCLUDE = {"가입코드", "추천코드", "내구제", "낙태약", "입금 보너스", "무료 영상"}

CHOSUNG_WORDS = {
    "ㅂㅋㄹ": "바카라", "ㅋㅈㄴ": "카지노", "ㅌㅌ": "토토", "ㅁㅌ": "먹튀", "ㅌㅌㅅㅇㅌ": "토토사이트",
    "ㅅㅅㅌㅌ": "사설토토", "ㅇㅈㄴㅇㅌ": "안전놀이터", "ㅁㅇㅈㄴㅇㅌ": "메이저놀이터", "ㅅㄹㅅㅇㅌ": "슬롯사이트",
    "ㅍㅇㅂ": "파워볼", "ㄲㅁㄴ": "꽁머니", "ㅈㄱㅁㄴ": "조건만남", "ㅊㅈㅇㅁ": "출장안마", "ㅇㅈㄱㅈ": "원조교제",
    "ㅈㅇㄷㅊ": "작업대출", "ㄷㅍㅌㅈ": "대포통장", "ㅂㅇㄱㄹ": "비아그라",
}

KEYBOARD = {
    "q": "ㅂ", "w": "ㅈ", "e": "ㄷ", "r": "ㄱ", "t": "ㅅ", "y": "ㅛ", "u": "ㅕ", "i": "ㅑ", "o": "ㅐ", "p": "ㅔ",
    "a": "ㅁ", "s": "ㄴ", "d": "ㅇ", "f": "ㄹ", "g": "ㅎ", "h": "ㅗ", "j": "ㅓ", "k": "ㅏ", "l": "ㅣ",
    "z": "ㅋ", "x": "ㅌ", "c": "ㅊ", "v": "ㅍ", "b": "ㅠ", "n": "ㅜ", "m": "ㅡ",
    "Q": "ㅃ", "W": "ㅉ", "E": "ㄸ", "R": "ㄲ", "T": "ㅆ", "O": "ㅒ", "P": "ㅖ",
}
VOWEL_PAIRS = {("ㅗ", "ㅏ"): "ㅘ", ("ㅗ", "ㅐ"): "ㅙ", ("ㅗ", "ㅣ"): "ㅚ", ("ㅜ", "ㅓ"): "ㅝ", ("ㅜ", "ㅔ"): "ㅞ",
               ("ㅜ", "ㅣ"): "ㅟ", ("ㅡ", "ㅣ"): "ㅢ"}
FINAL_PAIRS = {("ㄱ", "ㅅ"): "ㄳ", ("ㄴ", "ㅈ"): "ㄵ", ("ㄴ", "ㅎ"): "ㄶ", ("ㄹ", "ㄱ"): "ㄺ", ("ㄹ", "ㅁ"): "ㄻ",
               ("ㄹ", "ㅂ"): "ㄼ", ("ㄹ", "ㅅ"): "ㄽ", ("ㄹ", "ㅌ"): "ㄾ", ("ㄹ", "ㅍ"): "ㄿ", ("ㄹ", "ㅎ"): "ㅀ",
               ("ㅂ", "ㅅ"): "ㅄ"}

VARIANT_LABELS = {
    "normalize": "보이지 않는 문자·전각·닮은꼴 문자",
    ENCLOSED: "감싼 문자",
    STYLED: "특수 글꼴·첨자 문자",
    "symbols": "기호 삽입",
    "spaces": "띄어쓰기 변형",
    "digits": "숫자·영문 치환",
    "sound": "발음 변형",
    "chosung": "초성 표기",
    "keyboard": "한영 자판 변환",
}
FULL_WEIGHT_METHODS = {"normalize", "symbols", ENCLOSED, STYLED}


@dataclass
class Hit:
    keyword: Keyword
    method: str
    original: str
    reading: str
    weight: int

    @property
    def variant(self) -> bool:
        return self.method != "exact"


def _is_hangul_syllable(ch: str) -> bool:
    return "가" <= ch <= "힣"


def _is_hangul_jamo(ch: str) -> bool:
    return "ㄱ" <= ch <= "ㆎ"


def normalize(text: str) -> tuple[str, list[int]]:
    chars, index = [], []
    for i, ch in enumerate(text):
        if INVISIBLE.match(ch) or unicodedata.combining(ch):
            continue
        if not (_is_hangul_syllable(ch) or _is_hangul_jamo(ch)):
            ch = _plain(ch)
        for c in ch.translate(HOMOGLYPHS):
            if unicodedata.combining(c):
                continue
            chars.append(c)
            index.append(i)
    return "".join(chars), index


def _compact(text: str, index: list[int]) -> tuple[str, list[int]]:
    chars, idx = [], []
    for ch, i in zip(text, index):
        if ch.isalnum():
            chars.append(ch)
            idx.append(i)
    return "".join(chars), idx


def _original(text: str, index: list[int], start: int, end: int) -> str:
    if not index or start >= len(index):
        return ""
    return text[index[start]:index[end - 1] + 1]


def _decompose(ch: str) -> tuple[str, str, str]:
    code = ord(ch) - 0xAC00
    return CHOSUNG[code // 588], JUNGSUNG[(code % 588) // 28], JONGSUNG[code % 28]


def _skeleton(ch: str) -> str:
    if not _is_hangul_syllable(ch):
        return "##"
    cho, jung, _ = _decompose(ch)
    return CONSONANT_GROUP.get(cho, cho) + VOWEL_GROUP.get(jung, jung)


def _compose(jamos: list[str]) -> str:
    def syllable(cho, jung, jong):
        return chr(0xAC00 + CHOSUNG.index(cho) * 588 + JUNGSUNG.index(jung) * 28 + JONGSUNG.index(jong))

    out, i, n = [], 0, len(jamos)
    is_vowel = lambda c: c in JUNGSUNG
    is_cons = lambda c: c in CHOSUNG
    while i < n:
        c = jamos[i]
        if is_cons(c) and i + 1 < n and is_vowel(jamos[i + 1]):
            cho, jung = c, jamos[i + 1]
            i += 2
            if i < n and (jung, jamos[i]) in VOWEL_PAIRS:
                jung = VOWEL_PAIRS[(jung, jamos[i])]
                i += 1
            jong = ""
            if i < n and jamos[i] in JONGSUNG and not (i + 1 < n and is_vowel(jamos[i + 1])):
                jong = jamos[i]
                i += 1
                if (i < n and (jong, jamos[i]) in FINAL_PAIRS
                        and not (i + 1 < n and is_vowel(jamos[i + 1]))):
                    jong = FINAL_PAIRS[(jong, jamos[i])]
                    i += 1
            out.append(syllable(cho, jung, jong))
        else:
            out.append(c)
            i += 1
    return "".join(out)


def keyboard_to_hangul(latin: str) -> str:
    jamos = [KEYBOARD.get(ch) or KEYBOARD.get(ch.lower(), ch) for ch in latin]
    return _compose(jamos)


HANGUL_KEYWORDS = [k for k in KEYWORDS if re.fullmatch(r"[가-힣 ]+", k.word)]
FUZZY_KEYWORDS = [(k, "".join(_skeleton(c) for c in k.word.replace(" ", ""))) for k in HANGUL_KEYWORDS
                  if len(k.word.replace(" ", "")) >= 3 and k.word not in FUZZY_EXCLUDE and k.weight >= MEDIUM]
DIGIT_PATTERNS = [
    (k, re.compile("|".join(re.escape(w[:i]) + "[0-9A-Za-z]" + re.escape(w[i + 1:]) for i in range(len(w)))))
    for k, w in ((k, k.word.replace(" ", "")) for k in HANGUL_KEYWORDS)
    if len(w) >= 3 and k.word not in FUZZY_EXCLUDE
]
KEYWORD_BY_WORD = {k.word: k for k in KEYWORDS}


def _lower_weight(kw: Keyword) -> int:
    return max(1, kw.weight - 1)


def analyze(text: str) -> list[Hit]:
    if not text:
        return []
    hits: dict[str, Hit] = {}

    def add(kw: Keyword, method: str, original: str, reading: str = ""):
        if method == "normalize":
            method = _style_method(original) or method
        weight = kw.weight if method in ("exact", *FULL_WEIGHT_METHODS) else _lower_weight(kw)
        current = hits.get(kw.word)
        if current is None or weight > current.weight:
            hits[kw.word] = Hit(kw, method, original.strip(), reading or kw.word, weight)

    for kw, start, end in find_keyword_spans(text):
        add(kw, "exact", text[start:end])

    norm, index = normalize(text)
    if norm != text:
        for kw, start, end in find_keyword_spans(norm):
            add(kw, "normalize", _original(text, index, start, end))

    compact, cindex = _compact(norm, index)
    for kw, start, end in find_keyword_spans(compact):
        original = _original(text, cindex, start, end)
        if len(kw.word.replace(" ", "")) <= 2 and re.search(r"\s", original):
            continue
        inserted = re.sub(r"[\w\s]", "", original)
        add(kw, "symbols" if inserted else "spaces", original)

    for kw, pattern in DIGIT_PATTERNS:
        for m in pattern.finditer(compact):
            original = _original(text, cindex, m.start(), m.end())
            if not re.search(r"\s", original):
                add(kw, "digits", original)
                break

    skeleton = "".join(_skeleton(c) for c in compact)
    for kw, target in FUZZY_KEYWORDS:
        pos = skeleton.find(target)
        while pos != -1:
            if pos % 2 == 0:
                original = _original(text, cindex, pos // 2, pos // 2 + len(target) // 2)
                if not re.search(r"\s", original):
                    add(kw, "sound", original)
                    break
            pos = skeleton.find(target, pos + 1)

    for m in re.finditer(r"[ㄱ-ㅎ]+", norm):
        word = CHOSUNG_WORDS.get(m.group())
        if word and word in KEYWORD_BY_WORD:
            add(KEYWORD_BY_WORD[word], "chosung", _original(text, index, m.start(), m.end()))

    for m in re.finditer(r"[A-Za-z]{3,30}", norm):
        converted = keyboard_to_hangul(m.group())
        syllables = sum(1 for c in converted if _is_hangul_syllable(c))
        if syllables < 2:
            continue
        for kw, start, end in find_keyword_spans(converted):
            covered = len(kw.word.replace(" ", ""))
            if re.fullmatch(r"[가-힣 ]+", kw.word) and covered * 2 >= syllables:
                add(kw, "keyboard", _original(text, index, m.start(), m.end()), converted)

    return list(hits.values())


def _style_method(original: str) -> str:
    styles = {letter_style(ch) for ch in original}
    if ENCLOSED in styles:
        return ENCLOSED
    return STYLED if STYLED in styles else ""


def evidence_label(hit: Hit) -> str:
    base = f"{hit.keyword.category} 키워드 '{hit.keyword.word}'"
    if not hit.variant:
        return base
    reading = hit.reading if hit.method == "keyboard" else hit.keyword.word
    return f"{base} (변형 표기: {hit.original} → {reading}, {VARIANT_LABELS[hit.method]})"
