from __future__ import annotations

import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit('usage: python scripts/send_mock_message.py "Sender" "message text"')
    payload = {
        "sender": sys.argv[1],
        "text": sys.argv[2],
        "group_name": settings.whatsapp_group_name or "Mock维修工作群",
    }
    request = urllib.request.Request(
        f"http://{settings.app_host}:{settings.app_port}/api/mock/whatsapp/message",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.loads(response.read().decode("utf-8"))
    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    state = "OK" if result.get("ok") else "FAILED"
    print(
        f"{state} run_id={result.get('run_id')} "
        f"sender={result.get('sender')} "
        f"status={result.get('completion_status')} "
        f"record={result.get('mock_feishu_record_id')} "
        f"reminders={result.get('reminders_created')}"
    )


if __name__ == "__main__":
    main()
