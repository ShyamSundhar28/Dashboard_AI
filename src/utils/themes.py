from __future__ import annotations

from typing import Any

import pandas as pd


THEMES: dict[str, dict[str, Any]] = {
    "Custom": {
        "fields": [],
        "description": "No template. Keep all current columns and prepare manually.",
    },
    "Deliveries": {
        "fields": ["Date", "Location", "Weight"],
        "description": "Delivery events with date, delivery location, and delivered weight.",
    },
    "Transactions": {
        "fields": ["Date", "Category", "Amount"],
        "description": "Transaction records with date, category, and transaction amount.",
    },
    "People": {
        "fields": ["Name", "Date", "Attribute"],
        "description": "People-centric records with person name, relevant date, and an attribute.",
    },
}

_DATE_TOKENS = ("date", "time", "timestamp", "day")
_NUMERIC_TOKENS = ("amount", "weight", "qty", "quantity", "total", "price", "value")
_TEXT_TOKENS = ("location", "category", "name", "city", "country", "state", "type")


def _is_date_like(series: pd.Series) -> bool:
    non_null = series.dropna()
    if non_null.empty:
        return False
    parsed = pd.to_datetime(non_null, errors="coerce", infer_datetime_format=True)
    return parsed.notna().mean() >= 0.6


def _is_numeric_majority(series: pd.Series) -> bool:
    non_null = series.dropna()
    if non_null.empty:
        return False
    parsed = pd.to_numeric(non_null, errors="coerce")
    return parsed.notna().mean() >= 0.6


def _is_text_majority(series: pd.Series) -> bool:
    non_null = series.dropna()
    if non_null.empty:
        return False
    casted = non_null.astype(str).str.strip()
    return (casted != "").mean() >= 0.6


def suggest_mapping(df: pd.DataFrame, theme_fields: list[str]) -> dict[str, str | None]:
    mapping: dict[str, str | None] = {field: None for field in theme_fields}
    if df.empty or not theme_fields:
        return mapping

    available = list(df.columns)
    used: set[str] = set()

    for field in theme_fields:
        field_lower = field.lower()
        best_col: str | None = None

        for col in available:
            if col in used:
                continue

            col_lower = col.lower()
            series = df[col]

            if "date" in field_lower:
                if any(token in col_lower for token in _DATE_TOKENS) or _is_date_like(series):
                    best_col = col
                    break
            elif field_lower in {"amount", "weight"}:
                if any(token in col_lower for token in _NUMERIC_TOKENS) or _is_numeric_majority(series):
                    best_col = col
                    break
            else:
                if any(token in col_lower for token in _TEXT_TOKENS) or _is_text_majority(series):
                    best_col = col
                    break

        if best_col is None:
            for col in available:
                if col not in used:
                    best_col = col
                    break

        mapping[field] = best_col
        if best_col is not None:
            used.add(best_col)

    return mapping
