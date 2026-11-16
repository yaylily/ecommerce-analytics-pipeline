from __future__ import annotations

import os
import sys
import unittest
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_category_seller_trade as analysis  # noqa: E402


@unittest.skipUnless(
    os.environ.get("RUN_POSTGRES_TESTS") == "1",
    "set RUN_POSTGRES_TESTS=1 to run PostgreSQL integration tests",
)
class CategorySellerTradeAnalysisIntegrationTests(unittest.TestCase):
    def test_pandas_results_reconcile_to_sql_and_fixed_snapshot(self) -> None:
        load_dotenv(ROOT / ".env")
        config = analysis.DatabaseConfig.from_environment()
        with analysis.connect_database(config) as connection:
            category_frame, seller_frame, baselines = analysis.load_analysis_snapshot(
                connection
            )

        category, seller = analysis.validate_analysis_frames(
            category_frame, seller_frame
        )
        result = analysis.summarize_trades(category, seller)
        analysis.reconcile_with_database(category, seller, result, baselines)
        analysis.validate_expected_snapshot(result)

        self.assertEqual(
            tuple(result.monthly_overview["purchase_month"]),
            analysis.PRIMARY_MONTHS,
        )
        self.assertEqual(len(result.monthly_overview), 18)
        self.assertEqual(result.category_row_count, 1132)
        self.assertEqual(result.seller_row_count, 14458)
        self.assertEqual(result.period_ordered_item_row_count, 101825)
        self.assertEqual(result.period_gross_item_value, Decimal("12230652.13"))
        self.assertEqual(result.period_freight_amount, Decimal("2029493.87"))
        self.assertEqual(result.period_item_side_amount, Decimal("14260146.00"))
        self.assertEqual(
            tuple(
                result.top_categories.sort_values("category_rank")["category_key"]
            ),
            (
                "beleza_saude",
                "relogios_presentes",
                "cama_mesa_banho",
                "esporte_lazer",
                "informatica_acessorios",
            ),
        )


if __name__ == "__main__":
    unittest.main()
