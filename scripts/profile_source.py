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
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


REPORT_FILENAMES = (
    "source-manifest.json",
    "source-profile.json",
    "source-profile.md",
)
CSV_FIELD_SIZE_LIMIT = 10 * 1024 * 1024
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")

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

    def __post_init__(self) -> None:
        self.sums = {
            column: defaultdict(Decimal) for column in self.spec["amount_columns"]
        }

    def add(self, row: dict[str | None, str | None]) -> None:
        columns = self.spec["columns"]
        key = _key_from_row(row, columns)
        self.keys.add(row, columns)

        for column in self.spec["amount_columns"]:
            value = row[column]
            if value == "":
                self.null_amount_rows[column] += 1
                continue
            try:
                amount = Decimal(value)  # type: ignore[arg-type]
            except (InvalidOperation, ValueError):
                self.invalid_amount_rows[column] += 1
                continue
            if not amount.is_finite():
                self.invalid_amount_rows[column] += 1
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
) -> tuple[dict[str, Any], dict[str, Any]]:
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
    return manifest, profile


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


def generate_reports(data_dir: Path, contract_path: Path) -> dict[str, bytes]:
    contract = load_contract(contract_path)
    manifest, profile = _scan_sources(data_dir, contract)
    manifest_bytes = _canonical_json(manifest)
    profile["source_manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    profile_bytes = _canonical_json(profile)
    markdown_bytes = _render_markdown(manifest, profile)
    return {
        "source-manifest.json": manifest_bytes,
        "source-profile.json": profile_bytes,
        "source-profile.md": markdown_bytes,
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
