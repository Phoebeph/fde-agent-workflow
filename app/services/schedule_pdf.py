from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app.services.deepseek import DeepSeekClient
from app.services.fingerprint import file_sha256
from app.services.site_policy import ConfiguredSitePolicy


DAILY_PDF_SOURCE = "daily_pdf"
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 20
MAX_EXTRACTED_CHARS = 100_000
MIN_EXTRACTED_CHARS = 40
_LEAVE_MARKERS = {"al", "off", "leave", "annualleave", "rest", "休息", "放假", "年假", "病假", "请假", "請假"}


def daily_schedule_dir(data_root: Path, work_date: str) -> Path:
    parsed = datetime.strptime(work_date, "%Y-%m-%d")
    return Path(data_root) / parsed.strftime("%Y") / parsed.strftime("%m") / parsed.strftime("%d")


def discover_schedule_pdfs(day_dir: Path, filename_keywords: list[str]) -> list[Path]:
    if not day_dir.exists() or not day_dir.is_dir():
        return []
    normalized_keywords = {
        normalized
        for value in filename_keywords
        if (normalized := _normalized_filename(value))
    }
    if not normalized_keywords:
        return []
    candidates = [
        path
        for path in day_dir.iterdir()
        if path.is_file()
        and path.suffix.casefold() == ".pdf"
        and any(keyword in _normalized_filename(path.stem) for keyword in normalized_keywords)
    ]
    return sorted(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name.casefold()), reverse=True)


def extract_pdf_layout_text(path: Path) -> tuple[str, int]:
    if path.stat().st_size > MAX_PDF_BYTES:
        raise ValueError(f"schedule PDF exceeds {MAX_PDF_BYTES} bytes")
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - deployment dependency check
        raise RuntimeError("pypdf is not installed") from exc
    reader = PdfReader(str(path))
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ValueError(f"schedule PDF exceeds {MAX_PDF_PAGES} pages")
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text(
            extraction_mode="layout",
            layout_mode_space_vertically=False,
        ) or ""
        parts.append(text.strip())
    combined = "\n\n".join(part for part in parts if part).strip()
    if len(combined) > MAX_EXTRACTED_CHARS:
        raise ValueError(f"schedule PDF extracted text exceeds {MAX_EXTRACTED_CHARS} characters")
    return combined, len(reader.pages)


def sync_daily_schedule_pdf(
    *,
    db: Any,
    deepseek: DeepSeekClient,
    data_root: Path,
    work_date: str,
    enabled: bool,
    filename_keywords: list[str],
    site_policy: ConfiguredSitePolicy,
    resolve_staff_name: Callable[[str], str],
) -> dict[str, Any]:
    day_dir = daily_schedule_dir(data_root, work_date)
    base = {
        "work_date": work_date,
        "directory": str(day_dir),
        "candidate_files": [],
        "selected_file": "",
        "sha256": "",
        "status": "no_file",
        "inserted": 0,
        "kept": 0,
        "deactivated": 0,
        "rejected": 0,
        "error": "",
    }
    if not enabled:
        return {**base, "status": "disabled"}
    candidates = discover_schedule_pdfs(day_dir, filename_keywords)
    base["candidate_files"] = [str(path) for path in candidates]
    if not candidates:
        return base
    selected = candidates[0]
    digest = file_sha256(str(selected))
    base.update({"selected_file": str(selected), "sha256": digest})
    existing = db.get_schedule_document_by_hash(work_date, digest)
    if existing and existing.get("status") == "imported":
        return {**base, "status": "unchanged"}

    document_id = db.start_schedule_document(
        {
            "work_date": work_date,
            "source_path": str(selected),
            "source_filename": selected.name,
            "sha256": digest,
            "modified_at_ns": selected.stat().st_mtime_ns,
        }
    )
    try:
        text, page_count = extract_pdf_layout_text(selected)
    except Exception as exc:
        db.finish_schedule_document(document_id, status="failed", error=str(exc))
        return {**base, "status": "failed", "error": str(exc)}
    if len(text) < MIN_EXTRACTED_CHARS:
        error = "schedule PDF has no usable text layer"
        db.finish_schedule_document(
            document_id,
            status="ocr_required",
            error=error,
            page_count=page_count,
            extracted_chars=len(text),
        )
        return {**base, "status": "ocr_required", "error": error}
    if not deepseek.enabled:
        error = "DeepSeek is disabled"
        db.finish_schedule_document(
            document_id,
            status="ai_unavailable",
            error=error,
            page_count=page_count,
            extracted_chars=len(text),
        )
        return {**base, "status": "ai_unavailable", "error": error}
    try:
        raw_rows = deepseek.parse_daily_schedule(
            work_date=work_date,
            source_file=selected.name,
            extracted_text=text,
            allowed_site_names=[site.name for site in site_policy.sites],
        )
        rows, rejected = normalize_schedule_rows(
            raw_rows,
            work_date=work_date,
            source_file=str(selected),
            site_policy=site_policy,
            resolve_staff_name=resolve_staff_name,
        )
        result = db.replace_daily_pdf_schedules(document_id, work_date, rows)
    except Exception as exc:
        db.finish_schedule_document(
            document_id,
            status="failed",
            error=str(exc),
            page_count=page_count,
            extracted_chars=len(text),
        )
        return {**base, "status": "failed", "error": str(exc)}
    db.finish_schedule_document(
        document_id,
        status="imported",
        page_count=page_count,
        extracted_chars=len(text),
        imported_rows=len(rows),
        rejected_rows=rejected,
    )
    return {
        **base,
        "status": "imported",
        "inserted": result["inserted"],
        "kept": result["kept"],
        "deactivated": result["deactivated"],
        "rejected": rejected,
    }


def normalize_schedule_rows(
    raw_rows: list[dict[str, Any]],
    *,
    work_date: str,
    source_file: str,
    site_policy: ConfiguredSitePolicy,
    resolve_staff_name: Callable[[str], str],
) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    rejected = 0
    seen_keys: set[str] = set()
    for raw in raw_rows:
        staff = resolve_staff_name(str(raw.get("staff_name") or "").strip())
        task_text = str(raw.get("task_text") or "").strip()
        raw_site = str(raw.get("site") or "").strip()
        if not staff or not task_text or _is_leave_row(task_text) or bool(raw.get("is_leave")):
            rejected += 1
            continue
        resolution = site_policy.resolve(raw_site or task_text)
        if resolution.status != "matched" or not resolution.site_name:
            rejected += 1
            continue
        shift = _normalized_shift(str(raw.get("shift") or ""))
        confidence = _confidence(raw.get("confidence"))
        stable_key = _stable_key(work_date, staff, shift, resolution.site_name, task_text)
        if stable_key in seen_keys:
            continue
        seen_keys.add(stable_key)
        rows.append(
            {
                "work_date": work_date,
                "shift": shift,
                "staff_name": staff,
                "site": resolution.site_name,
                "task_text": task_text[:500],
                "source_file": source_file,
                "ocr_confidence": confidence,
                "review_status": "confirmed",
                "source_type": DAILY_PDF_SOURCE,
                "source_key": stable_key,
                "is_active": True,
            }
        )
    if not rows:
        raise ValueError("schedule PDF produced no valid configured-site work rows")
    return rows, rejected


def _normalized_filename(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def _normalized_shift(value: str) -> str:
    compact = value.replace(" ", "").replace(".", "").casefold()
    if compact in {"am", "上午"}:
        return "A.M."
    if compact in {"pm", "下午"}:
        return "P.M."
    return "ALL_DAY"


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.8


def _is_leave_row(task_text: str) -> bool:
    compact = re.sub(r"[\s._-]+", "", task_text).casefold()
    return compact in _LEAVE_MARKERS or any(marker in compact for marker in {"休息", "放假", "年假", "病假", "请假", "請假"})


def _stable_key(work_date: str, staff: str, shift: str, site: str, task_text: str) -> str:
    raw = json.dumps(
        [work_date, staff.casefold(), shift, site.casefold(), " ".join(task_text.split()).casefold()],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
