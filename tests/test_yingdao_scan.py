import unittest
from unittest.mock import patch

from scripts.yingdao_whatsapp_scan import (
    build_url,
    job_work_date,
    run_reminder_cycle_job,
    stable_external_message_id,
)


class YingdaoScanTests(unittest.TestCase):
    def test_stable_external_message_id_ignores_attachment_hint_changes(self) -> None:
        first = stable_external_message_id(
            sender="Kei",
            sent_at="2026-06-10T18:00:00+08:00",
            text="商场LY 例检完成",
            attachment_hints=[{"type": "image", "label": "Photo"}],
        )
        second = stable_external_message_id(
            sender="Kei",
            sent_at="2026-06-10T18:00:00+08:00",
            text="商场LY 例检完成",
            attachment_hints=[{"type": "image", "label": "Image"}, {"type": "pdf", "label": "PDF"}],
        )

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("yingdao_"))

    def test_build_url_skips_empty_query_values(self) -> None:
        self.assertEqual(
            build_url("http://127.0.0.1:8000/api/reminders/pending", limit=20, site_names="", group_name=None),
            "http://127.0.0.1:8000/api/reminders/pending?limit=20",
        )

    def test_job_work_date_uses_scheduled_for(self) -> None:
        self.assertEqual(
            job_work_date({"scheduled_for": "2026-06-27T18:15:00+08:00"}),
            "2026-06-27",
        )

    def test_final_reminder_job_syncs_pdf_before_enabling_pdf_followups(self) -> None:
        posted_urls = []

        def fake_post(url, payload, **kwargs):
            posted_urls.append(url)
            if "sync-daily-pdf" in url:
                return {"status": "imported"}
            return {"checked_schedules": 2, "checked_repair_records": 0, "reminders_created": 1}

        with (
            patch("scripts.yingdao_whatsapp_scan.ensure_group_open"),
            patch("scripts.yingdao_whatsapp_scan.post_json", side_effect=fake_post),
            patch("scripts.yingdao_whatsapp_scan.get_json", return_value={"reminders": []}),
        ):
            result = run_reminder_cycle_job(
                object(),
                {
                    "group_name": "维修群",
                    "scheduled_for": "2026-07-17T18:00:00+08:00",
                    "site_names": ["地点A"],
                    "actions": ["sync_daily_schedule_pdf", "run_followups", "send_reminders"],
                },
            )

        self.assertIn("sync-daily-pdf", posted_urls[0])
        self.assertIn("include_daily_pdf=true", posted_urls[1])
        self.assertTrue(result["include_daily_pdf"])

    def test_earlier_reminder_job_explicitly_excludes_pdf_followups(self) -> None:
        posted_urls = []

        def fake_post(url, payload, **kwargs):
            posted_urls.append(url)
            return {}

        with (
            patch("scripts.yingdao_whatsapp_scan.ensure_group_open"),
            patch("scripts.yingdao_whatsapp_scan.post_json", side_effect=fake_post),
            patch("scripts.yingdao_whatsapp_scan.get_json", return_value={"reminders": []}),
        ):
            result = run_reminder_cycle_job(
                object(),
                {
                    "group_name": "维修群",
                    "scheduled_for": "2026-07-17T12:00:00+08:00",
                    "actions": ["run_followups", "send_reminders"],
                },
            )

        self.assertNotIn("sync-daily-pdf", "\n".join(posted_urls))
        self.assertIn("include_daily_pdf=false", posted_urls[0])
        self.assertFalse(result["include_daily_pdf"])


if __name__ == "__main__":
    unittest.main()
