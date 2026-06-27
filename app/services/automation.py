from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.services.customer_config import CustomerSettings, CustomerWhatsAppGroup


SCAN_CYCLE = "scan_cycle"
REMINDER_CYCLE = "reminder_cycle"
STALE_CLAIM_SECONDS = 15 * 60
_WEEKDAY_CODES = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def build_due_automation_jobs(
    settings: CustomerSettings,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    if not settings.loaded or settings.error:
        return []
    timezone_name = settings.timezone
    zone = ZoneInfo(timezone_name)
    current_utc = now or datetime.now(timezone.utc)
    current_local = current_utc.astimezone(zone)
    jobs: list[dict[str, Any]] = []
    for group in settings.enabled_groups():
        jobs.extend(_build_due_scan_jobs(settings, group, current_local, timezone_name))
        jobs.extend(_build_due_reminder_jobs(settings, group, current_local, timezone_name))
    jobs.sort(key=lambda item: (item["scheduled_for"], item["job_type"], item["group_name"]))
    return jobs


def parse_site_names_csv(value: str | None) -> list[str]:
    if not value:
        return []
    result: list[str] = []
    for item in value.split(","):
        site_name = item.strip()
        if site_name and site_name not in result:
            result.append(site_name)
    return result


def _build_due_scan_jobs(
    settings: CustomerSettings,
    group: CustomerWhatsAppGroup,
    current_local: datetime,
    timezone_name: str,
) -> list[dict[str, Any]]:
    if not group.scan.enabled:
        return []
    interval = timedelta(minutes=group.scan.interval_minutes)
    slot = current_local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        seconds=group.scan.start_offset_seconds
    )
    jobs: list[dict[str, Any]] = []
    while slot <= current_local:
        jobs.append(
            _job_payload(
                settings,
                group,
                job_type=SCAN_CYCLE,
                scheduled_for=slot,
                timezone_name=timezone_name,
                actions=["collect_messages", "download_attachments"],
            )
        )
        slot += interval
    return jobs


def _build_due_reminder_jobs(
    settings: CustomerSettings,
    group: CustomerWhatsAppGroup,
    current_local: datetime,
    timezone_name: str,
) -> list[dict[str, Any]]:
    reminder = group.reminder
    if not reminder.enabled:
        return []
    weekday_code = _WEEKDAY_CODES[current_local.weekday()]
    if reminder.days_of_week and weekday_code not in reminder.days_of_week:
        return []
    jobs: list[dict[str, Any]] = []
    for time_text in reminder.times:
        hour = int(time_text[:2])
        minute = int(time_text[3:])
        slot = current_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if slot > current_local:
            continue
        jobs.append(
            _job_payload(
                settings,
                group,
                job_type=REMINDER_CYCLE,
                scheduled_for=slot,
                timezone_name=timezone_name,
                actions=["run_followups", "send_reminders"],
            )
        )
    return jobs


def _job_payload(
    settings: CustomerSettings,
    group: CustomerWhatsAppGroup,
    *,
    job_type: str,
    scheduled_for: datetime,
    timezone_name: str,
    actions: list[str],
) -> dict[str, Any]:
    return {
        "group_id": group.id,
        "group_name": group.name,
        "job_type": job_type,
        "scheduled_for": scheduled_for.isoformat(),
        "timezone": timezone_name,
        "site_names": settings.related_site_names(group),
        "actions": actions,
        "skip_if_previous_scan_running": group.scan.skip_if_previous_scan_running,
        "max_reminders_per_event_per_day": group.reminder.max_reminders_per_event_per_day,
        "skip_completed_events": group.reminder.skip_completed_events,
    }
