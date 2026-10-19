from __future__ import annotations

import copy
import os
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import load_raw  # noqa: E402
import profile_source  # noqa: E402


CONTRACT_PATH = ROOT / "config" / "olist-source-contract.json"
MANIFEST_PATH = ROOT / "reports" / "source-manifest.json"


class RawLoadContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = profile_source.load_contract(CONTRACT_PATH)
        self.manifest = load_raw.load_manifest(MANIFEST_PATH)

    def test_repository_contract_builds_exact_nine_specs_in_contract_order(self) -> None:
        specs = load_raw.build_table_specs(self.contract, self.manifest)
        self.assertEqual(len(specs), 9)
        self.assertEqual(
            [spec.table_name for spec in specs],
            [item["table"] for item in self.contract["files"]],
        )
        self.assertEqual(sum(spec.expected_rows for spec in specs), 1550922)
        self.assertTrue(all(spec.expected_bytes > 0 for spec in specs))

    def test_manifest_file_set_and_mapping_fail_closed(self) -> None:
        mutations = []

        missing = copy.deepcopy(self.manifest)
        missing["files"].pop()
        mutations.append(missing)

        extra = copy.deepcopy(self.manifest)
        extra["files"].append(copy.deepcopy(extra["files"][0]))
        extra["files"][-1]["name"] = "extra.csv"
        extra["files"][-1]["table"] = "extra_table"
        mutations.append(extra)

        wrong_table = copy.deepcopy(self.manifest)
        wrong_table["files"][0]["table"] = "wrong_table"
        mutations.append(wrong_table)

        wrong_header = copy.deepcopy(self.manifest)
        wrong_header["files"][0]["headers"] = list(
            reversed(wrong_header["files"][0]["headers"])
        )
        mutations.append(wrong_header)

        wrong_rows = copy.deepcopy(self.manifest)
        wrong_rows["files"][0]["logical_rows"] = -1
        mutations.append(wrong_rows)

        wrong_hash = copy.deepcopy(self.manifest)
        wrong_hash["files"][0]["sha256"] = "not-a-checksum"
        mutations.append(wrong_hash)

        for mutation in mutations:
            with self.subTest(mutation=mutations.index(mutation)):
                with self.assertRaises(load_raw.RawLoadError):
                    load_raw.build_table_specs(self.contract, mutation)

    def test_report_is_deterministic_and_aggregate_only(self) -> None:
        specs = load_raw.build_table_specs(self.contract, self.manifest)
        counts = {spec.table_name: spec.expected_rows for spec in specs}
        report = load_raw.build_report(
            specs,
            counts,
            manifest_sha256="a" * 64,
            postgres_version="15.19",
            dataset=self.manifest["dataset"],
            generated_by_command="load",
        )
        first_json = load_raw.render_report_json(report)
        second_json = load_raw.render_report_json(report)
        first_markdown = load_raw.render_report_markdown(report)
        second_markdown = load_raw.render_report_markdown(report)
        self.assertEqual(first_json, second_json)
        self.assertEqual(first_markdown, second_markdown)
        combined = first_json + first_markdown
        self.assertIn(b"1550922", combined)
        self.assertEqual(
            report["verification_scope"], "source_bytes_schema_and_row_counts"
        )
        for forbidden in (
            b"PGPASSWORD",
            b"postgresql://",
            b"/Users/",
            b"review_comment_message",
        ):
            self.assertNotIn(forbidden, combined)

    def test_database_config_requires_password_and_hides_it_in_repr(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(load_raw.RawLoadError, "PGPASSWORD"):
                load_raw.DatabaseConfig.from_environment()

        with mock.patch.dict(
            os.environ,
            {"PGPASSWORD": "do-not-print-this", "PGPORT": "55432"},
            clear=True,
        ):
            config = load_raw.DatabaseConfig.from_environment()
        self.assertEqual(config.port, 55432)
        self.assertNotIn("do-not-print-this", repr(config))

        with mock.patch.dict(
            os.environ,
            {"PGPASSWORD": "local-test-only", "PGHOST": "db.example.com"},
            clear=True,
        ):
            with self.assertRaisesRegex(load_raw.RawLoadError, "local loopback"):
                load_raw.DatabaseConfig.from_environment()


if __name__ == "__main__":
    unittest.main()
