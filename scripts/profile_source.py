#!/usr/bin/env python3
"""Create deterministic, aggregate-only profiles for contracted CSV sources."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


REPORT_FILENAMES = (
    "source-manifest.json",
    "source-profile.json",
    "source-profile.md",
    "source-value-profile.json",
    "source-value-profile.md",
)
CSV_FIELD_SIZE_LIMIT = 10 * 1024 * 1024
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
STRICT_INTEGER = re.compile(r"^[+-]?[0-9]+$")
BREAKDOWN_OTHER = "__other__"
BREAKDOWN_NULL = "__null__"

Key = str | tuple[str, ...]


class ProfileError(RuntimeError):
    """Expected validation failure that is safe to show without raw values."""


def _key_from_row(row: dict[str | None, str | None], columns: Iterable[str]) -> Key | None:
    values = tuple(row[column] for column in columns)
    if any(value == "" for value in values):
        return None
    if len(values) == 1:
        return values[0]  # type: ignore[return-value]
    return values  # type: ignore[return-value]


@dataclass
class KeyTracker:
    counts: Counter[Key] = field(default_factory=Counter)
    null_rows: int = 0

    def add(self, row: dict[str | None, str | None], columns: list[str]) -> None:
        key = _key_from_row(row, columns)
        if key is None:
            self.null_rows += 1
            return
        self.counts[key] += 1

    def summary(self) -> dict[str, int]:
        multiplicities = self.counts.values()
        return {
            "null_rows": self.null_rows,
            "distinct_keys": len(self.counts),
            "duplicate_rows": sum(count - 1 for count in multiplicities if count > 1),
            "keys_with_multiple_rows": sum(count > 1 for count in self.counts.values()),
            "max_multiplicity": max(self.counts.values(), default=0),
        }


@dataclass
class RelationshipRuntime:
    spec: dict[str, Any]
    parent: KeyTracker = field(default_factory=KeyTracker)
    child: KeyTracker = field(default_factory=KeyTracker)


@dataclass
class AmountSide:
    spec: dict[str, Any]
    keys: KeyTracker = field(default_factory=KeyTracker)
    sums: dict[str, defaultdict[Key, Decimal]] = field(default_factory=dict)
    null_amount_rows: Counter[str] = field(default_factory=Counter)
    invalid_amount_rows: Counter[str] = field(default_factory=Counter)
    incomplete_keys: dict[str, set[Key]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.sums = {
            column: defaultdict(Decimal) for column in self.spec["amount_columns"]
        }
        self.incomplete_keys = {
            column: set() for column in self.spec["amount_columns"]
        }

    def add(self, row: dict[str | None, str | None]) -> None:
        columns = self.spec["columns"]
        key = _key_from_row(row, columns)
        self.keys.add(row, columns)

        for column in self.spec["amount_columns"]:
            value = row[column]
            if value == "":
                self.null_amount_rows[column] += 1
                if key is not None:
                    self.incomplete_keys[column].add(key)
                continue
            if value is not None and value != value.strip() and key is not None:
                # Preserve the existing structural-profile parsing semantics while
                # excluding whitespace-padded values from the new reconciliation.
                self.incomplete_keys[column].add(key)
            try:
                amount = Decimal(value)  # type: ignore[arg-type]
            except (InvalidOperation, ValueError):
                self.invalid_amount_rows[column] += 1
                if key is not None:
                    self.incomplete_keys[column].add(key)
                continue
            if not amount.is_finite():
                self.invalid_amount_rows[column] += 1
                if key is not None:
                    self.incomplete_keys[column].add(key)
                continue
            if key is not None:
                self.sums[column][key] += amount


@dataclass
class JoinRuntime:
    spec: dict[str, Any]
    anchor: KeyTracker = field(default_factory=KeyTracker)
    left: AmountSide = field(init=False)
    right: AmountSide = field(init=False)

    def __post_init__(self) -> None:
        self.left = AmountSide(self.spec["left"])
        self.right = AmountSide(self.spec["right"])


ParsedValue = int | Decimal | datetime
ParseResult = tuple[str, ParsedValue | None]


def _breakdown_group(value: str, published_values: list[str]) -> str:
    if value == "":
        return BREAKDOWN_NULL
    if value in published_values:
        return value
    return BREAKDOWN_OTHER


def _parse_value(value: str, spec: dict[str, Any]) -> ParseResult:
    if value == "":
        return "null", None
    if value != value.strip():
        return "invalid", None
    try:
        target_type = spec["target_type"]
        if target_type == "integer":
            if STRICT_INTEGER.fullmatch(value) is None:
                return "invalid", None
            return "parseable", int(value)
        if target_type == "decimal":
            parsed_decimal = Decimal(value)
            if not parsed_decimal.is_finite():
                return "invalid", None
            return "parseable", parsed_decimal
        return "parseable", datetime.strptime(value, spec["format"])
    except (InvalidOperation, ValueError, OverflowError):
        return "invalid", None


@dataclass
class TypeCheckRuntime:
    spec: dict[str, Any]
    null_rows: int = 0
    parseable_rows: int = 0
    invalid_rows: int = 0
    zero_rows: int = 0
    negative_rows: int = 0
    minimum: ParsedValue | None = None
    maximum: ParsedValue | None = None

    def add(self, value: str) -> ParseResult:
        status, parsed = _parse_value(value, self.spec)
        if status == "null":
            self.null_rows += 1
        elif status == "invalid":
            self.invalid_rows += 1
        else:
            self.parseable_rows += 1
            if parsed is not None:
                if self.minimum is None or parsed < self.minimum:
                    self.minimum = parsed
                if self.maximum is None or parsed > self.maximum:
                    self.maximum = parsed
                if isinstance(parsed, (int, Decimal)):
                    if parsed == 0:
                        self.zero_rows += 1
                    elif parsed < 0:
                        self.negative_rows += 1
        return status, parsed

    def _value_text(self, value: ParsedValue | None) -> int | str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.strftime(self.spec["format"])
        if isinstance(value, Decimal):
            return _decimal_text(value)
        return value

    def summary(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "invalid_rows": self.invalid_rows,
            "maximum": self._value_text(self.maximum),
            "minimum": self._value_text(self.minimum),
            "null_rows": self.null_rows,
            "parseable_rows": self.parseable_rows,
            "rows": self.null_rows + self.parseable_rows + self.invalid_rows,
            "target_type": self.spec["target_type"],
        }
        if self.spec["target_type"] in {"integer", "decimal"}:
            result["negative_rows"] = self.negative_rows
            result["zero_rows"] = self.zero_rows
        return result


@dataclass
class DomainCountRuntime:
    spec: dict[str, Any]
    published_counts: Counter[str] = field(default_factory=Counter)
    other_values: set[str] = field(default_factory=set)
    null_rows: int = 0
    other_rows: int = 0

    def add(self, value: str) -> None:
        if value == "":
            self.null_rows += 1
        elif value in self.spec["published_values"]:
            self.published_counts[value] += 1
        else:
            self.other_rows += 1
            self.other_values.add(value)

    def summary(self) -> dict[str, Any]:
        published = {
            value: self.published_counts[value]
            for value in self.spec["published_values"]
        }
        return {
            "column": self.spec["column"],
            "null_rows": self.null_rows,
            "other_distinct_values": len(self.other_values),
            "other_rows": self.other_rows,
            "published_value_counts": published,
            "rows": self.null_rows + self.other_rows + sum(published.values()),
        }


@dataclass
class DatetimeComparisonRuntime:
    spec: dict[str, Any]
    left_null_rows: int = 0
    right_null_rows: int = 0
    left_invalid_rows: int = 0
    right_invalid_rows: int = 0
    left_before_right_rows: int = 0
    equal_rows: int = 0
    left_after_right_rows: int = 0
    skipped_null_rows: int = 0
    skipped_invalid_rows: int = 0
    rows: int = 0
    breakdown_counts: dict[str, Counter[str]] = field(
        default_factory=lambda: defaultdict(Counter)
    )

    def add(
        self,
        left: ParseResult,
        right: ParseResult,
        breakdown_value: str | None = None,
    ) -> None:
        self.rows += 1
        left_status, left_value = left
        right_status, right_value = right
        breakdown: Counter[str] | None = None
        if "breakdown_column" in self.spec:
            if breakdown_value is None:
                raise AssertionError("datetime breakdown value is missing")
            group = _breakdown_group(
                breakdown_value, self.spec["_breakdown_published_values"]
            )
            breakdown = self.breakdown_counts[group]
            breakdown["rows"] += 1
        if left_status == "null":
            self.left_null_rows += 1
        elif left_status == "invalid":
            self.left_invalid_rows += 1
        if right_status == "null":
            self.right_null_rows += 1
        elif right_status == "invalid":
            self.right_invalid_rows += 1
        if left_status == "null" or right_status == "null":
            self.skipped_null_rows += 1
            if breakdown is not None:
                breakdown["skipped_null_rows"] += 1
            return
        if left_status == "invalid" or right_status == "invalid":
            self.skipped_invalid_rows += 1
            if breakdown is not None:
                breakdown["skipped_invalid_rows"] += 1
            return

        if not isinstance(left_value, datetime) or not isinstance(right_value, datetime):
            raise AssertionError("datetime comparison received non-datetime values")
        if self.spec["comparison_unit"] == "date":
            comparable_left = left_value.date()
            comparable_right = right_value.date()
        else:
            comparable_left = left_value
            comparable_right = right_value
        if comparable_left < comparable_right:
            self.left_before_right_rows += 1
            if breakdown is not None:
                breakdown["left_before_right_rows"] += 1
        elif comparable_left == comparable_right:
            self.equal_rows += 1
            if breakdown is not None:
                breakdown["equal_rows"] += 1
        else:
            self.left_after_right_rows += 1
            if breakdown is not None:
                breakdown["left_after_right_rows"] += 1

    @staticmethod
    def _breakdown_summary(counts: Counter[str]) -> dict[str, int]:
        comparable_rows = (
            counts["left_before_right_rows"]
            + counts["equal_rows"]
            + counts["left_after_right_rows"]
        )
        return {
            "comparable_rows": comparable_rows,
            "equal_rows": counts["equal_rows"],
            "left_after_right_rows": counts["left_after_right_rows"],
            "left_before_right_rows": counts["left_before_right_rows"],
            "rows": counts["rows"],
            "skipped_invalid_rows": counts["skipped_invalid_rows"],
            "skipped_null_rows": counts["skipped_null_rows"],
        }

    def summary(self) -> dict[str, Any]:
        comparable_rows = (
            self.left_before_right_rows + self.equal_rows + self.left_after_right_rows
        )
        result: dict[str, Any] = {
            "comparable_rows": comparable_rows,
            "comparison_unit": self.spec["comparison_unit"],
            "equal_rows": self.equal_rows,
            "file": self.spec["file"],
            "kind": self.spec["kind"],
            "left_after_right_rows": self.left_after_right_rows,
            "left_before_right_rows": self.left_before_right_rows,
            "left_column": self.spec["left_column"],
            "left_invalid_rows": self.left_invalid_rows,
            "left_null_rows": self.left_null_rows,
            "right_column": self.spec["right_column"],
            "right_invalid_rows": self.right_invalid_rows,
            "right_null_rows": self.right_null_rows,
            "rows": self.rows,
            "skipped_invalid_rows": self.skipped_invalid_rows,
            "skipped_null_rows": self.skipped_null_rows,
        }
        if "breakdown_column" in self.spec:
            result["breakdown"] = {
                "column": self.spec["breakdown_column"],
                "null": self._breakdown_summary(
                    self.breakdown_counts[BREAKDOWN_NULL]
                ),
                "other": self._breakdown_summary(
                    self.breakdown_counts[BREAKDOWN_OTHER]
                ),
                "published_values": {
                    value: self._breakdown_summary(self.breakdown_counts[value])
                    for value in self.spec["_breakdown_published_values"]
                },
            }
        return result


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProfileError(f"contract field must be an object: {label}")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ProfileError(f"contract field must be an array: {label}")
    return value


def _validate_name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SAFE_NAME.fullmatch(value):
        raise ProfileError(f"contract contains an unsafe name: {label}")
    return value


def _validate_columns(
    columns: Any,
    *,
    label: str,
    headers: list[str],
) -> list[str]:
    result = _require_list(columns, label)
    if not result:
        raise ProfileError(f"contract column list is empty: {label}")
    validated = [_validate_name(column, label) for column in result]
    if len(validated) != len(set(validated)):
        raise ProfileError(f"contract column list has duplicates: {label}")
    if any(column not in headers for column in validated):
        raise ProfileError(f"contract column is absent from its file header: {label}")
    return validated


def load_contract(path: Path) -> dict[str, Any]:
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileError(f"cannot read contract: {type(exc).__name__}") from None

    contract = _require_dict(contract, "root")
    if contract.get("contract_version") != 1:
        raise ProfileError("unsupported contract_version")
    dataset = _require_dict(contract.get("dataset"), "dataset")
    for field_name in ("name", "slug", "url"):
        if not isinstance(dataset.get(field_name), str) or not dataset[field_name]:
            raise ProfileError(f"contract dataset field is missing: {field_name}")

    files = _require_list(contract.get("files"), "files")
    if not files:
        raise ProfileError("contract has no files")

    file_by_name: dict[str, dict[str, Any]] = {}
    table_names: set[str] = set()
    for index, raw_file_spec in enumerate(files):
        file_spec = _require_dict(raw_file_spec, f"files[{index}]")
        name = _validate_name(file_spec.get("name"), f"files[{index}].name")
        if Path(name).name != name or not name.endswith(".csv"):
            raise ProfileError("contract file names must be plain CSV file names")
        table = _validate_name(file_spec.get("table"), f"files[{index}].table")
        if name in file_by_name or table in table_names:
            raise ProfileError("contract has duplicate file or table names")
        headers = _require_list(file_spec.get("headers"), f"{name}.headers")
        validated_headers = [_validate_name(header, f"{name}.headers") for header in headers]
        if not validated_headers or len(validated_headers) != len(set(validated_headers)):
            raise ProfileError(f"contract has empty or duplicate headers: {name}")
        file_spec["headers"] = validated_headers

        for collection_name in ("candidate_keys", "group_profiles"):
            profiles = _require_list(file_spec.get(collection_name), f"{name}.{collection_name}")
            seen_profile_names: set[str] = set()
            for profile in profiles:
                profile = _require_dict(profile, f"{name}.{collection_name}")
                profile_name = _validate_name(profile.get("name"), f"{name}.{collection_name}.name")
                if profile_name in seen_profile_names:
                    raise ProfileError(f"duplicate key profile name in contract: {name}")
                seen_profile_names.add(profile_name)
                profile["columns"] = _validate_columns(
                    profile.get("columns"),
                    label=f"{name}.{collection_name}.{profile_name}",
                    headers=validated_headers,
                )

        file_by_name[name] = file_spec
        table_names.add(table)

    relationships = _require_list(contract.get("relationships"), "relationships")
    relationship_by_name: dict[str, dict[str, Any]] = {}
    for raw_relationship in relationships:
        relationship = _require_dict(raw_relationship, "relationships[]")
        name = _validate_name(relationship.get("name"), "relationship.name")
        if name in relationship_by_name:
            raise ProfileError("contract has duplicate relationship names")
        for side in ("parent", "child"):
            file_name = _validate_name(
                relationship.get(f"{side}_file"), f"{name}.{side}_file"
            )
            if file_name not in file_by_name:
                raise ProfileError(f"relationship references an unknown file: {name}")
            relationship[f"{side}_columns"] = _validate_columns(
                relationship.get(f"{side}_columns"),
                label=f"{name}.{side}_columns",
                headers=file_by_name[file_name]["headers"],
            )
        if len(relationship["parent_columns"]) != len(relationship["child_columns"]):
            raise ProfileError(f"relationship key widths do not match: {name}")
        relationship_by_name[name] = relationship

    fanouts = _require_list(contract.get("fanouts"), "fanouts")
    fanout_names: set[str] = set()
    for raw_fanout in fanouts:
        fanout = _require_dict(raw_fanout, "fanouts[]")
        name = _validate_name(fanout.get("name"), "fanout.name")
        relationship_name = _validate_name(fanout.get("relationship"), f"{name}.relationship")
        if name in fanout_names or relationship_name not in relationship_by_name:
            raise ProfileError(f"invalid fanout contract: {name}")
        fanout_names.add(name)

    joins = _require_list(contract.get("join_amplifications"), "join_amplifications")
    join_names: set[str] = set()
    join_by_name: dict[str, dict[str, Any]] = {}
    for raw_join in joins:
        join = _require_dict(raw_join, "join_amplifications[]")
        name = _validate_name(join.get("name"), "join_amplification.name")
        if name in join_names:
            raise ProfileError("contract has duplicate join amplification names")
        join_names.add(name)
        anchor_file = _validate_name(join.get("anchor_file"), f"{name}.anchor_file")
        if anchor_file not in file_by_name:
            raise ProfileError(f"join amplification references an unknown anchor: {name}")
        join["anchor_columns"] = _validate_columns(
            join.get("anchor_columns"),
            label=f"{name}.anchor_columns",
            headers=file_by_name[anchor_file]["headers"],
        )
        for side_name in ("left", "right"):
            side = _require_dict(join.get(side_name), f"{name}.{side_name}")
            file_name = _validate_name(side.get("file"), f"{name}.{side_name}.file")
            if file_name not in file_by_name:
                raise ProfileError(f"join amplification references an unknown file: {name}")
            side["columns"] = _validate_columns(
                side.get("columns"),
                label=f"{name}.{side_name}.columns",
                headers=file_by_name[file_name]["headers"],
            )
            side["amount_columns"] = _validate_columns(
                side.get("amount_columns"),
                label=f"{name}.{side_name}.amount_columns",
                headers=file_by_name[file_name]["headers"],
            )
            if len(side["columns"]) != len(join["anchor_columns"]):
                raise ProfileError(f"join amplification key widths do not match: {name}")
        join_by_name[name] = join

    raw_value_profiles = contract.get("value_profiles")
    if raw_value_profiles is None:
        value_profiles: dict[str, Any] = {
            "type_checks": [],
            "domain_counts": [],
            "datetime_comparisons": [],
            "amount_reconciliations": [],
        }
    else:
        value_profiles = _require_dict(raw_value_profiles, "value_profiles")
        for collection_name in (
            "type_checks",
            "domain_counts",
            "datetime_comparisons",
            "amount_reconciliations",
        ):
            value_profiles[collection_name] = _require_list(
                value_profiles.get(collection_name), f"value_profiles.{collection_name}"
            )

    type_check_by_file_column: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_type_check in value_profiles["type_checks"]:
        type_check = _require_dict(raw_type_check, "value_profiles.type_checks[]")
        file_name = _validate_name(type_check.get("file"), "type_check.file")
        if file_name not in file_by_name:
            raise ProfileError("type check references an unknown file")
        column = _validate_name(type_check.get("column"), "type_check.column")
        if column not in file_by_name[file_name]["headers"]:
            raise ProfileError("type check references an unknown column")
        target_type = _validate_name(
            type_check.get("target_type"), "type_check.target_type"
        )
        if target_type not in {"integer", "decimal", "timestamp"}:
            raise ProfileError("type check has an unsupported target_type")
        key = (file_name, column)
        if key in type_check_by_file_column:
            raise ProfileError("contract has duplicate type checks")
        if target_type == "timestamp":
            value_format = type_check.get("format")
            if not isinstance(value_format, str) or not value_format:
                raise ProfileError("timestamp type check requires a format")
        elif "format" in type_check:
            raise ProfileError("only timestamp type checks may define a format")
        type_check_by_file_column[key] = type_check

    domain_names: set[str] = set()
    domain_by_file_column: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_domain in value_profiles["domain_counts"]:
        domain = _require_dict(raw_domain, "value_profiles.domain_counts[]")
        name = _validate_name(domain.get("name"), "domain_count.name")
        file_name = _validate_name(domain.get("file"), f"{name}.file")
        if name in domain_names or file_name not in file_by_name:
            raise ProfileError(f"invalid domain count contract: {name}")
        column = _validate_name(domain.get("column"), f"{name}.column")
        if column not in file_by_name[file_name]["headers"]:
            raise ProfileError(f"domain count references an unknown column: {name}")
        published_values = _require_list(
            domain.get("published_values"), f"{name}.published_values"
        )
        if not published_values:
            raise ProfileError(f"domain count has no published values: {name}")
        validated_values = [
            _validate_name(value, f"{name}.published_values")
            for value in published_values
        ]
        if len(validated_values) != len(set(validated_values)):
            raise ProfileError(f"domain count has duplicate published values: {name}")
        domain["published_values"] = validated_values
        domain_key = (file_name, column)
        if domain_key in domain_by_file_column:
            raise ProfileError("contract has duplicate domain counts for a column")
        domain_by_file_column[domain_key] = domain
        domain_names.add(name)

    comparison_names: set[str] = set()
    for raw_comparison in value_profiles["datetime_comparisons"]:
        comparison = _require_dict(
            raw_comparison, "value_profiles.datetime_comparisons[]"
        )
        name = _validate_name(comparison.get("name"), "datetime_comparison.name")
        file_name = _validate_name(comparison.get("file"), f"{name}.file")
        if name in comparison_names or file_name not in file_by_name:
            raise ProfileError(f"invalid datetime comparison contract: {name}")
        for side in ("left", "right"):
            column = _validate_name(
                comparison.get(f"{side}_column"), f"{name}.{side}_column"
            )
            type_check = type_check_by_file_column.get((file_name, column))
            if type_check is None or type_check["target_type"] != "timestamp":
                raise ProfileError(
                    f"datetime comparison requires timestamp type checks: {name}"
                )
        comparison_unit = _validate_name(
            comparison.get("comparison_unit"), f"{name}.comparison_unit"
        )
        kind = _validate_name(comparison.get("kind"), f"{name}.kind")
        if comparison_unit not in {"timestamp", "date"}:
            raise ProfileError(f"invalid datetime comparison unit: {name}")
        if kind not in {"chronology", "delivery_timing"}:
            raise ProfileError(f"invalid datetime comparison kind: {name}")
        if "breakdown_column" in comparison:
            breakdown_column = _validate_name(
                comparison.get("breakdown_column"), f"{name}.breakdown_column"
            )
            if breakdown_column not in file_by_name[file_name]["headers"]:
                raise ProfileError(
                    f"datetime breakdown column must belong to the same file: {name}"
                )
            breakdown_domain = domain_by_file_column.get(
                (file_name, breakdown_column)
            )
            if breakdown_domain is None:
                raise ProfileError(
                    f"datetime breakdown requires a published domain count: {name}"
                )
            comparison["_breakdown_published_values"] = breakdown_domain[
                "published_values"
            ]
        comparison_names.add(name)

    reconciliation_names: set[str] = set()
    for raw_reconciliation in value_profiles["amount_reconciliations"]:
        reconciliation = _require_dict(
            raw_reconciliation, "value_profiles.amount_reconciliations[]"
        )
        name = _validate_name(reconciliation.get("name"), "amount_reconciliation.name")
        join_name = _validate_name(
            reconciliation.get("join_amplification"), f"{name}.join_amplification"
        )
        if name in reconciliation_names or join_name not in join_by_name:
            raise ProfileError(f"invalid amount reconciliation contract: {name}")
        join = join_by_name[join_name]
        for side_name in ("left", "right"):
            selected_columns = _validate_columns(
                reconciliation.get(f"{side_name}_amount_columns"),
                label=f"{name}.{side_name}_amount_columns",
                headers=join[side_name]["amount_columns"],
            )
            if not set(selected_columns).issubset(join[side_name]["amount_columns"]):
                raise ProfileError(
                    f"amount reconciliation references an untracked amount: {name}"
                )
            side_file = join[side_name]["file"]
            for column in selected_columns:
                type_check = type_check_by_file_column.get((side_file, column))
                if type_check is None or type_check["target_type"] != "decimal":
                    raise ProfileError(
                        f"amount reconciliation requires decimal type checks: {name}"
                    )
            reconciliation[f"{side_name}_amount_columns"] = selected_columns
        if "anchor_breakdown_column" in reconciliation:
            anchor_column = _validate_name(
                reconciliation.get("anchor_breakdown_column"),
                f"{name}.anchor_breakdown_column",
            )
            anchor_file = join["anchor_file"]
            if anchor_column not in file_by_name[anchor_file]["headers"]:
                raise ProfileError(
                    f"amount breakdown column must belong to the anchor file: {name}"
                )
            breakdown_domain = domain_by_file_column.get((anchor_file, anchor_column))
            if breakdown_domain is None:
                raise ProfileError(
                    f"amount breakdown requires a published domain count: {name}"
                )
            reconciliation["_anchor_breakdown_published_values"] = breakdown_domain[
                "published_values"
            ]
        reconciliation_names.add(name)

    contract["value_profiles"] = value_profiles

    return contract


def _validate_input_files(data_dir: Path, contract: dict[str, Any]) -> dict[str, Path]:
    try:
        root = data_dir.resolve(strict=True)
    except OSError as exc:
        raise ProfileError(f"cannot access data directory: {type(exc).__name__}") from None
    if not root.is_dir():
        raise ProfileError("data directory is not a directory")

    expected_names = {file_spec["name"] for file_spec in contract["files"]}
    try:
        actual_csv_names = {
            path.name
            for path in root.iterdir()
            if path.is_file() and path.suffix.lower() == ".csv"
        }
    except OSError as exc:
        raise ProfileError(f"cannot list data directory: {type(exc).__name__}") from None

    missing = sorted(expected_names - actual_csv_names)
    unexpected = sorted(actual_csv_names - expected_names)
    if missing:
        raise ProfileError(f"missing contracted CSV files: {', '.join(missing)}")
    if unexpected:
        raise ProfileError(f"unexpected CSV file count: {len(unexpected)}")

    result: dict[str, Path] = {}
    for name in sorted(expected_names):
        path = root / name
        if path.is_symlink():
            raise ProfileError(f"contracted CSV must not be a symlink: {name}")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ProfileError(f"cannot access contracted CSV {name}: {type(exc).__name__}") from None
        if resolved.parent != root or not resolved.is_file():
            raise ProfileError(f"contracted CSV path is unsafe: {name}")
        result[name] = resolved
    return result


def _sha256_size_and_bom(path: Path, safe_name: str) -> tuple[str, int, bool]:
    digest = hashlib.sha256()
    size = 0
    utf8_bom = False
    try:
        with path.open("rb") as handle:
            first_chunk = True
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                if first_chunk:
                    utf8_bom = chunk.startswith(b"\xef\xbb\xbf")
                    first_chunk = False
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise ProfileError(f"cannot hash contracted CSV {safe_name}: {type(exc).__name__}") from None
    return digest.hexdigest(), size, utf8_bom


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _ratio_text(numerator: int | Decimal, denominator: int | Decimal) -> str | None:
    if denominator == 0:
        return None
    return format(Decimal(numerator) / Decimal(denominator), ".6f")


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _scan_sources(
    data_dir: Path,
    contract: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    paths = _validate_input_files(data_dir, contract)
    candidate_trackers: dict[str, dict[str, tuple[list[str], KeyTracker]]] = {}
    group_trackers: dict[str, dict[str, tuple[list[str], KeyTracker]]] = {}
    relationship_runtimes = {
        spec["name"]: RelationshipRuntime(spec)
        for spec in contract["relationships"]
    }
    join_runtimes = {
        spec["name"]: JoinRuntime(spec)
        for spec in contract["join_amplifications"]
    }
    type_runtimes_by_file: dict[str, dict[str, TypeCheckRuntime]] = defaultdict(dict)
    for spec in contract["value_profiles"]["type_checks"]:
        type_runtimes_by_file[spec["file"]][spec["column"]] = TypeCheckRuntime(spec)
    domain_runtimes_by_file: dict[str, dict[str, DomainCountRuntime]] = defaultdict(dict)
    for spec in contract["value_profiles"]["domain_counts"]:
        domain_runtimes_by_file[spec["file"]][spec["name"]] = DomainCountRuntime(spec)
    comparison_runtimes_by_file: dict[
        str, dict[str, DatetimeComparisonRuntime]
    ] = defaultdict(dict)
    for spec in contract["value_profiles"]["datetime_comparisons"]:
        comparison_runtimes_by_file[spec["file"]][spec["name"]] = (
            DatetimeComparisonRuntime(spec)
        )
    reconciliation_breakdowns: dict[str, dict[Key, str]] = defaultdict(dict)
    reconciliations_by_anchor_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for reconciliation in contract["value_profiles"]["amount_reconciliations"]:
        if "anchor_breakdown_column" in reconciliation:
            join = join_runtimes[reconciliation["join_amplification"]].spec
            reconciliations_by_anchor_file[join["anchor_file"]].append(reconciliation)

    for file_spec in contract["files"]:
        file_name = file_spec["name"]
        candidate_trackers[file_name] = {
            profile["name"]: (profile["columns"], KeyTracker())
            for profile in file_spec["candidate_keys"]
        }
        group_trackers[file_name] = {
            profile["name"]: (profile["columns"], KeyTracker())
            for profile in file_spec["group_profiles"]
        }

    manifest_files: list[dict[str, Any]] = []
    table_profiles: dict[str, Any] = {}
    csv.field_size_limit(CSV_FIELD_SIZE_LIMIT)

    for file_spec in contract["files"]:
        file_name = file_spec["name"]
        table_name = file_spec["table"]
        headers = file_spec["headers"]
        path = paths[file_name]
        file_sha256, file_size, utf8_bom = _sha256_size_and_bom(path, file_name)
        row_count = 0
        null_counts = {header: 0 for header in headers}
        whitespace_only_counts = {header: 0 for header in headers}

        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                actual_headers = reader.fieldnames
                if actual_headers is None:
                    raise ProfileError(f"contracted CSV has no header: {file_name}")
                if len(actual_headers) != len(set(actual_headers)):
                    raise ProfileError(f"contracted CSV has duplicate headers: {file_name}")
                if actual_headers != headers:
                    raise ProfileError(f"contracted CSV header does not match: {file_name}")

                for logical_record, row in enumerate(reader, start=1):
                    if None in row or any(row[header] is None for header in headers):
                        raise ProfileError(
                            f"contracted CSV record width does not match in {file_name} "
                            f"at logical record {logical_record}"
                        )
                    row_count += 1

                    for header in headers:
                        value = row[header]
                        if value == "":
                            null_counts[header] += 1
                        elif value is not None and value.isspace():
                            whitespace_only_counts[header] += 1

                    for columns, tracker in candidate_trackers[file_name].values():
                        tracker.add(row, columns)
                    for columns, tracker in group_trackers[file_name].values():
                        tracker.add(row, columns)

                    for runtime in relationship_runtimes.values():
                        spec = runtime.spec
                        if spec["parent_file"] == file_name:
                            runtime.parent.add(row, spec["parent_columns"])
                        if spec["child_file"] == file_name:
                            runtime.child.add(row, spec["child_columns"])

                    for runtime in join_runtimes.values():
                        spec = runtime.spec
                        if spec["anchor_file"] == file_name:
                            runtime.anchor.add(row, spec["anchor_columns"])
                        if spec["left"]["file"] == file_name:
                            runtime.left.add(row)
                        if spec["right"]["file"] == file_name:
                            runtime.right.add(row)

                    parsed_values: dict[str, ParseResult] = {}
                    for column, runtime in type_runtimes_by_file[file_name].items():
                        parsed_values[column] = runtime.add(row[column])  # type: ignore[arg-type]
                    for runtime in domain_runtimes_by_file[file_name].values():
                        runtime.add(row[runtime.spec["column"]])  # type: ignore[arg-type]
                    for runtime in comparison_runtimes_by_file[file_name].values():
                        runtime.add(
                            parsed_values[runtime.spec["left_column"]],
                            parsed_values[runtime.spec["right_column"]],
                            (
                                row[runtime.spec["breakdown_column"]]
                                if "breakdown_column" in runtime.spec
                                else None
                            ),  # type: ignore[arg-type]
                        )
                    for reconciliation in reconciliations_by_anchor_file[file_name]:
                        join = join_runtimes[
                            reconciliation["join_amplification"]
                        ].spec
                        anchor_key = _key_from_row(row, join["anchor_columns"])
                        if anchor_key is not None:
                            breakdown_value = row[
                                reconciliation["anchor_breakdown_column"]
                            ]
                            breakdown_group = _breakdown_group(
                                breakdown_value,  # type: ignore[arg-type]
                                reconciliation[
                                    "_anchor_breakdown_published_values"
                                ],
                            )
                            breakdowns = reconciliation_breakdowns[
                                reconciliation["name"]
                            ]
                            previous_group = breakdowns.get(anchor_key)
                            if (
                                previous_group is not None
                                and previous_group != breakdown_group
                            ):
                                raise ProfileError(
                                    "anchor key has conflicting breakdown values: "
                                    f"{reconciliation['name']}"
                                )
                            breakdowns[anchor_key] = breakdown_group
        except ProfileError:
            raise
        except (csv.Error, UnicodeError) as exc:
            raise ProfileError(
                f"cannot parse contracted CSV {file_name}: {type(exc).__name__}"
            ) from None
        except OSError as exc:
            raise ProfileError(
                f"cannot read contracted CSV {file_name}: {type(exc).__name__}"
            ) from None

        manifest_files.append(
            {
                "bytes": file_size,
                "headers": headers,
                "logical_rows": row_count,
                "name": file_name,
                "sha256": file_sha256,
                "table": table_name,
                "utf8_bom": utf8_bom,
            }
        )
        table_profiles[table_name] = {
            "candidate_keys": {
                name: tracker.summary()
                for name, (_, tracker) in sorted(candidate_trackers[file_name].items())
            },
            "file": file_name,
            "group_profiles": {
                name: tracker.summary()
                for name, (_, tracker) in sorted(group_trackers[file_name].items())
            },
            "null_counts": null_counts,
            "rows": row_count,
            "whitespace_only_counts": whitespace_only_counts,
        }

    manifest = {
        "contract_version": contract["contract_version"],
        "dataset": {
            "name": contract["dataset"]["name"],
            "slug": contract["dataset"]["slug"],
            "url": contract["dataset"]["url"],
        },
        "files": manifest_files,
        "manifest_version": 1,
    }

    relationship_profiles: dict[str, Any] = {}
    for name, runtime in sorted(relationship_runtimes.items()):
        parent_keys = runtime.parent.counts
        child_keys = runtime.child.counts
        orphan_distinct_keys = 0
        orphan_rows = 0
        for key, count in child_keys.items():
            if key not in parent_keys:
                orphan_distinct_keys += 1
                orphan_rows += count
        matched_child_rows = sum(
            count for key, count in child_keys.items() if key in parent_keys
        )
        direct_join_rows = sum(
            child_count * parent_keys[key]
            for key, child_count in child_keys.items()
            if key in parent_keys
        )
        matched_parent_counts = [
            parent_keys[key] for key in child_keys if key in parent_keys
        ]
        relationship_profiles[name] = {
            "child_non_null_rows": sum(child_keys.values()),
            "child_null_key_rows": runtime.child.null_rows,
            "direct_join_row_increase": direct_join_rows - matched_child_rows,
            "direct_join_rows": direct_join_rows,
            "direct_join_rows_per_matched_child": _ratio_text(
                direct_join_rows, matched_child_rows
            ),
            "matched_child_rows": matched_child_rows,
            "matched_parent_distinct_keys": len(matched_parent_counts),
            "matched_parent_keys_with_multiple_rows": sum(
                count > 1 for count in matched_parent_counts
            ),
            "matched_parent_max_rows_per_key": max(matched_parent_counts, default=0),
            "orphan_distinct_keys": orphan_distinct_keys,
            "orphan_rows": orphan_rows,
            "parent_distinct_keys": len(parent_keys),
            "parent_null_key_rows": runtime.parent.null_rows,
        }

    fanout_profiles: dict[str, Any] = {}
    for fanout in sorted(contract["fanouts"], key=lambda item: item["name"]):
        runtime = relationship_runtimes[fanout["relationship"]]
        parent_keys = runtime.parent.counts
        child_keys = runtime.child.counts
        known_multiplicities = [child_keys.get(key, 0) for key in parent_keys]
        fanout_profiles[fanout["name"]] = {
            "child_rows_on_known_parents": sum(known_multiplicities),
            "max_children_per_parent": max(known_multiplicities, default=0),
            "parents_total": len(parent_keys),
            "parents_with_multiple_children": sum(
                multiplicity > 1 for multiplicity in known_multiplicities
            ),
            "parents_with_no_children": sum(
                multiplicity == 0 for multiplicity in known_multiplicities
            ),
            "parents_with_one_child": sum(
                multiplicity == 1 for multiplicity in known_multiplicities
            ),
        }

    join_profiles: dict[str, Any] = {}
    for name, runtime in sorted(join_runtimes.items()):
        anchor_keys = set(runtime.anchor.counts)
        common_keys = anchor_keys & set(runtime.left.keys.counts) & set(runtime.right.keys.counts)
        left_rows = sum(runtime.left.keys.counts[key] for key in common_keys)
        right_rows = sum(runtime.right.keys.counts[key] for key in common_keys)
        joined_rows = sum(
            runtime.left.keys.counts[key] * runtime.right.keys.counts[key]
            for key in common_keys
        )

        def amount_profile(
            side: AmountSide,
            multiplier_counts: Counter[Key],
        ) -> dict[str, Any]:
            amounts: dict[str, Any] = {}
            for column in side.spec["amount_columns"]:
                baseline = sum(
                    (side.sums[column].get(key, Decimal(0)) for key in common_keys),
                    Decimal(0),
                )
                after = sum(
                    (
                        side.sums[column].get(key, Decimal(0))
                        * multiplier_counts[key]
                        for key in common_keys
                    ),
                    Decimal(0),
                )
                values_complete = (
                    side.null_amount_rows[column] == 0
                    and side.invalid_amount_rows[column] == 0
                )
                amounts[column] = {
                    "baseline_on_common_keys": (
                        _decimal_text(baseline) if values_complete else None
                    ),
                    "increase_from_naive_join": (
                        _decimal_text(after - baseline) if values_complete else None
                    ),
                    "invalid_amount_rows_total": side.invalid_amount_rows[column],
                    "naive_join_total": _decimal_text(after) if values_complete else None,
                    "naive_join_to_baseline_ratio": (
                        _ratio_text(after, baseline) if values_complete else None
                    ),
                    "null_amount_rows_total": side.null_amount_rows[column],
                    "values_complete": values_complete,
                }
            return amounts

        join_profiles[name] = {
            "anchor_null_key_rows": runtime.anchor.null_rows,
            "keys_with_both_sides": len(common_keys),
            "left": {
                "amounts": amount_profile(runtime.left, runtime.right.keys.counts),
                "null_key_rows": runtime.left.keys.null_rows,
                "rows_before_on_common_keys": left_rows,
            },
            "naive_join": {
                "row_increase_vs_left": joined_rows - left_rows,
                "row_increase_vs_right": joined_rows - right_rows,
                "rows_after_to_left_ratio": _ratio_text(joined_rows, left_rows),
                "rows_after_to_right_ratio": _ratio_text(joined_rows, right_rows),
                "rows_after": joined_rows,
            },
            "right": {
                "amounts": amount_profile(runtime.right, runtime.left.keys.counts),
                "null_key_rows": runtime.right.keys.null_rows,
                "rows_before_on_common_keys": right_rows,
            },
        }

    profile = {
        "fanouts": fanout_profiles,
        "join_amplifications": join_profiles,
        "profile_scope": [
            "file_integrity",
            "headers_and_missing_values",
            "candidate_key_multiplicity",
            "relationship_coverage_and_fanout",
            "order_items_payments_join_amplification",
        ],
        "profile_version": 1,
        "relationships": relationship_profiles,
        "tables": table_profiles,
    }

    file_to_table = {
        file_spec["name"]: file_spec["table"] for file_spec in contract["files"]
    }
    value_table_profiles: dict[str, Any] = {}
    for file_name, table_name in sorted(file_to_table.items(), key=lambda item: item[1]):
        type_summaries = {
            column: runtime.summary()
            for column, runtime in sorted(type_runtimes_by_file[file_name].items())
        }
        domain_summaries = {
            name: runtime.summary()
            for name, runtime in sorted(domain_runtimes_by_file[file_name].items())
        }
        if type_summaries or domain_summaries:
            value_table_profiles[table_name] = {
                "domain_counts": domain_summaries,
                "file": file_name,
                "type_checks": type_summaries,
            }

    comparison_profiles = {
        name: runtime.summary()
        for file_runtimes in comparison_runtimes_by_file.values()
        for name, runtime in sorted(file_runtimes.items())
    }

    reconciliation_profiles: dict[str, Any] = {}
    for reconciliation in sorted(
        contract["value_profiles"]["amount_reconciliations"],
        key=lambda item: item["name"],
    ):
        runtime = join_runtimes[reconciliation["join_amplification"]]
        anchor_keys = set(runtime.anchor.counts)
        left_keys = set(runtime.left.keys.counts) & anchor_keys
        right_keys = set(runtime.right.keys.counts) & anchor_keys
        common_keys = left_keys & right_keys
        incomplete_keys: set[Key] = set()
        for column in reconciliation["left_amount_columns"]:
            incomplete_keys.update(runtime.left.incomplete_keys[column])
        for column in reconciliation["right_amount_columns"]:
            incomplete_keys.update(runtime.right.incomplete_keys[column])
        incomplete_common_keys = common_keys & incomplete_keys
        eligible_keys = common_keys - incomplete_keys

        left_total = Decimal(0)
        right_total = Decimal(0)
        absolute_difference_total = Decimal(0)
        maximum_absolute_difference = Decimal(0)
        exact_match_keys = 0
        left_greater_keys = 0
        right_greater_keys = 0
        amount_breakdown_counts: dict[str, Counter[str]] = defaultdict(Counter)
        breakdown_by_key = reconciliation_breakdowns[reconciliation["name"]]
        if "anchor_breakdown_column" in reconciliation:
            for key in anchor_keys:
                group_counts = amount_breakdown_counts[
                    breakdown_by_key.get(key, BREAKDOWN_OTHER)
                ]
                group_counts["anchor_keys"] += 1
                if key in common_keys:
                    group_counts["keys_with_both_sides"] += 1
                    if key in incomplete_common_keys:
                        group_counts["incomplete_common_keys"] += 1
                    else:
                        group_counts["eligible_keys"] += 1
                elif key in left_keys:
                    group_counts["keys_with_left_only"] += 1
                elif key in right_keys:
                    group_counts["keys_with_right_only"] += 1
                else:
                    group_counts["keys_with_neither_side"] += 1
        difference_buckets = {
            "absolute_difference_lte_0_01": 0,
            "absolute_difference_gt_0_01_lte_1": 0,
            "absolute_difference_gt_1_lte_10": 0,
            "absolute_difference_gt_10": 0,
        }
        for key in sorted(eligible_keys, key=repr):
            left_value = sum(
                (runtime.left.sums[column].get(key, Decimal(0))
                 for column in reconciliation["left_amount_columns"]),
                Decimal(0),
            )
            right_value = sum(
                (runtime.right.sums[column].get(key, Decimal(0))
                 for column in reconciliation["right_amount_columns"]),
                Decimal(0),
            )
            left_total += left_value
            right_total += right_value
            difference = right_value - left_value
            absolute_difference = abs(difference)
            absolute_difference_total += absolute_difference
            maximum_absolute_difference = max(
                maximum_absolute_difference, absolute_difference
            )
            if difference == 0:
                exact_match_keys += 1
                if "anchor_breakdown_column" in reconciliation:
                    amount_breakdown_counts[breakdown_by_key[key]][
                        "exact_match_keys"
                    ] += 1
            elif difference < 0:
                left_greater_keys += 1
                if "anchor_breakdown_column" in reconciliation:
                    amount_breakdown_counts[breakdown_by_key[key]][
                        "left_greater_keys"
                    ] += 1
            else:
                right_greater_keys += 1
                if "anchor_breakdown_column" in reconciliation:
                    amount_breakdown_counts[breakdown_by_key[key]][
                        "right_greater_keys"
                    ] += 1
            if difference == 0:
                continue
            if absolute_difference <= Decimal("0.01"):
                difference_buckets["absolute_difference_lte_0_01"] += 1
            elif absolute_difference <= Decimal("1"):
                difference_buckets["absolute_difference_gt_0_01_lte_1"] += 1
            elif absolute_difference <= Decimal("10"):
                difference_buckets["absolute_difference_gt_1_lte_10"] += 1
            else:
                difference_buckets["absolute_difference_gt_10"] += 1

        reconciliation_profile: dict[str, Any] = {
            "absolute_difference_buckets": difference_buckets,
            "absolute_difference_total": _decimal_text(absolute_difference_total),
            "anchor_keys": len(anchor_keys),
            "eligible_keys": len(eligible_keys),
            "exact_match_keys": exact_match_keys,
            "incomplete_common_keys": len(incomplete_common_keys),
            "join_amplification": reconciliation["join_amplification"],
            "difference_bucket_scope": "nonzero absolute differences; descriptive only",
            "keys_with_both_sides": len(common_keys),
            "keys_with_left_only": len(left_keys - right_keys),
            "keys_with_neither_side": len(anchor_keys - left_keys - right_keys),
            "keys_with_right_only": len(right_keys - left_keys),
            "left_amount_columns": reconciliation["left_amount_columns"],
            "left_greater_keys": left_greater_keys,
            "left_total_on_eligible_keys": _decimal_text(left_total),
            "maximum_absolute_key_difference": _decimal_text(
                maximum_absolute_difference
            ),
            "net_difference_right_minus_left": _decimal_text(
                right_total - left_total
            ),
            "right_amount_columns": reconciliation["right_amount_columns"],
            "right_greater_keys": right_greater_keys,
            "right_total_on_eligible_keys": _decimal_text(right_total),
            "scope": "anchor keys with both sides and complete selected amount values",
        }
        if "anchor_breakdown_column" in reconciliation:
            def amount_group_summary(counts: Counter[str]) -> dict[str, int]:
                return {
                    field_name: counts[field_name]
                    for field_name in (
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
                }

            reconciliation_profile["anchor_breakdown"] = {
                "column": reconciliation["anchor_breakdown_column"],
                "null": amount_group_summary(
                    amount_breakdown_counts[BREAKDOWN_NULL]
                ),
                "other": amount_group_summary(
                    amount_breakdown_counts[BREAKDOWN_OTHER]
                ),
                "published_values": {
                    value: amount_group_summary(amount_breakdown_counts[value])
                    for value in reconciliation[
                        "_anchor_breakdown_published_values"
                    ]
                },
            }
        reconciliation_profiles[reconciliation["name"]] = reconciliation_profile

    value_profile = {
        "amount_reconciliations": reconciliation_profiles,
        "datetime_comparisons": dict(sorted(comparison_profiles.items())),
        "profile_scope": [
            "type_convertibility",
            "published_domain_distribution",
            "datetime_comparisons",
            "anchor_grain_amount_reconciliation",
        ],
        "tables": value_table_profiles,
        "value_profile_version": 1,
    }
    return manifest, profile, value_profile


def _render_markdown(manifest: dict[str, Any], profile: dict[str, Any]) -> bytes:
    lines = [
        "# 원천 데이터 구조 프로파일",
        "",
        "집계 검사로 생성한 파일이며 원천 행이나 샘플 값을 포함하지 않습니다.",
        "후보키는 원천에서 관찰한 가설이며 아직 승인된 모델 기본키가 아닙니다.",
        "미연결 행과 다중 행은 관찰 결과이며 처리 방식은 후속 계약에서 결정합니다.",
        "타입·도메인·시간 순서와 원천 간 금액 대사는 후속 프로파일 범위입니다.",
        "",
        f"- Dataset: `{manifest['dataset']['slug']}`",
        f"- Manifest SHA-256: `{profile['source_manifest_sha256']}`",
        "",
        "## 파일",
        "",
        "| 테이블 | 논리 행 수 | 바이트 | UTF-8 BOM | SHA-256 |",
        "|---|---:|---:|:---:|---|",
    ]
    for file_info in manifest["files"]:
        lines.append(
            f"| `{file_info['table']}` | {file_info['logical_rows']} | "
            f"{file_info['bytes']} | {'yes' if file_info['utf8_bom'] else 'no'} | "
            f"`{file_info['sha256']}` |"
        )

    lines.extend(["", "## 후보키와 관찰된 다중도", ""])
    lines.extend(
        [
            "| 테이블 | 프로파일 | 고유값 | NULL 행 | 키 기준 추가 행 | 복수행 키 | 최대 다중도 |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for table_name, table_profile in sorted(profile["tables"].items()):
        for collection_name in ("candidate_keys", "group_profiles"):
            for profile_name, key_profile in sorted(table_profile[collection_name].items()):
                lines.append(
                    f"| `{table_name}` | `{profile_name}` | "
                    f"{key_profile['distinct_keys']} | {key_profile['null_rows']} | "
                    f"{key_profile['duplicate_rows']} | "
                    f"{key_profile['keys_with_multiple_rows']} | "
                    f"{key_profile['max_multiplicity']} |"
                )

    lines.extend(
        [
            "",
            "## NULL과 공백 문자열",
            "",
            "0보다 큰 항목만 표시합니다. 빈 문자열은 NULL로, 공백만 있는 문자열은 별도 집계합니다.",
            "",
            "| 테이블 | 열 | NULL 행 | 공백 문자열 행 |",
            "|---|---|---:|---:|",
        ]
    )
    missing_value_rows = 0
    for table_name, table_profile in sorted(profile["tables"].items()):
        for column, null_rows in table_profile["null_counts"].items():
            whitespace_rows = table_profile["whitespace_only_counts"][column]
            if null_rows or whitespace_rows:
                missing_value_rows += 1
                lines.append(
                    f"| `{table_name}` | `{column}` | {null_rows} | {whitespace_rows} |"
                )
    if missing_value_rows == 0:
        lines.append("| - | - | 0 | 0 |")

    lines.extend(
        [
            "",
            "## 관계",
            "",
            "부모 측 키가 고유하지 않으면 직접 조인에서 자식 행이 증폭될 수 있습니다.",
            "",
            "| 관계 | NULL 제외 자식 행 | NULL 키 | 연결 행 | 미연결 행 | 연결 부모 키당 최대 행 | 직접 조인 행 | 연결 자식당 행 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name, relationship in sorted(profile["relationships"].items()):
        lines.append(
            f"| `{name}` | {relationship['child_non_null_rows']} | "
            f"{relationship['child_null_key_rows']} | "
            f"{relationship['matched_child_rows']} | {relationship['orphan_rows']} | "
            f"{relationship['matched_parent_max_rows_per_key']} | "
            f"{relationship['direct_join_rows']} | "
            f"{relationship['direct_join_rows_per_matched_child'] or 'N/A'} |"
        )

    lines.extend(
        [
            "",
            "## Fan-out",
            "",
            "| 프로파일 | 부모 수 | 자식 0개 | 1개 | 복수 | 최대 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for name, fanout in sorted(profile["fanouts"].items()):
        lines.append(
            f"| `{name}` | {fanout['parents_total']} | "
            f"{fanout['parents_with_no_children']} | {fanout['parents_with_one_child']} | "
            f"{fanout['parents_with_multiple_children']} | "
            f"{fanout['max_children_per_parent']} |"
        )

    lines.extend(["", "## 직접 조인 증폭", ""])
    for name, join in sorted(profile["join_amplifications"].items()):
        lines.extend(
            [
                f"### `{name}`",
                "",
                f"- 양쪽에 모두 존재하는 키: {join['keys_with_both_sides']}",
                f"- 조인 전 왼쪽 행: {join['left']['rows_before_on_common_keys']}",
                f"- 조인 전 오른쪽 행: {join['right']['rows_before_on_common_keys']}",
                f"- 직접 조인 후 행: {join['naive_join']['rows_after']}",
                f"- 왼쪽 대비 행 배수: {join['naive_join']['rows_after_to_left_ratio'] or 'N/A'}",
                f"- 오른쪽 대비 행 배수: {join['naive_join']['rows_after_to_right_ratio'] or 'N/A'}",
                "",
                "| 측면 | 금액 열 | 기준 합계 | 직접 조인 합계 | 배수 | 증가액 | NULL 행 | 변환 실패 행 |",
                "|---|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for side_name in ("left", "right"):
            for column, amount in sorted(join[side_name]["amounts"].items()):
                lines.append(
                    f"| {side_name} | `{column}` | "
                    f"{amount['baseline_on_common_keys'] or 'N/A'} | "
                    f"{amount['naive_join_total'] or 'N/A'} | "
                    f"{amount['naive_join_to_baseline_ratio'] or 'N/A'} | "
                    f"{amount['increase_from_naive_join'] or 'N/A'} | "
                    f"{amount['null_amount_rows_total']} | {amount['invalid_amount_rows_total']} |"
                )

    return ("\n".join(lines) + "\n").encode("utf-8")


def _render_value_markdown(
    manifest: dict[str, Any], value_profile: dict[str, Any]
) -> bytes:
    configured_type_columns = sum(
        len(table_profile["type_checks"])
        for table_profile in value_profile["tables"].values()
    )
    lines = [
        "# 원천 데이터 값 프로파일",
        "",
        "집계 관찰 결과이며 승인된 데이터 제약이나 지표 정의가 아닙니다.",
        f"핵심 질문에 필요한 계약 지정 {configured_type_columns}개 열만 선택 검사했으며 9개 파일의 모든 열을 검사한 결과가 아닙니다.",
        "계약에 공개를 허용한 도메인 값만 표시하며 기타 값, 원천 행, 식별자와 샘플은 표시하지 않습니다.",
        "타입 변환 가능성은 Python 파서 기준의 사전 점검이며 PostgreSQL 변환 성공을 보장하지 않습니다.",
        "원천 timestamp에는 timezone 정보가 없어 별도의 timezone을 추정하지 않습니다.",
        "상품 측 금액과 결제 측 금액의 비교는 원천 간 대사 관찰이며 매출·이익을 뜻하지 않습니다.",
        "금액 차이 구간은 분포 설명용이며 통과 기준이 아닙니다.",
        "정확히 같은 키는 별도 집계하며 절대 차이 구간에는 포함하지 않습니다.",
        "",
        f"- Dataset: `{manifest['dataset']['slug']}`",
        f"- Manifest SHA-256: `{value_profile['source_manifest_sha256']}`",
        "",
        "## 타입 변환 가능성",
        "",
        "| 테이블 | 열 | 대상 타입 | 전체 | NULL | 변환 가능 | 변환 실패 | 0 | 음수 | 최소 | 최대 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    type_rows = 0
    for table_name, table_profile in sorted(value_profile["tables"].items()):
        for column, summary in sorted(table_profile["type_checks"].items()):
            type_rows += 1
            lines.append(
                f"| `{table_name}` | `{column}` | `{summary['target_type']}` | "
                f"{summary['rows']} | {summary['null_rows']} | "
                f"{summary['parseable_rows']} | {summary['invalid_rows']} | "
                f"{summary.get('zero_rows', 'N/A')} | "
                f"{summary.get('negative_rows', 'N/A')} | "
                f"{summary['minimum'] if summary['minimum'] is not None else 'N/A'} | "
                f"{summary['maximum'] if summary['maximum'] is not None else 'N/A'} |"
            )
    if type_rows == 0:
        lines.append("| - | - | - | 0 | 0 | 0 | 0 | - | - | - | - |")
    lines.extend(
        [
            "",
            "최소·최대는 해당 열에서 변환 가능한 값의 범위이며 데이터셋 전체 기간이나 범위를 뜻하지 않습니다.",
        ]
    )
    shipping_profile = value_profile["tables"].get("order_items", {}).get(
        "type_checks", {}
    ).get("shipping_limit_date")
    if shipping_profile is not None:
        lines.append(
            "`shipping_limit_date`의 최대값이 2020년으로 관찰되는 이유는 후속 원천·모델 계약에서 확인합니다."
        )

    lines.extend(
        [
            "",
            "## 공개 가능한 도메인 분포",
            "",
            "명시된 값은 관찰을 위해 공개한 값이며 업무상 허용값으로 승인된 것은 아닙니다.",
            "",
            "| 테이블 | 프로파일 | 값 | 행 | NULL | 기타 행 | 기타 고유값 수 |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
    )
    domain_rows = 0
    for table_name, table_profile in sorted(value_profile["tables"].items()):
        for name, summary in sorted(table_profile["domain_counts"].items()):
            for value, count in summary["published_value_counts"].items():
                domain_rows += 1
                lines.append(
                    f"| `{table_name}` | `{name}` | `{value}` | {count} | "
                    f"{summary['null_rows']} | {summary['other_rows']} | "
                    f"{summary['other_distinct_values']} |"
                )
    if domain_rows == 0:
        lines.append("| - | - | - | 0 | 0 | 0 | 0 |")

    lines.extend(
        [
            "",
            "## 날짜·시간 비교",
            "",
            "왼쪽과 오른쪽의 선후 관계를 집계하며 chronology와 delivery_timing을 구분합니다.",
            "전체표에는 주문 상태 필터를 적용하지 않았으며, 상태별 표를 함께 확인해야 결측과 역전을 오류로 오해하지 않습니다.",
            "timestamp 비교와 date 비교는 다릅니다. 예정일이 자정이면 같은 달력 날짜의 배송도 timestamp상 늦게 보일 수 있습니다.",
            "`review_creation↔customer_delivery`와 `shipping_limit↔purchase`는 서로 다른 파일을 연결해야 하므로 후속 모델 계약 검토 항목입니다.",
            "",
            "| 비교 | 왼쪽 열 | 오른쪽 열 | 종류 | 단위 | 비교 가능 | NULL로 비교 불가 | 변환 실패로 비교 불가 | 왼쪽 < 오른쪽 | 같음 | 왼쪽 > 오른쪽 | 왼쪽 NULL/실패 | 오른쪽 NULL/실패 |",
            "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name, summary in sorted(value_profile["datetime_comparisons"].items()):
        lines.append(
            f"| `{name}` | `{summary['left_column']}` | `{summary['right_column']}` | "
            f"`{summary['kind']}` | `{summary['comparison_unit']}` | "
            f"{summary['comparable_rows']} | {summary['skipped_null_rows']} | "
            f"{summary['skipped_invalid_rows']} | {summary['left_before_right_rows']} | "
            f"{summary['equal_rows']} | {summary['left_after_right_rows']} | "
            f"{summary['left_null_rows']}/{summary['left_invalid_rows']} | "
            f"{summary['right_null_rows']}/{summary['right_invalid_rows']} |"
        )
    if not value_profile["datetime_comparisons"]:
        lines.append(
            "| - | - | - | - | - | 0 | 0 | 0 | 0 | 0 | 0 | 0/0 | 0/0 |"
        )
    timestamp_delivery = value_profile["datetime_comparisons"].get(
        "delivered_vs_estimated_timestamp"
    )
    date_delivery = value_profile["datetime_comparisons"].get(
        "delivered_vs_estimated_date"
    )
    if timestamp_delivery is not None and date_delivery is not None:
        same_date_after = (
            timestamp_delivery["left_after_right_rows"]
            - date_delivery["left_after_right_rows"]
        )
        lines.extend(
            [
                "",
                f"같은 달력 날짜지만 timestamp 기준으로 배송 시각이 예정 시각보다 늦은 행은 {same_date_after}건입니다.",
            ]
        )

    for name, summary in sorted(value_profile["datetime_comparisons"].items()):
        breakdown = summary.get("breakdown")
        if breakdown is None:
            continue
        lines.extend(
            [
                "",
                f"### `{name}` 상태별",
                "",
                "| 주문 상태 | 전체 | 비교 가능 | NULL로 비교 불가 | 변환 실패로 비교 불가 | 왼쪽 < 오른쪽 | 같음 | 왼쪽 > 오른쪽 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        breakdown_rows = [
            (f"`{value}`", counts)
            for value, counts in breakdown["published_values"].items()
        ]
        breakdown_rows.extend(
            [
                ("기타(값 비공개)", breakdown["other"]),
                ("NULL", breakdown["null"]),
            ]
        )
        for label, counts in breakdown_rows:
            lines.append(
                f"| {label} | {counts['rows']} | {counts['comparable_rows']} | "
                f"{counts['skipped_null_rows']} | {counts['skipped_invalid_rows']} | "
                f"{counts['left_before_right_rows']} | {counts['equal_rows']} | "
                f"{counts['left_after_right_rows']} |"
            )

    lines.extend(["", "## 주문 기준 상품 측·결제 측 금액 대사", ""])
    for name, summary in sorted(value_profile["amount_reconciliations"].items()):
        left_columns = " + ".join(summary["left_amount_columns"])
        right_columns = " + ".join(summary["right_amount_columns"])
        buckets = summary["absolute_difference_buckets"]
        lines.extend(
            [
                f"### `{name}`",
                "",
                "- 비교 범위: 기준 키 중 상품·결제 양쪽이 존재하고 선택한 금액값이 모두 변환 가능한 키",
                f"- 상품 측 계산: 주문별 `SUM({left_columns})`",
                f"- 결제 측 계산: 주문별 `SUM({right_columns})`",
                "- 주문 상태 필터: 적용하지 않음",
                f"- 전체 기준 키: {summary['anchor_keys']}",
                f"- 양쪽 존재 / 비교 가능 / 값 불완전: {summary['keys_with_both_sides']} / {summary['eligible_keys']} / {summary['incomplete_common_keys']}",
                f"- 상품 측만 / 결제 측만 / 양쪽 없음: {summary['keys_with_left_only']} / {summary['keys_with_right_only']} / {summary['keys_with_neither_side']}",
                f"- 정확히 같음 / 상품 측 큼 / 결제 측 큼: {summary['exact_match_keys']} / {summary['left_greater_keys']} / {summary['right_greater_keys']}",
                f"- 상품 측 합계: {summary['left_total_on_eligible_keys']}",
                f"- 결제 측 합계: {summary['right_total_on_eligible_keys']}",
                f"- 순차이(결제 측-상품 측): {summary['net_difference_right_minus_left']}",
                "- 순차이는 양수·음수 주문이 서로 상쇄될 수 있어 품질 통과 기준으로 사용하지 않음",
                f"- 절대 차이 합계 / 키별 최대 절대 차이: {summary['absolute_difference_total']} / {summary['maximum_absolute_key_difference']}",
                f"- 0이 아닌 절대 차이 구간(0 < |차이| ≤ 0.01 / >0.01–1 / >1–10 / >10): {buckets['absolute_difference_lte_0_01']} / {buckets['absolute_difference_gt_0_01_lte_1']} / {buckets['absolute_difference_gt_1_lte_10']} / {buckets['absolute_difference_gt_10']}",
                "",
            ]
        )
        breakdown = summary.get("anchor_breakdown")
        if breakdown is not None:
            lines.extend(
                [
                    "#### 주문 상태별 비교 범위와 방향",
                    "",
                    "| 주문 상태 | 기준 주문 | 양쪽 있음 | 비교 가능 | 금액 불완전 | 상품만 | 결제만 | 둘 다 없음 | 같음 | 상품 측 큼 | 결제 측 큼 |",
                    "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
                ]
            )
            breakdown_rows = [
                (f"`{value}`", counts)
                for value, counts in breakdown["published_values"].items()
            ]
            breakdown_rows.extend(
                [
                    ("기타(값 비공개)", breakdown["other"]),
                    ("NULL", breakdown["null"]),
                ]
            )
            for label, counts in breakdown_rows:
                lines.append(
                    f"| {label} | {counts['anchor_keys']} | "
                    f"{counts['keys_with_both_sides']} | {counts['eligible_keys']} | "
                    f"{counts['incomplete_common_keys']} | {counts['keys_with_left_only']} | "
                    f"{counts['keys_with_right_only']} | {counts['keys_with_neither_side']} | "
                    f"{counts['exact_match_keys']} | {counts['left_greater_keys']} | "
                    f"{counts['right_greater_keys']} |"
                )
    if not value_profile["amount_reconciliations"]:
        lines.append("설정된 금액 대사가 없습니다.")

    lines.extend(
        [
            "",
            "## 후속 계약에서 결정할 항목",
            "",
            "- 어떤 주문 상태를 각 지표에 포함할지",
            "- 배송 예정일 초과를 timestamp와 calendar date 중 어느 단위로 판단할지",
            "- 시간 순서가 뒤집힌 원천 행을 보존·경고·제외 중 어떻게 처리할지",
            "- 상품 측 금액과 결제 측 금액의 차이에 허용 기준을 둘지와 예외 처리 방식",
            "- 관찰된 도메인을 dbt accepted-values 테스트에서 fail 또는 warn으로 관리할지",
        ]
    )

    return ("\n".join(lines) + "\n").encode("utf-8")


def generate_reports(data_dir: Path, contract_path: Path) -> dict[str, bytes]:
    contract = load_contract(contract_path)
    manifest, profile, value_profile = _scan_sources(data_dir, contract)
    manifest_bytes = _canonical_json(manifest)
    profile["source_manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    value_profile["source_manifest_sha256"] = profile["source_manifest_sha256"]
    profile_bytes = _canonical_json(profile)
    markdown_bytes = _render_markdown(manifest, profile)
    value_profile_bytes = _canonical_json(value_profile)
    value_markdown_bytes = _render_value_markdown(manifest, value_profile)
    return {
        "source-manifest.json": manifest_bytes,
        "source-profile.json": profile_bytes,
        "source-profile.md": markdown_bytes,
        "source-value-profile.json": value_profile_bytes,
        "source-value-profile.md": value_markdown_bytes,
    }


def _write_reports(output_dir: Path, reports: dict[str, bytes]) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ProfileError(f"cannot create output directory: {type(exc).__name__}") from None
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ProfileError("output directory is unsafe")

    staged: list[tuple[Path, Path]] = []
    try:
        for filename in REPORT_FILENAMES:
            fd, temporary_name = tempfile.mkstemp(
                dir=output_dir,
                prefix=f".{filename}.",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(reports[filename])
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                temporary_path.unlink(missing_ok=True)
                raise
            staged.append((temporary_path, output_dir / filename))

        # Each target is replaced atomically. A later check detects any interrupted
        # multi-file update before the reports are accepted.
        for temporary_path, target_path in staged:
            os.replace(temporary_path, target_path)
    except OSError as exc:
        raise ProfileError(f"cannot write reports: {type(exc).__name__}") from None
    finally:
        for temporary_path, _ in staged:
            temporary_path.unlink(missing_ok=True)


def build_reports(data_dir: Path, contract_path: Path, output_dir: Path) -> None:
    reports = generate_reports(data_dir, contract_path)
    _write_reports(output_dir, reports)


def check_reports(data_dir: Path, contract_path: Path, output_dir: Path) -> None:
    reports = generate_reports(data_dir, contract_path)
    mismatches: list[str] = []
    for filename in REPORT_FILENAMES:
        path = output_dir / filename
        try:
            actual = path.read_bytes()
        except OSError:
            mismatches.append(filename)
            continue
        if actual != reports[filename]:
            mismatches.append(filename)
    if mismatches:
        raise ProfileError(f"generated reports do not match: {', '.join(mismatches)}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or check deterministic aggregate profiles for contracted CSV files."
    )
    parser.add_argument("command", choices=("build", "check"))
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("config/olist-source-contract.json"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "build":
            build_reports(args.data_dir, args.contract, args.output_dir)
            print("source profiling reports built")
        else:
            check_reports(args.data_dir, args.contract, args.output_dir)
            print("source profiling reports match")
    except ProfileError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
