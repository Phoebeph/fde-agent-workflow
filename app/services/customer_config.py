from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
_WEEKDAY_CODES = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
_SAFE_ID_RE = re.compile(r"[^0-9A-Za-z_]+")


@dataclass(frozen=True)
class CustomerGroupScanConfig:
    enabled: bool = True
    interval_minutes: int = 5
    start_offset_seconds: int = 0
    skip_if_previous_scan_running: bool = True


@dataclass(frozen=True)
class CustomerGroupReminderConfig:
    enabled: bool = True
    days_of_week: list[str] = field(default_factory=list)
    times: list[str] = field(default_factory=list)
    max_reminders_per_event_per_day: int = 1
    skip_completed_events: bool = True


@dataclass(frozen=True)
class CustomerWhatsAppGroup:
    id: str
    name: str
    enabled: bool = True
    scan: CustomerGroupScanConfig = field(default_factory=CustomerGroupScanConfig)
    reminder: CustomerGroupReminderConfig = field(default_factory=CustomerGroupReminderConfig)
    related_site_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CustomerSite:
    id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass(frozen=True)
class CustomerWhatsAppConfig:
    use_current_logged_in_account: bool = True
    global_scan_lock_enabled: bool = True
    groups: list[CustomerWhatsAppGroup] = field(default_factory=list)
    watch_groups: list[str] = field(default_factory=list)
    reminder_sender_account: str = ""
    scan_interval_minutes: int = 5
    reminder_interval_minutes: int = 30


@dataclass(frozen=True)
class CustomerEventRules:
    completed_keywords: list[str] = field(default_factory=list)
    pending_keywords: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CustomerPhotoRecordRules:
    enabled: bool = True
    require_photo_for_quotation: bool = True
    require_photo_for_replacement: bool = True
    require_pdf_report_for_atal_material: bool = True
    required_photo_types: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CustomerSettings:
    path: str = ""
    timezone: str = "Asia/Hong_Kong"
    whatsapp: CustomerWhatsAppConfig = field(default_factory=CustomerWhatsAppConfig)
    sites: list[CustomerSite] = field(default_factory=list)
    event_rules: CustomerEventRules = field(default_factory=CustomerEventRules)
    photo_record_rules: CustomerPhotoRecordRules = field(default_factory=CustomerPhotoRecordRules)
    loaded: bool = False
    error: str = ""
    validation_errors: list[str] = field(default_factory=list)

    def enabled_groups(self) -> list[CustomerWhatsAppGroup]:
        return [group for group in self.whatsapp.groups if group.enabled]

    def site_map(self) -> dict[str, CustomerSite]:
        return {site.id: site for site in self.sites}

    def related_site_names(self, group: CustomerWhatsAppGroup) -> list[str]:
        site_map = self.site_map()
        names: list[str] = []
        for site_id in group.related_site_ids:
            site = site_map.get(site_id)
            if site and site.enabled and site.name not in names:
                names.append(site.name)
        return names


class CustomerSettingsStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._mtime_ns = _stat_mtime_ns(self.path)
        self._settings = load_customer_settings(self.path)

    def refresh(self) -> tuple[CustomerSettings, bool]:
        current_mtime_ns = _stat_mtime_ns(self.path)
        if current_mtime_ns == self._mtime_ns:
            return self._settings, False
        self._mtime_ns = current_mtime_ns
        self._settings = load_customer_settings(self.path)
        return self._settings, True

    def get(self) -> CustomerSettings:
        return self.refresh()[0]

    def set_for_tests(self, settings: CustomerSettings) -> None:
        self._settings = settings
        self._mtime_ns = None


def load_customer_settings(path: Path) -> CustomerSettings:
    config_path = Path(path)
    if not config_path.exists():
        return CustomerSettings(path=str(config_path))
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return CustomerSettings(path=str(config_path), loaded=False, error=str(exc), validation_errors=[str(exc)])

    if not isinstance(data, dict):
        message = "customer settings root must be a JSON object"
        return CustomerSettings(path=str(config_path), loaded=False, error=message, validation_errors=[message])

    try:
        return _parse_customer_settings(data, config_path)
    except ValueError as exc:
        message = str(exc)
        return CustomerSettings(path=str(config_path), loaded=False, error=message, validation_errors=[message])


def _parse_customer_settings(data: dict[str, Any], path: Path) -> CustomerSettings:
    timezone_name = _validated_timezone(data.get("timezone"), "timezone")
    sites = _parse_sites(data.get("sites"))
    site_ids = {site.id for site in sites}

    whatsapp = data.get("whatsapp")
    if whatsapp is None:
        whatsapp = {}
    if not isinstance(whatsapp, dict):
        raise ValueError("whatsapp must be an object")

    groups_data = whatsapp.get("groups")
    groups: list[CustomerWhatsAppGroup] = []
    if isinstance(groups_data, list) and groups_data:
        groups = _parse_groups(groups_data, site_ids)
        watch_groups = [group.name for group in groups if group.enabled]
        scan_interval = groups[0].scan.interval_minutes if groups else 5
        reminder_interval = 30
    else:
        watch_groups = _string_list(whatsapp.get("watch_groups"))
        scan_interval = _positive_int_legacy(whatsapp.get("scan_interval_minutes"), 5)
        reminder_interval = _positive_int_legacy(whatsapp.get("reminder_interval_minutes"), 30)
        groups = [
            CustomerWhatsAppGroup(
                id=_fallback_id(name, f"group_{index + 1}"),
                name=name,
                enabled=True,
                scan=CustomerGroupScanConfig(enabled=True, interval_minutes=scan_interval),
                reminder=CustomerGroupReminderConfig(enabled=False),
            )
            for index, name in enumerate(watch_groups)
        ]

    return CustomerSettings(
        path=str(path),
        timezone=timezone_name,
        whatsapp=CustomerWhatsAppConfig(
            use_current_logged_in_account=bool(whatsapp.get("use_current_logged_in_account", True)),
            global_scan_lock_enabled=bool(whatsapp.get("global_scan_lock_enabled", True)),
            groups=groups,
            watch_groups=watch_groups,
            reminder_sender_account=_text(whatsapp.get("reminder_sender_account")),
            scan_interval_minutes=scan_interval,
            reminder_interval_minutes=reminder_interval,
        ),
        sites=sites,
        event_rules=_parse_event_rules(data.get("event_rules")),
        photo_record_rules=_parse_photo_record_rules(data.get("photo_record_rules")),
        loaded=True,
    )


def _parse_sites(value: Any) -> list[CustomerSite]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("sites must be a list")
    sites: list[CustomerSite] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"sites[{index}] must be an object")
        name = _required_text(item.get("name"), f"sites[{index}].name")
        site_id = _fallback_id(item.get("id"), f"site_{index + 1}_{name}")
        if site_id in seen_ids:
            raise ValueError(f"duplicate site id: {site_id}")
        seen_ids.add(site_id)
        sites.append(
            CustomerSite(
                id=site_id,
                name=name,
                aliases=_string_list(item.get("aliases")),
                enabled=bool(item.get("enabled", True)),
            )
        )
    return sites


def _parse_groups(value: list[Any], site_ids: set[str]) -> list[CustomerWhatsAppGroup]:
    groups: list[CustomerWhatsAppGroup] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"whatsapp.groups[{index}] must be an object")
        name = _required_text(item.get("name"), f"whatsapp.groups[{index}].name")
        group_id = _fallback_id(item.get("id"), f"group_{index + 1}_{name}")
        if group_id in seen_ids:
            raise ValueError(f"duplicate group id: {group_id}")
        seen_ids.add(group_id)
        related_site_ids = _string_list(item.get("related_site_ids"))
        unknown_site_ids = [site_id for site_id in related_site_ids if site_id not in site_ids]
        if unknown_site_ids:
            raise ValueError(
                f"whatsapp.groups[{index}].related_site_ids contains unknown ids: {','.join(unknown_site_ids)}"
            )
        groups.append(
            CustomerWhatsAppGroup(
                id=group_id,
                name=name,
                enabled=bool(item.get("enabled", True)),
                scan=_parse_scan_config(item.get("scan"), f"whatsapp.groups[{index}].scan"),
                reminder=_parse_reminder_config(item.get("reminder"), f"whatsapp.groups[{index}].reminder"),
                related_site_ids=related_site_ids,
            )
        )
    return groups


def _parse_scan_config(value: Any, field_name: str) -> CustomerGroupScanConfig:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return CustomerGroupScanConfig(
        enabled=bool(value.get("enabled", True)),
        interval_minutes=_positive_int_strict(value.get("interval_minutes", 5), f"{field_name}.interval_minutes"),
        start_offset_seconds=_non_negative_int(value.get("start_offset_seconds", 0), f"{field_name}.start_offset_seconds"),
        skip_if_previous_scan_running=bool(value.get("skip_if_previous_scan_running", True)),
    )


def _parse_reminder_config(value: Any, field_name: str) -> CustomerGroupReminderConfig:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    days_of_week = [_validated_weekday_code(item, f"{field_name}.days_of_week") for item in _string_list(value.get("days_of_week"))]
    times = [_validated_time_text(item, f"{field_name}.times") for item in _string_list(value.get("times"))]
    return CustomerGroupReminderConfig(
        enabled=bool(value.get("enabled", True)),
        days_of_week=days_of_week,
        times=times,
        max_reminders_per_event_per_day=_positive_int_strict(
            value.get("max_reminders_per_event_per_day", 1),
            f"{field_name}.max_reminders_per_event_per_day",
        ),
        skip_completed_events=bool(value.get("skip_completed_events", True)),
    )


def _parse_event_rules(value: Any) -> CustomerEventRules:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("event_rules must be an object")
    return CustomerEventRules(
        completed_keywords=_string_list(value.get("completed_keywords")),
        pending_keywords=_string_list(value.get("pending_keywords")),
    )


def _parse_photo_record_rules(value: Any) -> CustomerPhotoRecordRules:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("photo_record_rules must be an object")
    return CustomerPhotoRecordRules(
        enabled=bool(value.get("enabled", True)),
        require_photo_for_quotation=bool(value.get("require_photo_for_quotation", True)),
        require_photo_for_replacement=bool(value.get("require_photo_for_replacement", True)),
        require_pdf_report_for_atal_material=bool(value.get("require_pdf_report_for_atal_material", True)),
        required_photo_types=_string_list(value.get("required_photo_types")),
    )


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _required_text(value: Any, field_name: str) -> str:
    text = _text(value)
    if not text:
        raise ValueError(f"{field_name} cannot be blank")
    return text


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _positive_int_strict(value: Any, field_name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer") from exc
    if number <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return number


def _non_negative_int(value: Any, field_name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a non-negative integer") from exc
    if number < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return number


def _positive_int_legacy(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _validated_time_text(value: str, field_name: str) -> str:
    time_text = _text(value)
    if not _TIME_RE.fullmatch(time_text):
        raise ValueError(f"{field_name} entries must use HH:MM format")
    hour = int(time_text[:2])
    minute = int(time_text[3:])
    if hour > 23 or minute > 59:
        raise ValueError(f"{field_name} entries must use valid HH:MM values")
    return time_text


def _validated_weekday_code(value: str, field_name: str) -> str:
    code = _text(value).upper()
    if code not in _WEEKDAY_CODES:
        raise ValueError(f"{field_name} entries must be one of {','.join(sorted(_WEEKDAY_CODES))}")
    return code


def _validated_timezone(value: Any, field_name: str) -> str:
    timezone_name = _text(value) or "Asia/Hong_Kong"
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"{field_name} is not a valid IANA timezone: {timezone_name}") from exc
    return timezone_name


def _fallback_id(value: Any, fallback: str) -> str:
    text = _text(value) or _text(fallback)
    normalized = _SAFE_ID_RE.sub("_", text).strip("_").lower()
    return normalized or "item"


def _stat_mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return None
