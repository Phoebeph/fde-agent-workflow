from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings


REQUIRED_DEEPSEEK = ["DEEPSEEK_API_KEY"]
REQUIRED_FEISHU = [
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "FEISHU_APP_TOKEN",
    "FEISHU_TABLE_ID",
]


def main() -> None:
    values = {
        "DEEPSEEK_API_KEY": settings.deepseek_api_key,
        "DEEPSEEK_BASE_URL": settings.deepseek_base_url,
        "DEEPSEEK_MODEL": settings.deepseek_model,
        "FEISHU_APP_ID": settings.feishu_app_id,
        "FEISHU_APP_SECRET": settings.feishu_app_secret,
        "FEISHU_APP_TOKEN": settings.feishu_app_token,
        "FEISHU_TABLE_ID": settings.feishu_table_id,
        "FEISHU_UPLOAD_PARENT_NODE": settings.feishu_upload_parent_node,
        "FEISHU_MOCK_MODE": str(settings.feishu_mock_mode),
        "WHATSAPP_GROUP_NAME": settings.whatsapp_group_name,
        "DISPATCH_MANAGER_SENDERS": ",".join(settings.dispatch_manager_senders),
        "FOLLOWUP_MANAGER_SENDERS": ",".join(settings.followup_manager_senders),
    }
    for key, value in values.items():
        print(f"{key}={_redact(value)}")

    missing_deepseek = [key for key in REQUIRED_DEEPSEEK if not values[key]]
    missing_feishu = [key for key in REQUIRED_FEISHU if not values[key]]
    print(f"deepseek_enabled={not missing_deepseek}")
    print(f"feishu_enabled={not missing_feishu}")
    print(f"feishu_sync_available={settings.feishu_sync_available}")
    if missing_deepseek:
        print(f"missing_deepseek={','.join(missing_deepseek)}")
    if missing_feishu:
        print(f"missing_feishu={','.join(missing_feishu)}")


def _redact(value: str) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 8:
        return "<set>"
    return f"{value[:3]}...{value[-3:]}"


if __name__ == "__main__":
    main()
