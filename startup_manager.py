import os
import sys
from pathlib import Path

import winshell


SHORTCUT_NAME = "VencordAutoRepair.lnk"


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def shortcut_path() -> Path:
    startup_dir = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return startup_dir / SHORTCUT_NAME


def add_to_startup() -> None:
    link_path = shortcut_path()

    if getattr(sys, "frozen", False):
        target = base_dir() / "main.exe"
        arguments = ""
        working_directory = str(base_dir())
    else:
        target = Path(sys.executable).resolve()
        arguments = str(base_dir() / "main.py")
        working_directory = str(base_dir())

    with winshell.shortcut(str(link_path)) as link:
        link.path = str(target)
        link.arguments = arguments
        link.working_directory = working_directory
        link.description = "Automatically repairs Vencord after Discord updates"

    print(f"Added startup shortcut at {link_path}")


def remove_from_startup() -> None:
    link_path = shortcut_path()
    if link_path.exists():
        link_path.unlink()
        print(f"Removed startup shortcut from {link_path}")
    else:
        print("Startup shortcut does not exist.")


def main() -> int:
    while True:
        print()
        print("[0] Exit")
        print("[1] Add to startup")
        print("[2] Remove from startup")
        choice = input("> ").strip()
        print()

        if choice == "0":
            return 0
        if choice == "1":
            add_to_startup()
            continue
        if choice == "2":
            remove_from_startup()
            continue

        print("Invalid option.")


if __name__ == "__main__":
    raise SystemExit(main())
