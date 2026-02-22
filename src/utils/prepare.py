from __future__ import annotations

import re
from typing import Any

import pandas as pd


def normalize_col_names(cols: list[str]) -> list[str]:
    normalized: list[str] = []
    for col in cols:
        clean = re.sub(r"\s+", " ", str(col).strip())
        normalized.append(clean)
    return normalized


def enforce_unique(cols: list[str]) -> tuple[list[str], dict[str, str]]:
    unique_cols: list[str] = []
    renames: dict[str, str] = {}
    counts: dict[str, int] = {}

    for idx, col in enumerate(cols):
        base = col or f"column_{idx + 1}"
        counts.setdefault(base, 0)
        counts[base] += 1

        if counts[base] == 1:
            candidate = base
        else:
            candidate = f"{base}_{counts[base]}"
            while candidate in counts:
                counts[base] += 1
                candidate = f"{base}_{counts[base]}"

        counts[candidate] = counts.get(candidate, 0)
        unique_cols.append(candidate)
        renames[col] = candidate

    return unique_cols, renames


def apply_type_conversions(df: pd.DataFrame, schema: dict[str, str]) -> tuple[pd.DataFrame, dict[str, int]]:
    converted = df.copy()
    errors: dict[str, int] = {}

    for col, target in schema.items():
        if col not in converted.columns or target == "Auto":
            continue

        original_non_null = converted[col].notna().sum()

        if target == "Text":
            converted[col] = converted[col].astype("string")
            continue

        if target == "Number":
            parsed = pd.to_numeric(converted[col], errors="coerce")
            converted[col] = parsed
        elif target == "Integer":
            parsed = pd.to_numeric(converted[col], errors="coerce")
            converted[col] = parsed.round().astype("Int64")
        elif target == "Date":
            parsed = pd.to_datetime(converted[col], errors="coerce")
            converted[col] = parsed.dt.date
        elif target == "DateTime":
            parsed = pd.to_datetime(converted[col], errors="coerce")
            converted[col] = parsed
        elif target == "Boolean":
            truthy = {"true", "1", "yes", "y", "t"}
            falsy = {"false", "0", "no", "n", "f"}

            def _to_bool(value: Any) -> Any:
                if pd.isna(value):
                    return pd.NA
                text = str(value).strip().lower()
                if text in truthy:
                    return True
                if text in falsy:
                    return False
                return pd.NA

            converted[col] = converted[col].map(_to_bool).astype("boolean")

        failed = max(0, original_non_null - converted[col].notna().sum())
        if failed:
            errors[col] = int(failed)

    return converted, errors


def drop_fully_empty(df: pd.DataFrame) -> pd.DataFrame:
    return df.dropna(axis=0, how="all").dropna(axis=1, how="all")


def apply_filter(df: pd.DataFrame, rule: dict[str, Any] | None) -> pd.DataFrame:
    if not rule or not rule.get("enabled"):
        return df

    column = rule.get("column")
    operator = rule.get("operator")
    value = rule.get("value")
    value2 = rule.get("value2")

    if column not in df.columns or operator is None:
        return df

    series = df[column]

    if operator == "equals":
        mask = series.astype(str) == str(value)
    elif operator == "contains":
        mask = series.astype(str).str.contains(str(value), case=False, na=False)
    elif operator == "startswith":
        mask = series.astype(str).str.startswith(str(value), na=False)
    elif operator == "greater than":
        mask = pd.to_numeric(series, errors="coerce") > pd.to_numeric(value, errors="coerce")
    elif operator == "less than":
        mask = pd.to_numeric(series, errors="coerce") < pd.to_numeric(value, errors="coerce")
    elif operator == "between":
        numeric = pd.to_numeric(series, errors="coerce")
        low = pd.to_numeric(value, errors="coerce")
        high = pd.to_numeric(value2, errors="coerce")
        mask = numeric.between(low, high, inclusive="both")
    else:
        return df

    return df[mask.fillna(False)]
