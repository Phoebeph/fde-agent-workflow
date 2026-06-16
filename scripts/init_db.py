from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.database import Database


def main() -> None:
    db = Database(settings.database_path)
    db.init()
    print(f"initialized database: {settings.database_path}")


if __name__ == "__main__":
    main()
