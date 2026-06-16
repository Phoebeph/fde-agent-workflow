import unittest

from app.services.deepseek import normalize_analysis


class DeepSeekNormalizeTests(unittest.TestCase):
    def test_missing_items_prevent_completed_status(self) -> None:
        result = normalize_analysis(
            {
                "completion_status": "已完成",
                "missing_items": ["report_pdf"],
            },
            {"sent_at": "2026-06-10 15:30", "sender": "Kit", "text": "report PDF 后补"},
            [],
            [],
        )

        self.assertEqual(result["completion_status"], "资料不足")
        self.assertGreater(result["completion_score"], 0)
        self.assertEqual(result["completion_level"], "较高")
        self.assertIn("维修报告 PDF", result["reminder_text"])

    def test_traditional_status_is_normalized_to_simplified(self) -> None:
        result = normalize_analysis(
            {
                "completion_status": "資料不足",
                "missing_items": ["維修報告 PDF"],
                "next_actions": ["需要跟進"],
                "reminder_text": "@Kit 請補充/確認：維修報告 PDF",
            },
            {"sent_at": "2026-06-10 15:30", "sender": "Kit", "text": "report PDF 後補"},
            [],
            [],
        )

        self.assertEqual(result["completion_status"], "资料不足")
        self.assertEqual(result["missing_items"], ["维修报告 PDF"])
        self.assertEqual(result["next_actions"], ["需要跟进"])
        self.assertEqual(result["reminder_text"], "@Kit 请补充/确认：维修报告 PDF")
        self.assertEqual(result["completion_score"], 78)
        self.assertEqual(result["completion_level"], "较高")


if __name__ == "__main__":
    unittest.main()
