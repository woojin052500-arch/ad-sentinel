import csv
import html
import json
from pathlib import Path
from urllib.parse import unquote, unquote_plus

CSV_COLUMNS = [
    ("번호", lambda f: f["id"]),
    ("판정", lambda f: f["level_label"]),
    ("유형", lambda f: f["pattern_label"]),
    ("분류", lambda f: f["category"]),
    ("점수", lambda f: f["score"]),
    ("내용", lambda f: f["content"]),
    ("게시글 제목", lambda f: f.get("post_title", "")),
    ("발견 페이지 수", lambda f: f["page_count"]),
    ("페이지 주소", lambda f: "\n".join(f["pages"])),
    ("위치(선택자)", lambda f: location_text(f)),
    ("숨김 이유", lambda f: ", ".join(f.get("hidden_reasons", []))),
    ("반사된 파라미터", lambda f: reflected_text(f)),
    ("링크·iframe 주소", lambda f: "\n".join(f.get("urls", []))),
    ("근거", lambda f: "\n".join(f"{e['label']} (+{e['points']})" for e in f["evidence"])),
    ("조치 안내", lambda f: f.get("advice", "")),
]


def display_url(url: str) -> str:
    base, sep, query = url.partition("?")
    return unquote(base, errors="replace") + sep + unquote_plus(query, errors="replace")


def location_text(finding: dict) -> str:
    parts = list(finding.get("frame_path", [])) + [finding.get("selector", "")]
    return " ▶ ".join(p for p in parts if p)


def reflected_text(finding: dict) -> str:
    return ", ".join(f"{p['name']}={p['value']}" for p in finding.get("reflected_params", []))


def unchecked_text(item: dict) -> str:
    where = item["url"] or "(주소 알 수 없음)"
    if item.get("frame_path"):
        where += f" (위치: {' ▶ '.join(item['frame_path'])})"
    trusted = " · 신뢰 도메인" if item.get("trusted_domain") else ""
    return f"[{item['kind_label']}] {where}{trusted} - {item['reason']}"


def stats_lines(report: dict) -> list[str]:
    st = report.get("stats", {})
    lines = [f"점검한 페이지: {st.get('pages', 0)}개"
             + (f" (열지 못한 페이지 {st['page_errors']}개)" if st.get("page_errors") else ""),
             f"점검한 iframe: {st.get('iframes', 0)}개",
             f"검사한 요소: {st.get('elements_scanned', 0):,}개",
             f"점검하지 못한 영역: {st.get('unchecked', 0)}곳"]
    if st.get("duration_sec") is not None:
        minutes, seconds = divmod(st["duration_sec"], 60)
        lines.append(f"소요 시간: {minutes}분 {seconds}초" if minutes else f"소요 시간: {seconds}초")
    if st.get("stopped_by_user"):
        lines.append("사용자가 중간에 중지함")
    meta = report.get("meta", {})
    if meta.get("gate"):
        lines.append(f"입장 버튼 클릭: '{meta['gate']['text']}'")
    if (meta.get("sitemap") or {}).get("urls"):
        lines.append(f"sitemap.xml에서 찾은 주소: {meta['sitemap']['urls']}개")
    return lines


def export_json(report: dict, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def export_csv(report: dict, path: str | Path) -> Path:
    path = Path(path)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([name for name, _ in CSV_COLUMNS])
        for finding in report["findings"]:
            writer.writerow([get(finding) for _, get in CSV_COLUMNS])
    return path


HTML_STYLE = """
body { font-family: "Malgun Gothic", "맑은 고딕", sans-serif; margin: 24px; color: #222; }
h1 { font-size: 22px; margin-bottom: 4px; }
.meta { color: #555; font-size: 13px; margin-bottom: 16px; }
.summary { display: flex; gap: 12px; margin: 16px 0; flex-wrap: wrap; }
.summary div { border: 1px solid #ddd; border-radius: 6px; padding: 10px 16px; min-width: 110px; }
.summary b { display: block; font-size: 22px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { border: 1px solid #ddd; padding: 6px 8px; vertical-align: top; text-align: left; }
th { background: #f3f4f6; }
td:nth-child(1), td:nth-child(2) { white-space: nowrap; }
tr.high td:first-child { background: #fde2e1; font-weight: bold; }
tr.suspect td:first-child { background: #fff1d6; font-weight: bold; }
.small { color: #555; font-size: 12px; word-break: break-all; }
ul { margin: 0; padding-left: 18px; }
"""


def export_html(report: dict, path: str | Path) -> Path:
    e = html.escape
    meta, summary = report["meta"], report["summary"]
    if meta.get("mode") == "list":
        mode, target = "URL 목록 점검", f"목록 주소 {meta.get('seed_count', 0)}개"
    else:
        mode, target = "사이트 점검", display_url(meta.get("start_url", ""))
    rows = []
    for f in report["findings"]:
        pages = "".join(f'<li><a href="{e(u)}">{e(display_url(u))}</a></li>' for u in f["pages"][:20])
        if len(f["pages"]) > 20:
            pages += f"<li>외 {len(f['pages']) - 20}개</li>"
        evidence = "".join(f"<li>{e(ev['label'])} (+{ev['points']})</li>" for ev in f["evidence"])
        extra = []
        if f.get("post_title"):
            extra.append(f"게시글: {e(f['post_title'])}")
        if f.get("hidden_reasons"):
            extra.append(f"숨김 이유: {e(', '.join(f['hidden_reasons']))}")
        if f.get("reflected_params"):
            extra.append(f"반사된 파라미터: {e(reflected_text(f))}")
        if f.get("urls"):
            extra.append("연결 주소: " + e(", ".join(f["urls"][:5])))
        rows.append(f"""
<tr class="{e(f['level'])}">
  <td>{e(f['level_label'])}</td>
  <td>{e(f['pattern_label'])}<br><span class="small">{e(f['category'])} · {f['score']}점</span></td>
  <td>{e(f['content'][:300])}<div class="small">{'<br>'.join(extra)}</div></td>
  <td>{f['page_count']}개<ul class="small">{pages}</ul>
      <div class="small">위치: {e(location_text(f))}</div></td>
  <td><ul class="small">{evidence}</ul></td>
  <td class="small">{e(f.get('advice', ''))}</td>
</tr>""")
    unknown = [d["host"] for d in report.get("external_domains", []) if not d["whitelisted"]]
    body = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><title>불법광고 점검 보고서</title><style>{HTML_STYLE}</style></head>
<body>
<h1>공공 웹사이트 불법광고 점검 보고서</h1>
<div class="meta">점검 방식: {mode} · 대상: {e(target)} · 점검 페이지 {meta.get('page_count', 0)}개 ·
점검 일시: {e(str(meta.get('detected_at', '')))} · AD Sentinel {e(str(meta.get('version', '')))}</div>
{''.join(f'<p style="background:#fff4e5;padding:8px 12px;border-radius:6px">{e(n)}</p>' for n in meta.get('notes') or [])}
<div class="summary">
  <div>전체 발견<b>{summary['findings']}건</b></div>
  <div>불법광고 의심<b>{summary['high']}건</b></div>
  <div>검토 필요<b>{summary['suspect']}건</b></div>
  {''.join(f'<div>{e(k)}<b>{v}건</b></div>' for k, v in summary.get('by_pattern', {}).items())}
</div>
<table>
<tr><th>판정</th><th>유형</th><th>내용</th><th>발견 페이지</th><th>근거</th><th>조치 안내</th></tr>
{''.join(rows) if rows else '<tr><td colspan="6">발견된 불법광고가 없습니다.</td></tr>'}
</table>
<h2 style="font-size:16px;margin-top:24px">점검 요약</h2>
<ul class="small">{''.join(f'<li>{e(line)}</li>' for line in stats_lines(report))}</ul>
<h2 style="font-size:16px;margin-top:24px">점검하지 못한 영역 ({len(report.get('unchecked', []))}곳)</h2>
<p class="small">숨겨진 iframe은 불법광고의 주요 수법입니다. 아래 영역은 직접 열어 확인하세요.</p>
<ul class="small">{''.join(f'<li>{e(unchecked_text(u))}<br>발견 페이지: {e(", ".join(display_url(p) for p in u["pages"][:5]))}</li>' for u in report.get('unchecked', [])) or '<li>없음</li>'}</ul>
<h2 style="font-size:16px;margin-top:24px">신뢰 목록에 없는 외부 도메인 ({len(unknown)}개)</h2>
<p class="small">{e(', '.join(unknown)) if unknown else '없음'}</p>
</body></html>
"""
    path = Path(path)
    path.write_text(body, encoding="utf-8")
    return path
