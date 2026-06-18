import unittest
from unittest.mock import patch

from app.config import Settings
from app.schemas import WhatsAppMessageBatchIn


class SchemaTests(unittest.TestCase):
    def test_whatsapp_batch_accepts_yingdao_chinese_fields(self) -> None:
        with patch("app.schemas.settings", Settings(whatsapp_group_name="维修工作群")):
            payload = WhatsAppMessageBatchIn.model_validate(
                {
                    "messages": [
                        {
                            "发送者": "num5",
                            "消息内容": "完成检查",
                            "时间": "17/6/2026 上午7:32",
                        },
                        {
                            "发送者": "num6",
                            "消息内容": "下午测试",
                            "时间": "17/6/2026 下午8:46",
                        },
                    ]
                }
            )

        self.assertEqual(payload.group_name, "维修工作群")
        self.assertEqual(payload.messages[0].sender, "num5")
        self.assertEqual(payload.messages[0].text, "完成检查")
        self.assertEqual(payload.messages[0].sent_at, "2026-06-17T07:32:00+08:00")
        self.assertEqual(payload.messages[0].raw_payload["发送者"], "num5")
        self.assertEqual(payload.messages[1].sent_at, "2026-06-17T20:46:00+08:00")

    def test_whatsapp_batch_accepts_yingdao_payload_without_group_name(self) -> None:
        with patch("app.schemas.settings", Settings(whatsapp_group_name="")):
            payload = WhatsAppMessageBatchIn.model_validate(
                {
                    "messages": [
                        {
                            "发送者": "aaa",
                            "消息内容": "英皇道 8樓12v火牛 換前",
                            "时间": "18/6/2026 上午7:47",
                        }
                    ]
                }
            )

        self.assertEqual(payload.group_name, "WhatsApp")
        self.assertEqual(payload.messages[0].sender, "aaa")
        self.assertEqual(payload.messages[0].text, "英皇道 8樓12v火牛 換前")
        self.assertEqual(payload.messages[0].sent_at, "2026-06-18T07:47:00+08:00")

    def test_whatsapp_batch_accepts_yingdao_collection_summary_payload(self) -> None:
        with patch("app.schemas.settings", Settings(whatsapp_group_name="")):
            payload = WhatsAppMessageBatchIn.model_validate(
                {
                    "messages": [
                        {
                            "发送者": "aaa",
                            "消息内容": "今日消息采集完成，共提取 5 条消息",
                            "时间": "18/6/2026 上午10:50",
                        }
                    ]
                }
            )

        self.assertEqual(payload.group_name, "WhatsApp")
        self.assertEqual(len(payload.messages), 1)
        self.assertEqual(payload.messages[0].sender, "aaa")
        self.assertEqual(payload.messages[0].text, "今日消息采集完成，共提取 5 条消息")
        self.assertEqual(payload.messages[0].sent_at, "2026-06-18T10:50:00+08:00")
        self.assertEqual(payload.messages[0].raw_payload["消息内容"], "今日消息采集完成，共提取 5 条消息")

    def test_whatsapp_batch_accepts_chinese_message_list_key(self) -> None:
        with patch("app.schemas.settings", Settings(whatsapp_group_name="")):
            payload = WhatsAppMessageBatchIn.model_validate(
                {
                    "消息列表": [
                        {
                            "发送者": "aaa",
                            "消息内容": "英皇道 8樓12v火牛 換前",
                            "时间": "18/6/2026 上午7:47",
                        }
                    ]
                }
            )

        self.assertEqual(payload.group_name, "WhatsApp")
        self.assertEqual(len(payload.messages), 1)


if __name__ == "__main__":
    unittest.main()
