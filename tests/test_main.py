import unittest

from app.main import _analyze_configured_site_segments, _build_analysis_groups
from app.services.customer_config import CustomerSite
from app.services.site_policy import ConfiguredSitePolicy


class FakeSegmentDeepSeek:
    def __init__(self, item_count: int = 1) -> None:
        self.item_count = item_count
        self.calls = []

    def analyze_message_items(self, *, message, attachments, rules):
        self.calls.append(message)
        return [
            {
                "work_date": "2026-07-15",
                "staff_name": "Casey",
                "site": "AI guessed site",
                "work_type": "maintenance",
                "summary": f"{message['text']} item {index + 1}",
                "result": "已完成",
                "completion_status": "已完成",
                "missing_items": [],
                "next_actions": [],
            }
            for index in range(self.item_count)
        ]


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


class MainSiteSegmentAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = ConfiguredSitePolicy(
            [
                CustomerSite(id="site_6pp", name="6PP"),
                CustomerSite(id="site_east", name="East Apartments"),
            ]
        )

    def test_backend_overrides_ai_date_for_site_without_own_date(self) -> None:
        deepseek = FakeSegmentDeepSeek()

        analyses, segments = _analyze_configured_site_segments(
            message={
                "group_name": "维修群",
                "sender": "Casey",
                "sent_at": "2026-07-17T10:52:00+08:00",
                "text": "15/7\n6PP\n例檢完成\nEast Apartments\n門禁已更換正常",
            },
            attachments=[],
            rules=[],
            deepseek=deepseek,
            policy=self.policy,
        )

        self.assertEqual([item["work_date"] for item in analyses], ["2026-07-15", "2026-07-17"])
        self.assertEqual([item["site"] for item in analyses], ["6PP", "East Apartments"])
        self.assertEqual(len(segments), 2)
        self.assertEqual(
            [call["allowed_site_names"] for call in deepseek.calls],
            [["6PP"], ["East Apartments"]],
        )

    def test_all_undated_sites_use_archive_date(self) -> None:
        analyses, _ = _analyze_configured_site_segments(
            message={
                "group_name": "维修群",
                "sender": "Casey",
                "sent_at": "2026-07-17T10:52:00+08:00",
                "text": "6PP 例檢完成\nEast Apartments 門禁已維修",
            },
            attachments=[],
            rules=[],
            deepseek=FakeSegmentDeepSeek(),
            policy=self.policy,
        )

        self.assertEqual([item["work_date"] for item in analyses], ["2026-07-17", "2026-07-17"])

    def test_invalid_explicit_date_falls_back_to_archive_date(self) -> None:
        analyses, _ = _analyze_configured_site_segments(
            message={
                "group_name": "维修群",
                "sender": "Casey",
                "sent_at": "2026-07-17T10:52:00+08:00",
                "text": "32/7\n6PP\n例檢完成",
            },
            attachments=[],
            rules=[],
            deepseek=FakeSegmentDeepSeek(),
            policy=self.policy,
        )

        self.assertEqual(analyses[0]["work_date"], "2026-07-17")

    def test_multiple_items_in_one_site_share_its_explicit_date(self) -> None:
        analyses, _ = _analyze_configured_site_segments(
            message={
                "group_name": "维修群",
                "sender": "Casey",
                "sent_at": "2026-07-17T10:52:00+08:00",
                "text": "15/7\n6PP\n例檢完成\n門禁已維修並需報價",
            },
            attachments=[],
            rules=[],
            deepseek=FakeSegmentDeepSeek(item_count=2),
            policy=self.policy,
        )

        self.assertEqual([item["work_date"] for item in analyses], ["2026-07-15", "2026-07-15"])


if __name__ == "__main__":
    unittest.main()
