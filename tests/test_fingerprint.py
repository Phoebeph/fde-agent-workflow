import unittest

from app.services.fingerprint import message_fingerprint, normalize_text


class FingerprintTests(unittest.TestCase):
    def test_normalize_text_collapses_whitespace(self) -> None:
        self.assertEqual(normalize_text("  A\n\n B\tC  "), "A B C")

    def test_message_fingerprint_is_stable(self) -> None:
        first = message_fingerprint(
            "维修群",
            "Kei",
            "2026-06-10 18:00",
            "商场LY 例检完成",
            attachment_hints=[{"type": "image"}],
        )
        second = message_fingerprint(
            "维修群",
            "Kei",
            "2026-06-10 18:00",
            " 商场LY   例检完成 ",
            attachment_hints=[{"type": "image"}],
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)


if __name__ == "__main__":
    unittest.main()
