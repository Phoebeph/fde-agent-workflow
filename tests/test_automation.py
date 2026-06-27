import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.database import Database
from app.main import _claim_next_automation_job
from app.services.automation import build_due_automation_jobs, parse_site_names_csv
from app.services.customer_config import (
    CustomerGroupReminderConfig,
    CustomerGroupScanConfig,
    CustomerSettings,
    CustomerSite,
    CustomerWhatsAppConfig,
    CustomerWhatsAppGroup,
)


class AutomationScheduleTests(unittest.TestCase):
    def test_build_due_automation_jobs_uses_timezone_and_group_site_mapping(self) -> None:
        settings = CustomerSettings(
            timezone="Asia/Hong_Kong",
            whatsapp=CustomerWhatsAppConfig(
                groups=[
                    CustomerWhatsAppGroup(
                        id="group_test",
                        name="test",
                        scan=CustomerGroupScanConfig(
                            enabled=True,
                            interval_minutes=20,
                            start_offset_seconds=60,
                        ),
                        reminder=CustomerGroupReminderConfig(
                            enabled=True,
                            days_of_week=["MON"],
                            times=["00:20", "00:40", "01:00"],
                            max_reminders_per_event_per_day=2,
                        ),
                        related_site_ids=["site_a"],
                    )
                ],
                watch_groups=["test"],
            ),
            sites=[CustomerSite(id="site_a", name="淺水灣", aliases=["Repulse Bay"], enabled=True)],
            loaded=True,
        )
        now_utc = datetime.datetime(2026, 6, 28, 16, 41, tzinfo=datetime.timezone.utc)

        jobs = build_due_automation_jobs(settings, now=now_utc)

        self.assertEqual(len(jobs), 5)
        self.assertEqual([job["job_type"] for job in jobs[:3]], ["scan_cycle", "reminder_cycle", "scan_cycle"])
        self.assertEqual(jobs[0]["scheduled_for"], "2026-06-29T00:01:00+08:00")
        self.assertEqual(jobs[1]["scheduled_for"], "2026-06-29T00:20:00+08:00")
        self.assertEqual(jobs[-1]["scheduled_for"], "2026-06-29T00:41:00+08:00")
        self.assertEqual(jobs[1]["site_names"], ["淺水灣"])
        self.assertEqual(jobs[1]["actions"], ["run_followups", "send_reminders"])

    def test_parse_site_names_csv_deduplicates_and_strips(self) -> None:
        self.assertEqual(parse_site_names_csv("A, B ,A,,C"), ["A", "B", "C"])
        self.assertEqual(parse_site_names_csv(None), [])


class AutomationClaimTests(unittest.TestCase):
    def test_claim_next_automation_job_respects_global_scan_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            settings = CustomerSettings(
                timezone="Asia/Hong_Kong",
                whatsapp=CustomerWhatsAppConfig(
                    global_scan_lock_enabled=True,
                    groups=[
                        CustomerWhatsAppGroup(
                            id="group_a",
                            name="群A",
                            scan=CustomerGroupScanConfig(enabled=True, interval_minutes=60),
                            reminder=CustomerGroupReminderConfig(enabled=False),
                        ),
                        CustomerWhatsAppGroup(
                            id="group_b",
                            name="群B",
                            scan=CustomerGroupScanConfig(enabled=True, interval_minutes=60),
                            reminder=CustomerGroupReminderConfig(enabled=False),
                        ),
                    ],
                    watch_groups=["群A", "群B"],
                ),
                loaded=True,
            )

            with (
                patch("app.main.db", db),
                patch("app.main._current_customer_settings", return_value=settings),
            ):
                first = _claim_next_automation_job()
                second = _claim_next_automation_job()

            self.assertIsNotNone(first)
            self.assertEqual(first["job_type"], "scan_cycle")
            self.assertIsNone(second)

    def test_claim_next_automation_job_allows_second_group_when_global_lock_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            settings = CustomerSettings(
                timezone="Asia/Hong_Kong",
                whatsapp=CustomerWhatsAppConfig(
                    global_scan_lock_enabled=False,
                    groups=[
                        CustomerWhatsAppGroup(
                            id="group_a",
                            name="群A",
                            scan=CustomerGroupScanConfig(enabled=True, interval_minutes=60),
                            reminder=CustomerGroupReminderConfig(enabled=False),
                        ),
                        CustomerWhatsAppGroup(
                            id="group_b",
                            name="群B",
                            scan=CustomerGroupScanConfig(enabled=True, interval_minutes=60),
                            reminder=CustomerGroupReminderConfig(enabled=False),
                        ),
                    ],
                    watch_groups=["群A", "群B"],
                ),
                loaded=True,
            )

            with (
                patch("app.main.db", db),
                patch("app.main._current_customer_settings", return_value=settings),
            ):
                first = _claim_next_automation_job()
                second = _claim_next_automation_job()

            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            self.assertNotEqual(first["group_id"], second["group_id"])


if __name__ == "__main__":
    unittest.main()
