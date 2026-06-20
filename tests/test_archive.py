from pathlib import Path
import unittest

from app.services.archive import archive_attachment, safe_part


class ArchiveTests(unittest.TestCase):
    def test_safe_part_removes_path_unsafe_chars(self) -> None:
        self.assertEqual(safe_part("商场/LY: A?", "fallback"), "商场_LY_A")

    def test_archive_attachment_copies_with_structured_name(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "temp report.PDF"
            source.write_bytes(b"pdf-bytes")

            archived = archive_attachment(
                str(source),
                tmp_path / "archive",
                original_filename="report.PDF",
                work_date="2026-06-10",
                site="商场LY",
                staff_name="Kei",
                work_type="maintenance",
                attachment_type="pdf",
            )

            target = Path(archived.archive_path)
            self.assertTrue(target.exists())
            self.assertEqual(target.read_bytes(), b"pdf-bytes")
            self.assertEqual(target.parent.parts[-4:], ("2026", "06", "10", "商场LY"))
            self.assertIn("2026-06-10_商场LY_Kei_maintenance_pdf", target.name)
            self.assertEqual(archived.archive_filename, target.name)
            self.assertTrue(archived.sha256)
            self.assertEqual(archived.size_bytes, len(b"pdf-bytes"))


if __name__ == "__main__":
    unittest.main()
