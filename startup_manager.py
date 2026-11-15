"""Per-user startup registration for Windows and Linux desktops."""

from __future__ import annotations

import contextlib
import logging
import os
import re
import subprocess
import sys
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

TASK_NAME_PREFIX = "VencordAutoRepair"
RUN_VALUE_NAME = "VencordAutoRepair"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
LEGACY_SHORTCUT_NAME = "VencordAutoRepair.lnk"
DESKTOP_FILENAME = "vencord-auto-repair.desktop"
TASK_CREATE_OR_UPDATE = 6
TASK_LOGON_INTERACTIVE_TOKEN = 3
TASK_NOT_FOUND_CODES = {0x80070002, 0x80070003, 0x8004130E}

_logger = logging.getLogger("vencord-auto-repair.startup")
_com_thread_state = threading.local()

__all__ = [
    "StartupRegistrationError",
    "add_to_startup",
    "is_enabled",
    "refresh_startup",
    "remove_from_startup",
    "startup_status",
    "task_name",
]


class StartupRegistrationError(RuntimeError):
    """Raised when neither startup backend could be registered."""


def _application_target() -> Path:
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().with_name("app.py")

    executable = Path(sys.executable).resolve()
    if executable.stem.lower() in {"startup_manager", "main"}:
        for candidate_name in ("app.exe", "main.exe"):
            candidate = executable.with_name(candidate_name)
            if candidate.is_file():
                return candidate
    return executable


def _pythonw_executable() -> Path:
    executable = Path(sys.executable).resolve()
    if os.name == "nt":
        candidate = executable.with_name("pythonw.exe")
        if candidate.is_file():
            return candidate
    return executable


def startup_command() -> tuple[list[str], Path]:
    """Return the normal one-shot command and its working directory."""

    target = _application_target()
    if getattr(sys, "frozen", False):
        command = [str(target), "--run-once", "--startup"]
    else:
        command = [
            str(_pythonw_executable()),
            str(target),
            "--run-once",
            "--startup",
        ]
    return command, target.parent


def _autostart_path() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "autostart" / DESKTOP_FILENAME


def legacy_shortcut_path() -> Path:
    startup_dir = (
        Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )
    return startup_dir / LEGACY_SHORTCUT_NAME


def shortcut_path() -> Path:
    """Compatibility helper for callers that need the currently platform-specific path."""

    return legacy_shortcut_path() if os.name == "nt" else _autostart_path()


@contextlib.contextmanager
def _scheduler_com() -> Iterator[Any]:
    import pythoncom
    import win32com.client

    if not getattr(_com_thread_state, "initialized", False):
        pythoncom.CoInitialize()
        _com_thread_state.initialized = True
    service = win32com.client.Dispatch("Schedule.Service")
    service.Connect()
    yield service.GetFolder("\\")


def _current_user_identifier() -> str:
    """Return the current user's SID, with a domain-qualified fallback."""

    try:
        import win32api
        import win32security

        token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32security.TOKEN_QUERY,
        )
        try:
            user, _attributes = win32security.GetTokenInformation(
                token,
                win32security.TokenUser,
            )
            return str(win32security.ConvertSidToStringSid(user))
        finally:
            token.Close()
    except Exception:
        domain = os.environ.get("USERDOMAIN", "")
        username = os.environ.get("USERNAME", "")
        if domain and username:
            return f"{domain}\\{username}"
        if username:
            return username
        raise RuntimeError("could not determine the current Windows user")


def task_name() -> str:
    """Return a scheduler name that is unique to the current user."""

    identifier = _current_user_identifier()
    safe_identifier = re.sub(r"[^A-Za-z0-9._-]+", "-", identifier).strip("-")
    if not safe_identifier:
        raise RuntimeError("could not build a per-user Task Scheduler name")
    return f"{TASK_NAME_PREFIX}-{safe_identifier}"


def _task_xml(
    command: Sequence[str],
    working_directory: Path,
    *,
    user_id: str | None = None,
    name: str | None = None,
) -> str:
    """Build the current-user, interactive, least-privilege scheduled task."""

    if not command:
        raise ValueError("startup command cannot be empty")
    user_id = user_id or _current_user_identifier()
    name = name or task_name()
    arguments = subprocess.list2cmdline(list(command[1:]))
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-16"?>',
            '<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">',
            "  <RegistrationInfo>",
            "    <Description>Automatically repairs Vencord after Discord updates.</Description>",
            f"    <URI>\\{escape(name)}</URI>",
            "  </RegistrationInfo>",
            "  <Triggers>",
            "    <LogonTrigger>",
            "      <Enabled>true</Enabled>",
            f"      <UserId>{escape(user_id)}</UserId>",
            "      <Delay>PT30S</Delay>",
            "    </LogonTrigger>",
            "  </Triggers>",
            "  <Principals>",
            '    <Principal id="Author">',
            f"      <UserId>{escape(user_id)}</UserId>",
            "      <LogonType>InteractiveToken</LogonType>",
            "      <RunLevel>LeastPrivilege</RunLevel>",
            "    </Principal>",
            "  </Principals>",
            "  <Settings>",
            "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>",
            "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>",
            "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>",
            "    <AllowHardTerminate>true</AllowHardTerminate>",
            "    <StartWhenAvailable>true</StartWhenAvailable>",
            "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>",
            "    <ExecutionTimeLimit>PT20M</ExecutionTimeLimit>",
            "    <AllowStartOnDemand>true</AllowStartOnDemand>",
            "    <Enabled>true</Enabled>",
            "  </Settings>",
            '  <Actions Context="Author">',
            "    <Exec>",
            f"      <Command>{escape(str(command[0]))}</Command>",
            f"      <Arguments>{escape(arguments)}</Arguments>",
            f"      <WorkingDirectory>{escape(str(working_directory))}</WorkingDirectory>",
            "    </Exec>",
            "  </Actions>",
            "</Task>",
            "",
        ]
    )


def _register_scheduled_task(name: str, xml: str) -> None:
    with _scheduler_com() as folder:
        folder.RegisterTask(
            name,
            xml,
            TASK_CREATE_OR_UPDATE,
            None,
            None,
            TASK_LOGON_INTERACTIVE_TOKEN,
            None,
        )


def _com_error_code(error: BaseException) -> int | None:
    value = getattr(error, "hresult", None)
    arguments = getattr(error, "args", ())
    if value is None and arguments:
        value = arguments[0]
    # COM dispatch failures use DISP_E_EXCEPTION; the actionable Task Scheduler
    # HRESULT is nested in EXCEPINFO.scode at args[2][5].
    if value in {-2147352567, 0x80020009} and len(arguments) > 2:
        exception_info = arguments[2]
        if isinstance(exception_info, tuple) and len(exception_info) > 5:
            nested = exception_info[5]
            if isinstance(nested, int):
                value = nested
    if isinstance(value, int):
        return value & 0xFFFFFFFF
    return None


def _scheduled_task_state() -> bool | None:
    try:
        with _scheduler_com() as folder:
            task = folder.GetTask(task_name())
            return bool(task.Enabled)
    except Exception as exc:
        if _com_error_code(exc) in TASK_NOT_FOUND_CODES:
            return False
        _logger.debug("Task Scheduler is unavailable: %s", exc)
        return None


def _delete_scheduled_task() -> bool:
    try:
        with _scheduler_com() as folder:
            folder.DeleteTask(task_name(), 0)
            return True
    except Exception as exc:
        if _com_error_code(exc) in TASK_NOT_FOUND_CODES:
            return False
        raise


def _register_run_entry(command: Sequence[str]) -> None:
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(
            key,
            RUN_VALUE_NAME,
            0,
            winreg.REG_SZ,
            subprocess.list2cmdline(list(command)),
        )


def _run_entry_present() -> bool | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE) as key:
            value, value_type = winreg.QueryValueEx(key, RUN_VALUE_NAME)
    except FileNotFoundError:
        return False
    except OSError:
        return None
    return value_type == winreg.REG_SZ and bool(str(value).strip())


def _delete_run_entry() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_VALUE_NAME)
            return True
    except FileNotFoundError:
        return False


def _legacy_shortcut_present() -> bool:
    return os.name == "nt" and legacy_shortcut_path().is_file()


def _remove_legacy_shortcut() -> bool:
    """Remove only the exact legacy shortcut after a new registration succeeded."""

    path = legacy_shortcut_path()
    if os.name != "nt" or not path.is_file():
        return False
    path.unlink()
    _logger.info("Removed legacy startup shortcut %s", path)
    return True


def _desktop_entry(command: Sequence[str], working_directory: Path) -> str:
    def quote(argument: str) -> str:
        # Desktop Entry Exec quoting uses double quotes, not shell quoting.
        escaped = argument.replace("\\", "\\\\").replace('"', '\\"')
        escaped = escaped.replace("`", "\\`").replace("$", "\\$")
        escaped = escaped.replace("%", "%%")
        return f'"{escaped}"'

    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Version=1.0",
            "Name=VencordAutoRepair",
            "Comment=Automatically repairs Vencord after Discord updates",
            f"Exec={' '.join(quote(str(argument)) for argument in command)}",
            f"Path={working_directory}",
            "Terminal=false",
            "X-GNOME-Autostart-enabled=true",
            "",
        ]
    )


def _desktop_enabled(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for line in content.splitlines():
        if line.strip().lower() == "x-gnome-autostart-enabled=false":
            return False
    return True


def startup_status() -> dict[str, Any]:
    """Return a JSON-safe snapshot of registrations without changing them."""

    if os.name != "nt":
        path = _autostart_path()
        enabled = _desktop_enabled(path)
        return {
            "enabled": enabled,
            "backend": "desktop" if enabled else "none",
            "path": str(path),
        }

    task_state = _scheduled_task_state()
    run_state = _run_entry_present()
    legacy_state = _legacy_shortcut_present()
    try:
        scheduler_name: str | None = task_name()
    except Exception:
        scheduler_name = None
    if task_state:
        backend = "task_scheduler"
    elif run_state:
        backend = "registry"
    elif legacy_state:
        backend = "legacy_shortcut"
    else:
        backend = "none"
    return {
        "enabled": backend != "none",
        "backend": backend,
        "task_name": scheduler_name,
        "task_scheduler": task_state,
        "registry": run_state,
        "legacy_shortcut": legacy_state,
    }


def is_enabled() -> bool:
    return bool(startup_status()["enabled"])


def add_to_startup() -> dict[str, Any]:
    """Register startup with Task Scheduler, falling back to HKCU Run.

    The command is always the non-elevated, one-shot ``app --run-once --startup``
    entry. Existing legacy registrations are removed only after this succeeds.
    """

    command, working_directory = startup_command()
    if os.name != "nt":
        path = _autostart_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_desktop_entry(command, working_directory), encoding="utf-8")
        path.chmod(0o644)
        return {
            "success": True,
            "enabled": True,
            "backend": "desktop",
            "path": str(path),
            "command": command,
        }

    if _legacy_shortcut_present():
        # The old shortcut may point at a different installation folder. Copy its
        # valid settings/state into this installation's runtime data before the
        # successful registration below permits deletion of the shortcut.
        try:
            import app_runtime

            app_runtime.migrate_legacy()
        except Exception as exc:
            _logger.warning("Could not inspect data beside the legacy shortcut: %s", exc)

    scheduler_error: Exception | None = None
    name: str | None = None
    backend: str
    try:
        user_id = _current_user_identifier()
        name = task_name()
        _register_scheduled_task(
            name,
            _task_xml(command, working_directory, user_id=user_id, name=name),
        )
        backend = "task_scheduler"
    except Exception as exc:
        scheduler_error = exc
        _logger.warning("Task Scheduler registration was rejected: %s", exc)
        try:
            _register_run_entry(command)
        except Exception as fallback_error:
            raise StartupRegistrationError(
                "startup registration failed in Task Scheduler and HKCU Run: "
                f"{exc}; {fallback_error}"
            ) from fallback_error
        backend = "registry"

    cleanup_warnings: list[str] = []
    if backend == "task_scheduler":
        try:
            _delete_run_entry()
        except Exception as exc:
            cleanup_warnings.append(f"could not remove previous HKCU Run entry: {exc}")
    try:
        legacy_removed = _remove_legacy_shortcut()
    except OSError as exc:
        legacy_removed = False
        cleanup_warnings.append(f"could not remove legacy shortcut: {exc}")

    result: dict[str, Any] = {
        "success": True,
        "enabled": True,
        "backend": backend,
        "task_name": name,
        "run_value": RUN_VALUE_NAME if backend == "registry" else None,
        "legacy_removed": legacy_removed,
        "command": command,
    }
    if scheduler_error is not None:
        result["scheduler_error"] = str(scheduler_error)
    if cleanup_warnings:
        result["warnings"] = cleanup_warnings
    return result


def refresh_startup() -> dict[str, Any]:
    """Re-register only when startup was already enabled.

    A legacy shortcut counts as enabled, so installer refreshes migrate it to
    the current backend while disabled installations remain untouched.
    """

    status = startup_status()
    if not status["enabled"]:
        return {"success": True, "enabled": False, "refreshed": False, "backend": "none"}
    result = add_to_startup()
    result["refreshed"] = True
    result["previous_backend"] = status["backend"]
    return result


def remove_from_startup() -> dict[str, Any]:
    """Remove all current and legacy registrations for this user."""

    if os.name != "nt":
        path = _autostart_path()
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return {"success": True, "enabled": False, "backend": "none", "path": str(path)}

    errors: list[str] = []
    try:
        _delete_scheduled_task()
    except Exception as exc:
        errors.append(f"Task Scheduler: {exc}")
    try:
        _delete_run_entry()
    except Exception as exc:
        errors.append(f"HKCU Run: {exc}")
    try:
        _remove_legacy_shortcut()
    except OSError as exc:
        errors.append(f"legacy shortcut: {exc}")
    result: dict[str, Any] = {
        "success": not errors,
        "enabled": is_enabled(),
        "backend": "none" if not errors else "partial",
        "task_name": task_name(),
    }
    if errors:
        result["errors"] = errors
    return result


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
            result = add_to_startup()
            print(result)
            continue
        if choice == "2":
            result = remove_from_startup()
            print(result)
            continue

        print("Invalid option.")


if __name__ == "__main__":
    raise SystemExit(main())
