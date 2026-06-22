import unittest

from app.services.diagnostics import build_location_coverage_report, infer_location_from_item


class DiagnosticsTests(unittest.TestCase):
    def test_infer_location_from_item(self) -> None:
        self.assertEqual(infer_location_from_item("The SOUI Tv wall 3 disconnect"), "The SOUI")
        self.assertEqual(infer_location_from_item("18/6 新村 G807 更換對講機"), "新村")
        self.assertEqual(infer_location_from_item("Trk house qr code 偶爾失靈"), "Trk house")
        self.assertEqual(infer_location_from_item("Checklist已簽"), "")

    def test_build_location_coverage_report_finds_missing_locations(self) -> None:
        report = build_location_coverage_report(
            messages=[
                {
                    "id": 1,
                    "sent_at": "2026-06-19T10:35:00+08:00",
                    "sender": "num5",
                    "text": "The SOUI\nTv wall 3 disconnect,重新config後正常",
                },
                {
                    "id": 2,
                    "sent_at": "2026-06-19T10:33:00+08:00",
                    "sender": "num5",
                    "text": "18/6 新村\nG807 更換對講機 更換後測試正常",
                },
            ],
            repair_records=[
                {
                    "id": 10,
                    "site": "The SOUI",
                    "summary": "Tv wall 3 disconnect",
                    "result": "正常",
                    "completion_status": "已完成",
                }
            ],
        )

        self.assertEqual(report["raw_locations"], ["The SOUI", "新村"])
        self.assertEqual(report["record_locations"], ["The SOUI"])
        self.assertEqual(report["possibly_missing_locations"], ["新村"])


if __name__ == "__main__":
    unittest.main()
