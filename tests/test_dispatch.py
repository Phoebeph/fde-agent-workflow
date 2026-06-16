import unittest

from app.services.dispatch import (
    followup_tracking_to_event,
    high_confidence_dispatch_to_schedule,
    is_followup_tracking_message,
)


class DispatchTests(unittest.TestCase):
    def test_dicky_dispatch_message_creates_schedule(self) -> None:
        schedule = high_confidence_dispatch_to_schedule(
            {
                "id": 1,
                "sender": "Dicky Company",
                "sent_at": "2026-05-26 13:52",
                "text": "@⁨Brian Company ono team⁩ 商场27 call, 过去看看\n1: Cam L1 ME.14 无画面\n2: 7/F 拍卡门故障",
            },
            dispatch_manager_senders=("Dicky Company",),
        )

        self.assertIsNotNone(schedule)
        self.assertEqual(schedule["work_date"], "2026-05-26")
        self.assertEqual(schedule["staff_name"], "Brian")
        self.assertEqual(schedule["site"], "商场27")
        self.assertIn("拍卡门故障", schedule["task_text"])

    def test_henry_followup_does_not_create_schedule(self) -> None:
        message = {
            "id": 2,
            "sender": "Henry atl",
            "sent_at": "2026-05-26 15:18",
            "text": "@⁨Brian Company ono team⁩ Brian, 22-May-2026, 商场26, 未回复上 Group",
        }
        schedule = high_confidence_dispatch_to_schedule(
            message,
            dispatch_manager_senders=("Dicky Company",),
        )

        self.assertIsNone(schedule)
        self.assertTrue(
            is_followup_tracking_message(
                message,
                followup_manager_senders=("Henry atl",),
            )
        )

    def test_henry_unreplied_followup_creates_event(self) -> None:
        event = followup_tracking_to_event(
            {
                "id": 4,
                "sender": "Henry atl",
                "sent_at": "2026-05-26 15:18",
                "text": "@⁨Brian Company ono team⁩ Brian, 22-May-2026, 商场26, 未回复上 Group",
            },
            followup_manager_senders=("Henry atl",),
        )

        self.assertIsNotNone(event)
        self.assertEqual(event["event_type"], "followup_unreplied")
        self.assertEqual(event["target_name"], "Brian")
        self.assertEqual(event["work_date"], "2026-05-22")
        self.assertEqual(event["site"], "商场26")
        self.assertIn("工作结果回复", event["event_payload"]["missing_items"])

    def test_henry_missing_pdf_followup_creates_event(self) -> None:
        event = followup_tracking_to_event(
            {
                "id": 5,
                "sender": "Henry atl",
                "sent_at": "2026-05-26 15:40",
                "text": "@⁨kelvin chan Company⁩ Kelvin, 22-May, 商场4, 有冇维修报告扫描?",
            },
            followup_manager_senders=("Henry atl",),
        )

        self.assertIsNotNone(event)
        self.assertEqual(event["event_type"], "followup_missing_pdf")
        self.assertEqual(event["target_name"], "kelvin chan")
        self.assertEqual(event["work_date"], "2026-05-22")
        self.assertEqual(event["site"], "商场4")
        self.assertIn("维修报告 PDF", event["event_payload"]["missing_items"])

    def test_tomorrow_dispatch_moves_work_date(self) -> None:
        schedule = high_confidence_dispatch_to_schedule(
            {
                "id": 3,
                "sender": "Rex Atl",
                "sent_at": "2026-05-26 18:40",
                "text": "@⁨lin atl⁩ 明早商场41 10:00 到场协调做检查",
            },
            dispatch_manager_senders=("Rex Atl",),
        )

        self.assertIsNotNone(schedule)
        self.assertEqual(schedule["work_date"], "2026-05-27")
        self.assertEqual(schedule["staff_name"], "lin")
        self.assertEqual(schedule["site"], "商场41")


if __name__ == "__main__":
    unittest.main()
