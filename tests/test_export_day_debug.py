from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


class ExportDayDebugScriptTests(unittest.TestCase):
    def test_script_exports_debug_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = dict(os.environ)
            env["DATA_ROOT"] = temp_dir
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/export_day_debug.py",
                    "2026-06-20",
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertIn("debug_export=", result.stdout)
            self.assertTrue((Path(temp_dir) / "debug" / "debug_2026-06-20.json").exists())


if __name__ == "__main__":
    unittest.main()
