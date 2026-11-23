"""Prepare an Ubuntu 24.04 host; installation never starts the Telegram bot.

Run with Python 3.12 as root after copying the application to APP_DIR:
    python3 deployment/install.py --install
    python3 deployment/install.py --check

Transfer secrets and stopped, consistent session/database files separately.
No configuration values or subprocess output are printed by this installer.
"""

import argparse
import importlib.util
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tempfile


APP_DIR = Path("/opt/tashkent-rent-bot")
DATA_DIR = Path("/var/lib/tashkent-rent-bot")
CONFIG_DIR = Path("/etc/tashkent-rent-bot")
ENV_FILE = CONFIG_DIR / ".env"
UNIT_NAME = "tashkent-rent-bot.service"
UNIT_FILE = Path("/etc/systemd/system") / UNIT_NAME
UNIT_SOURCE = Path(__file__).with_name(UNIT_NAME)
PYTHON = APP_DIR / ".venv/bin/python"
ACCOUNT = "rentbot"


class InstallError(Exception):
    """Only messages authored in this module may be displayed."""


def require_host():
    if sys.platform != "linux":
        raise InstallError("Run this installer on the Ubuntu server, not on Windows or macOS.")
    if os.geteuid() != 0:
        raise InstallError("Run this installer as root on the Ubuntu server.")
    if sys.version_info[:2] != (3, 12):
        raise InstallError("Python 3.12 is required.")
    release = platform.freedesktop_os_release()
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "24.04":
        raise InstallError("This installer supports Ubuntu 24.04 only.")
    if not Path("/run/systemd/system").is_dir():
        raise InstallError("A running systemd system is required.")
    for executable in ("systemctl", "systemd-run", "systemd-analyze", "useradd"):
        if shutil.which(executable) is None:
            raise InstallError("A required Ubuntu system utility is unavailable.")
    if APP_DIR.is_symlink() or not (APP_DIR / "pyproject.toml").is_file():
        raise InstallError("Copy the application source to /opt/tashkent-rent-bot first.")
    if not UNIT_SOURCE.is_file():
        raise InstallError("The deployment service template is missing.")
    if (APP_DIR / ".env").exists() or (APP_DIR / ".env").is_symlink():
        raise InstallError("Keep .env outside the application: use /etc/tashkent-rent-bot/.env.")


def run_command(arguments, step, *, accepted=(0,)):
    # Neither command output nor exception text is safe to print: pip and HTTP
    # failures can contain credential-bearing URLs inherited from the host.
    try:
        result = subprocess.run([str(value) for value in arguments], cwd=APP_DIR,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                encoding="utf-8", errors="replace", check=False)
    except (OSError, ValueError):
        raise InstallError(f"Could not complete: {step}. Command output is hidden.") from None
    if result.returncode not in accepted:
        raise InstallError(f"Failed: {step} (exit {result.returncode}). Command output is hidden.")
    return result


def account_record(*, create=False):
    import grp
    import pwd

    try:
        record = pwd.getpwnam(ACCOUNT)
    except KeyError:
        if not create:
            raise InstallError("The rentbot system account has not been installed.") from None
        run_command(["useradd", "--system", "--user-group", "--no-create-home",
                     "--home-dir", DATA_DIR, "--shell", "/usr/sbin/nologin", ACCOUNT],
                    "create the rentbot system account")
        record = pwd.getpwnam(ACCOUNT)
    try:
        group = grp.getgrnam(ACCOUNT)
    except KeyError:
        raise InstallError("The rentbot system group is missing.") from None
    if not (0 < record.pw_uid < 1000 and record.pw_gid == group.gr_gid
            and record.pw_dir == str(DATA_DIR) and record.pw_shell == "/usr/sbin/nologin"):
        raise InstallError("Existing rentbot account does not match the dedicated service account.")
    return record


def private_paths(record):
    for directory in (CONFIG_DIR, DATA_DIR):
        if directory.is_symlink():
            raise InstallError("Configuration and data directories must not be symbolic links.")
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chown(CONFIG_DIR, 0, 0)
    CONFIG_DIR.chmod(0o700)
    if ENV_FILE.is_symlink():
        raise InstallError("The environment file must not be a symbolic link.")
    if ENV_FILE.exists():
        if not ENV_FILE.is_file():
            raise InstallError("The environment file must be a regular file.")
        os.chown(ENV_FILE, 0, 0)
        ENV_FILE.chmod(0o600)
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    paths = [DATA_DIR, *DATA_DIR.rglob("*")]
    if any(path.is_symlink() or not (path.is_file() or path.is_dir()) for path in paths):
        raise InstallError("Data may contain only regular files and directories, without symbolic links.")
    for path in paths:
        os.chown(path, record.pw_uid, record.pw_gid)
        path.chmod(0o700 if path.is_dir() else 0o600)


def write_unit():
    content = UNIT_SOURCE.read_text(encoding="utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=UNIT_FILE.parent, prefix=".rentbot-", delete=False) as target:
            temporary = Path(target.name)
            target.write(content)
        temporary.chmod(0o644)
        os.replace(temporary, UNIT_FILE)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def install():
    active = run_command(["systemctl", "is-active", UNIT_NAME], "check whether the bot is stopped",
                         accepted=(0, 3, 4))
    if active.stdout.strip() not in ("inactive", "failed", "unknown"):
        raise InstallError("Stop the existing bot service before installing or updating it.")
    record = account_record(create=True)
    private_paths(record)
    APP_DIR.chmod(0o755)
    if importlib.util.find_spec("venv") is None or importlib.util.find_spec("ensurepip") is None:
        run_command(["apt-get", "update"], "refresh Ubuntu package metadata")
        run_command(["apt-get", "install", "--yes", "python3.12-venv"], "install Python venv support")
    run_command([sys.executable, "-m", "venv", APP_DIR / ".venv"], "create the virtual environment")
    run_command([PYTHON, "-m", "pip", "install", "--disable-pip-version-check", APP_DIR],
                "install the application and dependencies")
    write_unit()
    run_command(["systemd-analyze", "verify", UNIT_FILE], "validate the systemd unit")
    run_command(["systemctl", "daemon-reload"], "reload systemd units")
    run_command(["systemctl", "enable", UNIT_NAME], "enable startup after reboot")
    print("Installed and enabled for reboot; the bot has NOT been started.")
    print("Transfer configuration and session/data, then run --check before starting the service.")


def require_private_path(path, uid, gid, mode, *, directory=False):
    if path.is_symlink() or not (path.is_dir() if directory else path.is_file()):
        raise InstallError("A required configuration/data path is missing or is not a regular path.")
    metadata = path.stat()
    if metadata.st_uid != uid or metadata.st_gid != gid or stat.S_IMODE(metadata.st_mode) != mode:
        raise InstallError("Configuration/data ownership or permissions are incorrect; rerun --install while stopped.")


def check():
    record = account_record()
    require_private_path(CONFIG_DIR, 0, 0, 0o700, directory=True)
    require_private_path(ENV_FILE, 0, 0, 0o600)
    require_private_path(DATA_DIR, record.pw_uid, record.pw_gid, 0o700, directory=True)
    require_private_path(DATA_DIR / "reader.session", record.pw_uid, record.pw_gid, 0o600)
    require_private_path(DATA_DIR / "rentbot.sqlite3", record.pw_uid, record.pw_gid, 0o600)
    catalogue = DATA_DIR / "locations.json"
    if catalogue.exists() or catalogue.is_symlink():
        require_private_path(catalogue, record.pw_uid, record.pw_gid, 0o600)
    if not PYTHON.is_file() or not UNIT_FILE.is_file():
        raise InstallError("Install the virtual environment and service before running --check.")
    if UNIT_FILE.read_text(encoding="utf-8") != UNIT_SOURCE.read_text(encoding="utf-8"):
        raise InstallError("The installed service differs from the deployment template; rerun --install while stopped.")
    run_command(["systemd-analyze", "verify", UNIT_FILE], "validate the systemd unit")
    run_command(["systemctl", "is-enabled", UNIT_NAME], "verify startup after reboot is enabled")
    # systemd loads the root-only EnvironmentFile before switching to rentbot.
    # This runs only local configuration/import checks, never the watcher.
    run_command([
        "systemd-run", "--quiet", "--wait", "--pipe", "--collect",
        "--property=User=rentbot", "--property=Group=rentbot",
        f"--property=WorkingDirectory={APP_DIR}", f"--property=EnvironmentFile={ENV_FILE}",
        "--", "/usr/bin/env", f"DATA_DIR={DATA_DIR}", f"LOCATIONS_FILE={DATA_DIR / 'locations.json'}",
        "PYTHONDONTWRITEBYTECODE=1", PYTHON, "-c",
        "import telethon, tzdata; from rentbot.__main__ import main; raise SystemExit(main(['check-config']))",
    ], "check configuration and Python dependencies as rentbot")
    print("Local configuration, permissions, Python dependencies and service definition passed.")
    print("Telegram authentication and live routing still require separate verification. The bot was not started.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--install", action="store_true", help="install and enable the service, without starting it")
    actions.add_argument("--check", action="store_true", help="check a staged installation without starting the bot (default)")
    args = parser.parse_args(argv)
    try:
        require_host()
        install() if args.install else check()
        return 0
    except InstallError as error:
        print(str(error), file=sys.stderr)
    except Exception as error:
        print(f"Installation/check failed ({type(error).__name__}); details hidden to protect secrets.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
