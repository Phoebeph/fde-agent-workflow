import json
from pathlib import Path
import tempfile
import unittest

from app.services.customer_config import load_customer_settings


class CustomerConfigTests(unittest.TestCase):
    def test_missing_file_keeps_legacy_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = load_customer_settings(Path(temp_dir) / "missing.json")

            self.assertFalse(settings.loaded)
            self.assertEqual(settings.whatsapp.watch_groups, [])
            self.assertEqual(settings.whatsapp.scan_interval_minutes, 5)
            self.assertEqual(settings.sites, [])

    def test_loads_watch_groups_and_enabled_sites(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "customer_settings.json"
            path.write_text(
                json.dumps(
                    {
                        "whatsapp": {
                            "watch_groups": ["ELV Group", "test"],
                            "reminder_sender_account": "robot-account",
                            "scan_interval_minutes": 10,
                            "reminder_interval_minutes": 45,
                        },
                        "sites": [
                            {"name": "淺水灣", "aliases": ["浅水湾", "Repulse Bay"], "enabled": True},
                            {"name": "无关地点", "aliases": ["ignore"], "enabled": False},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            settings = load_customer_settings(path)

            self.assertTrue(settings.loaded)
            self.assertEqual(settings.whatsapp.watch_groups, ["ELV Group", "test"])
            self.assertEqual(settings.whatsapp.reminder_sender_account, "robot-account")
            self.assertEqual(settings.whatsapp.scan_interval_minutes, 10)
            self.assertEqual(settings.whatsapp.reminder_interval_minutes, 45)
            self.assertEqual(settings.sites[0].name, "淺水灣")
            self.assertEqual(settings.sites[0].aliases, ["浅水湾", "Repulse Bay"])
            self.assertFalse(settings.sites[1].enabled)


if __name__ == "__main__":
    unittest.main()
