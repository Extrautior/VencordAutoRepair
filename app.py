"""Lightweight VencordAutoRepair entry point with GUI and automation modes."""

from __future__ import annotations

import importlib.metadata
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import app_runtime

REPAIR_FLAGS = frozenset({"--run-once", "--startup", "--dry-run", "--force"})
CONTROL_FLAGS = frozenset(
    {"--enable-startup", "--disable-startup", "--refresh-startup", "--diagnostics"}
)
USAGE = (
    "Usage: app.py [--run-once] [--startup] [--dry-run] [--force]\n"
    "       app.py --enable-startup | --disable-startup | --refresh-startup\n"
    "       app.py --diagnostics"
)
_logger = logging.getLogger("vencord-auto-repair.app")


def _version() -> str:
    try:
        return importlib.metadata.version("VencordAutoRepair")
    except importlib.metadata.PackageNotFoundError:
        try:
            import main

            return str(main.SCRIPT_VERSION)
        except Exception:
            return "0.4.1"


def _emit(value: str, *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    if stream is None:
        return
    try:
        print(value, file=stream)
    except (AttributeError, OSError):
        pass


def sanitize_repair_args(arguments: Sequence[str]) -> list[str]:
    """Keep only flags understood by the repair engine, in their given order."""

    sanitized: list[str] = []
    for argument in arguments:
        if argument in REPAIR_FLAGS and argument not in sanitized:
            sanitized.append(argument)
    return sanitized


def _run_repair(arguments: Sequence[str]) -> int:
    sanitized = sanitize_repair_args(arguments)
    run_once = "--run-once" in sanitized
    app_runtime.configure_logging(console=not run_once and sys.stderr is not None)
    try:
        with app_runtime.process_lock():
            try:
                app_runtime.migrate_legacy()
            except Exception:
                _logger.exception("Legacy data migration failed; continuing")
            app_runtime.write_result(
                {
                    "status": "running",
                    "success": None,
                    "message": "Repair is running.",
                }
            )

            import main as repair_main

            previous_argv = sys.argv
            sys.argv = [str(Path(__file__).resolve()), *sanitized]
            try:
                result = repair_main.main()
                return_code = int(result) if result is not None else 0
            finally:
                sys.argv = previous_argv

            stored = app_runtime.read_result() or {}
            stored.update(
                {
                    "status": "success" if return_code == 0 else "failed",
                    "success": return_code == 0,
                    "returncode": return_code,
                }
            )
            stored["message"] = (
                "Repair completed successfully."
                if return_code == 0
                else "Repair finished with an error; see the log for details."
            )
            stored.pop("finished_at", None)
            app_runtime.write_result(stored)
            return return_code
    except app_runtime.ProcessLockBusy:
        _logger.info("Another repair is already running; duplicate run skipped")
        return 0
    except Exception as exc:
        _logger.exception("Repair entry point failed")
        app_runtime.write_result(
            {
                "status": "failed",
                "success": False,
                "returncode": 1,
                "message": f"{type(exc).__name__}: {exc}"[:2000],
            }
        )
        return 1


def _show_gui() -> int:
    try:
        with app_runtime.process_lock():
            app_runtime.migrate_legacy()
    except app_runtime.ProcessLockBusy:
        _logger.info("Repair lock busy; GUI startup migration deferred")
    except Exception:
        _logger.exception("Legacy data migration failed; GUI will continue")

    import gui

    result = gui.show_gui()
    return int(result) if result is not None else 0


def _startup_action(action: str) -> dict[str, Any]:
    import startup_manager

    if action == "enable":
        return startup_manager.add_to_startup()
    if action == "disable":
        return startup_manager.remove_from_startup()
    if action == "refresh":
        return startup_manager.refresh_startup()
    raise ValueError(f"unknown startup action: {action}")


def _diagnostics_payload() -> dict[str, Any]:
    try:
        import startup_manager

        startup = startup_manager.startup_status()
        startup_error = None
    except Exception as exc:
        startup = None
        startup_error = f"{type(exc).__name__}: {exc}"

    payload: dict[str, Any] = {
        "product": "VencordAutoRepair",
        "version": _version(),
        "schema_version": 1,
        "platform": sys.platform,
        "frozen": bool(getattr(sys, "frozen", False)),
        "data_dir": str(app_runtime.data_dir()),
        "settings_path": str(app_runtime.settings_path()),
        "state_path": str(app_runtime.state_path()),
        "log_path": str(app_runtime.log_path()),
        "result_path": str(app_runtime.result_path()),
        "startup": startup,
        "last_result": app_runtime.read_result(),
    }
    if startup_error is not None:
        payload["startup_error"] = startup_error
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    unknown = [argument for argument in arguments if argument not in REPAIR_FLAGS | CONTROL_FLAGS]
    controls = [argument for argument in arguments if argument in CONTROL_FLAGS]
    if unknown or len(controls) > 1:
        if unknown:
            _emit(f"Unknown option(s): {', '.join(unknown)}", error=True)
        _emit(USAGE, error=True)
        return 2
    if controls and any(argument in REPAIR_FLAGS for argument in arguments):
        _emit("Startup and diagnostics controls cannot be combined with a repair run.", error=True)
        _emit(USAGE, error=True)
        return 2

    if "--diagnostics" in controls:
        payload = _diagnostics_payload()
        app_runtime.atomic_write_json(app_runtime.diagnostics_path(), payload)
        _emit(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if controls:
        action = controls[0].removeprefix("--").removesuffix("-startup")
        try:
            result = _startup_action(action)
        except Exception as exc:
            result = {
                "success": False,
                "action": action,
                "error": f"{type(exc).__name__}: {exc}",
            }
            app_runtime.atomic_write_json(app_runtime.startup_result_path(), result)
            _emit(f"Startup update failed: {exc}", error=True)
            return 1
        app_runtime.atomic_write_json(app_runtime.startup_result_path(), result)
        _emit(json.dumps(result, sort_keys=True))
        return 0 if result.get("success", True) else 1

    if any(argument in REPAIR_FLAGS for argument in arguments):
        return _run_repair(arguments)

    app_runtime.configure_logging(console=sys.stderr is not None)
    return _show_gui()


if __name__ == "__main__":
    raise SystemExit(main())
