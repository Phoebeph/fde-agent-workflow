import unittest

from app.main import _build_analysis_groups


class MainMessageGroupingTests(unittest.TestCase):
    def test_build_analysis_groups_merges_same_sender_messages_within_three_minutes(self) -> None:
        groups = _build_analysis_groups(
            [
                {
                    "id": 1,
                    "group_name": "维修群",
                    "sender": "Casey",
                    "sent_at": "2026-06-27T10:00:00+08:00",
                    "text": "商场C CCTV 已处理",
                    "attachment_hints": [],
                    "has_attachments": False,
                    "message_fingerprint": "a" * 64,
                },
                {
                    "id": 2,
                    "group_name": "维修群",
                    "sender": "Casey",
                    "sent_at": "2026-06-27T10:02:00+08:00",
                    "text": "维修报告 PDF 后补",
                    "attachment_hints": [],
                    "has_attachments": False,
                    "message_fingerprint": "b" * 64,
                },
            ]
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["messages"]), 2)
        self.assertEqual(
            groups[0]["merged_message"]["text"],
            "商场C CCTV 已处理\n维修报告 PDF 后补",
        )

    def test_build_analysis_groups_merges_different_sites_for_same_sender_within_three_minutes(self) -> None:
        groups = _build_analysis_groups(
            [
                {
                    "id": 1,
                    "group_name": "维修群",
                    "sender": "Casey",
                    "sent_at": "2026-06-27T10:00:00+08:00",
                    "text": "商场C CCTV 已处理",
                    "attachment_hints": [],
                    "has_attachments": False,
                    "message_fingerprint": "a" * 64,
                },
                {
                    "id": 2,
                    "group_name": "维修群",
                    "sender": "Casey",
                    "sent_at": "2026-06-27T10:02:00+08:00",
                    "text": "商场D 门禁已处理",
                    "attachment_hints": [],
                    "has_attachments": False,
                    "message_fingerprint": "b" * 64,
                },
            ]
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["messages"]), 2)
        self.assertEqual(
            groups[0]["merged_message"]["text"],
            "商场C CCTV 已处理\n商场D 门禁已处理",
        )


if __name__ == "__main__":
    unittest.main()
