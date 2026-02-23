from __future__ import annotations

import re
from typing import Any

import pandas as pd


_DATE_KEYWORDS = ("date", "time", "day", "month", "year", "timestamp")
_LOCATION_KEYWORDS = ("location", "city", "country", "region", "state", "address", "site")
_VALUE_KEYWORDS = ("value", "amount", "total", "weight", "qty", "quantity", "price", "cost")


def _is_empty_value(value: Any) -> bool:
    if pd.isna(value):
        return True
    return str(value).strip() == ""


def drop_empty_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    removed: list[str] = []
    keep_cols: list[str] = []

    for col in df.columns:
        series = df[col]
        non_empty = series.map(lambda x: not _is_empty_value(x)).any()
        if non_empty:
            keep_cols.append(col)
        else:
            removed.append(str(col))

    return df[keep_cols].copy(), removed


def drop_empty_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    mask_non_empty = df.apply(lambda row: any(not _is_empty_value(v) for v in row), axis=1)
    removed_count = int((~mask_non_empty).sum())
    return df.loc[mask_non_empty].copy(), removed_count


def normalize_col_names(cols: list[str]) -> list[str]:
    normalized: list[str] = []
    for idx, col in enumerate(cols):
        text = str(col) if col is not None else ""
        text = text.strip().lower()
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[^a-z0-9]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        if not text:
            text = f"column_{idx + 1}"
        normalized.append(text)
    return normalized


def enforce_unique(cols: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    unique_cols: list[str] = []

    for col in cols:
        base = col
        counts[base] = counts.get(base, 0) + 1
        if counts[base] == 1:
            unique_cols.append(base)
        else:
            unique_cols.append(f"{base}_{counts[base]}")

    return unique_cols


def detect_header_row(df_sample: pd.DataFrame) -> int | None:
    if df_sample.empty:
        return None

    max_idx = 0
    max_count = -1

    for idx in range(len(df_sample)):
        count = int(df_sample.iloc[idx].map(lambda x: not _is_empty_value(x)).sum())
        if count > max_count:
            max_count = count
            max_idx = idx

    return int(max_idx)


def infer_types(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    typed = df.copy()
    inferred_date_columns: list[str] = []

    for col in typed.columns:
        series = typed[col]
        non_null = series.dropna()
        if non_null.empty:
            continue

        numeric_parsed = pd.to_numeric(series, errors="coerce")
        numeric_ratio = float(numeric_parsed.notna().mean())

        date_parsed = pd.to_datetime(series, errors="coerce")
        date_ratio = float(date_parsed.notna().mean())

        col_name = str(col).lower()
        has_date_keyword = any(keyword in col_name for keyword in _DATE_KEYWORDS)

        if numeric_ratio >= 0.8 and not has_date_keyword:
            typed[col] = numeric_parsed
        elif date_ratio >= 0.8:
            typed[col] = date_parsed
            inferred_date_columns.append(str(col))

    return typed, inferred_date_columns


def auto_detect_fields(df: pd.DataFrame) -> dict[str, str | None]:
    cols = list(df.columns)
    result: dict[str, str | None] = {"date": None, "location": None, "value": None}

    if not cols:
        return result

    def _pick_by_keywords(keywords: tuple[str, ...], skip: set[str]) -> str | None:
        for col in cols:
            if col in skip:
                continue
            lower = str(col).lower()
            if any(k in lower for k in keywords):
                return col
        return None

    used: set[str] = set()

    date_col = _pick_by_keywords(_DATE_KEYWORDS, used)
    if date_col is None:
        for col in cols:
            if col in used:
                continue
            parsed = pd.to_datetime(df[col], errors="coerce")
            if parsed.notna().mean() >= 0.8:
                date_col = col
                break
    if date_col is not None:
        used.add(date_col)
    result["date"] = date_col

    value_col = _pick_by_keywords(_VALUE_KEYWORDS, used)
    if value_col is None:
        for col in cols:
            if col in used:
                continue
            parsed = pd.to_numeric(df[col], errors="coerce")
            if parsed.notna().mean() >= 0.8:
                value_col = col
                break
    if value_col is not None:
        used.add(value_col)
    result["value"] = value_col

    location_col = _pick_by_keywords(_LOCATION_KEYWORDS, used)
    if location_col is None:
        for col in cols:
            if col in used:
                continue
            if pd.api.types.is_string_dtype(df[col]) or df[col].astype(str).str.len().mean() > 0:
                location_col = col
                break
    result["location"] = location_col

    return result


def prepare_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    working = df.copy()

    header_idx = detect_header_row(working.head(min(len(working), 10)))
    if header_idx is not None and header_idx > 0 and header_idx < len(working):
        new_header = [str(v) if not _is_empty_value(v) else f"column_{i+1}" for i, v in enumerate(working.iloc[header_idx].tolist())]
        working = working.iloc[header_idx + 1 :].copy().reset_index(drop=True)
        working.columns = new_header

    original_cols = [str(c) for c in working.columns]
    normalized_cols = normalize_col_names(original_cols)
    unique_cols = enforce_unique(normalized_cols)

    renamed_columns: dict[str, str] = {}
    for old, new in zip(original_cols, unique_cols):
        if old != new:
            renamed_columns[old] = new

    working.columns = unique_cols

    working, removed_empty_columns = drop_empty_columns(working)
    working, removed_empty_rows_count = drop_empty_rows(working)
    working, inferred_date_columns = infer_types(working)

    report = {
        "removed_empty_columns": removed_empty_columns,
        "removed_empty_rows_count": removed_empty_rows_count,
        "renamed_columns": renamed_columns,
        "detected_header_row": header_idx,
        "inferred_date_columns": inferred_date_columns,
    }

    return working, report
