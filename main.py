#!/usr/bin/env python3

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import psutil
import requests


logging.basicConfig(level=logging.INFO, format="(%(asctime)s) %(message)s")
logger = logging.getLogger("vencord-auto-repair")

SCRIPT_VERSION = "0.2.0"
WINDOWS_INSTALLER_URL = "https://github.com/Vencord/Installer/releases/latest/download/VencordInstallerCli.exe"
LINUX_INSTALLER_URL = "https://github.com/Vencord/Installer/releases/latest/download/VencordInstallerCli-linux"
SETTINGS_FILENAME = "settings.json"
STATE_FILENAME = "state.json"
INSTALLER_FILENAME = "VencordInstallerCli.exe" if os.name == "nt" else "VencordInstallerCli-linux"

BRANCH_TO_FOLDER = {
    "stable": "Discord",
    "ptb": "DiscordPTB",
    "canary": "DiscordCanary",
}

BRANCH_TO_PROCESS = {
    "stable": "Discord.exe",
    "ptb": "DiscordPTB.exe",
    "canary": "DiscordCanary.exe",
}

LINUX_BRANCH_TO_COMMANDS = {
    "stable": ["discord", "Discord"],
    "ptb": ["discord-ptb", "discordptb", "DiscordPTB"],
    "canary": ["discord-canary", "discordcanary", "DiscordCanary"],
}

LINUX_BRANCH_TO_DIRS = {
    "stable": [
        "Discord",
        "discord",
        "com.discordapp.Discord",
    ],
    "ptb": [
        "DiscordPTB",
        "discordptb",
        "discord-ptb",
        "com.discordapp.DiscordPTB",
    ],
    "canary": [
        "DiscordCanary",
        "discordcanary",
        "discord-canary",
        "com.discordapp.DiscordCanary",
    ],
}

UPDATER_DONE_MESSAGES = (
    "Updater main thread exiting",
    "Already up to date. Nothing to do",
)


@dataclass
class DiscordInstall:
    branch: str
    root_path: Path
    executable_hint: Optional[Path] = None

    @property
    def process_name(self) -> str:
        if os.name == "nt":
            return BRANCH_TO_PROCESS[self.branch]
        return LINUX_BRANCH_TO_COMMANDS[self.branch][0]

    @property
    def updater_log_path(self) -> Path:
        appdata = Path(os.environ["APPDATA"])
        return appdata / self.process_name.removesuffix(".exe").lower() / "logs" / f"{self.process_name.removesuffix('.exe')}_updater_rCURRENT.log"

    @property
    def update_exe(self) -> Path:
        return self.root_path / "Update.exe"

    def latest_app_dir(self) -> Optional[Path]:
        if os.name != "nt":
            return None

        app_dirs = []
        for child in self.root_path.iterdir():
            if child.is_dir() and child.name.startswith("app-"):
                app_dirs.append(child)

        if not app_dirs:
            return None

        app_dirs.sort(key=lambda item: version_key(item.name.removeprefix("app-")))
        return app_dirs[-1]

    def latest_version(self) -> Optional[str]:
        if os.name != "nt":
            return self.install_signature()

        app_dir = self.latest_app_dir()
        return None if app_dir is None else app_dir.name

    def resources_dir(self) -> Optional[Path]:
        if os.name != "nt":
            resources = self.root_path / "resources"
            if resources.exists():
                return resources
            if (self.root_path / "app.asar").exists():
                return self.root_path
            return None

        app_dir = self.latest_app_dir()
        if app_dir is None:
            return None
        return app_dir / "resources"

    def app_asar_path(self) -> Optional[Path]:
        resources = self.resources_dir()
        if resources is None:
            return None
        path = resources / "app.asar"
        return path if path.exists() else None

    def backup_asar_path(self) -> Optional[Path]:
        resources = self.resources_dir()
        if resources is None:
            return None
        for candidate in ("_app.asar", "_app.asar.unpacked"):
            path = resources / candidate
            if path.exists():
                return path
        return None

    def is_vencord_patched(self) -> bool:
        return self.app_asar_path() is not None and self.backup_asar_path() is not None

    def has_plain_app_asar(self) -> bool:
        return self.app_asar_path() is not None and self.backup_asar_path() is None

    def install_signature(self) -> Optional[str]:
        app_asar = self.app_asar_path()
        if app_asar is None:
            return None
        stat = app_asar.stat()
        return f"{app_asar}:{stat.st_size}:{int(stat.st_mtime)}"


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def settings_path() -> Path:
    return base_dir() / SETTINGS_FILENAME


def state_path() -> Path:
    return base_dir() / STATE_FILENAME


def installer_path() -> Path:
    return base_dir() / INSTALLER_FILENAME


def version_key(version: str) -> tuple[int, ...]:
    parts = version.split(".")
    parsed = []
    for part in parts:
        digits = "".join(ch for ch in part if ch.isdigit())
        parsed.append(int(digits or "0"))
    return tuple(parsed)


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default.copy()

    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return {**default, **data}


def save_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def default_settings() -> dict:
    return {
        "installer_path": str(installer_path()),
        "download_installer_if_missing": True,
        "restart_discord_after_repair": True,
        "restart_discord_after_install": True,
        "watched_branches": ["stable", "ptb", "canary"],
    }


def discover_installs() -> list[DiscordInstall]:
    if os.name == "nt":
        return discover_windows_installs()
    return discover_linux_installs()


def discover_windows_installs() -> list[DiscordInstall]:
    localappdata = Path(os.environ["LOCALAPPDATA"])
    installs = []

    for branch, folder_name in BRANCH_TO_FOLDER.items():
        root = localappdata / folder_name
        if root.exists():
            installs.append(DiscordInstall(branch=branch, root_path=root))

    return installs


def discover_linux_installs() -> list[DiscordInstall]:
    home = Path.home()
    search_roots = [
        Path("/usr/share"),
        Path("/usr/lib64"),
        Path("/opt"),
        home / ".local/share",
        home / ".dvm",
        Path("/var/lib/flatpak/app"),
        home / ".local/share/flatpak/app",
    ]

    installs = []
    seen = set()
    for branch, dir_names in LINUX_BRANCH_TO_DIRS.items():
        for root in search_roots:
            for dir_name in dir_names:
                candidate = root / dir_name
                resolved = resolve_linux_discord_root(candidate)
                if resolved is None:
                    continue

                key = str(resolved)
                if key in seen:
                    continue
                seen.add(key)
                installs.append(
                    DiscordInstall(
                        branch=branch,
                        root_path=resolved,
                        executable_hint=find_linux_executable(branch, resolved),
                    )
                )
    return installs


def resolve_linux_discord_root(candidate: Path) -> Optional[Path]:
    if not candidate.exists():
        return None

    flatpak_prefix = "com.discordapp."
    if candidate.name.startswith(flatpak_prefix) and "current" not in candidate.parts:
        suffix = candidate.name[len(flatpak_prefix):]
        mapped = {
            "Discord": "discord",
            "DiscordPTB": "discord-ptb",
            "DiscordCanary": "discord-canary",
        }.get(suffix, suffix.lower())
        candidate = candidate / "current" / "active" / "files" / mapped

    resources = candidate / "resources"
    if resources.exists() or (candidate / "app.asar").exists():
        return candidate
    return None


def find_linux_executable(branch: str, root_path: Path) -> Optional[Path]:
    candidates = [
        root_path / "Discord",
        root_path / "discord",
        root_path.parent / "bin" / LINUX_BRANCH_TO_COMMANDS[branch][0],
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def get_processes_by_name(process_name: str) -> list[psutil.Process]:
    matches = []
    for proc in psutil.process_iter(["name", "exe", "cmdline"]):
        try:
            if proc.info["name"] == process_name:
                matches.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return matches


def get_processes_for_install(install: DiscordInstall) -> list[psutil.Process]:
    if os.name == "nt":
        return get_processes_by_name(install.process_name)

    names = set(LINUX_BRANCH_TO_COMMANDS[install.branch])
    matches = []
    for proc in psutil.process_iter(["name", "exe", "cmdline"]):
        try:
            name = proc.info.get("name") or ""
            exe = Path(proc.info.get("exe") or "").name
            cmdline = " ".join(proc.info.get("cmdline") or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        if name in names or exe in names or any(token in cmdline for token in names):
            matches.append(proc)
    return matches


def is_running(install: DiscordInstall) -> bool:
    return bool(get_processes_for_install(install))


def is_update_exe_running(install: DiscordInstall) -> bool:
    if os.name != "nt":
        return False

    update_exe = str(install.update_exe).lower()
    for proc in psutil.process_iter(["name", "exe", "cmdline"]):
        try:
            exe = (proc.info.get("exe") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        if exe == update_exe or update_exe in cmdline:
            return True
    return False


def clear_updater_log(log_path: Path) -> None:
    if os.name != "nt":
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")


def start_discord(install: DiscordInstall) -> None:
    if os.name == "nt":
        if not install.update_exe.exists():
            raise FileNotFoundError(f"Update.exe not found at {install.update_exe}")

        command = [str(install.update_exe), "--processStart", install.process_name]
        logger.info("Starting %s via Update.exe", install.branch)
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return

    executable = install.executable_hint
    if executable is None or not executable.exists():
        for candidate in LINUX_BRANCH_TO_COMMANDS[install.branch]:
            resolved = shutil.which(candidate)
            if resolved:
                executable = Path(resolved)
                break

    if executable is None:
        raise FileNotFoundError(f"Could not find a Discord executable for {install.branch}")

    logger.info("Starting %s via %s", install.branch, executable)
    subprocess.Popen([str(executable)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def kill_discord(install: DiscordInstall) -> None:
    for proc in get_processes_for_install(install):
        try:
            logger.info("Killing %s (PID %s)", proc.name(), proc.pid)
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    deadline = time.time() + 15
    while time.time() < deadline and is_running(install):
        time.sleep(0.25)


def updater_log_signals_done(log_path: Path) -> bool:
    if os.name != "nt":
        return True
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return False

    return any(message in content for message in UPDATER_DONE_MESSAGES)


def wait_for_update_completion(install: DiscordInstall, timeout_seconds: int = 120) -> None:
    logger.info("Waiting for Discord updater to settle for %s", install.branch)
    deadline = time.time() + timeout_seconds
    seen_update_activity = False
    last_version = install.latest_version()
    stable_checks = 0

    while time.time() < deadline:
        current_version = install.latest_version()
        if current_version != last_version:
            seen_update_activity = True
            last_version = current_version
            stable_checks = 0

        updater_running = is_update_exe_running(install)
        log_done = updater_log_signals_done(install.updater_log_path)

        if updater_running:
            seen_update_activity = True

        if not updater_running and (log_done or seen_update_activity):
            stable_checks += 1
            if stable_checks >= 4:
                return
        else:
            stable_checks = 0

        time.sleep(0.5)

    logger.warning("Timed out waiting for updater on %s; continuing anyway", install.branch)


def download_installer(target: Path) -> None:
    logger.info("Downloading official Vencord installer CLI")
    installer_url = WINDOWS_INSTALLER_URL if os.name == "nt" else LINUX_INSTALLER_URL
    response = requests.get(installer_url, timeout=60)
    response.raise_for_status()
    target.write_bytes(response.content)
    if os.name != "nt":
        target.chmod(0o755)


def ensure_installer(settings: dict) -> Path:
    configured = Path(settings["installer_path"]).expanduser()
    if configured.exists():
        return configured

    if not settings.get("download_installer_if_missing", True):
        raise FileNotFoundError(f"Vencord installer not found at {configured}")

    configured.parent.mkdir(parents=True, exist_ok=True)
    download_installer(configured)
    return configured


def run_vencord_repair(installer: Path, install: DiscordInstall) -> None:
    logger.info("Repairing Vencord for %s using official installer", install.branch)
    command = [
        str(installer),
        "--repair",
        "--location",
        str(install.root_path),
    ]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Vencord installer exited with code {result.returncode} for {install.branch}")


def run_vencord_install(installer: Path, install: DiscordInstall) -> None:
    logger.info("Installing Vencord for %s using official installer", install.branch)
    command = [
        str(installer),
        "--install",
        "--location",
        str(install.root_path),
    ]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Vencord installer exited with code {result.returncode} for {install.branch}")


def maybe_prepare_update(install: DiscordInstall) -> None:
    if is_update_exe_running(install):
        wait_for_update_completion(install)
    elif is_running(install):
        logger.info("%s is running without updater activity; leaving it alone until repair is needed", install.branch)
    else:
        logger.info("%s is not running and updater is idle; skipping forced launch", install.branch)


def load_state() -> dict:
    return load_json(
        state_path(),
        {
            "last_seen_versions": {},
            "last_action": {},
        },
    )


def process_install(install: DiscordInstall, settings: dict, state: dict, force: bool, dry_run: bool) -> bool:
    logger.info("")
    logger.info("Processing %s at %s", install.branch, install.root_path)

    maybe_prepare_update(install)

    current_version = install.latest_version()
    if current_version is None:
        logger.warning("No app-* directory found for %s", install.branch)
        return False

    last_seen_version = state["last_seen_versions"].get(install.branch)
    last_action = state["last_action"].get(install.branch)
    has_seen_branch_before = last_seen_version is not None or last_action is not None
    version_changed = current_version != last_seen_version
    vencord_patched = install.is_vencord_patched()
    patch_missing = not vencord_patched
    plain_discord = install.has_plain_app_asar()

    if last_action == "installed":
        desired_action = "repair"
    elif force:
        desired_action = "repair" if plain_discord else "install"
    elif not patch_missing:
        desired_action = None
    elif has_seen_branch_before and version_changed and plain_discord:
        desired_action = "repair"
    elif plain_discord:
        desired_action = "install"
    else:
        desired_action = "repair"

    logger.info("Current version: %s | Last seen: %s", current_version, last_seen_version)
    logger.info("Vencord patched: %s", "yes" if not patch_missing else "no")
    logger.info("Planned action: %s", desired_action or "none")

    if desired_action is None:
        logger.info("No action needed for %s", install.branch)
        return False

    if dry_run:
        logger.info("Dry run: would %s %s now", desired_action, install.branch)
        return False

    installer = ensure_installer(settings)
    kill_discord(install)

    if desired_action == "install":
        run_vencord_install(installer, install)
    else:
        run_vencord_repair(installer, install)

    if not install.is_vencord_patched():
        raise RuntimeError(f"{desired_action.title()} finished but Vencord does not appear patched for {install.branch}")

    state["last_seen_versions"][install.branch] = current_version
    state["last_action"][install.branch] = desired_action

    should_restart = (
        desired_action == "repair" and settings.get("restart_discord_after_repair", True)
    ) or (
        desired_action == "install" and settings.get("restart_discord_after_install", True)
    )

    if should_restart:
        start_discord(install)

    logger.info("%s completed for %s", desired_action.title(), install.branch)
    return True


def main() -> int:
    logger.info("VencordAutoRepair v%s", SCRIPT_VERSION)
    force = "--force" in sys.argv
    dry_run = "--dry-run" in sys.argv

    settings = load_json(settings_path(), default_settings())
    state = load_state()
    save_json(settings_path(), settings)
    save_json(state_path(), state)

    installs = discover_installs()
    watched = set(settings.get("watched_branches", []))
    installs = [install for install in installs if install.branch in watched]

    if not installs:
        logger.error("No Discord installs found in LOCALAPPDATA")
        return 1

    changed = False
    for install in installs:
        changed = process_install(install, settings, state, force, dry_run) or changed

    save_json(settings_path(), settings)
    save_json(state_path(), state)

    logger.info("")
    logger.info("Done%s", " with repairs applied" if changed else "; everything was already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
