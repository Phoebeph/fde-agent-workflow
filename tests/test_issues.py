import unittest

from app.services.issues import issue_candidate_from_message, issue_schedule_match_score


class IssueDetectionTests(unittest.TestCase):
    def test_ordinary_member_problem_becomes_issue_candidate(self) -> None:
        issue = issue_candidate_from_message(
            {
                "id": 1,
                "sender": "Brian",
                "sent_at": "2026-06-12 10:30",
                "text": "商场41 控制室 CCTV mon 又闪，客户说需要处理。",
            },
            dispatch_manager_senders=("Dicky Company",),
            followup_manager_senders=("Henry atl",),
        )

        self.assertIsNotNone(issue)
        self.assertEqual(issue["reported_by"], "Brian")
        self.assertEqual(issue["site"], "商场41")
        self.assertIn("CCTV", issue["issue_summary"])

    def test_dispatch_manager_message_is_not_issue_candidate(self) -> None:
        issue = issue_candidate_from_message(
            {
                "id": 2,
                "sender": "Dicky Company",
                "sent_at": "2026-06-12 10:30",
                "text": "商场41 控制室 CCTV mon 又闪，客户说需要处理。",
            },
            dispatch_manager_senders=("Dicky Company",),
            followup_manager_senders=("Henry atl",),
        )

        self.assertIsNone(issue)

    def test_completion_report_is_not_issue_candidate(self) -> None:
        issue = issue_candidate_from_message(
            {
                "id": 3,
                "sender": "Brian",
                "sent_at": "2026-06-12 10:30",
                "text": "商场41 CCTV 故障已处理，测试正常。",
            },
            dispatch_manager_senders=("Dicky Company",),
            followup_manager_senders=("Henry atl",),
        )

        self.assertIsNone(issue)

    def test_issue_schedule_match_requires_site_and_keyword_overlap(self) -> None:
        score = issue_schedule_match_score(
            {
                "site": "商场41",
                "issue_text": "商场41 控制室 CCTV mon 又闪",
                "issue_summary": "商场41 CCTV mon 闪",
            },
            {
                "site": "商场41",
                "task_text": "安排 Lin 检查控制室 CCTV mon 闪烁问题",
            },
        )
        mismatch = issue_schedule_match_score(
            {
                "site": "商场41",
                "issue_text": "商场41 控制室 CCTV mon 又闪",
                "issue_summary": "商场41 CCTV mon 闪",
            },
            {
                "site": "商场52",
                "task_text": "安排 Lin 检查控制室 CCTV mon 闪烁问题",
            },
        )

        self.assertGreaterEqual(score, 7)
        self.assertEqual(mismatch, 0)


if __name__ == "__main__":
    unittest.main()
