import unittest

from app.services.deepseek import (
    infer_work_date_from_text,
    normalize_analysis,
    normalize_analysis_items,
    split_work_item_text,
)


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

    def test_split_work_item_text_merges_checklist_and_weather_detail_lines(self) -> None:
        checklist_items = split_work_item_text(
            "17/6\n\n海明例檢完成\n\nChecklist已簽\n\n"
            "18/6\n\n海灣例檢完成\n\n5月checklist已交俾工程部"
        )
        weather_items = split_work_item_text(
            "18/6 新村\n\n"
            "G807 更換對講機 更換後測試正常\n"
            "Mon3 cam5 轉轉鏡 需再調教路線\n"
            "因天雨關係 需再跟進"
        )

        self.assertEqual(checklist_items, [
            "17/6 海明例檢完成，Checklist已簽",
            "18/6 海灣例檢完成，5月checklist已交俾工程部",
        ])
        self.assertEqual(len(weather_items), 2)
        self.assertIn("因天雨關係", weather_items[1])

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

    def test_normalize_analysis_items_appends_model_missing_split_items(self) -> None:
        items = normalize_analysis_items(
            {
                "items": [
                    {
                        "work_date": "2026-06-18",
                        "staff_name": "num5",
                        "site": "G807",
                        "work_type": "maintenance",
                        "summary": "G807 更换对讲机",
                        "result": "更换后测试正常",
                        "completion_status": "已完成",
                    },
                    {
                        "work_date": "2026-06-18",
                        "staff_name": "num5",
                        "site": "R座",
                        "work_type": "maintenance",
                        "summary": "R座 重新过资料",
                        "result": "等客试",
                        "completion_status": "需要跟进",
                    },
                ]
            },
            {
                "sender": "num5",
                "sent_at": "2026-06-19T10:33:00+08:00",
                "text": (
                    "18/6 新村\n"
                    "G807 更換對講機 更換後測試正常\n"
                    "R座 有客加新卡拍唔到8達通 重新過資料後等客試\n"
                    "Mon3 cam5 轉轉鏡 需再調教路線"
                ),
            },
            [],
            [],
        )

        self.assertEqual(len(items), 3)
        self.assertIn("Mon3", items[2]["summary"])

    def test_infer_work_date_from_text_uses_message_year(self) -> None:
        self.assertEqual(
            infer_work_date_from_text("17/6 LPP 例檢完成", "2026-06-20"),
            "2026-06-17",
        )


if __name__ == "__main__":
    unittest.main()
