from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import export_dashboard_data as exporter  # noqa: E402
from dashboard.lib import load_dashboard_data  # noqa: E402


@unittest.skipUnless(
    os.environ.get("RUN_POSTGRES_TESTS") == "1",
    "set RUN_POSTGRES_TESTS=1 to run PostgreSQL integration tests",
)
class DashboardExporterIntegrationTests(unittest.TestCase):
    def test_actual_database_build_and_check(self) -> None:
        trade_result, delivery_summary = exporter.load_verified_results()
        rows = exporter.public_rows(trade_result, delivery_summary)
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory) / "data"
            exporter.build_bundle(rows, data_dir)
            exporter.check_bundle(rows, data_dir)
            loaded = load_dashboard_data(data_dir)
            self.assertEqual(len(loaded.trade_monthly_overview), 18)
            self.assertEqual(len(loaded.category_mix), 108)
            self.assertEqual(len(loaded.seller_concentration), 18)
            self.assertEqual(len(loaded.delivery_timing_summary), 6)
            self.assertEqual(len(loaded.delivery_monthly), 18)
            self.assertEqual(len(loaded.delivery_sensitivity), 2)


if __name__ == "__main__":
    unittest.main()
