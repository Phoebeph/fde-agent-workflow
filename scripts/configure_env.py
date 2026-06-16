from __future__ import annotations

from getpass import getpass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
EXAMPLE_PATH = ROOT / ".env.example"

SECRET_KEYS = {
    "DEEPSEEK_API_KEY",
    "FEISHU_APP_SECRET",
}

PROMPTS = {
    "DEEPSEEK_API_KEY": "DeepSeek API key",
    "FEISHU_APP_ID": "Feishu App ID",
    "FEISHU_APP_SECRET": "Feishu App Secret",
    "FEISHU_APP_TOKEN": "Feishu Bitable App Token",
    "FEISHU_TABLE_ID": "Feishu Bitable Table ID",
    "FEISHU_UPLOAD_PARENT_NODE": "Feishu upload parent node token",
    "FEISHU_MOCK_MODE": "Use mock Feishu sink (true/false)",
    "WHATSAPP_GROUP_NAME": "WhatsApp group name",
    "DISPATCH_MANAGER_SENDERS": "Dispatch manager senders, comma-separated",
    "FOLLOWUP_MANAGER_SENDERS": "Follow-up manager senders, comma-separated",
}


def main() -> None:
    if not EXAMPLE_PATH.exists():
        raise SystemExit(".env.example not found")

    values = _load_env(EXAMPLE_PATH)
    if ENV_PATH.exists():
        values.update(_load_env(ENV_PATH))

    print("Press Enter to keep the current value. Secret values are not echoed.")
    for key, label in PROMPTS.items():
        current = values.get(key, "")
        shown = "<set>" if current and key in SECRET_KEYS else current
        prompt = f"{label} [{shown}]: "
        if key in SECRET_KEYS:
            entered = getpass(prompt)
        else:
            entered = input(prompt)
        if entered.strip():
            values[key] = entered.strip()

    _write_env(values)
    print(f"updated {ENV_PATH}")


def _load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def _write_env(values: dict[str, str]) -> None:
    keys = [line.split("=", 1)[0] for line in EXAMPLE_PATH.read_text().splitlines() if "=" in line]
    lines = [f"{key}={values.get(key, '')}" for key in keys]
    ENV_PATH.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nconfiguration cancelled")
