from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.services.fingerprint import file_sha256


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
    target_dir = archive_root / year / month / site_part
    target_dir.mkdir(parents=True, exist_ok=True)

    base_name = f"{date_part}_{site_part}_{staff_part}_{work_part}_{type_part}_{digest[:10]}{ext.lower()}"
    target = target_dir / safe_part(base_name, f"attachment_{digest[:10]}{ext.lower()}")
    if not target.exists():
        shutil.copy2(source, target)

    return ArchivedFile(
        original_path=str(source),
        archive_path=str(target),
        archive_filename=target.name,
        sha256=digest,
        size_bytes=target.stat().st_size,
        original_filename=original_filename,
    )
