from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import pandas as pd
import streamlit as st


@dataclass
class TableBundle:
    source_name: str
    tables: Dict[str, pd.DataFrame]


def _best_header_row(df_raw: pd.DataFrame) -> int:
    """
    Choose header row as the row with the most non-null cells.
    """
    non_null_counts = df_raw.notna().sum(axis=1)
    best_idx = int(non_null_counts.idxmax())
    return best_idx


def _clean_columns(cols) -> list[str]:
    cleaned = []
    seen = {}
    for c in cols:
        name = str(c).strip()
        if name == "" or name.lower() == "nan":
            name = "Unnamed"

        # de-dup
        base = name
        k = seen.get(base, 0)
        if k > 0:
            name = f"{base}_{k+1}"
        seen[base] = k + 1
        cleaned.append(name)
    return cleaned


def _drop_empty_rows_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(axis=0, how="all")
    df = df.dropna(axis=1, how="all")
    return df


def load_tables_from_upload(uploaded) -> TableBundle:
    filename = getattr(uploaded, "name", "uploaded")

    if filename.lower().endswith(".csv"):
        df = pd.read_csv(uploaded)
        df = _drop_empty_rows_cols(df)
        df.columns = _clean_columns(df.columns)
        return TableBundle(source_name=filename, tables={"Table1": df})

    # Excel: read sheet names
    xls = pd.ExcelFile(uploaded)
    tables: Dict[str, pd.DataFrame] = {}

    for sheet_name in xls.sheet_names:
        # read raw without header
        raw = pd.read_excel(xls, sheet_name=sheet_name, header=None)
        raw = _drop_empty_rows_cols(raw)

        if raw.empty:
            continue

        header_row = _best_header_row(raw)

        # build df with header
        header = raw.iloc[header_row].tolist()
        df = raw.iloc[header_row + 1 :].copy()
        df.columns = _clean_columns(header)
        df = _drop_empty_rows_cols(df)

        # ensure unique table name
        name = sheet_name.strip() or "Sheet"
        if name in tables:
            i = 2
            while f"{name}_{i}" in tables:
                i += 1
            name = f"{name}_{i}"

        tables[name] = df

    if not tables:
        st.warning("No usable sheets found. Check if the Excel has data.")
        return TableBundle(source_name=filename, tables={})

    return TableBundle(source_name=filename, tables=tables)