"""결과를 JSON 파일로 저장하고 읽는다."""

import json
from datetime import datetime
from pathlib import Path

from ad_sentinel.paths import output_dir


def save_json(data: dict, path: str | Path | None = None, prefix: str = "crawl") -> Path:
    """data를 JSON으로 저장하고 저장된 경로를 돌려준다.

    path를 주지 않으면 output/crawl_20261001_153000.json 형식으로 저장한다.
    한글이 깨지지 않도록 ensure_ascii=False, 인코딩은 UTF-8.
    """
    if path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = output_dir() / f"{prefix}_{stamp}.json"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def load_json(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
