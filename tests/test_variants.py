import json
from pathlib import Path

import pytest

from ad_sentinel.detector import Detector, detect
from ad_sentinel.detector.detector import HIGH, SUSPECT
from ad_sentinel.detector.variants import analyze, keyboard_to_hangul, normalize

START = "https://www.example.go.kr/"
FIXTURES = Path(__file__).parent / "fixtures"


def _hit(text):
    hits = [h for h in analyze(text) if h.variant]
    assert len(hits) == 1, [(h.keyword.word, h.method) for h in analyze(text)]
    return hits[0]


@pytest.mark.parametrize("text,word,method,original", [
    ("밖!콰라!!", "바카라", "sound", "밖!콰라"),
    ("카징노 바로가기", "카지노", "sound", "카징노"),
    ("qkzkfk사이트", "바카라", "keyboard", "qkzkfk"),
    ("ㅂㅋㄹ 가입", "바카라", "chosung", "ㅂㅋㄹ"),
    ("카​지노", "카지노", "normalize", "카​지노"),
    ("casinо 777", "casino", "confusable", "casinо"),
    ("ｃａｓｉｎｏ", "casino", "normalize", "ｃａｓｉｎｏ"),
    ("카2노 가입", "카지노", "digits", "카2노"),
    ("토.토", "토토", "symbols", "토.토"),
    ("꽁.머.니!!", "꽁머니", "exact", ""),
])
def test_variant_is_read_back(text, word, method, original):
    hits = {h.keyword.word: h for h in analyze(text)}
    assert word in hits
    assert hits[word].method == method
    if original:
        assert hits[word].original == original


def test_variant_weight_is_lower_than_exact():
    assert _hit("밖!콰라").weight == 2
    assert _hit("qkzkfk").weight == 2
    assert _hit("카​지노").weight == 3


def test_keyboard_conversion_and_normalize():
    assert keyboard_to_hangul("qkzkfk") == "바카라"
    assert keyboard_to_hangul("dkssudgktpdy") == "안녕하세요"
    assert keyboard_to_hangul("rhkswkd") == "관장"
    assert normalize("ｃａｓｉｎо​")[0] == "casino"


@pytest.mark.parametrize("text", [
    "바나나", "카페라떼", "토마토", "나대야 한다", "이번 주까지 노력하겠습니다", "가지 노을",
    "The quick brown fox jumps over the lazy dog", "Please contact us for more information",
    "Release Notes", "dkssudgktpdy", "웹 접근성인증", "놀이터 안전", "내구재 소비 증가",
    "민원 서비스 바로가기", "ㅋㅋㅋㅋ 좋아요", "행정안전부 유튜브 새창으로 열기",
])
def test_normal_text_has_no_variant(text):
    assert [h for h in analyze(text) if h.variant] == []


def _crawl(*records):
    page = {"url": START, "final_url": START, "elements": list(records)}
    return {"meta": {"start_url": START, "config": {"include_subdomains": True}}, "pages": [page]}


def _rec(type_, content, **extra):
    rec = {"type": type_, "content": content, "selector": "#c > div", "frame_path": [], "frame_url": START}
    rec.update(extra)
    return rec


@pytest.mark.parametrize("rec,level", [
    (_rec("hidden", "밖!콰라!! 바로가기", hidden_reasons=["display:none"], links=["http://ads.invalid/"]), HIGH),
    (_rec("link", "카징노 가입 텔레그램 @bet777", href="http://bet777.xyz/"), HIGH),
    (_rec("hidden", "qkzkfk사이트", hidden_reasons=["off-screen"], links=["http://ads.invalid/"]), HIGH),
    (_rec("text", "ㅂㅋㄹ 가입코드 010-1234-5678"), HIGH),
    (_rec("hidden", "카​지노 바로가기", hidden_reasons=["tiny-font"]), HIGH),
    (_rec("link", "casinо", href="http://casino-777.invalid/"), HIGH),
    (_rec("hidden", "ｃａｓｉｎｏ", hidden_reasons=["same-color-as-background"]), HIGH),
    (_rec("hidden", "카2노", hidden_reasons=["display:none"]), SUSPECT),
    (_rec("text", "ㅂㅋㄹ 가입코드"), SUSPECT),
])
def test_variant_ads_with_other_evidence(rec, level):
    result = detect(_crawl(rec))
    assert result["findings"], rec
    f = result["findings"][0]
    assert f["level"] == level
    assert any("변형 표기" in e["label"] for e in f["evidence"])


def test_evidence_shows_original_and_reading():
    f = Detector(_crawl()).score(_rec("hidden", "밖!콰라!!", hidden_reasons=["display:none"],
                                      links=["http://ads.invalid/"]))
    label = next(e["label"] for e in f["evidence"] if e["kind"] == "variant")
    assert "변형 표기: 밖!콰라 → 바카라 (발음 변형)" in label and "발음 변형" in label


@pytest.mark.parametrize("text", ["밖!콰라!!", "qkzkfk", "ㅂㅋㄹ", "카징노"])
def test_single_variant_alone_is_not_ad(text):
    assert Detector(_crawl()).score(_rec("text", text)) is None


def test_real_mois_data_still_has_no_findings():
    sample = json.loads((FIXTURES / "mois_sample.json").read_text(encoding="utf-8"))
    assert detect(sample)["findings"] == []


@pytest.mark.parametrize("text,word,method", [
    ("ⓒⓐⓢⓘⓝⓞ", "casino", "enclosed"),
    ("ⓑⓐⓒⓒⓐⓡⓐⓣ", "baccarat", "enclosed"),
    ("㉳㉸㉱ 추천", "바카라", "enclosed"),
    ("⒞⒜⒮⒤⒩⒪", "casino", "enclosed"),
    ("🄲🄰🅂🄸🄽🄾", "casino", "enclosed"),
    ("🅒🅐🅢🅘🅝🅞", "casino", "enclosed"),
    ("🅲🅰🆂🅸🅽🅾", "casino", "enclosed"),
    ("🅟🅞🅡🅝", "porn", "enclosed"),
    ("𝐜𝐚𝐬𝐢𝐧𝐨", "casino", "styled"),
    ("𝓬𝓪𝓼𝓲𝓷𝓸", "casino", "styled"),
    ("𝕔𝕒𝕤𝕚𝕟𝕠", "casino", "styled"),
    ("ᶜᵃˢⁱⁿᵒ", "casino", "styled"),
    ("ᴄᴀꜱɪɴᴏ", "casino", "styled"),
    ("cⓐ𝐬ino", "casino", "enclosed"),
    ("c𝐚sino", "casino", "styled"),
])
def test_enclosed_and_styled_letters_keep_full_weight(text, word, method):
    hits = {h.keyword.word: h for h in analyze(text)}
    assert word in hits, [(h.keyword.word, h.method) for h in analyze(text)]
    hit = hits[word]
    assert hit.method == method and hit.original == text.split()[0]
    assert hit.weight == hit.keyword.weight


@pytest.mark.parametrize("disguised,plain", [
    ("ⓒⓐⓢⓘⓝⓞ 바로가기 텔레그램 @win777", "casino 바로가기 텔레그램 @win777"),
    ("🅲🅰🆂🅸🅽🅾 바로가기", "casino 바로가기"),
    ("㉳㉸㉱ 가입코드 777", "바카라 가입코드 777"),
])
def test_enclosed_scores_same_as_plain_text(disguised, plain):
    detector = Detector(_crawl())
    f = detector.score(_rec("link", disguised, href="http://win777.invalid/"))
    g = detector.score(_rec("link", plain, href="http://win777.invalid/"))
    assert (f["score"], f["level"]) == (g["score"], g["level"])
    label = next(e["label"] for e in f["evidence"] if e["kind"] == "variant")
    assert f"변형 표기: {disguised.split()[0]} → " in label and "감싼 문자" in label


def test_circled_chosung_is_read_as_chosung():
    hits = {h.keyword.word: h for h in analyze("㉥㉪㉣ 가입")}
    assert hits["바카라"].method == "chosung"


@pytest.mark.parametrize("text", [
    "① 신청서 작성 ② 서류 제출 ③ 심사 결과 안내",
    "⑴ 대상 ⑵ 기간 ⒜ 신청 방법 ⒝ 제출 서류",
    "Copyright ⓒ 2024 행정안전부. All rights reserved.",
    "ⓒ 한국지능정보사회진흥원 ㈜한국정보통신 ㈔한국웹접근성협회",
    "❶ 공지 ➋ 안내 ⓫ 기타 🄰 등급 🅐 구역",
    "ᴴᴰ 화질 영상 m² km³ H₂O",
])
def test_normal_enclosed_characters_are_not_ads(text):
    assert analyze(text) == []
    assert detect(_crawl(_rec("text", text), _rec("link", text, href="https://www.korea.kr/")))["findings"] == []


@pytest.mark.parametrize("text,word,original", [
    ("çâśîñö 바로가기", "casino", "çâśîñö"),
    ("ƥóŕñ", "porn", "ƥóŕñ"),
    ("pørn", "porn", "pørn"),
    ("ćàšíñø", "casino", "ćàšíñø"),
    ("bàççàràt", "baccarat", "bàççàràt"),
    ("vïágrà", "viagra", "vïágrà"),
    ("cásino", "casino", "cásino"),
])
def test_accented_letters_keep_full_weight(text, word, original):
    hits = {h.keyword.word: h for h in analyze(text)}
    assert word in hits, [(h.keyword.word, h.method) for h in analyze(text)]
    hit = hits[word]
    assert (hit.method, hit.original, hit.weight) == ("accent", original, hit.keyword.weight)


def test_accent_letters_are_stripped_for_reading():
    assert normalize("ĥéĺĺö")[0] == "hello"
    assert normalize("ø đ ł ı ƥ")[0] == "o d l i p"


def test_accent_evidence_label_and_score():
    detector = Detector(_crawl())
    f = detector.score(_rec("link", "çâśîñö 바로가기", href="http://win777.invalid/"))
    g = detector.score(_rec("link", "casino 바로가기", href="http://win777.invalid/"))
    assert (f["score"], f["level"]) == (g["score"], g["level"])
    label = next(e["label"] for e in f["evidence"] if e["kind"] == "variant")
    assert "변형 표기: çâśîñö → casino (악센트 문자)" in label


@pytest.mark.parametrize("text", [
    "café résumé naïve façade déjà vu",
    "Zürich São Paulo Ångström Łódź Øresund İstanbul Dvořák",
    "Tôi yêu Việt Nam. Đà Nẵng và Hà Nội",
    "El niño comió jalapeños en la montaña",
])
def test_normal_accented_words_are_not_ads(text):
    assert analyze(text) == []
    assert detect(_crawl(_rec("text", text)))["findings"] == []


@pytest.mark.parametrize("text", ["바카라", "한글은 자모로 쪼개지지 않습니다", "ㄱㄴㄷ ㅏㅑㅓ", "㉳㉸㉱"])
def test_hangul_is_not_decomposed(text):
    norm = normalize(text)[0]
    assert all(not ("ᄀ" <= c <= "ᇿ") for c in norm)
    if text != "㉳㉸㉱":
        assert norm == text
