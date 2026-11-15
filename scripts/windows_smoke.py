#!/usr/bin/env python3
"""Safe compiled-app smoke checks for Windows.

Default checks are network-free: PE metadata, portable/installed staging,
diagnostics, no-Discord results, and duplicate-process locking. GUI coverage is
separate. ``--real-repair`` opts into the official installer against a temporary
DiscordCanary fixture after confirming DiscordCanary.exe is not running.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse

import pefile
import psutil
import requests

ROOT = Path(__file__).resolve().parents[1]
INSTALLER_URL = "https://github.com/Vencord/Installer/releases/latest/download/VencordInstallerCli.exe"
CANARY = "DiscordCanary.exe"
MAX_INSTALLER_BYTES = 30 * 1024 * 1024
AS_INVOKER = re.compile(r"<requestedExecutionLevel\b[^>]*\blevel\s*=\s*['\"]asInvoker['\"]", re.I | re.S)
class SmokeFailure(RuntimeError):
    pass
@dataclass(frozen=True)
class Fixture:
    base: Path
    local: Path
    roaming: Path
    env: dict[str, str]

    @property
    def data(self) -> Path: return self.local / "VencordAutoRepair"
    @property
    def result(self) -> Path: return self.data / "last-result.json"
    @property
    def log(self) -> Path: return self.data / "VencordAutoRepair.log"
def require(condition: bool, message: str) -> None:
    if not condition: raise SmokeFailure(message)
def equal(actual: Any, expected: Any, label: str) -> None:
    require(actual == expected, f"{label}: expected {expected!r}, got {actual!r}")
def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SmokeFailure(f"Could not read {path}: {exc}") from exc
    require(isinstance(value, dict), f"Expected a JSON object in {path}")
    return value
def same_path(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))

def make_fixture(root: Path, name: str) -> Fixture:
    base = root / name
    local, roaming, temp, profile = base / "local", base / "roaming", base / "temp", base / "profile"
    [path.mkdir(parents=True, exist_ok=True) for path in (local, roaming, temp, profile)]
    env = os.environ.copy()
    env.update(LOCALAPPDATA=str(local), APPDATA=str(roaming), TEMP=str(temp), TMP=str(temp),
               USERPROFILE=str(profile), VENCORD_USER_DATA_DIR=str(roaming / "Vencord"))
    env.pop("DISCORD_USER_DATA_DIR", None)
    return Fixture(base, local, roaming, env)

def run_app(exe: Path, args: Sequence[str], fx: Fixture, timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run([str(exe), *args], cwd=exe.parent, env=fx.env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout,
                              creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    except subprocess.TimeoutExpired as exc:
        raise SmokeFailure(f"Timed out: {exe.name} {' '.join(args)}") from exc

def start_app(exe: Path, args: Sequence[str], fx: Fixture) -> subprocess.Popen[bytes]:
    return subprocess.Popen([str(exe), *args], cwd=exe.parent, env=fx.env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW)

def stop_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None: return
    try: children = psutil.Process(process.pid).children(recursive=True)
    except psutil.Error: children = []
    for child in reversed(children):
        child.terminate()
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    for child in children:
        try:
            child.kill()
        except psutil.Error:
            pass

def wait_status(path: Path, status: str, process: subprocess.Popen[bytes], timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            try:
                if read_json(path).get("status") == status:
                    return
            except SmokeFailure:
                pass
        require(process.poll() is None, f"Process exited before result status {status!r}")
        time.sleep(0.05)
    raise SmokeFailure(f"Timed out waiting for result status {status!r}")

def assert_no_canary() -> None:
    pids = [p.info["pid"] for p in psutil.process_iter(["pid", "name"])
            if (p.info.get("name") or "").casefold() == CANARY.casefold()]
    require(not pids, f"Refusing real repair: {CANARY} is running (PIDs {pids})")

def manifest_texts(image: pefile.PE) -> list[str]:
    texts: list[str] = []
    try:
        entries = image.DIRECTORY_ENTRY_RESOURCE.entries
    except AttributeError:
        return texts
    for type_entry in entries:
        if getattr(type_entry, "id", None) != 24:  # RT_MANIFEST
            continue
        for name_entry in type_entry.directory.entries:
            for language in name_entry.directory.entries:
                data = language.data.struct
                blob = image.get_memory_mapped_image()[data.OffsetToData:data.OffsetToData + data.Size]
                for encoding in ("utf-8-sig", "utf-16-le"):
                    text = blob.decode(encoding, errors="ignore")
                    if "requestedExecutionLevel" in text:
                        texts.append(text)
                        break
    return texts

def check_pe(path: Path) -> None:
    image = pefile.PE(str(path), fast_load=False)
    try:
        equal(image.OPTIONAL_HEADER.Subsystem, 2, f"{path.name} PE subsystem")
        manifests = manifest_texts(image)
    finally:
        image.close()
    external = Path(str(path) + ".manifest")
    if external.is_file(): manifests.append(external.read_text(encoding="utf-8-sig", errors="replace"))
    require(manifests, f"No requestedExecutionLevel manifest in {path}")
    text = "\n".join(manifests)
    require(bool(AS_INVOKER.search(text)), f"{path.name} does not request asInvoker")
    require("requireAdministrator" not in text, f"{path.name} requests elevation")

def stage(source: Path, destination: Path) -> Path:
    shutil.copytree(source.parent, destination)
    return destination / source.name

def exercise_layout(source: Path, root: Path, name: str, timeout: float) -> Path:
    fx = make_fixture(root, name)
    exe = stage(source, fx.base / "app")
    check_pe(exe)
    diagnostic = run_app(exe, ["--diagnostics"], fx, timeout)
    equal(diagnostic.returncode, 0, "diagnostics exit")
    payload = read_json(fx.data / "diagnostics.json")
    equal(payload.get("frozen"), True, "diagnostics frozen")
    require(same_path(payload.get("data_dir", ""), fx.data), "diagnostics escaped LOCALAPPDATA")
    run = run_app(exe, ["--run-once", "--dry-run"], fx, timeout)
    equal(run.returncode, 1, f"{name} no-Discord exit")
    result = read_json(fx.result)
    equal(result.get("status"), "failed", "no-Discord status")
    equal(result.get("returncode"), 1, "no-Discord returncode")
    require((fx.data / "settings.json").is_file(), "settings.json missing")
    require((fx.data / "state.json").is_file(), "state.json missing")
    return exe

def check_lock(exe: Path, root: Path, timeout: float) -> None:
    fx = make_fixture(root, "duplicate")
    args = ["--run-once", "--startup", "--dry-run"]
    holder = start_app(exe, args, fx)
    try:
        wait_status(fx.result, "running", holder)
        duplicate = run_app(exe, args, fx, min(timeout, 15))
        equal(duplicate.returncode, 0, "duplicate exit")
        log = fx.log.read_text(encoding="utf-8", errors="replace") if fx.log.exists() else ""
        require(read_json(fx.result).get("status") == "already-running"
                or "duplicate run skipped" in log.casefold(),
                "duplicate process did not report lock contention")
        require(holder.poll() is None, "holder exited during duplicate check")
    finally:
        stop_tree(holder)
    probe = run_app(exe, ["--run-once", "--dry-run"], fx, timeout)
    equal(probe.returncode, 1, "post-termination probe exit")
    require(read_json(fx.result).get("status") != "already-running", "lock was not released")

def download_installer(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".download")
    try:
        with requests.get(INSTALLER_URL, stream=True, timeout=(15, 60),
                          headers={"User-Agent": "VencordAutoRepair-Windows-Smoke/1"}) as response:
            response.raise_for_status()
            host = (urlparse(response.url).hostname or "").casefold()
            require(host == "github.com" or host.endswith(".github.com")
                    or host.endswith(".githubusercontent.com"),
                    f"Installer final host is not GitHub: {host}")
            size = 0
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(64 * 1024):
                    size += len(chunk)
                    require(size <= MAX_INSTALLER_BYTES, "Installer download too large")
                    handle.write(chunk)
        require(size > 0 and temporary.read_bytes()[:2] == b"MZ", "Installer download invalid"); temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
def check_real_repair(exe: Path, root: Path, installer_timeout: float) -> None:
    fx = make_fixture(root, "real-repair")
    installer = fx.data / "downloads" / "VencordInstallerCli.exe"
    download_installer(installer)
    discord_root = fx.local / "DiscordCanary"
    resources = discord_root / "app-1.0.0" / "resources"
    resources.mkdir(parents=True)
    app_asar, backup = resources / "app.asar", resources / "_app.asar"
    original = b"windows-smoke original app.asar\n"
    app_asar.write_bytes(original)
    settings = {"installer_path": str(installer), "download_installer_if_missing": False}
    settings.update(repair_noise_toggle_bridge=False, restart_discord_after_noise_toggle_bridge=False,
                    restart_discord_after_repair=False, restart_discord_after_install=False, watched_branches=["canary"])
    (fx.data / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    assert_no_canary()
    equal(run_app(exe, ["--run-once"], fx, installer_timeout).returncode, 0, "install exit")
    equal(read_json(fx.result).get("status"), "success", "install status")
    equal(backup.read_bytes(), original, "original backup"); require(b"patcher.js" in app_asar.read_bytes(), "patched app.asar missing patcher")
    require((fx.roaming / "Vencord" / "dist" / "patcher.js").is_file(), "patcher missing")
    previous_app, previous_backup, previous_patch = app_asar, backup, app_asar.read_bytes()
    resources = discord_root / "app-1.0.1" / "resources"; resources.mkdir(parents=True)
    app_asar, backup = resources / "app.asar", resources / "_app.asar"
    app_asar.write_bytes(original)
    assert_no_canary()
    equal(run_app(exe, ["--run-once"], fx, installer_timeout).returncode, 0, "repair exit")
    equal(backup.read_bytes(), original, "repair backup")
    require(b"patcher.js" in app_asar.read_bytes(), "repair did not patch app.asar")
    equal(previous_backup.read_bytes(), original, "previous backup preserved")
    equal(previous_app.read_bytes(), previous_patch, "previous patch preserved")
    equal(read_json(fx.data / "state.json")["last_action"]["canary"], "repair", "last action")
def find_exe() -> Path:
    preferred = ROOT / "dist" / "VencordAutoRepair" / "VencordAutoRepair.exe"
    if preferred.is_file():
        return preferred
    found = list((ROOT / "dist").rglob("VencordAutoRepair.exe")) if (ROOT / "dist").is_dir() else []
    require(len(found) == 1, "Pass --exe; compiled VencordAutoRepair.exe not uniquely found")
    return found[0]

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, help="compiled distribution executable")
    parser.add_argument("--real-repair", action="store_true", help="official Canary fixture")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--installer-timeout", type=float, default=420)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)
    if os.name != "nt":
        print("FAIL: Windows required", file=sys.stderr)
        return 2
    root, failed = None, False
    try:
        source = (args.exe or find_exe()).resolve()
        check_pe(source)
        print("PASS PE GUI subsystem and asInvoker manifest"); root = Path(tempfile.mkdtemp(prefix="vencord-windows-smoke-"))
        portable = exercise_layout(source, root, "portable", args.timeout)
        print("PASS portable diagnostics and no-Discord result")
        exercise_layout(source, root, "installed", args.timeout)
        print("PASS installed diagnostics and no-Discord result")
        check_lock(portable, root, args.timeout)
        print("PASS duplicate exits cleanly and releases lock")
        if args.real_repair:
            check_real_repair(portable, root, args.installer_timeout)
            print("PASS official install, update simulation, repair")
        else:
            print("SKIP official installer (use --real-repair after review)")
        print("SKIP GUI (verify separately)")
    except SmokeFailure as exc:
        failed = True
        print(f"FAIL: {exc}", file=sys.stderr)
    except Exception:
        failed = True
        traceback.print_exc()
    finally:
        if root is not None:
            if args.keep or failed:
                print(f"Fixture kept at {root}")
            else:
                shutil.rmtree(root, ignore_errors=True)
    return 1 if failed else 0

if __name__ == "__main__":
    raise SystemExit(main())
