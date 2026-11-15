"""Collect redistribution licenses beside the packaged runtime."""
from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys

output = Path(sys.argv[1]) / "licenses"
output.mkdir(parents=True, exist_ok=True)
for name in ("psutil", "requests", "certifi", "charset-normalizer", "idna", "urllib3",
             "pywin32", "pyinstaller", "setuptools", "packaging"):
    package = distribution(name)
    for item in package.files or []:
        if any(word in item.name.lower() for word in ("license", "copying", "notice")):
            source = Path(package.locate_file(item))
            if source.is_file():
                target = output / name / str(item).replace("../", "").replace("..\\", "")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
base = Path(sys.base_prefix)
for relative in ("LICENSE.txt", "tcl/tcl8.6/license.terms", "tcl/tk8.6/license.terms"):
    source = base / relative
    if source.exists():
        target = output / "Python" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
