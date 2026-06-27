import json
from pathlib import Path
import tempfile
import unittest

from app.services.customer_config import CustomerSettingsStore, load_customer_settings


class CustomerConfigTests(unittest.TestCase):
    def test_missing_file_keeps_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = load_customer_settings(Path(temp_dir) / "missing.json")

            self.assertFalse(settings.loaded)
            self.assertEqual(settings.timezone, "Asia/Hong_Kong")
            self.assertEqual(settings.whatsapp.watch_groups, [])
            self.assertEqual(settings.whatsapp.groups, [])
            self.assertEqual(settings.sites, [])

    def test_loads_full_example_style_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "customer_settings.json"
            path.write_text(
                json.dumps(
                    {
                        "timezone": "Asia/Hong_Kong",
                        "whatsapp": {
                            "use_current_logged_in_account": True,
                            "global_scan_lock_enabled": True,
                            "groups": [
                                {
                                    "id": "group_test",
                                    "name": "test",
                                    "enabled": True,
                                    "scan": {
                                        "enabled": True,
                                        "interval_minutes": 20,
                                        "start_offset_seconds": 60,
                                        "skip_if_previous_scan_running": True,
                                    },
                                    "reminder": {
                                        "enabled": True,
                                        "days_of_week": ["MON", "FRI"],
                                        "times": ["12:00", "18:00"],
                                        "max_reminders_per_event_per_day": 2,
                                        "skip_completed_events": True,
                                    },
                                    "related_site_ids": ["site_repulse_bay"],
                                }
                            ],
                        },
                        "sites": [
                            {
                                "id": "site_repulse_bay",
                                "name": "淺水灣",
                                "aliases": ["浅水湾", "Repulse Bay"],
                                "enabled": True,
                            }
                        ],
                        "event_rules": {
                            "completed_keywords": ["done"],
                            "pending_keywords": ["需跟進"],
                        },
                        "photo_record_rules": {
                            "enabled": True,
                            "require_photo_for_quotation": True,
                            "require_photo_for_replacement": True,
                            "require_pdf_report_for_atal_material": True,
                            "required_photo_types": ["wide_shot", "close_up"],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            settings = load_customer_settings(path)

            self.assertTrue(settings.loaded)
            self.assertEqual(settings.timezone, "Asia/Hong_Kong")
            self.assertEqual(settings.whatsapp.watch_groups, ["test"])
            self.assertEqual(settings.whatsapp.groups[0].scan.interval_minutes, 20)
            self.assertEqual(settings.whatsapp.groups[0].scan.start_offset_seconds, 60)
            self.assertEqual(settings.whatsapp.groups[0].reminder.times, ["12:00", "18:00"])
            self.assertEqual(settings.whatsapp.groups[0].related_site_ids, ["site_repulse_bay"])
            self.assertEqual(settings.related_site_names(settings.whatsapp.groups[0]), ["淺水灣"])
            self.assertEqual(settings.event_rules.completed_keywords, ["done"])
            self.assertEqual(settings.photo_record_rules.required_photo_types, ["wide_shot", "close_up"])

    def test_invalid_time_produces_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "customer_settings.json"
            path.write_text(
                json.dumps(
                    {
                        "whatsapp": {
                            "groups": [
                                {
                                    "id": "group_test",
                                    "name": "test",
                                    "reminder": {
                                        "enabled": True,
                                        "days_of_week": ["MON"],
                                        "times": ["25:00"],
                                    },
                                }
                            ]
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            settings = load_customer_settings(path)

            self.assertFalse(settings.loaded)
            self.assertIn("HH:MM", settings.error)

    def test_store_refreshes_when_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "customer_settings.json"
            path.write_text(
                json.dumps({"whatsapp": {"watch_groups": ["Group A"]}}, ensure_ascii=False),
                encoding="utf-8",
            )
            store = CustomerSettingsStore(path)
            self.assertEqual(store.get().whatsapp.watch_groups, ["Group A"])

            path.write_text(
                json.dumps({"whatsapp": {"watch_groups": ["Group B"]}}, ensure_ascii=False),
                encoding="utf-8",
            )

            refreshed, changed = store.refresh()
            self.assertTrue(changed)
            self.assertEqual(refreshed.whatsapp.watch_groups, ["Group B"])


if __name__ == "__main__":
    unittest.main()
