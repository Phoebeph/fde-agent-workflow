from pathlib import Path
import unittest

from app.services.archive import archive_attachment, mirror_attachment_for_category, safe_part


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
            by_site_target = tmp_path / "archive" / "by_site" / "商场LY" / "2026" / "06" / "10" / target.name
            self.assertTrue(by_site_target.exists())
            self.assertEqual(by_site_target.read_bytes(), b"pdf-bytes")
            self.assertTrue(archived.sha256)
            self.assertEqual(archived.size_bytes, len(b"pdf-bytes"))

    def test_mirror_attachment_uses_site_first_category_path(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.jpg"
            source.write_bytes(b"image")

            mirrored = mirror_attachment_for_category(
                str(source),
                root / "data",
                work_date="2026-07-17",
                site="地点A",
                business_category="维修",
                attachment_type="image",
            )

            target = Path(mirrored.archive_path)
            self.assertEqual(target.parts[-8:], ("by_site", "地点A", "2026", "07", "17", "维修", "图片", "source.jpg"))
            self.assertEqual(target.read_bytes(), b"image")
            self.assertFalse((root / "data" / "地点A").exists())


if __name__ == "__main__":
    unittest.main()
