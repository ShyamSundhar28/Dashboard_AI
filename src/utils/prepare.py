from __future__ import annotations

import re
from collections import Counter
from typing import Any

import pandas as pd


BLANK_LIKE_STRINGS = {"", "nan", "none", "null", "nat"}


def is_blank(x: Any) -> bool:
    if x is None:
        return True
    if pd.isna(x):
        return True
    if isinstance(x, str) and x.strip().lower() in BLANK_LIKE_STRINGS:
        return True
    return False


def drop_empty_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    empty_cols = [col for col in df.columns if df[col].map(is_blank).all()]
    return df.drop(columns=empty_cols), empty_cols


def drop_empty_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    mask_all_blank = df.apply(lambda row: row.map(is_blank).all(), axis=1)
    removed = int(mask_all_blank.sum())
    return df.loc[~mask_all_blank].copy(), removed


def normalize_col_names(cols) -> list[str]:
    normalized = []
    for c in cols:
        text = "" if c is None else str(c)
        text = re.sub(r"\s+", " ", text.strip())
        text = re.sub(r"[^0-9a-zA-Z]+", "_", text)
        text = text.strip("_").lower()
        normalized.append(text)
    return normalized


def enforce_unique(cols) -> list[str]:
    seen = Counter()
    out: list[str] = []
    for c in cols:
        base = c if str(c).strip() else "column"
        seen[base] += 1
        if seen[base] == 1:
            out.append(base)
        else:
            out.append(f"{base}_{seen[base]}")
    return out


def detect_header_row(df: pd.DataFrame) -> int | None:
    if df.empty:
        return None

    scan_rows = min(len(df), 50)
    non_blank_counts = []
    unnamed_like_counts = []

    for idx in range(scan_rows):
        row = df.iloc[idx]
        non_blank = sum(not is_blank(v) for v in row)
        unnamed_like = sum(
            isinstance(v, str) and (v.strip().lower().startswith("unnamed") or v.strip() == "")
            for v in row
        )
        non_blank_counts.append(non_blank)
        unnamed_like_counts.append(unnamed_like)

    best_idx = int(pd.Series(non_blank_counts).idxmax())
    row0_count = non_blank_counts[0]
    best_count = non_blank_counts[best_idx]
    row0_unnamed_ratio = unnamed_like_counts[0] / max(1, len(df.columns))

    significantly_better = best_idx != 0 and best_count >= row0_count + max(2, int(len(df.columns) * 0.1))
    row0_poor_header = row0_unnamed_ratio >= 0.3 or row0_count <= max(1, int(len(df.columns) * 0.4))

    if significantly_better or (best_idx != 0 and row0_poor_header):
        return best_idx
    return None


def apply_header_row(df: pd.DataFrame, header_row_index: int) -> pd.DataFrame:
    header = df.iloc[header_row_index].tolist()
    out = df.iloc[header_row_index + 1 :].copy()
    out.columns = header
    return out.reset_index(drop=True)


def _maybe_to_datetime(series: pd.Series) -> tuple[pd.Series, float]:
    parsed = pd.to_datetime(series, errors="coerce")
    ratio = float(parsed.notna().mean())
    return parsed, ratio


def _maybe_to_numeric(series: pd.Series) -> tuple[pd.Series, float]:
    parsed = pd.to_numeric(series, errors="coerce")
    ratio = float(parsed.notna().mean())
    return parsed, ratio


def infer_types(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    out = df.copy()
    inferred_date_cols: list[str] = []

    for col in out.columns:
        s = out[col]
        if s.map(is_blank).all():
            continue

        if pd.api.types.is_datetime64_any_dtype(s):
            inferred_date_cols.append(col)
            continue

        if pd.api.types.is_numeric_dtype(s):
            continue

        dt, dt_ratio = _maybe_to_datetime(s)
        if dt_ratio >= 0.8:
            out[col] = dt
            inferred_date_cols.append(col)
            continue

        num, num_ratio = _maybe_to_numeric(s)
        if num_ratio >= 0.8:
            out[col] = num

    return out, inferred_date_cols


def auto_detect_fields(df: pd.DataFrame) -> dict[str, str | None]:
    columns = list(df.columns)

    def _best(candidates: list[tuple[str, float]]) -> str | None:
        if not candidates:
            return None
        return sorted(candidates, key=lambda x: x[1], reverse=True)[0][0]

    date_cands = []
    location_cands = []
    value_cands = []

    for col in columns:
        name = str(col).lower()
        s = df[col]

        date_score = 0.0
        if any(k in name for k in ["date", "time", "day"]):
            date_score += 3
        if pd.api.types.is_datetime64_any_dtype(s):
            date_score += 4
        else:
            _, ratio = _maybe_to_datetime(s)
            date_score += ratio * 2
        date_cands.append((col, date_score))

        loc_score = 0.0
        if any(k in name for k in ["location", "place", "site", "branch", "school", "center", "category"]):
            loc_score += 4
        if pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s):
            nunique = s.nunique(dropna=True)
            if 1 < nunique < max(3, len(s) * 0.7):
                loc_score += 2
        location_cands.append((col, loc_score))

        val_score = 0.0
        if any(k in name for k in ["value", "amount", "count", "qty", "quantity", "total", "metric"]):
            val_score += 4
        if pd.api.types.is_numeric_dtype(s):
            val_score += 3
        else:
            _, ratio = _maybe_to_numeric(s)
            val_score += ratio * 2
        value_cands.append((col, val_score))

    return {
        "date_col": _best(date_cands),
        "location_col": _best(location_cands),
        "value_col": _best(value_cands),
    }


def prepare_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    report: dict[str, Any] = {
        "detected_header_row": None,
        "removed_empty_columns": [],
        "removed_empty_rows_count": 0,
        "renamed_columns": {},
        "inferred_date_columns": [],
    }

    working = df.copy()
    detected = detect_header_row(working)
    if detected is not None:
        working = apply_header_row(working, detected)
        report["detected_header_row"] = int(detected)

    working, removed_cols = drop_empty_columns(working)
    working, removed_rows = drop_empty_rows(working)

    old_cols = [str(c) for c in working.columns]
    normalized = normalize_col_names(old_cols)
    unique_cols = enforce_unique(normalized)

    rename_map = {old: new for old, new in zip(old_cols, unique_cols) if old != new}
    working.columns = unique_cols

    working, inferred_dates = infer_types(working)

    report["removed_empty_columns"] = removed_cols
    report["removed_empty_rows_count"] = int(removed_rows)
    report["renamed_columns"] = rename_map
    report["inferred_date_columns"] = inferred_dates

    return working.reset_index(drop=True), report


def validate_ready(df: pd.DataFrame, field_map: dict[str, str | None]) -> tuple[bool, list[str]]:
    issues: list[str] = []

    cols = list(df.columns)
    if any(str(c).strip() == "" for c in cols):
        issues.append("Found empty column name(s).")

    if any(str(c).lower().startswith("unnamed") for c in cols):
        issues.append("Found columns named like 'Unnamed: ...'.")

    all_null_cols = [col for col in cols if df[col].map(is_blank).all()]
    if all_null_cols:
        issues.append(f"All-null columns present: {', '.join(map(str, all_null_cols))}.")

    if len(cols) != len(set(cols)):
        issues.append("Column names are not unique.")

    date_col = field_map.get("date_col")
    location_col = field_map.get("location_col")
    value_col = field_map.get("value_col")

    for key, col in [("Date", date_col), ("Location", location_col), ("Value", value_col)]:
        if not col or col not in cols:
            issues.append(f"Mapped {key} column is missing.")

    if date_col and date_col in cols:
        parsed = pd.to_datetime(df[date_col], errors="coerce")
        if float(parsed.notna().mean()) < 0.8:
            issues.append("Date column parsing success is below 80%.")

    if value_col and value_col in cols:
        parsed = pd.to_numeric(df[value_col], errors="coerce")
        if float(parsed.notna().mean()) < 0.8:
            issues.append("Value column numeric conversion success is below 80%.")

    return len(issues) == 0, issues
