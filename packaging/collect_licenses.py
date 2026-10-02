import shutil
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = {"playwright": "playwright", "sv-ttk": "sv-ttk", "pyinstaller": "pyinstaller"}


def copy(src: Path, dest_dir: Path) -> None:
    if src.is_file():
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_dir / src.name)


def main(dist: str) -> None:
    out = Path(dist) / "licenses"
    if out.exists():
        shutil.rmtree(out)
    for package, folder in PACKAGES.items():
        try:
            dist_info = metadata.distribution(package)
        except metadata.PackageNotFoundError:
            continue
        for f in dist_info.files or []:
            if any(word in f.name.upper() for word in ("LICENSE", "COPYING", "NOTICE")):
                copy(Path(dist_info.locate_file(f)), out / folder)
    try:
        import playwright

        driver = Path(playwright.__file__).parent / "driver"
        copy(driver / "LICENSE", out / "playwright-driver-node")
        for name in ("LICENSE", "NOTICE", "ThirdPartyNotices.txt"):
            copy(driver / "package" / name, out / "playwright-driver")
    except ImportError:
        pass
    for name in ("LICENSE.txt", "LICENSE"):
        copy(Path(sys.base_prefix) / name, out / "python")
    copy(ROOT / "ad_sentinel" / "detector" / "data" / "LICENSE-UNICODE.txt", out / "unicode")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.txt", Path(dist) / "THIRD_PARTY_NOTICES.txt")
    print(f"licenses -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
