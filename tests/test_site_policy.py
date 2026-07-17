import unittest

from app.services.customer_config import (
    CustomerSettings,
    CustomerSite,
    CustomerWhatsAppConfig,
    CustomerWhatsAppGroup,
)
from app.services.site_policy import ConfiguredSitePolicy, business_categories


class SitePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = CustomerSettings(
            whatsapp=CustomerWhatsAppConfig(
                groups=[
                    CustomerWhatsAppGroup(
                        id="group_a",
                        name="维修群",
                        related_site_ids=["site_a", "site_b", "site_c"],
                    )
                ]
            ),
            sites=[
                CustomerSite(id="site_a", name="地点A", aliases=["Alpha", "Common"]),
                CustomerSite(id="site_b", name="地点B", aliases=["Beta", "Common"]),
                CustomerSite(id="site_c", name="地点C", aliases=["Gamma"]),
                CustomerSite(id="site_other", name="其他地点", aliases=["Other"]),
            ],
            loaded=True,
        )

    def test_policy_uses_group_sites_and_rejects_ambiguous_alias(self) -> None:
        policy = ConfiguredSitePolicy.for_group(self.settings, "维修群")

        self.assertEqual(policy.resolve("Alpha 已完成维修").site_name, "地点A")
        self.assertEqual(policy.resolve("Common 需跟进").status, "unmatched")
        self.assertEqual(policy.resolve("Other 已完成").status, "unmatched")

    def test_split_handles_multiple_sites_in_one_message(self) -> None:
        policy = ConfiguredSitePolicy.for_group(self.settings, "维修群")

        segments = policy.split("Alpha 门禁已维修；Beta CCTV 需报价")

        self.assertEqual([item.site_name for item in segments], ["地点A", "地点B"])
        self.assertIn("维修", segments[0].text)
        self.assertIn("报价", segments[1].text)
        self.assertEqual(business_categories({}, segments[0].text), ["维修"])
        self.assertEqual(business_categories({}, segments[1].text), ["报价"])

    def test_split_consumes_date_for_only_the_immediately_following_site(self) -> None:
        policy = ConfiguredSitePolicy.for_group(self.settings, "维修群")

        segments = policy.split("15/7\nAlpha\n例检完成\nBeta\nCCTV 已维修")

        self.assertEqual([item.explicit_date_text for item in segments], ["15/7", ""])
        self.assertIn("15/7", segments[0].text)
        self.assertNotIn("15/7", segments[1].text)
        self.assertEqual(
            [item.source_segment_id for item in segments],
            ["site_segment_1", "site_segment_2"],
        )

    def test_split_moves_a_new_date_heading_to_the_next_site(self) -> None:
        policy = ConfiguredSitePolicy.for_group(self.settings, "维修群")

        segments = policy.split("15/7\nAlpha\n例检完成\n16/7\nBeta\nCCTV 已维修")

        self.assertEqual([item.explicit_date_text for item in segments], ["15/7", "16/7"])
        self.assertNotIn("16/7", segments[0].text)
        self.assertIn("16/7", segments[1].text)

    def test_split_supports_same_line_date_without_inheriting_it(self) -> None:
        policy = ConfiguredSitePolicy.for_group(self.settings, "维修群")

        segments = policy.split("15-7 Alpha 已维修；Beta 已维修")

        self.assertEqual([item.explicit_date_text for item in segments], ["15-7", ""])

    def test_split_supports_a_new_inline_date_before_the_next_site(self) -> None:
        policy = ConfiguredSitePolicy.for_group(self.settings, "维修群")

        segments = policy.split("15/7 Alpha 已维修；16/7 Beta CCTV 已维修")

        self.assertEqual([item.explicit_date_text for item in segments], ["15/7", "16/7"])
        self.assertNotIn("16/7", segments[0].text)
        self.assertIn("16/7", segments[1].text)

    def test_split_keeps_repeated_site_mentions_as_independent_segments(self) -> None:
        policy = ConfiguredSitePolicy.for_group(self.settings, "维修群")

        segments = policy.split("15/7 Alpha 门禁已维修；Alpha CCTV 已维修")

        self.assertEqual([item.site_name for item in segments], ["地点A", "地点A"])
        self.assertEqual([item.explicit_date_text for item in segments], ["15/7", ""])

    def test_split_discards_unknown_location_prefix_before_first_configured_site(self) -> None:
        policy = ConfiguredSitePolicy.for_group(self.settings, "维修群")

        segments = policy.split("15/7\nUnknown Site\n例检完成\nBeta\nCCTV 已维修")

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].site_name, "地点B")
        self.assertEqual(segments[0].explicit_date_text, "")
        self.assertEqual(segments[0].text, "Beta\nCCTV 已维修")

    def test_split_keeps_same_line_context_before_first_configured_site(self) -> None:
        policy = ConfiguredSitePolicy.for_group(self.settings, "维修群")

        segments = policy.split("已完成 Alpha 门禁维修")

        self.assertEqual(segments[0].text, "已完成 Alpha 门禁维修")

    def test_business_categories_support_mixed_item(self) -> None:
        categories = business_categories(
            {"work_type": "maintenance", "summary": "更换后正常，需后补报价"}
        )

        self.assertEqual(categories, ["维修", "报价"])


if __name__ == "__main__":
    unittest.main()
