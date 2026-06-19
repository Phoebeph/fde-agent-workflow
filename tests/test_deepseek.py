import unittest

from app.services.deepseek import normalize_analysis, normalize_analysis_items, split_work_item_text


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

    def test_split_work_item_text_extracts_multiple_jobs(self) -> None:
        items = split_work_item_text(
            "The SOUI\n\n"
            "Tv wall 3(LG cam 198)disconnect,重新config後正常\n"
            "LG 08鋪旁電子門失靈（LG06),更換工程部提供火牛後正常\n"
            "LG09鋪旁電子門失靈（LG07)更換工程部提供火牛及Atal 電鎖後正常，電鎖後補報價\n"
            "G/F 03 cam,因天氣未能跟進\n"
            "LCP pos 草地speakers 因天氣未能跟進，料已放control"
        )

        self.assertEqual(len(items), 5)
        self.assertTrue(all(item.startswith("The SOUI") for item in items))
        self.assertIn("LG09", items[2])

    def test_normalize_analysis_items_splits_when_model_returns_single_object(self) -> None:
        items = normalize_analysis_items(
            {"completion_status": "待人工确认", "summary": "多个项目"},
            {
                "sender": "num5",
                "sent_at": "2026-06-19T10:35:00+08:00",
                "text": (
                    "The SOUI\n"
                    "Tv wall 3(LG cam 198)disconnect,重新config後正常\n"
                    "G/F 03 cam,因天氣未能跟進"
                ),
            },
            [],
            [],
        )

        self.assertEqual(len(items), 2)
        self.assertIn("tv wall", items[0]["summary"].lower())
        self.assertEqual(items[1]["completion_status"], "需要跟进")


if __name__ == "__main__":
    unittest.main()
