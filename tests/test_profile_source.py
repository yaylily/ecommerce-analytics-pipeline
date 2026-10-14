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


def _write_value_fixture(root: Path) -> tuple[Path, Path]:
    contract = _synthetic_contract()
    by_name = {item["name"]: item for item in contract["files"]}
    by_name["orders.csv"]["headers"] = [
        "order_id",
        "note",
        "order_status",
        "purchased_at",
        "delivered_at",
        "estimated_at",
    ]
    by_name["payments.csv"]["headers"] += ["payment_type", "installments"]
    by_name["reviews.csv"]["headers"] += [
        "review_score",
        "created_at",
        "answered_at",
    ]
    contract["value_profiles"] = {
        "type_checks": [
            {
                "file": "orders.csv",
                "column": "purchased_at",
                "target_type": "timestamp",
                "format": "%Y-%m-%d %H:%M:%S",
            },
            {
                "file": "orders.csv",
                "column": "delivered_at",
                "target_type": "timestamp",
                "format": "%Y-%m-%d %H:%M:%S",
            },
            {
                "file": "orders.csv",
                "column": "estimated_at",
                "target_type": "timestamp",
                "format": "%Y-%m-%d %H:%M:%S",
            },
            {"file": "items.csv", "column": "item_id", "target_type": "integer"},
            {"file": "items.csv", "column": "price", "target_type": "decimal"},
            {
                "file": "items.csv",
                "column": "freight_value",
                "target_type": "decimal",
            },
            {
                "file": "payments.csv",
                "column": "payment_value",
                "target_type": "decimal",
            },
            {
                "file": "payments.csv",
                "column": "installments",
                "target_type": "integer",
            },
            {
                "file": "reviews.csv",
                "column": "review_score",
                "target_type": "integer",
            },
            {
                "file": "reviews.csv",
                "column": "created_at",
                "target_type": "timestamp",
                "format": "%Y-%m-%d %H:%M:%S",
            },
            {
                "file": "reviews.csv",
                "column": "answered_at",
                "target_type": "timestamp",
                "format": "%Y-%m-%d %H:%M:%S",
            },
        ],
        "domain_counts": [
            {
                "name": "order_status",
                "file": "orders.csv",
                "column": "order_status",
                "published_values": ["delivered", "canceled"],
            },
            {
                "name": "payment_type",
                "file": "payments.csv",
                "column": "payment_type",
                "published_values": ["credit_card", "voucher"],
            },
            {
                "name": "review_score",
                "file": "reviews.csv",
                "column": "review_score",
                "published_values": ["1", "2", "3", "4", "5"],
            },
        ],
        "datetime_comparisons": [
            {
                "name": "delivered_vs_estimated_timestamp",
                "file": "orders.csv",
                "left_column": "delivered_at",
                "right_column": "estimated_at",
                "comparison_unit": "timestamp",
                "kind": "delivery_timing",
                "breakdown_column": "order_status",
            },
            {
                "name": "delivered_vs_estimated_date",
                "file": "orders.csv",
                "left_column": "delivered_at",
                "right_column": "estimated_at",
                "comparison_unit": "date",
                "kind": "delivery_timing",
                "breakdown_column": "order_status",
            },
            {
                "name": "review_created_vs_answered",
                "file": "reviews.csv",
                "left_column": "created_at",
                "right_column": "answered_at",
                "comparison_unit": "timestamp",
                "kind": "chronology",
            },
        ],
        "amount_reconciliations": [
            {
                "name": "items_vs_payments_by_order",
                "join_amplification": "items_x_payments",
                "left_amount_columns": ["price", "freight_value"],
                "right_amount_columns": ["payment_value"],
                "anchor_breakdown_column": "order_status",
            }
        ],
    }

    data_dir = root / "raw"
    data_dir.mkdir(parents=True)
    contract_path = root / "contract.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False), encoding="utf-8"
    )
    (data_dir / "orders.csv").write_text(
        "order_id,note,order_status,purchased_at,delivered_at,estimated_at\n"
        "o1,first,delivered,2020-01-01 10:00:00,2020-01-04 01:00:00,2020-01-03 23:00:00\n"
        "o2,second,delivered,2020-01-01 10:00:00,2020-01-03 10:00:00,2020-01-03 11:00:00\n"
        "o3,third,canceled,2020-01-02 10:00:00,,2020-01-05 00:00:00\n",
        encoding="utf-8",
        newline="",
    )
    (data_dir / "items.csv").write_text(
        "order_id,item_id,price,freight_value\n"
        "o1,1,10.00,1.00\n"
        "o1,2,20.00,2.00\n"
        "o2,1,5.00,0.50\n",
        encoding="utf-8",
        newline="",
    )
    (data_dir / "payments.csv").write_text(
        "order_id,payment_sequence,payment_value,payment_type,installments\n"
        "o1,1,33.00,credit_card,2\n"
        "o1,2,1.00,voucher,1\n"
        "o2,1,5.50,credit_card,1\n",
        encoding="utf-8",
        newline="",
    )
    (data_dir / "reviews.csv").write_text(
        "review_id,order_id,comment,review_score,created_at,answered_at\n"
        "r1,o1,first review,5,2020-01-05 10:00:00,2020-01-05 11:00:00\n"
        "r1,o2,second review,4,2020-01-06 12:00:00,2020-01-06 11:00:00\n"
        "r2,o1,third review,3,2020-01-07 10:00:00,2020-01-07 10:00:00\n",
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
        value_profiles = contract["value_profiles"]
        self.assertEqual(len(value_profiles["type_checks"]), 15)
        self.assertEqual(
            {item["name"] for item in value_profiles["domain_counts"]},
            {"order_status", "payment_type", "review_score"},
        )
        self.assertEqual(
            {item["name"] for item in value_profiles["datetime_comparisons"]},
            {
                "purchase_vs_approval",
                "purchase_vs_carrier",
                "approval_vs_carrier",
                "carrier_vs_customer",
                "purchase_vs_customer",
                "purchase_vs_estimated",
                "review_creation_vs_answer",
                "delivered_vs_estimated_timestamp",
                "delivered_vs_estimated_date",
            },
        )
        comparisons_by_name = {
            item["name"]: item for item in value_profiles["datetime_comparisons"]
        }
        self.assertEqual(
            {
                name
                for name, item in comparisons_by_name.items()
                if item.get("breakdown_column") == "order_status"
            },
            {
                "purchase_vs_carrier",
                "approval_vs_carrier",
                "carrier_vs_customer",
                "delivered_vs_estimated_date",
            },
        )
        self.assertEqual(
            value_profiles["amount_reconciliations"][0][
                "anchor_breakdown_column"
            ],
            "order_status",
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
            value_profile = json.loads(first_reports["source-value-profile.json"])
            self.assertEqual(value_profile["tables"], {})
            self.assertEqual(value_profile["datetime_comparisons"], {})
            self.assertEqual(value_profile["amount_reconciliations"], {})
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

    def test_value_profiles_type_domain_datetime_and_amounts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir, contract_path = _write_value_fixture(Path(temporary))
            reports = profile_source.generate_reports(data_dir, contract_path)
            value_profile = json.loads(reports["source-value-profile.json"])

            price = value_profile["tables"]["items"]["type_checks"]["price"]
            self.assertEqual(price["parseable_rows"], 3)
            self.assertEqual(price["invalid_rows"], 0)
            self.assertEqual(price["zero_rows"], 0)
            self.assertEqual(price["negative_rows"], 0)
            self.assertEqual(price["minimum"], "5.00")
            self.assertEqual(price["maximum"], "20.00")

            statuses = value_profile["tables"]["orders"]["domain_counts"][
                "order_status"
            ]
            self.assertEqual(
                statuses["published_value_counts"],
                {"canceled": 1, "delivered": 2},
            )
            self.assertEqual(statuses["other_rows"], 0)

            timestamp_check = value_profile["datetime_comparisons"][
                "delivered_vs_estimated_timestamp"
            ]
            self.assertEqual(timestamp_check["rows"], 3)
            self.assertEqual(timestamp_check["comparable_rows"], 2)
            self.assertEqual(timestamp_check["skipped_null_rows"], 1)
            self.assertEqual(timestamp_check["skipped_invalid_rows"], 0)
            self.assertEqual(timestamp_check["left_before_right_rows"], 1)
            self.assertEqual(timestamp_check["left_after_right_rows"], 1)
            self.assertEqual(
                timestamp_check["rows"],
                timestamp_check["comparable_rows"]
                + timestamp_check["skipped_null_rows"]
                + timestamp_check["skipped_invalid_rows"],
            )
            date_check = value_profile["datetime_comparisons"][
                "delivered_vs_estimated_date"
            ]
            self.assertEqual(date_check["equal_rows"], 1)
            self.assertEqual(date_check["left_after_right_rows"], 1)
            date_breakdown = date_check["breakdown"]
            self.assertEqual(
                date_breakdown["published_values"]["delivered"]["rows"], 2
            )
            self.assertEqual(
                date_breakdown["published_values"]["delivered"]["comparable_rows"],
                2,
            )
            self.assertEqual(
                date_breakdown["published_values"]["canceled"][
                    "skipped_null_rows"
                ],
                1,
            )
            for field_name in (
                "rows",
                "comparable_rows",
                "skipped_null_rows",
                "skipped_invalid_rows",
                "left_before_right_rows",
                "equal_rows",
                "left_after_right_rows",
            ):
                grouped_total = sum(
                    group[field_name]
                    for group in (
                        *date_breakdown["published_values"].values(),
                        date_breakdown["other"],
                        date_breakdown["null"],
                    )
                )
                self.assertEqual(grouped_total, date_check[field_name])

            reconciliation = value_profile["amount_reconciliations"][
                "items_vs_payments_by_order"
            ]
            self.assertEqual(reconciliation["anchor_keys"], 3)
            self.assertEqual(reconciliation["keys_with_both_sides"], 2)
            self.assertEqual(reconciliation["keys_with_neither_side"], 1)
            self.assertEqual(reconciliation["eligible_keys"], 2)
            self.assertEqual(reconciliation["exact_match_keys"], 1)
            self.assertEqual(reconciliation["right_greater_keys"], 1)
            self.assertEqual(reconciliation["left_total_on_eligible_keys"], "38.50")
            self.assertEqual(reconciliation["right_total_on_eligible_keys"], "39.50")
            self.assertEqual(reconciliation["net_difference_right_minus_left"], "1.00")
            self.assertEqual(
                reconciliation["absolute_difference_buckets"],
                {
                    "absolute_difference_gt_0_01_lte_1": 1,
                    "absolute_difference_gt_1_lte_10": 0,
                    "absolute_difference_gt_10": 0,
                    "absolute_difference_lte_0_01": 0,
                },
            )
            self.assertEqual(
                reconciliation["eligible_keys"],
                reconciliation["exact_match_keys"]
                + sum(reconciliation["absolute_difference_buckets"].values()),
            )
            amount_breakdown = reconciliation["anchor_breakdown"]
            delivered_amounts = amount_breakdown["published_values"]["delivered"]
            canceled_amounts = amount_breakdown["published_values"]["canceled"]
            self.assertEqual(delivered_amounts["keys_with_both_sides"], 2)
            self.assertEqual(delivered_amounts["eligible_keys"], 2)
            self.assertEqual(delivered_amounts["exact_match_keys"], 1)
            self.assertEqual(delivered_amounts["right_greater_keys"], 1)
            self.assertEqual(canceled_amounts["keys_with_neither_side"], 1)
            amount_fields = (
                "anchor_keys",
                "keys_with_both_sides",
                "eligible_keys",
                "incomplete_common_keys",
                "keys_with_left_only",
                "keys_with_right_only",
                "keys_with_neither_side",
                "exact_match_keys",
                "left_greater_keys",
                "right_greater_keys",
            )
            for field_name in amount_fields:
                grouped_total = sum(
                    group[field_name]
                    for group in (
                        *amount_breakdown["published_values"].values(),
                        amount_breakdown["other"],
                        amount_breakdown["null"],
                    )
                )
                self.assertEqual(grouped_total, reconciliation[field_name])
            for group in (
                *amount_breakdown["published_values"].values(),
                amount_breakdown["other"],
                amount_breakdown["null"],
            ):
                self.assertEqual(
                    group["anchor_keys"],
                    group["keys_with_both_sides"]
                    + group["keys_with_left_only"]
                    + group["keys_with_right_only"]
                    + group["keys_with_neither_side"],
                )
                self.assertEqual(
                    group["keys_with_both_sides"],
                    group["eligible_keys"] + group["incomplete_common_keys"],
                )
                self.assertEqual(
                    group["eligible_keys"],
                    group["exact_match_keys"]
                    + group["left_greater_keys"]
                    + group["right_greater_keys"],
                )
            markdown = reports["source-value-profile.md"].decode("utf-8")
            self.assertIn("승인된 데이터 제약이나 지표 정의가 아닙니다", markdown)
            self.assertIn("통과 기준이 아닙니다", markdown)
            self.assertIn("상태별 비교 범위와 방향", markdown)
            self.assertIn("기타(값 비공개)", markdown)
            self.assertIn("0 < |차이| ≤ 0.01", markdown)
            self.assertIn("서로 상쇄될 수 있어", markdown)

    def test_value_profiles_do_not_change_existing_three_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir, contract_path = _write_value_fixture(root)
            with_value_profiles = profile_source.generate_reports(data_dir, contract_path)

            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract.pop("value_profiles")
            without_value_profiles_path = root / "contract-without-value-profiles.json"
            without_value_profiles_path.write_text(
                json.dumps(contract, ensure_ascii=False), encoding="utf-8"
            )
            without_value_profiles = profile_source.generate_reports(
                data_dir, without_value_profiles_path
            )

            for filename in (
                "source-manifest.json",
                "source-profile.json",
                "source-profile.md",
            ):
                self.assertEqual(
                    with_value_profiles[filename], without_value_profiles[filename]
                )

    def test_value_profiles_hide_unknown_values_and_parse_strictly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir, contract_path = _write_value_fixture(Path(temporary))
            orders_path = data_dir / "orders.csv"
            orders_path.write_text(
                orders_path.read_text(encoding="utf-8")
                .replace("canceled", "SECRET_STATUS")
                .replace("2020-01-03 10:00:00", " SECRET_TIME")
                .replace("o3,third", "SYNTHETIC_SECRET_ID,third"),
                encoding="utf-8",
                newline="",
            )
            items_path = data_dir / "items.csv"
            items_path.write_text(
                items_path.read_text(encoding="utf-8").replace("o1,1,10.00", "o1, 1,10.00"),
                encoding="utf-8",
                newline="",
            )

            reports = profile_source.generate_reports(data_dir, contract_path)
            value_profile = json.loads(reports["source-value-profile.json"])
            statuses = value_profile["tables"]["orders"]["domain_counts"][
                "order_status"
            ]
            self.assertEqual(statuses["other_rows"], 1)
            self.assertEqual(statuses["other_distinct_values"], 1)
            date_breakdown = value_profile["datetime_comparisons"][
                "delivered_vs_estimated_date"
            ]["breakdown"]
            self.assertEqual(date_breakdown["other"]["rows"], 1)
            self.assertEqual(date_breakdown["other"]["skipped_null_rows"], 1)
            amount_breakdown = value_profile["amount_reconciliations"][
                "items_vs_payments_by_order"
            ]["anchor_breakdown"]
            self.assertEqual(amount_breakdown["other"]["anchor_keys"], 1)
            self.assertEqual(amount_breakdown["other"]["keys_with_neither_side"], 1)
            delivered = value_profile["tables"]["orders"]["type_checks"][
                "delivered_at"
            ]
            self.assertEqual(delivered["invalid_rows"], 1)
            item_id = value_profile["tables"]["items"]["type_checks"]["item_id"]
            self.assertEqual(item_id["invalid_rows"], 1)
            comparison = value_profile["datetime_comparisons"][
                "delivered_vs_estimated_timestamp"
            ]
            self.assertEqual(comparison["skipped_null_rows"], 1)
            self.assertEqual(comparison["skipped_invalid_rows"], 1)
            self.assertEqual(
                comparison["rows"],
                comparison["comparable_rows"]
                + comparison["skipped_null_rows"]
                + comparison["skipped_invalid_rows"],
            )
            combined_output = b"\n".join(reports.values()).decode("utf-8")
            self.assertNotIn("SECRET_STATUS", combined_output)
            self.assertNotIn("SECRET_TIME", combined_output)
            self.assertNotIn("SYNTHETIC_SECRET_ID", combined_output)

    def test_numeric_type_profile_counts_zero_negative_and_invalid(self) -> None:
        runtime = profile_source.TypeCheckRuntime(
            {"column": "amount", "target_type": "decimal"}
        )
        for value in ("-1.50", "0", "2.00", "NaN", " 3"):
            runtime.add(value)
        summary = runtime.summary()
        self.assertEqual(summary["parseable_rows"], 3)
        self.assertEqual(summary["invalid_rows"], 2)
        self.assertEqual(summary["negative_rows"], 1)
        self.assertEqual(summary["zero_rows"], 1)
        self.assertEqual(summary["minimum"], "-1.50")
        self.assertEqual(summary["maximum"], "2.00")

    def test_amount_reconciliation_excludes_only_incomplete_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir, contract_path = _write_value_fixture(Path(temporary))
            items_path = data_dir / "items.csv"
            items_path.write_text(
                items_path.read_text(encoding="utf-8").replace("20.00", "SECRET_AMOUNT"),
                encoding="utf-8",
                newline="",
            )

            reports = profile_source.generate_reports(data_dir, contract_path)
            value_profile = json.loads(reports["source-value-profile.json"])
            reconciliation = value_profile["amount_reconciliations"][
                "items_vs_payments_by_order"
            ]
            self.assertEqual(reconciliation["keys_with_both_sides"], 2)
            self.assertEqual(reconciliation["incomplete_common_keys"], 1)
            self.assertEqual(reconciliation["eligible_keys"], 1)
            self.assertEqual(reconciliation["exact_match_keys"], 1)
            self.assertEqual(reconciliation["left_total_on_eligible_keys"], "5.50")
            self.assertEqual(reconciliation["right_total_on_eligible_keys"], "5.50")
            combined_output = b"\n".join(reports.values()).decode("utf-8")
            self.assertNotIn("SECRET_AMOUNT", combined_output)

    def test_amount_breakdown_rejects_conflicting_anchor_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir, contract_path = _write_value_fixture(Path(temporary))
            orders_path = data_dir / "orders.csv"
            orders_path.write_text(
                orders_path.read_text(encoding="utf-8")
                + "o1,duplicate,canceled,2020-01-01 10:00:00,,2020-01-03 23:00:00\n",
                encoding="utf-8",
                newline="",
            )

            with self.assertRaisesRegex(
                profile_source.ProfileError,
                "anchor key has conflicting breakdown values",
            ):
                profile_source.generate_reports(data_dir, contract_path)

    def test_value_profile_contract_validation(self) -> None:
        def unsupported_type(contract: dict) -> None:
            contract["value_profiles"]["type_checks"][0]["target_type"] = "float"

        def missing_type_column(contract: dict) -> None:
            contract["value_profiles"]["type_checks"][0]["column"] = "missing_column"

        def untracked_reconciliation_amount(contract: dict) -> None:
            contract["value_profiles"]["amount_reconciliations"][0][
                "left_amount_columns"
            ] = ["not_tracked"]

        def datetime_breakdown_without_domain(contract: dict) -> None:
            contract["value_profiles"]["datetime_comparisons"][0][
                "breakdown_column"
            ] = "note"

        def amount_breakdown_without_domain(contract: dict) -> None:
            contract["value_profiles"]["amount_reconciliations"][0][
                "anchor_breakdown_column"
            ] = "note"

        def reconciliation_amount_without_decimal_check(contract: dict) -> None:
            price_check = next(
                item
                for item in contract["value_profiles"]["type_checks"]
                if item["file"] == "items.csv" and item["column"] == "price"
            )
            price_check["target_type"] = "integer"

        for label, mutate in (
            ("unsupported type", unsupported_type),
            ("missing column", missing_type_column),
            ("untracked amount", untracked_reconciliation_amount),
            ("datetime breakdown without domain", datetime_breakdown_without_domain),
            ("amount breakdown without domain", amount_breakdown_without_domain),
            (
                "reconciliation amount without decimal check",
                reconciliation_amount_without_decimal_check,
            ),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                _, contract_path = _write_value_fixture(Path(temporary))
                contract = json.loads(contract_path.read_text(encoding="utf-8"))
                mutate(contract)
                contract_path.write_text(json.dumps(contract), encoding="utf-8")
                with self.assertRaises(profile_source.ProfileError):
                    profile_source.load_contract(contract_path)

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
