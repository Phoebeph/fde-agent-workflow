from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.services.fingerprint import file_sha256
from app.services.site_policy import BUSINESS_CATEGORIES


_SAFE_CHARS_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff\u3400-\u4dbf._-]+")


def safe_part(value: str | None, fallback: str) -> str:
    raw = (value or "").strip() or fallback
    cleaned = _SAFE_CHARS_RE.sub("_", raw).strip("._-")
    return cleaned[:80] or fallback


@dataclass(frozen=True)
class ArchivedFile:
    original_path: str
    archive_path: str
    archive_filename: str
    sha256: str
    size_bytes: int
    original_filename: str


@dataclass(frozen=True)
class CategoryArchivedFile:
    archive_path: str
    archive_filename: str
    site: str
    business_category: str


def archive_attachment(
    temp_path: str,
    archive_root: Path,
    *,
    original_filename: str,
    work_date: str | None,
    site: str | None,
    staff_name: str | None,
    work_type: str | None,
    attachment_type: str,
) -> ArchivedFile:
    source = Path(temp_path).expanduser()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"attachment file not found: {source}")

    digest = file_sha256(str(source))
    ext = Path(original_filename).suffix or source.suffix
    if not ext:
        ext = ".bin"

    date_part = safe_part(work_date, "unknown_date")
    site_part = safe_part(site, "unknown_site")
    staff_part = safe_part(staff_name, "unknown_staff")
    work_part = safe_part(work_type, "work")
    type_part = safe_part(attachment_type, "attachment")

    year = date_part[:4] if len(date_part) >= 4 and date_part[:4].isdigit() else "unknown_year"
    month = date_part[5:7] if len(date_part) >= 7 and date_part[5:7].isdigit() else "unknown_month"
    day = date_part[8:10] if len(date_part) >= 10 and date_part[8:10].isdigit() else "unknown_day"
    target_dir = archive_root / year / month / day / site_part
    target_dir.mkdir(parents=True, exist_ok=True)
    site_index_dir = archive_root / "by_site" / site_part / year / month / day
    site_index_dir.mkdir(parents=True, exist_ok=True)

    base_name = f"{date_part}_{site_part}_{staff_part}_{work_part}_{type_part}_{digest[:10]}{ext.lower()}"
    target = target_dir / safe_part(base_name, f"attachment_{digest[:10]}{ext.lower()}")
    if not target.exists():
        shutil.copy2(source, target)
    site_index_target = site_index_dir / target.name
    if not site_index_target.exists():
        shutil.copy2(target, site_index_target)

    return ArchivedFile(
        original_path=str(source),
        archive_path=str(target),
        archive_filename=target.name,
        sha256=digest,
        size_bytes=target.stat().st_size,
        original_filename=original_filename,
    )


def mirror_attachment_for_category(
    archived_path: str,
    output_root: Path,
    *,
    work_date: str,
    site: str,
    business_category: str,
    attachment_type: str,
) -> CategoryArchivedFile:
    source = Path(archived_path)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"archived attachment not found: {source}")
    if business_category not in BUSINESS_CATEGORIES:
        raise ValueError(f"unsupported business category: {business_category}")
    date_part = safe_part(work_date, "unknown_date")
    if len(date_part) < 10 or not date_part[:4].isdigit():
        raise ValueError("valid work_date is required for category archive")
    site_part = safe_part(site, "")
    if not site_part:
        raise ValueError("valid configured site is required for category archive")
    category_part = safe_part(business_category, "")
    media_dir = "图片" if attachment_type == "image" else "PDF及其他附件"
    target_dir = (
        output_root
        / site_part
        / date_part[:4]
        / date_part[5:7]
        / date_part[8:10]
        / category_part
        / media_dir
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    if not target.exists():
        shutil.copy2(source, target)
    return CategoryArchivedFile(
        archive_path=str(target),
        archive_filename=target.name,
        site=site,
        business_category=business_category,
    )
