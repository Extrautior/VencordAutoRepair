"""Create a deterministic ZIP archive for the PyInstaller onedir build."""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path


FIXED_TIMESTAMP = (2026, 11, 15, 0, 0, 0)


def _entry(source: Path, root: Path) -> zipfile.ZipInfo:
    relative = source.relative_to(root.parent).as_posix()
    is_directory = source.is_dir()
    if is_directory:
        relative += "/"
    info = zipfile.ZipInfo(relative, FIXED_TIMESTAMP)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED if not is_directory else zipfile.ZIP_STORED
    if is_directory:
        info.external_attr = (0o40755 << 16) | 0x10
    else:
        mode = 0o100755 if source.suffix.lower() == ".exe" else 0o100644
        info.external_attr = mode << 16
    return info


def build_archive(source_root: Path, destination: Path) -> None:
    if not source_root.is_dir():
        raise SystemExit(f"Portable source directory does not exist: {source_root}")
    if source_root.name != "VencordAutoRepair":
        raise SystemExit(f"Unexpected portable source directory: {source_root.name}")

    entries = [source_root, *source_root.rglob("*")]
    entries.sort(key=lambda item: item.relative_to(source_root.parent).as_posix().lower())
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True,
        ) as archive:
            for path in entries:
                info = _entry(path, source_root)
                if path.is_dir():
                    archive.writestr(info, b"")
                    continue
                with path.open("rb") as source, archive.open(info, "w") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: package_portable.py SOURCE_DIR DESTINATION_ZIP", file=sys.stderr)
        return 2
    build_archive(Path(argv[1]).resolve(), Path(argv[2]).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

