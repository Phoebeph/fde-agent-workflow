import unittest
from unittest.mock import patch

from app.main import _is_standalone_attachment_label, ingest_whatsapp_messages
from app.schemas import WhatsAppMessageBatchIn


class FakeDatabase:
    def __init__(self) -> None:
        self.inserted_rows = []
        self.fingerprints = []
        self.insert_result = None
        self.existing_fingerprints = set()
        self.insert_called = False

    def insert_messages(self, rows):
        self.inserted_rows = rows
        self.insert_called = True
        if self.insert_result is not None:
            return self.insert_result
        return {"inserted": len(rows), "skipped": 0}

    def list_messages_by_fingerprints(self, fingerprints):
        self.fingerprints = fingerprints
        if not self.insert_called:
            return [
                {"message_fingerprint": fingerprint}
                for fingerprint in fingerprints
                if fingerprint in self.existing_fingerprints
            ]
        return [{"message_fingerprint": fingerprint} for fingerprint in fingerprints]


class IngestTests(unittest.TestCase):
    def test_standalone_attachment_labels_are_detected(self) -> None:
        self.assertTrue(_is_standalone_attachment_label("料"))
        self.assertTrue(_is_standalone_attachment_label("電鎖前"))
        self.assertTrue(_is_standalone_attachment_label(" 後 "))
        self.assertFalse(_is_standalone_attachment_label("LG09 電鎖後更換正常"))

    def test_ingest_filters_automation_notice_messages(self) -> None:
        fake_db = FakeDatabase()
        payload = WhatsAppMessageBatchIn.model_validate(
            {
                "messages": [
                    {
                        "发送者": "hello",
                        "消息内容": "自动化助手提示：今日消息采集完成，共提取 4 条消息。",
                        "时间": "18/6/2026 上午10:50",
                    },
                    {
                        "发送者": "aaa",
                        "消息内容": "英皇道 8樓12v火牛 換前",
                        "时间": "18/6/2026 上午10:51",
                    },
                ]
            }
        )

        with (
            patch("app.main.db", fake_db),
            patch("app.main._discover_and_save_dispatch_schedules", return_value={"created": 0}),
        ):
            result = ingest_whatsapp_messages(payload)

        self.assertEqual(result["messages"], {"inserted": 1, "skipped": 0, "filtered": 1})
        self.assertEqual(len(fake_db.inserted_rows), 1)
        self.assertEqual(fake_db.inserted_rows[0]["sender"], "aaa")
        self.assertEqual(fake_db.inserted_rows[0]["text"], "英皇道 8樓12v火牛 換前")
        self.assertEqual(fake_db.inserted_rows[0]["sent_at"], "2026-06-18T10:51:00+08:00")
        self.assertEqual(len(fake_db.fingerprints), 1)

    def test_ingest_schedules_pipeline_for_existing_messages(self) -> None:
        fake_db = FakeDatabase()
        fake_db.insert_result = {"inserted": 0, "skipped": 1}
        payload = WhatsAppMessageBatchIn.model_validate(
            {
                "messages": [
                    {
                        "发送者": "aaa",
                        "消息内容": "The SOUI Tv wall 正常",
                        "时间": "24/6/2026 上午10:51",
                    },
                ]
            }
        )

        with (
            patch("app.main.db", fake_db),
            patch("app.main._discover_and_save_dispatch_schedules", return_value={"created": 0}),
            patch("app.main.message_fingerprint", return_value="existing-fingerprint"),
            patch("app.main._schedule_post_ingest_pipeline") as schedule_pipeline,
        ):
            fake_db.existing_fingerprints = {"existing-fingerprint"}
            result = ingest_whatsapp_messages(payload, background_tasks=object())

        self.assertEqual(result["messages"], {"inserted": 0, "skipped": 1, "filtered": 0})
        self.assertFalse(result["auto_pipeline"]["scheduled"])
        self.assertEqual(result["auto_pipeline"]["reason"], "no newly inserted messages")
        schedule_pipeline.assert_not_called()

    def test_ingest_schedules_pipeline_only_for_new_messages(self) -> None:
        fake_db = FakeDatabase()
        payload = WhatsAppMessageBatchIn.model_validate(
            {
                "messages": [
                    {
                        "发送者": "aaa",
                        "消息内容": "The SOUI Tv wall 正常",
                        "时间": "24/6/2026 上午10:51",
                    },
                ]
            }
        )

        with (
            patch("app.main.db", fake_db),
            patch("app.main._discover_and_save_dispatch_schedules", return_value={"created": 0}),
            patch("app.main.message_fingerprint", return_value="new-fingerprint"),
            patch(
                "app.main._schedule_post_ingest_pipeline",
                return_value={"scheduled": True, "background": True, "message_count": 1},
            ) as schedule_pipeline,
        ):
            result = ingest_whatsapp_messages(payload, background_tasks=object())

        self.assertEqual(result["messages"], {"inserted": 1, "skipped": 0, "filtered": 0})
        self.assertTrue(result["auto_pipeline"]["scheduled"])
        schedule_pipeline.assert_called_once()


if __name__ == "__main__":
    unittest.main()
