import unittest

from app.main import preview_reminder
from app.schemas import ReminderPreviewIn
from app.services.reminder_text import generate_analysis_reminder_message, generate_reminder_message, reminder_missing_type


class ReminderTextTests(unittest.TestCase):
    def test_inspection_result_with_record(self) -> None:
        message = generate_reminder_message(
            {
                "mention_name": "@希Atal",
                "assignee": "Hei",
                "reminder_count": 2,
                "task_date": "18-Jun",
                "site": "德福廣場",
                "task_content": "一支鏡望巴士站冇畫面",
                "missing_type": "inspection_result",
                "record": "Brian 17-Jun 23:00: 德福廣場一支鏡望巴士站冇畫面，已同現場講明日例檢跟進",
            }
        )

        self.assertIn("@希Atal Hei，仲未收到你回覆（第2次问）", message)
        self.assertIn("咩情況? 有冇檢查結果?", message)
        self.assertIn("Record:", message)
        self.assertIn('"Brian 17-Jun 23:00: 德福廣場一支鏡望巴士站冇畫面，已同現場講明日例檢跟進"', message)

    def test_repair_report_pdf(self) -> None:
        message = generate_reminder_message(
            {
                "mention_name": "@Brian",
                "assignee": "Brian",
                "reminder_count": 3,
                "task_date": "19-Jun",
                "site": "The Henderson",
                "task_content": "ecall service",
                "missing_type": "repair_report_pdf",
            }
        )

        self.assertIn("有冇維修報告掃描?", message)

    def test_photo_record_without_record_section(self) -> None:
        message = generate_reminder_message(
            {
                "mention_name": "@Keung",
                "assignee": "Keung",
                "reminder_count": 1,
                "task_date": "20-Jun",
                "site": "LPP",
                "task_content": "更換 ATAL 物料",
                "missing_type": "photo_record",
                "record": "",
            }
        )

        self.assertIn("有冇 換前 換中 換後 的 Photo Record?", message)
        self.assertNotIn("Record:", message)

    def test_route_plan_includes_special_note(self) -> None:
        message = generate_reminder_message(
            {
                "mention_name": "@Hei",
                "assignee": "Hei",
                "reminder_count": 2,
                "task_date": "21-Jun",
                "site": "德福廣場",
                "task_content": "報價放新線",
                "missing_type": "route_plan",
            }
        )

        self.assertIn("有冇放線路線平面圖?", message)
        self.assertIn("如要報價放新線，要在平面圖 mark 返條路線", message)
        self.assertIn("冇附上平面圖，是出唔到報價的。", message)

    def test_unknown_missing_type_uses_default_question(self) -> None:
        message = generate_reminder_message(
            {
                "mention_name": "",
                "assignee": "Brian",
                "reminder_count": None,
                "task_date": "",
                "site": "",
                "task_content": "",
                "missing_type": "something_else",
            }
        )

        self.assertIn("咩情況? 有冇最新跟進結果?", message)
        self.assertIn("第1次问", message)

    def test_analysis_reminder_maps_pdf_missing_to_template(self) -> None:
        message = generate_analysis_reminder_message(
            {
                "staff_name": "Brian",
                "work_date": "2026-06-19",
                "site": "The Henderson",
                "summary": "ecall service 維修",
                "completion_status": "资料不足",
                "missing_items": ["维修报告 PDF"],
                "next_actions": [],
            },
            record="Brian 2026-06-19 ecall service 維修完成",
        )

        self.assertIn("@Brian Brian，仲未收到你回覆（第1次问）", message)
        self.assertIn("Brian，19-Jun，The Henderson", message)
        self.assertIn("有冇維修報告掃描?", message)
        self.assertIn("Record:", message)

    def test_missing_type_ignores_generic_photo_when_not_in_analysis(self) -> None:
        missing_type = reminder_missing_type(
            {
                "completion_status": "需要跟进",
                "summary": "普通维修需要确认结果",
                "missing_items": [],
                "next_actions": ["补充明确工作结果"],
            }
        )

        self.assertEqual(missing_type, "work_result")

    def test_preview_api_returns_message(self) -> None:
        response = preview_reminder(
            ReminderPreviewIn.model_validate(
                {
                "mention_name": "@希Atal",
                "assignee": "Hei",
                "reminder_count": 2,
                "task_date": "18-Jun",
                "site": "德福廣場",
                "task_content": "一支鏡望巴士站冇畫面",
                "missing_type": "inspection_result",
                "record": "Brian 17-Jun 23:00: 德福廣場一支鏡望巴士站冇畫面，已同現場講明日例檢跟進",
                }
            )
        )

        self.assertIn("咩情況? 有冇檢查結果?", response["message"])


if __name__ == "__main__":
    unittest.main()
