import unittest

from scripts.yingdao_whatsapp_scan import build_url, job_work_date, stable_external_message_id


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


if __name__ == "__main__":
    unittest.main()
