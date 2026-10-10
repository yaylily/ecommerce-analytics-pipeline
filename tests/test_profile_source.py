from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import profile_source


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OLIST_CONTRACT = REPOSITORY_ROOT / "config" / "olist-source-contract.json"


def _synthetic_contract() -> dict:
    return {
        "contract_version": 1,
        "dataset": {
            "name": "Synthetic commerce fixture",
            "slug": "synthetic/commerce",
            "url": "https://example.invalid/synthetic",
        },
        "files": [
            {
                "name": "orders.csv",
                "table": "orders",
                "headers": ["order_id", "note"],
                "candidate_keys": [
                    {"name": "order_id", "columns": ["order_id"]}
                ],
                "group_profiles": [],
            },
            {
                "name": "items.csv",
                "table": "items",
                "headers": [
                    "order_id",
                    "item_id",
                    "price",
                    "freight_value",
                ],
                "candidate_keys": [
                    {
                        "name": "order_id_item_id",
                        "columns": ["order_id", "item_id"],
                    }
                ],
                "group_profiles": [],
            },
            {
                "name": "payments.csv",
                "table": "payments",
                "headers": ["order_id", "payment_sequence", "payment_value"],
                "candidate_keys": [
                    {
                        "name": "order_id_payment_sequence",
                        "columns": ["order_id", "payment_sequence"],
                    }
                ],
                "group_profiles": [],
            },
            {
                "name": "reviews.csv",
                "table": "reviews",
                "headers": ["review_id", "order_id", "comment"],
                "candidate_keys": [
                    {
                        "name": "review_id_order_id",
                        "columns": ["review_id", "order_id"],
                    }
                ],
                "group_profiles": [
                    {"name": "review_id", "columns": ["review_id"]},
                    {"name": "order_id", "columns": ["order_id"]},
                ],
            },
        ],
        "relationships": [
            {
                "name": "items_to_orders",
                "child_file": "items.csv",
                "child_columns": ["order_id"],
                "parent_file": "orders.csv",
                "parent_columns": ["order_id"],
            },
            {
                "name": "payments_to_orders",
                "child_file": "payments.csv",
                "child_columns": ["order_id"],
                "parent_file": "orders.csv",
                "parent_columns": ["order_id"],
            },
            {
                "name": "reviews_to_orders",
                "child_file": "reviews.csv",
                "child_columns": ["order_id"],
                "parent_file": "orders.csv",
                "parent_columns": ["order_id"],
            },
        ],
        "fanouts": [
            {"name": "items_per_order", "relationship": "items_to_orders"},
            {"name": "payments_per_order", "relationship": "payments_to_orders"},
            {"name": "reviews_per_order", "relationship": "reviews_to_orders"},
        ],
        "join_amplifications": [
            {
                "name": "items_x_payments",
                "anchor_file": "orders.csv",
                "anchor_columns": ["order_id"],
                "left": {
                    "file": "items.csv",
                    "columns": ["order_id"],
                    "amount_columns": ["price", "freight_value"],
                },
                "right": {
                    "file": "payments.csv",
                    "columns": ["order_id"],
                    "amount_columns": ["payment_value"],
                },
            }
        ],
    }


def _write_fixture(root: Path) -> tuple[Path, Path]:
    data_dir = root / "raw"
    data_dir.mkdir(parents=True)
    contract_path = root / "contract.json"
    contract_path.write_text(
        json.dumps(_synthetic_contract(), ensure_ascii=False), encoding="utf-8"
    )

    # BOM, CRLF and non-ASCII text are intentional.
    (data_dir / "orders.csv").write_bytes(
        "\ufefforder_id,note\r\no1,첫 주문\r\no2,second\r\no3,third\r\n".encode(
            "utf-8"
        )
    )
    (data_dir / "items.csv").write_text(
        "order_id,item_id,price,freight_value\n"
        "o1,i1,10.00,1.00\n"
        "o1,i2,20.00,2.00\n"
        "o2,i1,5.00,0.50\n",
        encoding="utf-8",
        newline="",
    )
    (data_dir / "payments.csv").write_text(
        "order_id,payment_sequence,payment_value\n"
        "o1,1,33.00\n"
        "o1,2,1.00\n"
        "o2,1,5.50\n",
        encoding="utf-8",
        newline="",
    )
    (data_dir / "reviews.csv").write_text(
        "review_id,order_id,comment\r\n"
        'r1,o1,"SECRET, quoted\nline"\r\n'
        "r1,o2,second synthetic review\r\n"
        "r2,o1,third synthetic review\r\n",
        encoding="utf-8",
        newline="",
    )
    return data_dir, contract_path


class RepositoryContractTests(unittest.TestCase):
    def test_contract_has_exact_olist_files_and_key_boundaries(self) -> None:
        contract = json.loads(OLIST_CONTRACT.read_text(encoding="utf-8"))
        expected_files = {
            "olist_customers_dataset.csv",
            "olist_geolocation_dataset.csv",
            "olist_order_items_dataset.csv",
            "olist_order_payments_dataset.csv",
            "olist_order_reviews_dataset.csv",
            "olist_orders_dataset.csv",
            "olist_products_dataset.csv",
            "olist_sellers_dataset.csv",
            "product_category_name_translation.csv",
        }
        self.assertEqual({item["name"] for item in contract["files"]}, expected_files)
        self.assertEqual(len(contract["files"]), 9)

        by_table = {item["table"]: item for item in contract["files"]}
        self.assertEqual(by_table["geolocation"]["candidate_keys"], [])
        self.assertEqual(
            by_table["reviews"]["candidate_keys"],
            [
                {
                    "name": "review_id_order_id",
                    "columns": ["review_id", "order_id"],
                }
            ],
        )
        self.assertEqual(
            {profile["name"] for profile in by_table["reviews"]["group_profiles"]},
            {"review_id", "order_id"},
        )
        self.assertEqual(
            by_table["customers"]["group_profiles"],
            [{"name": "customer_unique_id", "columns": ["customer_unique_id"]}],
        )


class SourceProfilerTests(unittest.TestCase):
    def test_reports_are_deterministic_and_aggregate_only(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_data, first_contract = _write_fixture(Path(first))
            second_data, second_contract = _write_fixture(Path(second))

            first_reports = profile_source.generate_reports(first_data, first_contract)
            second_reports = profile_source.generate_reports(second_data, second_contract)
            self.assertEqual(first_reports, second_reports)

            manifest = json.loads(first_reports["source-manifest.json"])
            profile = json.loads(first_reports["source-profile.json"])
            manifest_by_table = {item["table"]: item for item in manifest["files"]}
            self.assertEqual(manifest_by_table["orders"]["logical_rows"], 3)
            self.assertEqual(manifest_by_table["reviews"]["logical_rows"], 3)
            self.assertTrue(manifest_by_table["orders"]["utf8_bom"])
            self.assertFalse(manifest_by_table["reviews"]["utf8_bom"])

            review_keys = profile["tables"]["reviews"]
            self.assertEqual(
                review_keys["candidate_keys"]["review_id_order_id"]["duplicate_rows"],
                0,
            )
            self.assertEqual(
                review_keys["group_profiles"]["review_id"]["duplicate_rows"], 1
            )
            self.assertEqual(
                review_keys["group_profiles"]["order_id"]["duplicate_rows"], 1
            )

            review_fanout = profile["fanouts"]["reviews_per_order"]
            self.assertEqual(review_fanout["parents_with_no_children"], 1)
            self.assertEqual(review_fanout["parents_with_one_child"], 1)
            self.assertEqual(review_fanout["parents_with_multiple_children"], 1)
            self.assertEqual(review_fanout["max_children_per_parent"], 2)

            item_relationship = profile["relationships"]["items_to_orders"]
            self.assertEqual(item_relationship["matched_child_rows"], 3)
            self.assertEqual(item_relationship["direct_join_rows"], 3)
            self.assertEqual(
                item_relationship["direct_join_rows_per_matched_child"], "1.000000"
            )

            join = profile["join_amplifications"]["items_x_payments"]
            self.assertEqual(join["left"]["rows_before_on_common_keys"], 3)
            self.assertEqual(join["right"]["rows_before_on_common_keys"], 3)
            self.assertEqual(join["naive_join"]["rows_after"], 5)
            self.assertEqual(
                join["left"]["amounts"]["price"]["baseline_on_common_keys"],
                "35.00",
            )
            self.assertEqual(
                join["left"]["amounts"]["price"]["naive_join_total"],
                "65.00",
            )
            self.assertEqual(
                join["right"]["amounts"]["payment_value"]["naive_join_total"],
                "73.50",
            )

            combined_output = b"\n".join(first_reports.values()).decode("utf-8")
            self.assertNotIn("SECRET", combined_output)
            self.assertNotIn("first", combined_output)
            self.assertNotIn(str(Path(first)), combined_output)

    def test_non_unique_parent_reports_direct_join_amplification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir, contract_path = _write_fixture(root)
            (data_dir / "orders.csv").write_bytes(
                (
                    "\ufefforder_id,note\r\n"
                    "o1,first\r\n"
                    "o1,duplicate parent\r\n"
                    "o2,second\r\n"
                    "o3,third\r\n"
                ).encode("utf-8")
            )

            profile = json.loads(
                profile_source.generate_reports(data_dir, contract_path)[
                    "source-profile.json"
                ]
            )
            relationship = profile["relationships"]["items_to_orders"]
            self.assertEqual(relationship["matched_child_rows"], 3)
            self.assertEqual(relationship["matched_parent_max_rows_per_key"], 2)
            self.assertEqual(relationship["direct_join_rows"], 5)
            self.assertEqual(
                relationship["direct_join_rows_per_matched_child"], "1.666667"
            )

    def test_incomplete_amounts_do_not_publish_partial_totals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir, contract_path = _write_fixture(root)
            (data_dir / "items.csv").write_text(
                "order_id,item_id,price,freight_value\n"
                "o1,i1,,1.00\n"
                "o1,i2,NOT_A_NUMBER,2.00\n"
                "o2,i1,5.00,0.50\n",
                encoding="utf-8",
                newline="",
            )

            reports = profile_source.generate_reports(data_dir, contract_path)
            profile = json.loads(reports["source-profile.json"])
            price = profile["join_amplifications"]["items_x_payments"]["left"][
                "amounts"
            ]["price"]
            self.assertFalse(price["values_complete"])
            self.assertEqual(price["null_amount_rows_total"], 1)
            self.assertEqual(price["invalid_amount_rows_total"], 1)
            self.assertIsNone(price["baseline_on_common_keys"])
            self.assertIsNone(price["naive_join_total"])
            combined_output = b"\n".join(reports.values()).decode("utf-8")
            self.assertNotIn("NOT_A_NUMBER", combined_output)

    def test_relationship_counts_null_and_orphan_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir, contract_path = _write_fixture(root)
            (data_dir / "items.csv").write_text(
                "order_id,item_id,price,freight_value\n"
                "o1,i1,10.00,1.00\n"
                "o1,i2,20.00,2.00\n"
                "o2,i1,5.00,0.50\n"
                "missing,i1,1.00,0.10\n"
                ",i2,2.00,0.20\n",
                encoding="utf-8",
                newline="",
            )

            profile = json.loads(
                profile_source.generate_reports(data_dir, contract_path)[
                    "source-profile.json"
                ]
            )
            relationship = profile["relationships"]["items_to_orders"]
            self.assertEqual(relationship["child_non_null_rows"], 4)
            self.assertEqual(relationship["child_null_key_rows"], 1)
            self.assertEqual(relationship["matched_child_rows"], 3)
            self.assertEqual(relationship["orphan_rows"], 1)

    def test_build_then_check_and_detect_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir, contract_path = _write_fixture(root)
            output_dir = root / "reports"
            profile_source.build_reports(data_dir, contract_path, output_dir)
            profile_source.check_reports(data_dir, contract_path, output_dir)

            (output_dir / "source-profile.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(profile_source.ProfileError, "do not match"):
                profile_source.check_reports(data_dir, contract_path, output_dir)

    def test_source_byte_change_changes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir, contract_path = _write_fixture(root)
            before = json.loads(
                profile_source.generate_reports(data_dir, contract_path)[
                    "source-manifest.json"
                ]
            )
            orders_path = data_dir / "orders.csv"
            orders_path.write_bytes(orders_path.read_bytes().replace(b"second", b"SECOND"))
            after = json.loads(
                profile_source.generate_reports(data_dir, contract_path)[
                    "source-manifest.json"
                ]
            )
            before_orders = next(item for item in before["files"] if item["table"] == "orders")
            after_orders = next(item for item in after["files"] if item["table"] == "orders")
            self.assertNotEqual(before_orders["sha256"], after_orders["sha256"])
            self.assertEqual(before_orders["logical_rows"], after_orders["logical_rows"])

    def test_invalid_record_does_not_leak_or_replace_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir, contract_path = _write_fixture(root)
            output_dir = root / "reports"
            profile_source.build_reports(data_dir, contract_path, output_dir)
            before = {
                name: (output_dir / name).read_bytes()
                for name in profile_source.REPORT_FILENAMES
            }

            (data_dir / "items.csv").write_text(
                "order_id,item_id,price,freight_value\n"
                "o1,i1,10.00,1.00,LEAK_ME\n",
                encoding="utf-8",
                newline="",
            )
            with self.assertRaises(profile_source.ProfileError) as raised:
                profile_source.build_reports(data_dir, contract_path, output_dir)
            self.assertNotIn("LEAK_ME", str(raised.exception))
            after = {
                name: (output_dir / name).read_bytes()
                for name in profile_source.REPORT_FILENAMES
            }
            self.assertEqual(before, after)

    def test_missing_and_unexpected_csv_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir, contract_path = _write_fixture(root)
            (data_dir / "reviews.csv").unlink()
            with self.assertRaisesRegex(profile_source.ProfileError, "missing contracted"):
                profile_source.generate_reports(data_dir, contract_path)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir, contract_path = _write_fixture(root)
            (data_dir / "unexpected.csv").write_text("id\n1\n", encoding="utf-8")
            with self.assertRaisesRegex(profile_source.ProfileError, "unexpected CSV"):
                profile_source.generate_reports(data_dir, contract_path)

    def test_header_mismatch_fails_without_echoing_header_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir, contract_path = _write_fixture(root)
            (data_dir / "orders.csv").write_text(
                "order_id,LEAK_HEADER\no1,value\n", encoding="utf-8"
            )
            with self.assertRaises(profile_source.ProfileError) as raised:
                profile_source.generate_reports(data_dir, contract_path)
            self.assertNotIn("LEAK_HEADER", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
