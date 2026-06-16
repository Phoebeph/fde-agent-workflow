import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.database import Database
from app.services.rules import load_rules_from_xlsx


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/import_rules.py /path/to/工作規則.xlsx")
    db = Database(settings.database_path)
    db.init()
    rules = load_rules_from_xlsx(sys.argv[1])
    result = db.upsert_rules(rules)
    print(f"imported rules: {result['upserted']}")


if __name__ == "__main__":
    main()
