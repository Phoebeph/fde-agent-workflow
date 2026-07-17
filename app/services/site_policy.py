from __future__ import annotations

from dataclasses import dataclass
import re

from app.services.customer_config import CustomerSettings, CustomerSite


REPAIR_CATEGORY = "维修"
QUOTATION_CATEGORY = "报价"
BUSINESS_CATEGORIES = (REPAIR_CATEGORY, QUOTATION_CATEGORY)

_DATE_TOKEN_PATTERN = r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?"
_DATE_ONLY_LINE_RE = re.compile(
    rf"^[ \t]*(?P<date>{_DATE_TOKEN_PATTERN})[ \t]*$",
    re.MULTILINE,
)
_TRAILING_INLINE_DATE_RE = re.compile(
    rf"(?:^|[ \t,;，；|])(?P<date>{_DATE_TOKEN_PATTERN})[ \t]*$"
)

_QUOTE_MARKERS = (
    "报价",
    "報價",
    "quotation",
    "quote",
)
_REPAIR_MARKERS = (
    "维修",
    "維修",
    "更换",
    "更換",
    "检查",
    "檢查",
    "故障",
    "例检",
    "例檢",
    "测试",
    "測試",
    "修复",
    "修復",
    "maintenance",
    "repair",
    "fixed",
    "ad-hoc",
    "adhoc",
)


@dataclass(frozen=True)
class SiteMention:
    site_name: str
    matched_text: str
    start: int
    end: int


@dataclass(frozen=True)
class SiteResolution:
    status: str
    site_name: str = ""
    matched_text: str = ""


@dataclass(frozen=True)
class SiteSegment:
    source_segment_id: str
    site_name: str
    text: str
    explicit_date_text: str = ""


class ConfiguredSitePolicy:
    def __init__(self, sites: list[CustomerSite]):
        self.sites = list(sites)
        variants: dict[str, set[str]] = {}
        display_values: dict[str, str] = {}
        for site in self.sites:
            for raw_value in (site.name, *site.aliases):
                value = _compact(raw_value)
                if not value:
                    continue
                key = value.casefold()
                variants.setdefault(key, set()).add(site.name)
                display_values.setdefault(key, value)
        self._unique_variants = [
            (display_values[key], next(iter(names)))
            for key, names in variants.items()
            if len(names) == 1
        ]
        self._unique_variants.sort(key=lambda item: len(item[0]), reverse=True)

    @classmethod
    def for_group(cls, settings: CustomerSettings, group_name: str) -> "ConfiguredSitePolicy":
        return cls(settings.allowed_sites_for_group(group_name))

    def mentions(self, text: str) -> list[SiteMention]:
        source = str(text or "")
        candidates: list[SiteMention] = []
        for variant, site_name in self._unique_variants:
            flags = re.IGNORECASE if _is_ascii_variant(variant) else 0
            boundary = r"(?<![A-Za-z0-9])" if _is_ascii_variant(variant) else ""
            ending = r"(?![A-Za-z0-9])" if _is_ascii_variant(variant) else ""
            for match in re.finditer(f"{boundary}{re.escape(variant)}{ending}", source, flags):
                candidates.append(
                    SiteMention(
                        site_name=site_name,
                        matched_text=match.group(0),
                        start=match.start(),
                        end=match.end(),
                    )
                )
        candidates.sort(key=lambda item: (item.start, -(item.end - item.start), item.site_name))
        selected: list[SiteMention] = []
        for candidate in candidates:
            if any(candidate.start < item.end and candidate.end > item.start for item in selected):
                continue
            selected.append(candidate)
        return sorted(selected, key=lambda item: item.start)

    def resolve(self, text: str) -> SiteResolution:
        mentions = self.mentions(text)
        names = list(dict.fromkeys(item.site_name for item in mentions))
        if not names:
            return SiteResolution(status="unmatched")
        if len(names) > 1:
            return SiteResolution(status="ambiguous")
        first = next(item for item in mentions if item.site_name == names[0])
        return SiteResolution(
            status="matched",
            site_name=names[0],
            matched_text=first.matched_text,
        )

    def canonical_name(self, value: str | None) -> str:
        candidate = _compact(value)
        if not candidate:
            return ""
        normalized = candidate.casefold()
        exact_names = {site.name for site in self.sites if site.name.casefold() == normalized}
        if len(exact_names) == 1:
            return next(iter(exact_names))
        exact_alias_names = {
            site.name
            for site in self.sites
            if any(_compact(alias).casefold() == normalized for alias in site.aliases)
        }
        if len(exact_alias_names) == 1:
            return next(iter(exact_alias_names))
        return ""

    def split(self, text: str) -> list[SiteSegment]:
        source = str(text or "").strip()
        mentions = self.mentions(source)
        if not mentions:
            return []
        segment_starts: list[int] = []
        explicit_dates: list[str] = []
        for index, mention in enumerate(mentions):
            gap_start = mentions[index - 1].end if index else 0
            gap = source[gap_start:mention.start]
            date_match = _trailing_date_heading(gap)
            explicit_dates.append(date_match.group("date") if date_match else "")
            if date_match:
                segment_starts.append(gap_start + date_match.start())
            elif index == 0:
                segment_starts.append(_line_start(source, mention.start))
            else:
                segment_starts.append(mention.start)

        segments: list[SiteSegment] = []
        for index, mention in enumerate(mentions):
            end = segment_starts[index + 1] if index + 1 < len(mentions) else len(source)
            chunk = source[segment_starts[index]:end].strip(" \t\r\n,;，；")
            if chunk:
                segments.append(
                    SiteSegment(
                        source_segment_id=f"site_segment_{index + 1}",
                        site_name=mention.site_name,
                        text=chunk,
                        explicit_date_text=explicit_dates[index],
                    )
                )
        return segments


def business_categories(analysis: dict[str, object], source_text: str = "") -> list[str]:
    combined = " ".join(
        str(value or "")
        for value in (
            source_text,
            analysis.get("work_type"),
            analysis.get("summary"),
            analysis.get("result"),
            " ".join(str(item) for item in analysis.get("next_actions") or []),
        )
    ).casefold()
    categories: list[str] = []
    if any(marker.casefold() in combined for marker in _REPAIR_MARKERS):
        categories.append(REPAIR_CATEGORY)
    if any(marker.casefold() in combined for marker in _QUOTE_MARKERS):
        categories.append(QUOTATION_CATEGORY)
    if not categories:
        categories.append(REPAIR_CATEGORY)
    return categories


def _compact(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _trailing_date_heading(value: str) -> re.Match[str] | None:
    matches = list(_DATE_ONLY_LINE_RE.finditer(value))
    if matches:
        match = matches[-1]
        if not value[match.end():].strip():
            return match
    return _TRAILING_INLINE_DATE_RE.search(value)


def _line_start(value: str, position: int) -> int:
    return value.rfind("\n", 0, position) + 1


def _is_ascii_variant(value: str) -> bool:
    return bool(value) and all(ord(char) < 128 for char in value)
