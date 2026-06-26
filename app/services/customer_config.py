from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CustomerSite:
    name: str
    aliases: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass(frozen=True)
class CustomerWhatsAppConfig:
    watch_groups: list[str] = field(default_factory=list)
    reminder_sender_account: str = ""
    scan_interval_minutes: int = 5
    reminder_interval_minutes: int = 30


@dataclass(frozen=True)
class CustomerSettings:
    whatsapp: CustomerWhatsAppConfig = field(default_factory=CustomerWhatsAppConfig)
    sites: list[CustomerSite] = field(default_factory=list)
    loaded: bool = False
    error: str = ""


def load_customer_settings(path: Path) -> CustomerSettings:
    if not path.exists():
        return CustomerSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return CustomerSettings(loaded=False, error=str(exc))

    whatsapp = data.get("whatsapp") if isinstance(data, dict) else {}
    if not isinstance(whatsapp, dict):
        whatsapp = {}
    sites_data = data.get("sites") if isinstance(data, dict) else []
    if not isinstance(sites_data, list):
        sites_data = []

    return CustomerSettings(
        whatsapp=CustomerWhatsAppConfig(
            watch_groups=_string_list(whatsapp.get("watch_groups")),
            reminder_sender_account=_text(whatsapp.get("reminder_sender_account")),
            scan_interval_minutes=_positive_int(whatsapp.get("scan_interval_minutes"), 5),
            reminder_interval_minutes=_positive_int(whatsapp.get("reminder_interval_minutes"), 30),
        ),
        sites=[
            CustomerSite(
                name=_text(item.get("name")),
                aliases=_string_list(item.get("aliases")),
                enabled=bool(item.get("enabled", True)),
            )
            for item in sites_data
            if isinstance(item, dict) and _text(item.get("name"))
        ],
        loaded=True,
    )


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default
