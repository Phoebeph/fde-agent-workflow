from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


if load_dotenv:
    load_dotenv()


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if not raw:
        return default
    values = tuple(item.strip() for item in raw.split(",") if item.strip())
    return values or default


def _path_env(name: str, default: str | Path) -> Path:
    raw = os.getenv(name)
    if raw:
        return Path(raw)
    return Path(default)


DATA_ROOT_ENV = os.getenv("DATA_ROOT", "")
DATA_ROOT = Path(DATA_ROOT_ENV) if DATA_ROOT_ENV else None


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    app_host: str = os.getenv("APP_HOST", "127.0.0.1")
    app_port: int = _int_env("APP_PORT", 8000)

    data_root: Path = _path_env("DATA_ROOT", "./data")
    database_path: Path = _path_env(
        "DATABASE_PATH",
        (DATA_ROOT / "database" / "whatsapp_repair.db") if DATA_ROOT else "./data/whatsapp_repair.db",
    )
    archive_root: Path = _path_env("ARCHIVE_ROOT", DATA_ROOT if DATA_ROOT else "./archive")
    downloads_root: Path = _path_env(
        "DOWNLOADS_ROOT",
        (DATA_ROOT / "downloads" / "yingdao") if DATA_ROOT else "./downloads/yingdao",
    )
    exports_root: Path = _path_env("EXPORTS_ROOT", DATA_ROOT if DATA_ROOT else "./exports")
    logs_root: Path = _path_env("LOGS_ROOT", (DATA_ROOT / "logs") if DATA_ROOT else "./logs")
    backups_root: Path = _path_env("BACKUPS_ROOT", (DATA_ROOT / "backups") if DATA_ROOT else "./backups")

    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    feishu_app_id: str = os.getenv("FEISHU_APP_ID", "")
    feishu_app_secret: str = os.getenv("FEISHU_APP_SECRET", "")
    feishu_app_token: str = os.getenv("FEISHU_APP_TOKEN", "")
    feishu_table_id: str = os.getenv("FEISHU_TABLE_ID", "")
    feishu_base_url: str = os.getenv("FEISHU_BASE_URL", "https://open.feishu.cn")
    feishu_upload_parent_type: str = os.getenv("FEISHU_UPLOAD_PARENT_TYPE", "bitable_file")
    feishu_upload_parent_node: str = os.getenv("FEISHU_UPLOAD_PARENT_NODE", "")
    feishu_mock_mode: bool = _bool_env("FEISHU_MOCK_MODE", False)

    whatsapp_group_name: str = os.getenv("WHATSAPP_GROUP_NAME", "")
    reminder_daily_limit: int = _int_env("REMINDER_DAILY_LIMIT", 1)
    auto_analyze_on_ingest: bool = _bool_env("AUTO_ANALYZE_ON_INGEST", True)
    auto_export_on_ingest: bool = _bool_env("AUTO_EXPORT_ON_INGEST", True)
    auto_pipeline_background: bool = _bool_env("AUTO_PIPELINE_BACKGROUND", True)
    auto_sync_feishu_on_ingest: bool = _bool_env("AUTO_SYNC_FEISHU_ON_INGEST", False)
    dispatch_manager_senders: tuple[str, ...] = _csv_env(
        "DISPATCH_MANAGER_SENDERS",
        ("Dicky Company", "Rex Atl", "Ono atl"),
    )
    followup_manager_senders: tuple[str, ...] = _csv_env(
        "FOLLOWUP_MANAGER_SENDERS",
        ("Henry atl",),
    )

    @property
    def deepseek_enabled(self) -> bool:
        return bool(self.deepseek_api_key)

    @property
    def feishu_enabled(self) -> bool:
        required = [
            self.feishu_app_id,
            self.feishu_app_secret,
            self.feishu_app_token,
            self.feishu_table_id,
        ]
        return all(required)

    @property
    def feishu_sync_available(self) -> bool:
        return self.feishu_enabled or self.feishu_mock_mode


settings = Settings()
