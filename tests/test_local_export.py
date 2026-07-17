from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from app.services.local_export import export_daily_workbook, export_site_classified_workbooks


class FakeExportDatabase:
    def list_export_repair_records(self, work_date: str, site: str | None = None) -> list[dict[str, object]]:
        records = [
            {
                "id": 1,
                "export_date": work_date,
                "work_date": "2026-06-15",
                "staff_name": "Brian",
                "site": "The SOUI",
                "work_type": "maintenance",
                "business_category": "维修",
                "summary": "TV wall 重新 config",
                "result": "正常",
                "completion_status": "已完成",
                "completion_score": 100,
                "missing_items": [],
                "next_actions": [],
                "whatsapp_sent_at": f"{work_date}T10:35:00+08:00",
                "whatsapp_text": "TV wall 正常",
            },
            {
                "id": 2,
                "export_date": work_date,
                "work_date": work_date,
                "staff_name": "Brian",
                "site": "新村",
                "work_type": "maintenance",
                "business_category": "维修",
                "summary": "Mon3 cam5 需调教路线",
                "result": "天雨未完成",
                "completion_status": "需要跟进",
                "completion_score": 34,
                "missing_items": ["照片"],
                "next_actions": ["天晴后跟进"],
                "whatsapp_sent_at": f"{work_date}T10:33:00+08:00",
                "whatsapp_text": "Mon3 cam5",
            },
            {
                "id": 3,
                "export_date": work_date,
                "work_date": work_date,
                "staff_name": "Brian",
                "site": "The SOUI",
                "work_type": "quotation",
                "business_category": "报价",
                "summary": "电锁需报价",
                "result": "待报价",
                "completion_status": "需要跟进",
                "completion_score": 40,
                "missing_items": [],
                "next_actions": ["准备报价"],
                "whatsapp_sent_at": f"{work_date}T11:00:00+08:00",
                "whatsapp_text": "The SOUI 电锁需报价",
            },
        ]
        return [record for record in records if site is None or record["site"] == site]

    def list_export_attachment_checks(self, work_date: str, site: str | None = None) -> list[dict[str, object]]:
        records = self.list_export_repair_records(work_date, site)
        for record in records:
            record["attachments"] = [
                {
                    "archive_filename": "2026-06-19_The_SOUI_Brian_maintenance_image_abcd.jpg",
                    "archive_path": "C:/Users/test/data/2026/06/19/The_SOUI/photo.jpg",
                }
            ] if record["site"] == "The SOUI" else []
            record["category_archives"] = [
                {
                    "archive_filename": f"{record['business_category']}.jpg",
                    "archive_path": f"C:/data/{record['site']}/{work_date}/{record['business_category']}.jpg",
                    "business_category": record["business_category"],
                }
            ]
        return records

    def list_export_reminders(self, work_date: str, site: str | None = None) -> list[dict[str, object]]:
        reminders = [
            {
                "id": 1,
                "export_date": work_date,
                "work_date": work_date,
                "site": "新村",
                "staff_name": "Brian",
                "target_name": "Brian",
                "reason": "照片",
                "content": "@Brian 请补充照片",
                "status": "pending",
                "sent_at": None,
                "resolved_at": None,
                "summary": "Mon3 cam5 需调教路线",
                "business_category": "维修",
            }
        ]
        return [reminder for reminder in reminders if site is None or reminder["site"] == site]

    def list_export_repair_records_for_year(self, year: str, site: str) -> list[dict[str, object]]:
        return self.list_export_repair_records(f"{year}-06-19", site)

    def list_export_attachment_checks_for_year(self, year: str, site: str) -> list[dict[str, object]]:
        return self.list_export_attachment_checks(f"{year}-06-19", site)

    def list_export_reminders_for_year(self, year: str, site: str) -> list[dict[str, object]]:
        return self.list_export_reminders(f"{year}-06-19", site)


class LocalExportTests(unittest.TestCase):
    def test_export_daily_workbook_writes_total_and_site_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = export_daily_workbook(
                db=FakeExportDatabase(),
                work_date="2026-06-19",
                export_root=Path(temp_dir),
            )

            total_path = Path(result.total_path)
            self.assertTrue(total_path.exists())
            self.assertEqual(total_path.parts[-4:], ("2026", "06", "19", "2026-06-19_维修与提醒总表.xlsx"))
            self.assertEqual(len(result.site_paths), 2)
            self.assertTrue(any("The_SOUI" in path for path in result.site_paths))
            self.assertTrue(any("新村" in path for path in result.site_paths))
            for site_path in result.site_paths:
                path = Path(site_path)
                site = path.parent.name
                by_site_copy = (
                    Path(temp_dir)
                    / "by_site"
                    / site
                    / "2026"
                    / "06"
                    / "19"
                    / path.name
                )
                self.assertTrue(by_site_copy.exists())

            with ZipFile(total_path) as workbook:
                workbook_xml = workbook.read("xl/workbook.xml").decode("utf-8")
                sheet_xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
            self.assertIn("维修记录", workbook_xml)
            self.assertIn("附件检查", workbook_xml)
            self.assertIn("提醒记录", workbook_xml)
            self.assertIn("归档日期", sheet_xml)
            self.assertIn("实际工作日期", sheet_xml)
            self.assertIn("备注", sheet_xml)
            self.assertIn(
                "2026-06-19 记录的其他日期工作：实际工作日期 2026-06-15",
                sheet_xml,
            )

    def test_site_classified_exports_keep_site_first_daily_and_annual_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = export_site_classified_workbooks(
                db=FakeExportDatabase(),
                work_date="2026-06-19",
                output_root=Path(temp_dir),
            )

            repair_path = Path(temp_dir) / "by_site" / "The_SOUI" / "2026" / "06" / "19" / "维修" / "The_SOUI_2026-06-19_维修.xlsx"
            quotation_path = Path(temp_dir) / "by_site" / "The_SOUI" / "2026" / "06" / "19" / "报价" / "The_SOUI_2026-06-19_报价.xlsx"
            annual_path = Path(temp_dir) / "by_site" / "The_SOUI" / "2026" / "The_SOUI_2026_总表.xlsx"
            self.assertTrue(repair_path.exists())
            self.assertTrue(quotation_path.exists())
            self.assertTrue(annual_path.exists())
            self.assertFalse((Path(temp_dir) / "The_SOUI").exists())
            self.assertIn(str(repair_path), result.daily_paths)
            with ZipFile(annual_path) as workbook:
                workbook_xml = workbook.read("xl/workbook.xml").decode("utf-8")
            self.assertIn("维修汇总", workbook_xml)
            self.assertIn("报价汇总", workbook_xml)
            self.assertIn("附件索引", workbook_xml)
            self.assertIn("提醒汇总", workbook_xml)


if __name__ == "__main__":
    unittest.main()
