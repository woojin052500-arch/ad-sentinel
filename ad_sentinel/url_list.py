import csv
import io
import re
import zipfile
from pathlib import Path

from ad_sentinel.crawler.url_utils import normalize_url

ENCODINGS = ("utf-8-sig", "utf-16", "cp949")
BARE_DOMAIN = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}(/\S*)?$", re.IGNORECASE)


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def _to_url(cell: str) -> str:
    cell = (cell or "").strip().strip('"').strip()
    if not cell or cell.startswith("#"):
        return ""
    if not cell.lower().startswith(("http://", "https://")):
        if not BARE_DOMAIN.match(cell):
            return ""
        cell = "http://" + cell
    return normalize_url(cell)


def _first_column(text: str) -> list[str]:
    sample = text[:4096]
    delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
    return [row[0] for row in csv.reader(io.StringIO(text), delimiter=delimiter) if row]


def _from_zip(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith((".csv", ".txt"))]
        preferred = [n for n in names if "page" in n.lower() or "페이지" in n]
        for name in preferred + names:
            text = _decode(z.read(name))
            if "http" in text:
                return text
    return ""


def parse_url_text(text: str) -> list[str]:
    urls = []
    for cell in _first_column(text):
        url = _to_url(cell)
        if url and url not in urls:
            urls.append(url)
    return urls


def load_url_list(path: str | Path) -> list[str]:
    path = Path(path)
    if path.suffix.lower() == ".zip":
        text = _from_zip(path)
    else:
        text = _decode(path.read_bytes())
    return parse_url_text(text)
