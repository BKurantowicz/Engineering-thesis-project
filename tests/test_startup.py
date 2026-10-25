"""Clean-tree import and startup regressions with isolated application data."""

import ast
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
        cls.tracked_paths = output.decode("utf-8").rstrip("\0").split("\0")

    def test_tracked_database_path_matches_every_application_import(self):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        imports = [
            node.module for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and any(alias.name == "DatabaseManager" for alias in node.names)
        ]
        self.assertEqual(len(imports), 1)
        module = imports[0]
        expected_path = module.replace(".", "/") + ".py"
        matching_paths = [path for path in self.tracked_paths if path.casefold() == expected_path.casefold()]
        self.assertEqual(matching_paths, [expected_path])

        for path in self.tracked_paths:
            if not path.endswith(".py") or path.startswith("tests/"):
                continue
            source = ast.parse((ROOT / path).read_text(encoding="utf-8"))
            for node in ast.walk(source):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.casefold() == module.casefold():
                    with self.subTest(path=path, line=node.lineno):
                        self.assertEqual(node.module, module)

    def test_clean_tree_starts_main_window_with_isolated_empty_database(self):
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            # Materialize exact Git-tracked path spellings without local data or caches.
            for path in self.tracked_paths:
                if path.startswith("tests/"):
                    continue
                if path.endswith(".py") or (path.startswith("utils/translations_") and path.endswith(".json")):
                    destination = checkout / path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / path, destination)
            config_path = checkout / "config.json"
            config_text = json.dumps({
                "localization": {"language": "en", "date_format": "YYYY-MM-DD"},
                "appearance": {"theme": "dark", "font_size": "medium"},
                "paths": {"database": "warehouse.db"},
            })
            config_path.write_text(config_text, encoding="utf-8")
            environment = os.environ.copy()
            environment.pop("PYTHONCASEOK", None)
            environment.pop("PYTHONPATH", None)
            environment["QT_QPA_PLATFORM"] = "offscreen"
            script = textwrap.dedent("""
                import runpy
                from PySide6.QtCore import QTimer
                from PySide6.QtWidgets import QApplication
                from models.database import DatabaseManager

                DatabaseManager("warehouse.db")
                real_exec = QApplication.exec

                def finish_after_startup():
                    ready = any(
                        type(widget).__name__ == "MainWindow" and widget.isVisible()
                        for widget in QApplication.topLevelWidgets()
                    )
                    print("MAIN_WINDOW_READY" if ready else "MAIN_WINDOW_MISSING")
                    QApplication.exit(0 if ready else 1)

                def bounded_exec(self):
                    QTimer.singleShot(0, finish_after_startup)
                    return real_exec()

                QApplication.exec = bounded_exec
                runpy.run_path("main.py", run_name="__main__")
            """)
            result = subprocess.run(
                [sys.executable, "-B", "-c", script], cwd=checkout, env=environment,
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("MAIN_WINDOW_READY", result.stdout)
            self.assertNotIn("Error fetching", result.stdout)
            self.assertEqual(config_path.read_text(encoding="utf-8"), config_text)
            with closing(sqlite3.connect(checkout / "warehouse.db")) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM dict_order_statuses").fetchone()[0], 4)

    def test_database_reinitialization_preserves_existing_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(Path(directory) / "existing.db")
            # Keep application-owned SQLite handles in a process that exits before cleanup.
            script = textwrap.dedent("""
                from contextlib import closing
                import sys
                from models.database import DatabaseManager

                manager = DatabaseManager(sys.argv[1])
                with closing(manager.get_connection()) as connection:
                    with connection:
                        connection.execute(
                            "INSERT INTO products (product_id, sku, name_pl, name_en, price) VALUES (?, ?, ?, ?, ?)",
                            (1, "KEEP-001", "Produkt", "Product", 12.50),
                        )
                        connection.execute(
                            "INSERT INTO locations (location_id, location_code, max_weight, max_volume) VALUES (?, ?, ?, ?)",
                            (1, "A-01", 500, 1),
                        )
                        connection.execute("INSERT INTO inventory VALUES (?, ?, ?)", (1, 1, 5))
                    before = list(connection.iterdump())
                DatabaseManager(sys.argv[1])
                with closing(manager.get_connection()) as connection:
                    assert list(connection.iterdump()) == before, "Existing database contents changed"
            """)
            result = subprocess.run(
                [sys.executable, "-B", "-c", script, database_path], cwd=ROOT,
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
