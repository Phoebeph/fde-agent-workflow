from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings


def _load_payload(path: Path) -> dict[str, object]:
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except FileNotFoundError as exc:
        raise SystemExit(f"payload file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"payload is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("payload root must be a JSON object")
    if not payload.get("group_name") or not payload.get("messages"):
        raise SystemExit("payload must contain group_name and non-empty messages")
    return payload


def _post_payload(url: str, payload: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"request failed: {exc}") from exc


def _inserted_count(items: object) -> int:
    if not isinstance(items, list):
        return 0
    return sum(1 for item in items if isinstance(item, dict) and item.get("inserted"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a Yingdao-style WhatsApp message payload to the local backend.",
    )
    parser.add_argument("payload", help="Path to JSON payload file")
    parser.add_argument(
        "--url",
        default=f"http://{settings.app_host}:{settings.app_port}/api/whatsapp/messages",
        help="Target backend URL",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON response")
    args = parser.parse_args()

    payload = _load_payload(Path(args.payload))
    result = _post_payload(args.url, payload)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    messages = result.get("messages") or {}
    dispatch = result.get("dispatch_schedules") or {}
    issue_records = dispatch.get("issue_records") or []
    auto_converted = dispatch.get("auto_converted_issues") or []
    followup_events = dispatch.get("followup_events") or []
    print(
        "OK "
        f"inserted={messages.get('inserted', 0)} "
        f"skipped={messages.get('skipped', 0)} "
        f"dispatch={dispatch.get('inserted', 0)} "
        f"issues={_inserted_count(issue_records)}/{len(issue_records)} "
        f"auto_converted={len(auto_converted)} "
        f"followups={_inserted_count(followup_events)}/{len(followup_events)}"
    )


if __name__ == "__main__":
    main()
