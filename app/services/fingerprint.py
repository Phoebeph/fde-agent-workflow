from __future__ import annotations

import hashlib
import json
import re
from typing import Any


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return _WHITESPACE_RE.sub(" ", value.strip())


def message_fingerprint(
    group_name: str,
    sender: str,
    sent_at: str,
    text: str,
    external_message_id: str | None = None,
    attachment_hints: list[dict[str, Any]] | None = None,
) -> str:
    del attachment_hints
    payload = {
        "group_name": normalize_text(group_name),
        "sender": normalize_text(sender),
        "sent_at": normalize_text(sent_at),
        "text": normalize_text(text),
        "external_message_id": normalize_text(external_message_id),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
