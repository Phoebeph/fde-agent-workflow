from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from app.services.local_export import export_daily_workbook


class FakeExportDatabase:
    def list_export_repair_records(self, work_date: str, site: str | None = None) -> list[dict[str, object]]:
        records = [
            {
                "id": 1,
                "work_date": work_date,
                "staff_name": "Brian",
                "site": "The SOUI",
                "work_type": "maintenance",
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
                "work_date": work_date,
                "staff_name": "Brian",
                "site": "新村",
                "work_type": "maintenance",
                "summary": "Mon3 cam5 需调教路线",
                "result": "天雨未完成",
                "completion_status": "需要跟进",
                "completion_score": 34,
                "missing_items": ["照片"],
                "next_actions": ["天晴后跟进"],
                "whatsapp_sent_at": f"{work_date}T10:33:00+08:00",
                "whatsapp_text": "Mon3 cam5",
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
        return records

    def list_export_reminders(self, work_date: str, site: str | None = None) -> list[dict[str, object]]:
        reminders = [
            {
                "id": 1,
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
            }
        ]
        return [reminder for reminder in reminders if site is None or reminder["site"] == site]


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

            with ZipFile(total_path) as workbook:
                workbook_xml = workbook.read("xl/workbook.xml").decode("utf-8")
            self.assertIn("维修记录", workbook_xml)
            self.assertIn("附件检查", workbook_xml)
            self.assertIn("提醒记录", workbook_xml)


if __name__ == "__main__":
    unittest.main()
