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
    ("casinо 777", "casino", "normalize", "casinо"),
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
    assert "변형 표기: 밖!콰라 → 바카라" in label and "발음 변형" in label


@pytest.mark.parametrize("text", ["밖!콰라!!", "qkzkfk", "ㅂㅋㄹ", "카징노"])
def test_single_variant_alone_is_not_ad(text):
    assert Detector(_crawl()).score(_rec("text", text)) is None


def test_real_mois_data_still_has_no_findings():
    sample = json.loads((FIXTURES / "mois_sample.json").read_text(encoding="utf-8"))
    assert detect(sample)["findings"] == []
