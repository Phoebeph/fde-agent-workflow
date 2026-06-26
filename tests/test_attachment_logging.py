from pathlib import Path
import asyncio
import logging
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.config import Settings
from app.database import Database
from app.logging_config import configure_backend_logging
from app.main import ingest_attachment, request_validation_exception_handler
from app.schemas import AttachmentIn


class AttachmentLoggingTests(unittest.TestCase):
    def test_attachment_validation_error_is_written_to_backend_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = _configure_test_logging(Path(temp_dir))

            response = _validation_response(
                {
                    "attachment_type": "image",
                },
            )

            self.assertEqual(response.status_code, 422)
            log_text = _read_log(log_path)
            self.assertIn("request validation failed status=422", log_text)
            self.assertIn("/api/whatsapp/attachments", log_text)
            self.assertIn("message_fingerprint or external_message_id is required", log_text)

    def test_attachment_invalid_type_is_written_to_backend_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = _configure_test_logging(Path(temp_dir))

            response = _validation_response(
                {
                    "external_message_id": "yingdao_bad_type",
                    "original_filename": "photo.jpg",
                    "temp_path": str(Path(temp_dir) / "photo.jpg"),
                    "attachment_type": "photo",
                },
            )

            self.assertEqual(response.status_code, 422)
            log_text = _read_log(log_path)
            self.assertIn("request validation failed status=422", log_text)
            self.assertIn("attachment_type", log_text)
            self.assertIn("literal_error", log_text)

    def test_attachment_missing_file_is_written_to_backend_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            log_path = _configure_test_logging(root)
            db = _database_with_attachment_message(root, "a" * 64, "yingdao_missing_file")
            missing_path = root / "downloads" / "missing.jpg"

            with (
                patch("app.main.db", db),
                patch("app.main.settings", _settings(root)),
            ):
                response = _call_ingest_attachment(
                    {
                        "external_message_id": "yingdao_missing_file",
                        "original_filename": "missing.jpg",
                        "temp_path": str(missing_path),
                        "attachment_type": "image",
                    },
                )

            self.assertEqual(response.status_code, 400)
            log_text = _read_log(log_path)
            self.assertIn("attachment file not found", log_text)
            self.assertIn(str(missing_path), log_text)

    def test_attachment_unknown_message_is_written_to_backend_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            log_path = _configure_test_logging(root)
            db = Database(root / "test.db")
            db.init()

            with patch("app.main.db", db):
                response = _call_ingest_attachment(
                    {
                        "external_message_id": "yingdao_unknown",
                        "original_filename": "photo.jpg",
                        "temp_path": str(root / "photo.jpg"),
                        "attachment_type": "image",
                    },
                )

            self.assertEqual(response.status_code, 404)
            log_text = _read_log(log_path)
            self.assertIn("attachment message reference not found", log_text)
            self.assertIn("yingdao_unknown", log_text)

    def test_attachment_without_temp_path_uses_latest_downloaded_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            log_path = _configure_test_logging(root)
            downloads_root = root / "downloads"
            downloads_root.mkdir(parents=True, exist_ok=True)
            older = downloads_root / "older.jpg"
            older.write_bytes(b"older-image")
            newer = downloads_root / "latest.png"
            newer.write_bytes(b"latest-image")
            db = _database_with_attachment_message(root, "b" * 64, "yingdao_auto_image")

            with (
                patch("app.main.db", db),
                patch("app.main.settings", _settings(root)),
            ):
                response = _call_ingest_attachment(
                    {
                        "external_message_id": "yingdao_auto_image",
                        "attachment_type": "image",
                    },
                )

            self.assertTrue(response["inserted"])
            message = db.get_message_by_external_id("yingdao_auto_image")
            attachments = db.list_attachments_for_message(message["id"])
            self.assertEqual(len(attachments), 1)
            self.assertEqual(attachments[0]["original_filename"], "2026-06-10_Kei_image.png")
            self.assertIn("2026/06/10/unknown_site", attachments[0]["archive_path"])
            self.assertTrue(Path(attachments[0]["archive_path"]).exists())
            log_text = _read_log(log_path)
            self.assertIn("strategy=downloads_root_scan", log_text)
            self.assertIn(str(newer), log_text)

    def test_attachment_pdf_preserves_real_source_filename_when_temp_path_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            log_path = _configure_test_logging(root)
            downloads_root = root / "downloads" / "yingdao"
            downloads_root.mkdir(parents=True, exist_ok=True)
            source = downloads_root / "service_report_final.PDF"
            source.write_bytes(b"pdf-bytes")
            db = _database_with_attachment_message(root, "c" * 64, "yingdao_auto_pdf")

            with (
                patch("app.main.db", db),
                patch("app.main.settings", _settings(root)),
            ):
                response = _call_ingest_attachment(
                    {
                        "external_message_id": "yingdao_auto_pdf",
                        "attachment_type": "pdf",
                    },
                )

            self.assertTrue(response["inserted"])
            message = db.get_message_by_external_id("yingdao_auto_pdf")
            attachments = db.list_attachments_for_message(message["id"])
            self.assertEqual(attachments[0]["original_filename"], "service_report_final.PDF")
            self.assertTrue(attachments[0]["archive_filename"].endswith(".pdf"))
            log_text = _read_log(log_path)
            self.assertIn("original_filename=service_report_final.PDF", log_text)


def _configure_test_logging(root: Path) -> Path:
    return configure_backend_logging(root / "logs")


def _validation_response(payload: dict[str, object]):
    try:
        AttachmentIn.model_validate(payload)
    except ValidationError as exc:
        request = SimpleNamespace(
            url=SimpleNamespace(path="/api/whatsapp/attachments"),
            method="POST",
        )
        return asyncio.run(
            request_validation_exception_handler(
                request,
                RequestValidationError(exc.errors()),
            )
        )
    raise AssertionError("payload should fail validation")


def _call_ingest_attachment(payload: dict[str, object]):
    try:
        return ingest_attachment(
            AttachmentIn.model_validate(payload),
            BackgroundTasks(),
        )
    except Exception as exc:
        return exc


def _read_log(log_path: Path) -> str:
    for handler in logging.getLogger().handlers:
        handler.flush()
    return log_path.read_text(encoding="utf-8")


def _settings(root: Path) -> Settings:
    return Settings(
        data_root=root / "data",
        database_path=root / "test.db",
        archive_root=root / "archive",
        downloads_root=root / "downloads",
        exports_root=root / "exports",
        logs_root=root / "logs",
        backups_root=root / "backups",
    )


def _database_with_attachment_message(root: Path, fingerprint: str, external_id: str) -> Database:
    db = Database(root / "test.db")
    db.init()
    db.insert_messages(
        [
            {
                "group_name": "维修群",
                "sender": "Kei",
                "sent_at": "2026-06-10T18:00:00+08:00",
                "text": "完成，附相",
                "message_fingerprint": fingerprint,
                "external_message_id": external_id,
                "has_attachments": True,
                "attachment_hints": [{"type": "image"}],
                "raw_payload": {},
            }
        ]
    )
    return db


if __name__ == "__main__":
    unittest.main()
