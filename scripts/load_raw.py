#!/usr/bin/env python3
"""Load the contracted Olist snapshot into PostgreSQL raw tables."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import psycopg
from dotenv import load_dotenv
from psycopg import sql

import profile_source


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RAW_SCHEMA = "raw"
REPORT_JSON = "raw-load-reconciliation.json"
REPORT_MARKDOWN = "raw-load-reconciliation.md"
COPY_CHUNK_BYTES = 1024 * 1024
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
LOCAL_DATABASE_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class RawLoadError(RuntimeError):
    """Expected raw-load failure that is safe to show without row values."""


@dataclass(frozen=True)
class TableSpec:
    file_name: str
    table_name: str
    columns: tuple[str, ...]
    expected_rows: int
    expected_bytes: int
    expected_sha256: str


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str = field(repr=False)

    @classmethod
    def from_environment(cls) -> "DatabaseConfig":
        password = os.environ.get("PGPASSWORD")
        if not password:
            raise RawLoadError(
                "PGPASSWORD is required; copy .env.example to .env and set a local password"
            )
        host = os.environ.get("PGHOST", "127.0.0.1")
        if host.lower() not in LOCAL_DATABASE_HOSTS:
            raise RawLoadError("PGHOST must be a local loopback host")
        raw_port = os.environ.get("PGPORT", "55432")
        try:
            port = int(raw_port)
        except ValueError:
            raise RawLoadError("PGPORT must be an integer") from None
        if not 1 <= port <= 65535:
            raise RawLoadError("PGPORT must be between 1 and 65535")
        return cls(
            host=host,
            port=port,
            dbname=os.environ.get("PGDATABASE", "olist"),
            user=os.environ.get("PGUSER", "olist"),
            password=password,
        )

    def connection_kwargs(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.dbname,
            "user": self.user,
            "password": self.password,
            "connect_timeout": 10,
            "application_name": "ecommerce_analytics_raw_loader",
            "autocommit": True,
        }


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RawLoadError(f"cannot read {label}: {type(exc).__name__}") from None
    if not isinstance(value, dict):
        raise RawLoadError(f"{label} root must be an object")
    return value


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = _read_json(path, "source manifest")
    if manifest.get("manifest_version") != 1:
        raise RawLoadError("unsupported source manifest version")
    return manifest


def _require_nonnegative_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RawLoadError(f"source manifest has an invalid {label}")
    return value


def build_table_specs(
    contract: dict[str, Any], manifest: dict[str, Any]
) -> tuple[TableSpec, ...]:
    if manifest.get("contract_version") != contract.get("contract_version"):
        raise RawLoadError("source manifest and contract versions do not match")
    if manifest.get("dataset") != contract.get("dataset"):
        raise RawLoadError("source manifest and contract datasets do not match")

    contract_files = contract.get("files")
    manifest_files = manifest.get("files")
    if not isinstance(contract_files, list) or not isinstance(manifest_files, list):
        raise RawLoadError("contract and manifest files must be arrays")

    manifest_by_name: dict[str, dict[str, Any]] = {}
    manifest_tables: set[str] = set()
    for raw_item in manifest_files:
        if not isinstance(raw_item, dict):
            raise RawLoadError("source manifest file entry must be an object")
        name = raw_item.get("name")
        table = raw_item.get("table")
        if not isinstance(name, str) or not isinstance(table, str):
            raise RawLoadError("source manifest file identity is invalid")
        if name in manifest_by_name or table in manifest_tables:
            raise RawLoadError("source manifest has duplicate file or table entries")
        manifest_by_name[name] = raw_item
        manifest_tables.add(table)

    contract_names = {item["name"] for item in contract_files}
    if set(manifest_by_name) != contract_names:
        raise RawLoadError("source manifest and contract file sets do not match")

    specs: list[TableSpec] = []
    for contract_item in contract_files:
        name = contract_item["name"]
        manifest_item = manifest_by_name[name]
        table = contract_item["table"]
        columns = tuple(contract_item["headers"])
        if not SAFE_IDENTIFIER.fullmatch(table) or any(
            not SAFE_IDENTIFIER.fullmatch(column) for column in columns
        ):
            raise RawLoadError("contract contains an unsafe SQL identifier")
        if manifest_item.get("table") != table:
            raise RawLoadError(f"source manifest table does not match contract: {name}")
        if manifest_item.get("headers") != list(columns):
            raise RawLoadError(f"source manifest headers do not match contract: {name}")
        sha256 = manifest_item.get("sha256")
        if not isinstance(sha256, str) or not SHA256.fullmatch(sha256):
            raise RawLoadError(f"source manifest has an invalid checksum: {name}")
        if not isinstance(manifest_item.get("utf8_bom"), bool):
            raise RawLoadError(f"source manifest has an invalid BOM flag: {name}")
        specs.append(
            TableSpec(
                file_name=name,
                table_name=table,
                columns=columns,
                expected_rows=_require_nonnegative_integer(
                    manifest_item.get("logical_rows"), f"row count: {name}"
                ),
                expected_bytes=_require_nonnegative_integer(
                    manifest_item.get("bytes"), f"byte count: {name}"
                ),
                expected_sha256=sha256,
            )
        )
    return tuple(specs)


def prepare_snapshot(
    data_dir: Path, contract_path: Path, reports_dir: Path
) -> tuple[tuple[TableSpec, ...], str, dict[str, Any]]:
    # This full deterministic check validates exact files, headers, logical rows,
    # checksums and all committed source-profile results before any DB mutation.
    profile_source.check_reports(data_dir, contract_path, reports_dir)
    contract = profile_source.load_contract(contract_path)
    manifest_path = reports_dir / "source-manifest.json"
    manifest = load_manifest(manifest_path)
    specs = build_table_specs(contract, manifest)
    try:
        manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise RawLoadError(
            f"cannot hash source manifest: {type(exc).__name__}"
        ) from None
    return specs, manifest_sha256, manifest


def connect_database(config: DatabaseConfig) -> psycopg.Connection[Any]:
    try:
        return psycopg.connect(**config.connection_kwargs())
    except psycopg.Error as exc:
        raise RawLoadError(f"database connection failed: {type(exc).__name__}") from None


def require_postgresql_15(connection: psycopg.Connection[Any]) -> str:
    try:
        row = connection.execute(
            "SELECT current_setting('server_version_num'), "
            "current_setting('server_version')"
        ).fetchone()
    except psycopg.Error as exc:
        raise RawLoadError(f"database version check failed: {type(exc).__name__}") from None
    if row is None:
        raise RawLoadError("database version check returned no result")
    try:
        version_number = int(row[0])
    except (TypeError, ValueError):
        raise RawLoadError("database returned an invalid version") from None
    if not 150000 <= version_number < 160000:
        raise RawLoadError("PostgreSQL 15 is required")
    return str(row[1])


def _validate_schema_name(schema: str) -> None:
    if not SAFE_IDENTIFIER.fullmatch(schema):
        raise RawLoadError("unsafe PostgreSQL schema name")


def _qualified_table(schema: str, table: str) -> sql.Composed:
    return sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))


def _ensure_raw_tables(
    cursor: psycopg.Cursor[Any], specs: Iterable[TableSpec], schema: str
) -> None:
    cursor.execute(
        sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema))
    )
    for spec in specs:
        definitions = sql.SQL(", ").join(
            sql.SQL("{} text").format(sql.Identifier(column))
            for column in spec.columns
        )
        cursor.execute(
            sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(
                _qualified_table(schema, spec.table_name), definitions
            )
        )


def validate_raw_schema(
    cursor: psycopg.Cursor[Any], specs: Iterable[TableSpec], schema: str = RAW_SCHEMA
) -> None:
    _validate_schema_name(schema)
    specs = tuple(specs)
    expected_tables = {spec.table_name for spec in specs}

    cursor.execute(
        """
        SELECT c.relname, c.relkind, c.relpersistence,
               c.relrowsecurity, c.relforcerowsecurity
        FROM pg_catalog.pg_class AS c
        JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
        ORDER BY c.relname
        """,
        (schema,),
    )
    relations = cursor.fetchall()
    actual_tables = {str(row[0]) for row in relations}
    if actual_tables != expected_tables or any(
        row[1] != "r" or row[2] != "p" for row in relations
    ):
        raise RawLoadError("raw schema table set or relation type does not match contract")
    if any(row[3] or row[4] for row in relations):
        raise RawLoadError("raw tables must not use row-level security")

    cursor.execute(
        """
        SELECT table_name, column_name, ordinal_position, data_type,
               is_nullable, column_default, is_identity, is_generated
        FROM information_schema.columns
        WHERE table_schema = %s
        ORDER BY table_name, ordinal_position
        """,
        (schema,),
    )
    rows_by_table: dict[str, list[tuple[Any, ...]]] = {
        spec.table_name: [] for spec in specs
    }
    for row in cursor.fetchall():
        table_name = str(row[0])
        if table_name in rows_by_table:
            rows_by_table[table_name].append(tuple(row))

    for spec in specs:
        actual = rows_by_table[spec.table_name]
        if len(actual) != len(spec.columns):
            raise RawLoadError(
                f"raw table columns do not match contract: {spec.table_name}"
            )
        for position, (column, row) in enumerate(zip(spec.columns, actual), start=1):
            (
                _,
                actual_column,
                ordinal,
                data_type,
                nullable,
                default,
                identity,
                generated,
            ) = row
            if (
                actual_column != column
                or ordinal != position
                or data_type != "text"
                or nullable != "YES"
                or default is not None
                or identity != "NO"
                or generated != "NEVER"
            ):
                raise RawLoadError(
                    f"raw table column definition does not match contract: {spec.table_name}"
                )

    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.table_constraints
        WHERE table_schema = %s
        LIMIT 1
        """,
        (schema,),
    )
    if cursor.fetchone() is not None:
        raise RawLoadError("raw tables must not have database constraints")

    cursor.execute(
        "SELECT tablename FROM pg_catalog.pg_indexes WHERE schemaname = %s LIMIT 1",
        (schema,),
    )
    if cursor.fetchone() is not None:
        raise RawLoadError("raw tables must not have indexes")

    cursor.execute(
        """
        SELECT c.relname
        FROM pg_catalog.pg_trigger AS t
        JOIN pg_catalog.pg_class AS c ON c.oid = t.tgrelid
        JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND NOT t.tgisinternal
        LIMIT 1
        """,
        (schema,),
    )
    if cursor.fetchone() is not None:
        raise RawLoadError("raw tables must not have user triggers")

    cursor.execute(
        """
        SELECT c.relname
        FROM pg_catalog.pg_rewrite AS r
        JOIN pg_catalog.pg_class AS c ON c.oid = r.ev_class
        JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND r.rulename <> '_RETURN'
        LIMIT 1
        """,
        (schema,),
    )
    if cursor.fetchone() is not None:
        raise RawLoadError("raw tables must not have user rewrite rules")


def copy_csv(
    cursor: psycopg.Cursor[Any],
    spec: TableSpec,
    path: Path,
    *,
    schema: str = RAW_SCHEMA,
    chunk_size: int = COPY_CHUNK_BYTES,
) -> None:
    if chunk_size <= 0:
        raise RawLoadError("COPY chunk size must be positive")
    columns = sql.SQL(", ").join(sql.Identifier(column) for column in spec.columns)
    # FORCE_NOT_NULL delays NULL interpretation until dbt staging: both quoted and
    # unquoted empty CSV fields arrive as empty text in the raw layer.
    statement = sql.SQL(
        "COPY {} ({}) FROM STDIN WITH ("
        "FORMAT CSV, HEADER TRUE, ENCODING 'UTF8', FORCE_NOT_NULL ({})"
        ")"
    ).format(
        _qualified_table(schema, spec.table_name),
        columns,
        columns,
    )
    digest = hashlib.sha256()
    byte_count = 0
    try:
        with path.open("rb") as source, cursor.copy(statement) as copy:
            while chunk := source.read(chunk_size):
                digest.update(chunk)
                byte_count += len(chunk)
                copy.write(chunk)
    except (OSError, psycopg.Error) as exc:
        raise RawLoadError(
            f"COPY failed for raw table {spec.table_name}: {type(exc).__name__}"
        ) from None
    if byte_count != spec.expected_bytes or digest.hexdigest() != spec.expected_sha256:
        raise RawLoadError(
            f"source bytes changed during COPY for raw table {spec.table_name}"
        )


def _row_counts(
    cursor: psycopg.Cursor[Any], specs: Iterable[TableSpec], schema: str
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for spec in specs:
        cursor.execute(
            sql.SQL("SELECT COUNT(*) FROM {}").format(
                _qualified_table(schema, spec.table_name)
            )
        )
        row = cursor.fetchone()
        if row is None:
            raise RawLoadError(f"row count returned no result: {spec.table_name}")
        counts[spec.table_name] = int(row[0])
    return counts


def _require_matching_counts(
    specs: Iterable[TableSpec], counts: dict[str, int]
) -> None:
    mismatches = [
        spec.table_name
        for spec in specs
        if counts.get(spec.table_name) != spec.expected_rows
    ]
    if mismatches:
        raise RawLoadError(
            "raw row count does not match source manifest: " + ", ".join(mismatches)
        )


def load_snapshot(
    connection: psycopg.Connection[Any],
    specs: Iterable[TableSpec],
    data_dir: Path,
    *,
    schema: str = RAW_SCHEMA,
    chunk_size: int = COPY_CHUNK_BYTES,
) -> dict[str, int]:
    _validate_schema_name(schema)
    specs = tuple(specs)
    try:
        with connection.transaction():
            with connection.cursor() as cursor:
                _ensure_raw_tables(cursor, specs, schema)
                validate_raw_schema(cursor, specs, schema)
                targets = sql.SQL(", ").join(
                    _qualified_table(schema, spec.table_name) for spec in specs
                )
                cursor.execute(sql.SQL("TRUNCATE TABLE {}").format(targets))
                for spec in specs:
                    copy_csv(
                        cursor,
                        spec,
                        data_dir / spec.file_name,
                        schema=schema,
                        chunk_size=chunk_size,
                    )
                counts = _row_counts(cursor, specs, schema)
                _require_matching_counts(specs, counts)
        return counts
    except RawLoadError:
        raise
    except psycopg.Error as exc:
        raise RawLoadError(f"raw load failed: {type(exc).__name__}") from None


def check_snapshot(
    connection: psycopg.Connection[Any],
    specs: Iterable[TableSpec],
    *,
    schema: str = RAW_SCHEMA,
) -> dict[str, int]:
    specs = tuple(specs)
    try:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                validate_raw_schema(cursor, specs, schema)
                counts = _row_counts(cursor, specs, schema)
                _require_matching_counts(specs, counts)
        return counts
    except RawLoadError:
        raise
    except psycopg.Error as exc:
        raise RawLoadError(f"raw check failed: {type(exc).__name__}") from None


def build_report(
    specs: Iterable[TableSpec],
    counts: dict[str, int],
    *,
    manifest_sha256: str,
    postgres_version: str,
    dataset: dict[str, Any],
    generated_by_command: str,
) -> dict[str, Any]:
    if generated_by_command not in {"load", "check"}:
        raise RawLoadError("unknown report command")
    tables = [
        {
            "actual_rows": counts.get(spec.table_name),
            "expected_rows": spec.expected_rows,
            "matches": counts.get(spec.table_name) == spec.expected_rows,
            "source_file": spec.file_name,
            "table": spec.table_name,
        }
        for spec in specs
    ]
    mismatch_count = sum(not table["matches"] for table in tables)
    return {
        "all_counts_match": mismatch_count == 0,
        "dataset": dataset,
        "generated_by_command": generated_by_command,
        "load_mode": "transactional_full_refresh",
        "mismatch_count": mismatch_count,
        "postgresql_version": postgres_version,
        "raw_column_type": "text",
        "raw_empty_field_policy": "empty_text",
        "report_version": 1,
        "schema": RAW_SCHEMA,
        "source_manifest_sha256": manifest_sha256,
        "verification_scope": (
            "source_bytes_schema_and_row_counts"
            if generated_by_command == "load"
            else "schema_and_row_counts"
        ),
        "table_count": len(tables),
        "tables": tables,
        "total_actual_rows": sum(
            int(table["actual_rows"] or 0) for table in tables
        ),
        "total_expected_rows": sum(int(table["expected_rows"]) for table in tables),
    }


def render_report_json(report: dict[str, Any]) -> bytes:
    return (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def render_report_markdown(report: dict[str, Any]) -> bytes:
    status = "PASS" if report["all_counts_match"] else "FAIL"
    lines = [
        "# PostgreSQL raw 적재 검산",
        "",
        "## 목적과 범위",
        "",
        "승인된 Olist CSV snapshot 9개가 PostgreSQL `raw` schema에 원천 행 단위로",
        "빠짐없이 적재됐는지 확인한다. 이 단계에서는 타입 변환, 공백 정리, 중복 제거와",
        "업무 규칙 적용을 하지 않는다.",
        "",
        "## 결과 요약",
        "",
        f"- 판정: **{status}**",
        f"- PostgreSQL: `{report['postgresql_version']}`",
        f"- 보고서 생성 명령: `{report['generated_by_command']}`",
        f"- Manifest SHA-256: `{report['source_manifest_sha256']}`",
        f"- 테이블: {report['table_count']}개",
        f"- 원천 기대 행: {report['total_expected_rows']:,}",
        f"- DB 실제 행: {report['total_actual_rows']:,}",
        f"- 불일치 테이블: {report['mismatch_count']}개",
        "",
        "## 테이블별 행 수 대사",
        "",
        "| raw table | source file | 기대 행 | DB 행 | 결과 |",
        "|---|---|---:|---:|---|",
    ]
    for table in report["tables"]:
        table_status = "일치" if table["matches"] else "불일치"
        actual = table["actual_rows"]
        actual_text = "없음" if actual is None else f"{actual:,}"
        lines.append(
            f"| `{table['table']}` | `{table['source_file']}` | "
            f"{table['expected_rows']:,} | {actual_text} | {table_status} |"
        )
    if report["generated_by_command"] == "load":
        execution_lines = [
            "- 적재 중 읽은 동일한 파일 바이트의 크기와 SHA-256를 manifest와 다시 비교했다.",
            "- 이번 `load` 실행은 9개 테이블을 한 transaction에서 비우고 `COPY`한 뒤",
            "  전수 행 수가 모두 맞을 때만 commit했다.",
        ]
    else:
        execution_lines = [
            "- 이번 `check` 실행은 DB를 변경하지 않고 현재 schema와 행 수를 다시 확인했다.",
            "  loader의 `load` 경로는 9개 테이블을 한 transaction에서 full refresh하도록",
            "  구현돼 있다.",
            "- `check`는 값 전체를 원천과 다시 대조하지 않으므로 행 수가 같은 값 변경까지",
            "  탐지하는 명령은 아니다.",
        ]
    lines.extend(
        [
            "",
            "## 확인한 것",
            "",
            "- DB를 변경하기 전에 기존 source profiler의 `check`로 정확한 파일 9개,",
            "  헤더·논리 행 수·파일 checksum과 공개 집계 보고서의 일치를 다시 확인했다.",
            "- `raw`에는 계약의 테이블 9개만 있고, 열 이름·순서가 계약과 같으며 모든 열이",
            "  nullable `text`이고 constraint·index·trigger·rule·RLS가 없음을 확인했다.",
        ]
    )
    lines.extend(execution_lines)
    lines.extend(
        [
            "- `load`는 재실행해도 행이 누적되지 않는 full refresh 방식이다.",
            "- 빈 CSV field는 raw에서 빈 text로 보존한다. NULL·숫자·timestamp 해석은 다음",
            "  dbt staging 단계의 명시적 규칙으로 미룬다.",
            "",
            "## 의미와 한계",
            "",
            "- 파일 checksum은 적재에 사용한 입력 파일이 승인된 snapshot과 같은지 보장한다.",
            "  DB 각 행의 checksum이라는 뜻은 아니다.",
            "- 행 수 대사는 누락·중복 적재를 탐지하지만, 값의 업무적 타당성까지 보장하지 않는다.",
            "  key·cast·domain·관계 검증은 승인된 계약에 따라 dbt staging에서 구현한다.",
            "- 이 구성은 로컬 재현 환경이며 production 운영, 실시간 처리나 cloud 배포를",
            "  증명하지 않는다.",
            "",
            "## 재현 방법",
            "",
            "```bash",
            "cp .env.example .env",
            "python3 -m venv .venv",
            ".venv/bin/python -m pip install -r requirements.txt",
            "docker compose up -d --wait",
            ".venv/bin/python scripts/load_raw.py load --data-dir data/raw",
            ".venv/bin/python scripts/load_raw.py check --data-dir data/raw",
            "```",
        ]
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_reports(reports_dir: Path, report: dict[str, Any]) -> None:
    payloads = {
        REPORT_JSON: render_report_json(report),
        REPORT_MARKDOWN: render_report_markdown(report),
    }
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RawLoadError(f"cannot create report directory: {type(exc).__name__}") from None
    if reports_dir.is_symlink() or not reports_dir.is_dir():
        raise RawLoadError("report directory is unsafe")

    staged: list[tuple[Path, Path]] = []
    try:
        for filename, payload in payloads.items():
            descriptor, temporary_name = tempfile.mkstemp(
                dir=reports_dir, prefix=f".{filename}.", suffix=".tmp"
            )
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                temporary_path.unlink(missing_ok=True)
                raise
            staged.append((temporary_path, reports_dir / filename))
        for temporary_path, target in staged:
            os.replace(temporary_path, target)
    except OSError as exc:
        raise RawLoadError(f"cannot write raw-load reports: {type(exc).__name__}") from None
    finally:
        for temporary_path, _ in staged:
            temporary_path.unlink(missing_ok=True)


def execute(
    command: str,
    *,
    data_dir: Path,
    contract_path: Path,
    reports_dir: Path,
) -> dict[str, Any]:
    specs, manifest_sha256, manifest = prepare_snapshot(
        data_dir, contract_path, reports_dir
    )
    config = DatabaseConfig.from_environment()
    with connect_database(config) as connection:
        postgres_version = require_postgresql_15(connection)
        if command == "load":
            counts = load_snapshot(connection, specs, data_dir)
        else:
            counts = check_snapshot(connection, specs)
    report = build_report(
        specs,
        counts,
        manifest_sha256=manifest_sha256,
        postgres_version=postgres_version,
        dataset=manifest["dataset"],
        generated_by_command=command,
    )
    write_reports(reports_dir, report)
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Load or check contracted Olist CSVs in PostgreSQL raw tables."
    )
    parser.add_argument("command", choices=("load", "check"))
    parser.add_argument(
        "--data-dir", type=Path, default=REPOSITORY_ROOT / "data" / "raw"
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=REPOSITORY_ROOT / "config" / "olist-source-contract.json",
    )
    parser.add_argument(
        "--reports-dir", type=Path, default=REPOSITORY_ROOT / "reports"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPOSITORY_ROOT / ".env", override=False)
    args = _build_parser().parse_args(argv)
    try:
        report = execute(
            args.command,
            data_dir=args.data_dir,
            contract_path=args.contract,
            reports_dir=args.reports_dir,
        )
    except (RawLoadError, profile_source.ProfileError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    action = "loaded and checked" if args.command == "load" else "checked"
    print(
        f"raw snapshot {action}: {report['table_count']} tables, "
        f"{report['total_actual_rows']} rows, {report['mismatch_count']} mismatches"
    )
    print("raw-load reconciliation reports written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
