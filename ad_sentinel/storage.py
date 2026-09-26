import json
from datetime import datetime
from pathlib import Path

from ad_sentinel.paths import output_dir


def save_json(data: dict, path: str | Path | None = None, prefix: str = "crawl") -> Path:
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
