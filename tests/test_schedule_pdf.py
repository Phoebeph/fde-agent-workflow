import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.services.customer_config import CustomerSite
from app.services.schedule_pdf import (
    discover_schedule_pdfs,
    normalize_schedule_rows,
    sync_daily_schedule_pdf,
)
from app.services.site_policy import ConfiguredSitePolicy


class _FakeDb:
    def __init__(self) -> None:
        self.documents = {}
        self.finished = []
        self.rows = []

    def get_schedule_document_by_hash(self, work_date, digest):
        return self.documents.get((work_date, digest))

    def start_schedule_document(self, document):
        document_id = len(self.documents) + 1
        self.documents[(document["work_date"], document["sha256"])] = {
            "id": document_id,
            "status": "processing",
        }
        return document_id

    def finish_schedule_document(self, document_id, **fields):
        self.finished.append((document_id, fields))
        for document in self.documents.values():
            if document["id"] == document_id:
                document.update(fields)

    def replace_daily_pdf_schedules(self, document_id, work_date, rows):
        self.rows = rows
        return {"inserted": len(rows), "kept": 0, "deactivated": 0}


class _FakeDeepSeek:
    enabled = True

    def parse_daily_schedule(self, **kwargs):
        return [
            {
                "staff_name": "kei alias",
                "shift": "AM",
                "site": "Site A",
                "task_text": "Site A 例检",
                "confidence": 0.95,
            },
            {
                "staff_name": "Off Staff",
                "shift": "PM",
                "site": "Site A",
                "task_text": "AL",
                "is_leave": True,
            },
            {
                "staff_name": "Unknown",
                "shift": "PM",
                "site": "Unknown Site",
                "task_text": "维修",
            },
        ]


class _DisabledDeepSeek:
    enabled = False


class DailySchedulePdfTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = ConfiguredSitePolicy(
            [CustomerSite(id="site_a", name="配置地点A", aliases=["Site A"], enabled=True)]
        )

    def test_discovery_accepts_misspelling_and_uses_latest_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            older = root / "Work Schedule v1.pdf"
            newer = root / "WORKSCHEdual-final.PDF"
            ignored = root / "report.pdf"
            for path in (older, newer, ignored):
                path.write_bytes(b"pdf")
            os.utime(older, ns=(1_000_000_000, 1_000_000_000))
            os.utime(newer, ns=(2_000_000_000, 2_000_000_000))

            files = discover_schedule_pdfs(root, ["work schedule", "work schedual"])

            self.assertEqual(files, [newer, older])

    def test_normalization_forces_directory_date_and_rejects_leave_and_unknown_site(self) -> None:
        rows, rejected = normalize_schedule_rows(
            _FakeDeepSeek().parse_daily_schedule(),
            work_date="2026-07-17",
            source_file="schedule.pdf",
            site_policy=self.policy,
            resolve_staff_name=lambda name: "Kei" if name == "kei alias" else name,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rejected, 2)
        self.assertEqual(rows[0]["work_date"], "2026-07-17")
        self.assertEqual(rows[0]["staff_name"], "Kei")
        self.assertEqual(rows[0]["site"], "配置地点A")
        self.assertEqual(rows[0]["source_type"], "daily_pdf")

    def test_sync_returns_no_file_without_calling_ai(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = sync_daily_schedule_pdf(
                db=_FakeDb(),
                deepseek=_FakeDeepSeek(),
                data_root=Path(temp_dir),
                work_date="2026-07-17",
                enabled=True,
                filename_keywords=["work schedule"],
                site_policy=self.policy,
                resolve_staff_name=lambda name: name,
            )

        self.assertEqual(result["status"], "no_file")
        self.assertEqual(result["candidate_files"], [])

    def test_successful_sync_imports_once_then_hash_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf = Path(temp_dir) / "2026" / "07" / "17" / "Work Schedule.pdf"
            pdf.parent.mkdir(parents=True)
            pdf.write_bytes(b"fake-pdf-content")
            db = _FakeDb()
            with patch(
                "app.services.schedule_pdf.extract_pdf_layout_text",
                return_value=("valid schedule text " * 10, 1),
            ):
                first = sync_daily_schedule_pdf(
                    db=db,
                    deepseek=_FakeDeepSeek(),
                    data_root=Path(temp_dir),
                    work_date="2026-07-17",
                    enabled=True,
                    filename_keywords=["work schedule"],
                    site_policy=self.policy,
                    resolve_staff_name=lambda name: "Kei" if name == "kei alias" else name,
                )
                second = sync_daily_schedule_pdf(
                    db=db,
                    deepseek=_FakeDeepSeek(),
                    data_root=Path(temp_dir),
                    work_date="2026-07-17",
                    enabled=True,
                    filename_keywords=["work schedule"],
                    site_policy=self.policy,
                    resolve_staff_name=lambda name: name,
                )

        self.assertEqual(first["status"], "imported")
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["status"], "unchanged")

    def test_textless_pdf_is_marked_ocr_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf = Path(temp_dir) / "2026" / "07" / "17" / "workschedual.pdf"
            pdf.parent.mkdir(parents=True)
            pdf.write_bytes(b"fake")
            db = _FakeDb()
            with patch("app.services.schedule_pdf.extract_pdf_layout_text", return_value=("", 1)):
                result = sync_daily_schedule_pdf(
                    db=db,
                    deepseek=_FakeDeepSeek(),
                    data_root=Path(temp_dir),
                    work_date="2026-07-17",
                    enabled=True,
                    filename_keywords=["work schedual"],
                    site_policy=self.policy,
                    resolve_staff_name=lambda name: name,
                )

        self.assertEqual(result["status"], "ocr_required")
        self.assertEqual(db.finished[-1][1]["status"], "ocr_required")

    def test_ai_unavailable_does_not_import_schedule_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf = Path(temp_dir) / "2026" / "07" / "17" / "Work Schedule.pdf"
            pdf.parent.mkdir(parents=True)
            pdf.write_bytes(b"fake")
            db = _FakeDb()
            with patch(
                "app.services.schedule_pdf.extract_pdf_layout_text",
                return_value=("valid schedule text " * 10, 1),
            ):
                result = sync_daily_schedule_pdf(
                    db=db,
                    deepseek=_DisabledDeepSeek(),
                    data_root=Path(temp_dir),
                    work_date="2026-07-17",
                    enabled=True,
                    filename_keywords=["work schedule"],
                    site_policy=self.policy,
                    resolve_staff_name=lambda name: name,
                )

        self.assertEqual(result["status"], "ai_unavailable")
        self.assertEqual(db.rows, [])


if __name__ == "__main__":
    unittest.main()
