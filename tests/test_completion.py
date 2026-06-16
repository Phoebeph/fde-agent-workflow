import unittest

from app.services.completion import apply_schedule_completion, schedule_gap_analysis


class CompletionTests(unittest.TestCase):
    def test_completed_schedule_with_required_attachments(self) -> None:
        analysis = apply_schedule_completion(
            analysis={"completion_status": "已完成", "missing_items": [], "next_actions": []},
            message={
                "sender": "Brian",
                "sent_at": "2026-06-10 11:00",
                "text": "商场B 门磁坏已更换，测试正常，照片和维修报告 PDF 已上传。",
                "attachment_hints": [{"type": "image"}, {"type": "pdf"}],
            },
            attachments=[{"attachment_type": "image"}, {"attachment_type": "pdf"}],
            schedules=[
                {
                    "id": 1,
                    "work_date": "2026-06-10",
                    "staff_name": "Brian",
                    "site": "商场B",
                    "task_text": "门磁坏更换维修，需照片记录和维修报告 PDF",
                }
            ],
        )

        self.assertEqual(analysis["completion_status"], "已完成")
        self.assertEqual(analysis["completion_score"], 100)
        self.assertEqual(analysis["completion_level"], "高")
        self.assertEqual(analysis["work_schedule_id"], 1)

    def test_missing_required_pdf_changes_status_to_insufficient(self) -> None:
        analysis = apply_schedule_completion(
            analysis={"completion_status": "已完成", "missing_items": [], "next_actions": []},
            message={
                "sender": "Casey",
                "sent_at": "2026-06-10 13:00",
                "text": "商场C 读卡器无反应已更换火牛，测试正常，维修报告 PDF 后补。",
                "attachment_hints": [{"type": "image"}],
            },
            attachments=[{"attachment_type": "image"}],
            schedules=[
                {
                    "id": 2,
                    "work_date": "2026-06-10",
                    "staff_name": "Casey",
                    "site": "商场C",
                    "task_text": "读卡器维修，需照片记录和维修报告 PDF",
                }
            ],
        )

        self.assertEqual(analysis["completion_status"], "资料不足")
        self.assertIn("维修报告 PDF", analysis["missing_items"])
        self.assertLess(analysis["completion_score"], 85)
        self.assertEqual(analysis["completion_level"], "较高")

    def test_unfinished_work_is_followup_even_when_evidence_is_missing(self) -> None:
        analysis = apply_schedule_completion(
            analysis={"completion_status": "已完成", "missing_items": [], "next_actions": []},
            message={
                "sender": "Casey",
                "sent_at": "2026-06-10 13:00",
                "text": "商场C 弱电线路已到场检查，暂时未完成，需要继续安排跟进和报价，路线图稍后补。",
                "attachment_hints": [{"type": "image"}],
            },
            attachments=[{"attachment_type": "image"}],
            schedules=[
                {
                    "id": 6,
                    "work_date": "2026-06-10",
                    "staff_name": "Casey",
                    "site": "商场C",
                    "task_text": "弱电线路故障，需要检查路线并提交路线图、照片记录和维修报告 PDF",
                }
            ],
        )

        self.assertEqual(analysis["completion_status"], "需要跟进")
        self.assertLess(analysis["completion_score"], 50)

    def test_evidence_filters_contradicted_ai_missing_items(self) -> None:
        analysis = apply_schedule_completion(
            analysis={
                "completion_status": "资料不足",
                "missing_items": [
                    "未在 ELV Group 汇报当日工作结果",
                    "未明确维修报告是否已签",
                    "照片记录未明确区分换前、换中、换后",
                    "未注明物料来源",
                ],
                "next_actions": [
                    "请将工作结果汇报至 ELV Group",
                    "请确认维修报告是否已签",
                    "请补充换前、换中、换后照片",
                    "请注明物料来源",
                ],
            },
            message={
                "sender": "Brian",
                "sent_at": "2026-06-10 11:00",
                "text": "商场B 门磁坏已更换，测试正常，工作已完成。照片和维修报告 PDF 已上传。",
                "attachment_hints": [{"type": "image"}, {"type": "pdf"}],
            },
            attachments=[{"attachment_type": "image"}, {"attachment_type": "pdf"}],
            schedules=[
                {
                    "id": 4,
                    "work_date": "2026-06-10",
                    "staff_name": "Brian",
                    "site": "商场B",
                    "task_text": "门磁坏更换维修，需照片记录和维修报告 PDF",
                }
            ],
        )

        self.assertNotIn("未在 ELV Group 汇报当日工作结果", analysis["missing_items"])
        self.assertNotIn("未明确维修报告是否已签", analysis["missing_items"])
        self.assertIn("照片记录未明确区分换前、换中、换后", analysis["missing_items"])
        self.assertGreaterEqual(analysis["completion_score"], 75)
        self.assertEqual(analysis["completion_level"], "较高")

    def test_three_images_satisfy_before_during_after_photo_record(self) -> None:
        analysis = apply_schedule_completion(
            analysis={
                "completion_status": "资料不足",
                "missing_items": ["换前照片", "换中照片", "换后照片"],
                "next_actions": ["补充更换前、更换中、更换后照片"],
            },
            message={
                "sender": "Brian",
                "sent_at": "2026-06-10 11:00",
                "text": "商场B 门磁坏已更换，测试正常，工作已完成。照片和维修报告 PDF 已上传。",
                "attachment_hints": [{"type": "image"}, {"type": "image"}, {"type": "image"}, {"type": "pdf"}],
            },
            attachments=[
                {"attachment_type": "image"},
                {"attachment_type": "image"},
                {"attachment_type": "image"},
                {"attachment_type": "pdf"},
            ],
            schedules=[
                {
                    "id": 5,
                    "work_date": "2026-06-10",
                    "staff_name": "Brian",
                    "site": "商场B",
                    "task_text": "门磁坏更换维修，需照片记录和维修报告 PDF",
                }
            ],
        )

        self.assertEqual(analysis["missing_items"], [])
        self.assertEqual(analysis["completion_status"], "已完成")
        self.assertEqual(analysis["completion_score"], 100)

    def test_schedule_gap_analysis_marks_unreplied(self) -> None:
        analysis = schedule_gap_analysis(
            {
                "id": 3,
                "work_date": "2026-06-10",
                "staff_name": "Evan",
                "site": "商场E",
                "task_text": "车闸维修检查",
            }
        )

        self.assertEqual(analysis["completion_status"], "未回复")
        self.assertEqual(analysis["completion_score"], 0)
        self.assertEqual(analysis["completion_level"], "低")
        self.assertIn("工作结果回复", analysis["missing_items"])


if __name__ == "__main__":
    unittest.main()
