from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings


REQUIRED_DEEPSEEK = ["DEEPSEEK_API_KEY"]
def main() -> None:
    values = {
        "DEEPSEEK_API_KEY": settings.deepseek_api_key,
        "DEEPSEEK_BASE_URL": settings.deepseek_base_url,
        "DEEPSEEK_MODEL": settings.deepseek_model,
        "DATA_ROOT": str(settings.data_root),
        "DATABASE_PATH": str(settings.database_path),
        "ARCHIVE_ROOT": str(settings.archive_root),
        "DOWNLOADS_ROOT": str(settings.downloads_root),
        "EXPORTS_ROOT": str(settings.exports_root),
        "AUTO_ANALYZE_ON_INGEST": str(settings.auto_analyze_on_ingest),
        "AUTO_EXPORT_ON_INGEST": str(settings.auto_export_on_ingest),
        "AUTO_SYNC_FEISHU_ON_INGEST": str(settings.auto_sync_feishu_on_ingest),
        "WHATSAPP_GROUP_NAME": settings.whatsapp_group_name,
        "DISPATCH_MANAGER_SENDERS": ",".join(settings.dispatch_manager_senders),
        "FOLLOWUP_MANAGER_SENDERS": ",".join(settings.followup_manager_senders),
    }
    for key, value in values.items():
        print(f"{key}={_redact(value)}")

    missing_deepseek = [key for key in REQUIRED_DEEPSEEK if not values[key]]
    print(f"deepseek_enabled={not missing_deepseek}")
    print(f"local_storage_enabled=True")
    print(f"feishu_required=False")
    if missing_deepseek:
        print(f"missing_deepseek={','.join(missing_deepseek)}")


def _redact(value: str) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 8:
        return "<set>"
    return f"{value[:3]}...{value[-3:]}"


if __name__ == "__main__":
    main()
