from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.services.customer_config import load_customer_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate local backend and Yingdao deployment config")
    parser.add_argument("--mode", choices=("all", "backend", "yingdao"), default="all")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    env_path = ROOT / ".env"
    print(f"mode={args.mode}")
    print(f"env_file={env_path}")
    print(f"env_file_exists={env_path.exists()}")
    if not env_path.exists():
        warnings.append(".env file is missing")

    print(f"app_host={settings.app_host}")
    print(f"app_port={settings.app_port}")
    print(f"database_path={settings.database_path}")
    print(f"archive_root={settings.archive_root}")
    print(f"downloads_root={settings.downloads_root}")
    print(f"exports_root={settings.exports_root}")
    print(f"logs_root={settings.logs_root}")
    print(f"backups_root={settings.backups_root}")
    print(f"customer_settings_path={settings.customer_settings_path}")
    print(f"deepseek_enabled={bool(settings.deepseek_api_key)}")

    customer_settings = load_customer_settings(settings.customer_settings_path)
    print(f"customer_settings_loaded={customer_settings.loaded}")
    print(f"customer_settings_timezone={customer_settings.timezone}")
    print(f"customer_settings_groups={len(customer_settings.whatsapp.groups)}")
    print(f"customer_settings_sites={len(customer_settings.sites)}")
    if customer_settings.error:
        print(f"customer_settings_error={customer_settings.error}")
        errors.append(f"customer_settings invalid: {customer_settings.error}")
    if not settings.customer_settings_path.exists():
        errors.append(f"customer_settings.json not found: {settings.customer_settings_path}")

    for path in writable_targets():
        writable = ensure_writable(path)
        print(f"writable:{path}={writable}")
        if not writable:
            errors.append(f"path not writable: {path}")

    start_backend_script = ROOT / "scripts" / "start_backend.bat"
    run_yingdao_script = ROOT / "scripts" / "run_yingdao_poll.bat"
    print(f"start_backend_script={start_backend_script}")
    print(f"start_backend_script_exists={start_backend_script.exists()}")
    print(f"run_yingdao_script={run_yingdao_script}")
    print(f"run_yingdao_script_exists={run_yingdao_script.exists()}")
    if args.mode in {"all", "backend"} and not start_backend_script.exists():
        errors.append(f"missing script: {start_backend_script}")
    if args.mode in {"all", "yingdao"} and not run_yingdao_script.exists():
        errors.append(f"missing script: {run_yingdao_script}")

    python_candidates = [
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
        Path(sys.executable),
    ]
    python_path = next((path for path in python_candidates if path.exists()), None)
    print(f"python_runtime={python_path or '<missing>'}")
    if python_path is None:
        errors.append("python runtime not found for startup script")

    yingdao_entry_command = os.getenv("YINGDAO_ENTRY_COMMAND", "").strip()
    print(f"yingdao_entry_command={'<set>' if yingdao_entry_command else '<empty>'}")
    if args.mode in {"all", "yingdao"}:
        if not yingdao_entry_command:
            errors.append("YINGDAO_ENTRY_COMMAND is empty")
        else:
            executable = command_executable(yingdao_entry_command)
            print(f"yingdao_entry_executable={executable or '<unknown>'}")
            if executable and not executable.exists():
                errors.append(f"YINGDAO_ENTRY_COMMAND executable not found: {executable}")

    if warnings:
        print(f"warnings={len(warnings)}")
        for item in warnings:
            print(f"warning: {item}")
    if errors:
        print(f"errors={len(errors)}")
        for item in errors:
            print(f"error: {item}")
        raise SystemExit(1)

    print("ok=True")


def writable_targets() -> list[Path]:
    return [
        settings.database_path.parent,
        settings.archive_root,
        settings.downloads_root,
        settings.exports_root,
        settings.logs_root,
        settings.backups_root,
        settings.customer_settings_path.parent,
    ]


def ensure_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix="cfg_", suffix=".tmp", delete=True):
            return True
    except OSError:
        return False


def command_executable(command: str) -> Path | None:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError:
        return None
    if not parts:
        return None
    first = parts[0].strip().strip('"').strip("'")
    if not first:
        return None
    candidate = Path(first)
    if candidate.is_absolute():
        return candidate
    return ROOT / first if any(sep in first for sep in ("\\", "/")) else None


if __name__ == "__main__":
    main()
