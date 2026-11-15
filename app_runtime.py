"""Shared paths, persistence, logging, and process locking for VencordAutoRepair."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import shlex
import sys
import tempfile
import threading
import time
from collections.abc import Iterable, Iterator, Mapping
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

APP_DIR_NAME = "VencordAutoRepair"
LOG_FILENAME = "VencordAutoRepair.log"
RESULT_FILENAME = "last-result.json"
LOCK_FILENAME = "VencordAutoRepair.lock"
SETTINGS_FILENAME = "settings.json"
STATE_FILENAME = "state.json"
DIAGNOSTICS_FILENAME = "diagnostics.json"
STARTUP_RESULT_FILENAME = "startup-result.json"
OFFICIAL_INSTALLER_NAMES = frozenset(
    {"VencordInstallerCli.exe", "VencordInstallerCli-linux"}
)
LEGACY_SHORTCUT_NAME = "VencordAutoRepair.lnk"

_LOG_FORMAT = "(%(asctime)s) %(levelname)s %(message)s"
_LOG_MAX_BYTES = 2 * 1024 * 1024
_LOG_BACKUPS = 3
_logger = logging.getLogger("vencord-auto-repair.runtime")
_com_thread_state = threading.local()

__all__ = [
    "ProcessLockBusy",
    "atomic_write_json",
    "configure_logging",
    "data_dir",
    "diagnostics_path",
    "log_path",
    "migrate_legacy",
    "process_lock",
    "read_result",
    "result_path",
    "settings_path",
    "startup_result_path",
    "state_path",
    "write_result",
]


class ProcessLockBusy(TimeoutError):
    """Raised when another process for this user already owns the repair lock."""


def data_dir(
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Return the per-user writable data directory for this platform."""

    platform_name = platform_name or sys.platform
    environ = environ if environ is not None else os.environ
    if platform_name.startswith("win"):
        base = environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_DIR_NAME
        home = environ.get("USERPROFILE") or str(Path.home())
        return Path(home) / "AppData" / "Local" / APP_DIR_NAME

    base = environ.get("XDG_DATA_HOME")
    if not base:
        home = environ.get("HOME") or str(Path.home())
        base = str(Path(home) / ".local" / "share")
    return Path(base) / APP_DIR_NAME


def settings_path() -> Path:
    return data_dir() / SETTINGS_FILENAME


def state_path() -> Path:
    return data_dir() / STATE_FILENAME


def log_path() -> Path:
    return data_dir() / LOG_FILENAME


def result_path() -> Path:
    return data_dir() / RESULT_FILENAME


def lock_path() -> Path:
    return data_dir() / LOCK_FILENAME


def diagnostics_path() -> Path:
    return data_dir() / DIAGNOSTICS_FILENAME


def startup_result_path() -> Path:
    return data_dir() / STARTUP_RESULT_FILENAME


def atomic_write_json(path: Path | str, data: Any) -> None:
    """Write JSON through a same-directory temporary file and atomic replace."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        data,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    ) + "\n"

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _fsync_directory(directory: Path) -> None:
    """Best-effort directory sync; Windows does not permit opening directories this way."""

    if os.name == "nt":
        return
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def configure_logging(
    level: int = logging.INFO,
    *,
    console: bool | None = None,
) -> Path:
    """Install the rotating application log and return its path.

    ``console`` is intentionally opt-in. In particular, ``--run-once`` can call
    this before importing ``main`` with ``console=False`` without creating a
    console handler.
    """

    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)

    for handler in list(root.handlers):
        if getattr(handler, "_vencord_runtime_handler", False):
            root.removeHandler(handler)
            handler.close()

    file_handler = RotatingFileHandler(
        path,
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUPS,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    file_handler._vencord_runtime_handler = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)

    if console is True:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        stream_handler._vencord_runtime_handler = True  # type: ignore[attr-defined]
        root.addHandler(stream_handler)
    return path


def _legacy_directories() -> list[Path]:
    directories: list[Path] = []
    if getattr(sys, "frozen", False):
        directories.append(Path(sys.executable).resolve().parent)
    directories.append(Path(__file__).resolve().parent)
    directories.extend(_shortcut_application_dirs())

    unique: list[Path] = []
    for directory in directories:
        if directory not in unique:
            unique.append(directory)
    return unique


def _legacy_shortcut_path() -> Path:
    startup = (
        Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )
    return startup / LEGACY_SHORTCUT_NAME


def _shortcut_application_dirs() -> list[Path]:
    """Discover an old application folder from the exact legacy shortcut."""

    shortcut = _legacy_shortcut_path()
    if os.name != "nt" or not shortcut.is_file():
        return []
    try:
        import pythoncom
        import win32com.client

        if not getattr(_com_thread_state, "initialized", False):
            pythoncom.CoInitialize()
            _com_thread_state.initialized = True
        link = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(shortcut))
        candidates = [str(getattr(link, "TargetPath", "") or "")]
        try:
            candidates.extend(shlex.split(str(link.Arguments or ""), posix=False))
        except ValueError:
            pass
    except Exception as exc:
        _logger.debug("Could not inspect legacy startup shortcut: %s", exc)
        return []

    directories: list[Path] = []
    for candidate in candidates:
        candidate = candidate.strip().strip('"')
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            continue
        directory = path.parent.resolve()
        if directory not in directories and any(
            (directory / filename).is_file()
            for filename in (SETTINGS_FILENAME, STATE_FILENAME)
        ):
            directories.append(directory)
    return directories


def migrate_legacy(
    legacy_dirs: Iterable[Path | str] | None = None,
    *,
    destination: Path | str | None = None,
) -> list[Path]:
    """Copy valid legacy settings/state without overwriting newer runtime files.

    Legacy files remain in place. Only JSON objects named ``settings.json`` and
    ``state.json`` are considered, and only when the destination does not already
    contain that file.
    """

    target_dir = Path(destination) if destination is not None else data_dir()
    sources = list(legacy_dirs) if legacy_dirs is not None else _legacy_directories()
    migrated: list[Path] = []

    for source_dir in sources:
        source_dir = Path(source_dir).resolve()
        if source_dir == target_dir.resolve():
            continue
        for filename in (SETTINGS_FILENAME, STATE_FILENAME):
            source = source_dir / filename
            destination_file = target_dir / filename
            if destination_file.exists() or not source.is_file():
                continue
            try:
                with source.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if not isinstance(data, dict):
                    raise ValueError("legacy JSON is not an object")
                if filename == SETTINGS_FILENAME:
                    installer = data.get("installer_path")
                    if isinstance(installer, str):
                        installer_path = Path(installer).expanduser()
                        if (
                            installer_path.is_absolute()
                            and installer_path.name in OFFICIAL_INSTALLER_NAMES
                            and installer_path.parent.resolve() == source_dir
                        ):
                            data = dict(data)
                            data["installer_path"] = str(
                                target_dir / "downloads" / installer_path.name
                            )
                atomic_write_json(destination_file, data)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                _logger.warning("Could not migrate %s: %s", source, exc)
                continue
            migrated.append(destination_file)
            _logger.info("Migrated legacy %s to %s", source, destination_file)
    return migrated


def write_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Atomically write a JSON-safe result and return the stored payload."""

    payload = dict(result)
    payload.setdefault("schema_version", 1)
    payload.setdefault("finished_at", datetime.now(UTC).isoformat())
    atomic_write_json(result_path(), payload)
    return payload


def read_result() -> dict[str, Any] | None:
    """Read the last result, returning ``None`` when it is absent or invalid."""

    path = result_path()
    try:
        with path.open("r", encoding="utf-8") as handle:
            result = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _logger.warning("Could not read last result from %s: %s", path, exc)
        return None
    return result if isinstance(result, dict) else None


def _windows_user_sid() -> str | None:
    import ctypes
    from ctypes import wintypes

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("sid", wintypes.LPVOID), ("attributes", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    )
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = (
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPWSTR),
    )
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel32.LocalFree.restype = wintypes.HLOCAL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        0x0008,  # TOKEN_QUERY
        ctypes.byref(token),
    ):
        return None
    sid_string = wintypes.LPWSTR()
    try:
        needed = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
        if not needed.value:
            return None
        buffer = ctypes.create_string_buffer(needed.value)
        if not advapi32.GetTokenInformation(
            token,
            1,  # TokenUser
            buffer,
            needed.value,
            ctypes.byref(needed),
        ):
            return None
        user = ctypes.cast(buffer, ctypes.POINTER(SidAndAttributes)).contents
        if not advapi32.ConvertSidToStringSidW(user.sid, ctypes.byref(sid_string)):
            return None
        return sid_string.value
    finally:
        if sid_string:
            kernel32.LocalFree(sid_string)
        kernel32.CloseHandle(token)


def _windows_mutex_name() -> str:
    identity = _windows_user_sid() or "\\".join(
        (
            os.environ.get("USERDOMAIN", ""),
            os.environ.get("USERNAME", ""),
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()[:24]
    return rf"Global\VencordAutoRepair-{digest}"


@contextlib.contextmanager
def _windows_lock(timeout: float) -> Iterator[None]:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateMutexW(None, False, _windows_mutex_name())
    if not handle:
        raise OSError(ctypes.get_last_error(), "CreateMutexW failed")
    try:
        wait_milliseconds = min(0xFFFFFFFE, max(0, int(timeout * 1000)))
        wait_result = kernel32.WaitForSingleObject(handle, wait_milliseconds)
        if wait_result not in (0x00000000, 0x00000080):
            if wait_result == 0x00000102:
                raise ProcessLockBusy("another VencordAutoRepair process is running")
            raise OSError(ctypes.get_last_error(), "WaitForSingleObject failed")
        try:
            yield
        finally:
            kernel32.ReleaseMutex(handle)
    finally:
        kernel32.CloseHandle(handle)


@contextlib.contextmanager
def _linux_lock(timeout: float) -> Iterator[None]:
    import fcntl

    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProcessLockBusy("another VencordAutoRepair process is running")
                time.sleep(min(0.1, remaining))
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


@contextlib.contextmanager
def process_lock(timeout: float = 0.0) -> Iterator[None]:
    """Hold the per-user, cross-process application lock.

    Windows uses a user-SID named ``Global`` mutex; Linux uses an advisory
    ``flock`` in the XDG data directory. A second process receives
    :class:`ProcessLockBusy` when the timeout expires.
    """

    if timeout < 0:
        raise ValueError("lock timeout must be non-negative")
    lock = _windows_lock if os.name == "nt" else _linux_lock
    with lock(float(timeout)):
        yield
