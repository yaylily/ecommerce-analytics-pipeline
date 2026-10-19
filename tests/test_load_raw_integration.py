from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
load_dotenv(ROOT / ".env", override=False)

import load_raw  # noqa: E402
from psycopg import sql  # noqa: E402


RUN_POSTGRES_TESTS = os.environ.get("RUN_POSTGRES_TESTS") == "1"


def _spec(path: Path, table: str, expected_rows: int) -> load_raw.TableSpec:
    payload = path.read_bytes()
    return load_raw.TableSpec(
        file_name=path.name,
        table_name=table,
        columns=("id", "note", "label"),
        expected_rows=expected_rows,
        expected_bytes=len(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
    )


@unittest.skipUnless(
    RUN_POSTGRES_TESTS,
    "set RUN_POSTGRES_TESTS=1 with local PostgreSQL variables to run",
)
class PostgreSQLRawLoadIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        config = load_raw.DatabaseConfig.from_environment()
        self.connection = load_raw.connect_database(config)
        load_raw.require_postgresql_15(self.connection)
        self.schema = f"raw_test_{uuid.uuid4().hex}"

    def tearDown(self) -> None:
        try:
            self.connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(self.schema)
                )
            )
        finally:
            self.connection.close()

    def test_copy_handles_bom_crlf_empty_fields_multiline_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            path = data_dir / "edge.csv"
            path.write_bytes(
                b"\xef\xbb\xbfid,note,label\r\n"
                b"1,,x\r\n"
                b'2,"",y\r\n'
                + "3,\"hello,\r\nworld\",한글\r\n".encode("utf-8")
            )
            spec = _spec(path, "edge_cases", 3)

            first = load_raw.load_snapshot(
                self.connection,
                (spec,),
                data_dir,
                schema=self.schema,
                chunk_size=5,
            )
            second = load_raw.load_snapshot(
                self.connection,
                (spec,),
                data_dir,
                schema=self.schema,
                chunk_size=5,
            )
            self.assertEqual(first, {"edge_cases": 3})
            self.assertEqual(second, first)
            rows = self.connection.execute(
                sql.SQL("SELECT id, note, label FROM {}.{} ORDER BY id").format(
                    sql.Identifier(self.schema), sql.Identifier("edge_cases")
                )
            ).fetchall()
            self.assertEqual(
                rows,
                [("1", "", "x"), ("2", "", "y"), ("3", "hello,\r\nworld", "한글")],
            )

    def test_late_row_count_failure_rolls_back_all_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            first_path = data_dir / "first.csv"
            second_path = data_dir / "second.csv"
            first_path.write_text(
                "id,note,label\n1,baseline,a\n", encoding="utf-8", newline=""
            )
            second_path.write_text(
                "id,note,label\n2,baseline,b\n", encoding="utf-8", newline=""
            )
            baseline = (
                _spec(first_path, "first_table", 1),
                _spec(second_path, "second_table", 1),
            )
            load_raw.load_snapshot(
                self.connection, baseline, data_dir, schema=self.schema, chunk_size=7
            )

            first_path.write_text(
                "id,note,label\n9,replacement,x\n", encoding="utf-8", newline=""
            )
            second_path.write_text(
                "id,note,label\n8,replacement,y\n", encoding="utf-8", newline=""
            )
            failing = (
                _spec(first_path, "first_table", 1),
                _spec(second_path, "second_table", 2),
            )
            with self.assertRaisesRegex(load_raw.RawLoadError, "row count"):
                load_raw.load_snapshot(
                    self.connection,
                    failing,
                    data_dir,
                    schema=self.schema,
                    chunk_size=7,
                )

            first_rows = self.connection.execute(
                sql.SQL("SELECT id, note, label FROM {}.{}").format(
                    sql.Identifier(self.schema), sql.Identifier("first_table")
                )
            ).fetchall()
            second_rows = self.connection.execute(
                sql.SQL("SELECT id, note, label FROM {}.{}").format(
                    sql.Identifier(self.schema), sql.Identifier("second_table")
                )
            ).fetchall()
            self.assertEqual(first_rows, [("1", "baseline", "a")])
            self.assertEqual(second_rows, [("2", "baseline", "b")])

    def test_value_rewriting_trigger_is_rejected_before_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            path = data_dir / "trigger.csv"
            path.write_text(
                "id,note,label\n1,baseline,a\n", encoding="utf-8", newline=""
            )
            spec = _spec(path, "trigger_table", 1)
            load_raw.load_snapshot(
                self.connection, (spec,), data_dir, schema=self.schema
            )

            function_name = "rewrite_note"
            trigger_name = "rewrite_note_before_insert"
            self.connection.execute(
                sql.SQL(
                    "CREATE FUNCTION {}.{}() RETURNS trigger LANGUAGE plpgsql AS "
                    "'BEGIN NEW.note := ''rewritten''; RETURN NEW; END'"
                ).format(sql.Identifier(self.schema), sql.Identifier(function_name))
            )
            self.connection.execute(
                sql.SQL(
                    "CREATE TRIGGER {} BEFORE INSERT ON {}.{} "
                    "FOR EACH ROW EXECUTE FUNCTION {}.{}()"
                ).format(
                    sql.Identifier(trigger_name),
                    sql.Identifier(self.schema),
                    sql.Identifier("trigger_table"),
                    sql.Identifier(self.schema),
                    sql.Identifier(function_name),
                )
            )

            path.write_text(
                "id,note,label\n2,replacement,b\n", encoding="utf-8", newline=""
            )
            replacement = _spec(path, "trigger_table", 1)
            with self.assertRaisesRegex(load_raw.RawLoadError, "triggers"):
                load_raw.load_snapshot(
                    self.connection, (replacement,), data_dir, schema=self.schema
                )

            rows = self.connection.execute(
                sql.SQL("SELECT id, note, label FROM {}.{}").format(
                    sql.Identifier(self.schema), sql.Identifier("trigger_table")
                )
            ).fetchall()
            self.assertEqual(rows, [("1", "baseline", "a")])


if __name__ == "__main__":
    unittest.main()
