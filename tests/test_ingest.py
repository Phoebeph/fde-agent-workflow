import unittest
from unittest.mock import patch

from app.main import ingest_whatsapp_messages
from app.schemas import WhatsAppMessageBatchIn


class FakeDatabase:
    def __init__(self) -> None:
        self.inserted_rows = []
        self.fingerprints = []

    def insert_messages(self, rows):
        self.inserted_rows = rows
        return {"inserted": len(rows), "skipped": 0}

    def list_messages_by_fingerprints(self, fingerprints):
        self.fingerprints = fingerprints
        return [{"message_fingerprint": fingerprint} for fingerprint in fingerprints]


class IngestTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
