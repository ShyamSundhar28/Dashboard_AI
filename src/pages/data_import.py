from __future__ import annotations

import streamlit as st
import pandas as pd

from src.utils.importer import load_tables_from_upload, TableBundle
from src.utils.prepare import (
    apply_filter,
    apply_type_conversions,
    drop_fully_empty,
    enforce_unique,
    normalize_col_names,
)
from src.utils.themes import THEMES, suggest_mapping

_TYPE_OPTIONS = ["Auto", "Text", "Number", "Integer", "Date", "DateTime", "Boolean"]
_FILTER_OPERATORS = ["equals", "contains", "startswith", "greater than", "less than", "between"]


def _init_session_state() -> None:
    st.session_state.setdefault("tables", {})
    st.session_state.setdefault("source_name", "")
    st.session_state.setdefault("prep", {})
    st.session_state.setdefault("selected_table", None)
    st.session_state.setdefault("last_upload_signature", None)


def _default_prep_state(df: pd.DataFrame) -> dict:
    return {
        "staged_df": df.copy(),
        "theme": "Custom",
        "mapping": {},
        "required_fields": [],
        "schema": {col: "Auto" for col in df.columns},
        "drops": [],
        "remove_empty_rows": True,
        "remove_duplicates": False,
        "filter": {
            "enabled": False,
            "column": df.columns[0] if len(df.columns) else None,
            "operator": "equals",
            "value": "",
            "value2": "",
        },
        "preview_rows": 200,
        "fix_columns_enabled": False,
    }


def _ensure_prep_state(table_name: str, df: pd.DataFrame) -> dict:
    prep = st.session_state["prep"]
    if table_name not in prep:
        prep[table_name] = _default_prep_state(df)
    return prep[table_name]


def _load_upload_if_needed() -> None:
    uploaded = st.file_uploader(
        "Upload a dataset",
        type=["xlsx", "csv"],
        accept_multiple_files=False,
    )

    if uploaded is None:
        if not st.session_state["tables"]:
            st.info("Upload a file to begin.")
        return

    signature = (uploaded.name, uploaded.size)
    if st.session_state["last_upload_signature"] == signature:
        return

    with st.spinner("Reading file..."):
        bundle: TableBundle = load_tables_from_upload(uploaded)

    st.session_state["tables"] = bundle.tables
    st.session_state["source_name"] = bundle.source_name
    st.session_state["prep"] = {}
    st.session_state["selected_table"] = next(iter(bundle.tables), None)
    st.session_state["last_upload_signature"] = signature
    st.success(f"Loaded **{len(bundle.tables)}** table(s).")


def _render_theme_section(selected: str, prep_state: dict) -> None:
    st.subheader("Prepare Data (Power BI style)")

    theme = st.selectbox(
        "Data Theme",
        options=list(THEMES.keys()),
        index=list(THEMES.keys()).index(prep_state.get("theme", "Custom")),
        key=f"theme_{selected}",
    )
    prep_state["theme"] = theme
    theme_meta = THEMES[theme]
    st.caption(theme_meta["description"])

    fields = theme_meta["fields"]
    prep_state["required_fields"] = fields

    if theme == "Custom":
        return

    if not prep_state.get("mapping") or set(prep_state["mapping"].keys()) != set(fields):
        prep_state["mapping"] = suggest_mapping(prep_state["staged_df"], fields)

    cols = list(prep_state["staged_df"].columns)
    col_options = ["-- Select column --"] + cols

    st.markdown("**Theme mapping**")
    new_mapping: dict[str, str | None] = {}
    for field in fields:
        suggested = prep_state["mapping"].get(field)
        default_idx = col_options.index(suggested) if suggested in col_options else 0
        choice = st.selectbox(
            f"{field} →",
            options=col_options,
            index=default_idx,
            key=f"mapping_{selected}_{field}",
        )
        new_mapping[field] = None if choice == "-- Select column --" else choice

    prep_state["mapping"] = new_mapping

    if st.button("Apply Theme Mapping", key=f"apply_theme_{selected}"):
        if any(value is None for value in new_mapping.values()):
            st.error("Please map all required theme fields before applying.")
        else:
            mapped = {src: field for field, src in new_mapping.items() if src is not None}
            themed_df = prep_state["staged_df"][list(mapped.keys())].rename(columns=mapped)
            prep_state["staged_df"] = themed_df
            prep_state["schema"] = {col: prep_state.get("schema", {}).get(col, "Auto") for col in themed_df.columns}
            prep_state["drops"] = [d for d in prep_state.get("drops", []) if d in themed_df.columns]
            if themed_df.columns.any():
                prep_state["filter"]["column"] = themed_df.columns[0]
            st.success("Theme mapping applied to staged data.")


def _render_fix_columns(selected: str, prep_state: dict) -> None:
    if st.button("Enable Fix Columns", key=f"enable_fix_{selected}"):
        prep_state["fix_columns_enabled"] = True

    if not prep_state.get("fix_columns_enabled"):
        return

    st.markdown("**Fix Columns**")
    staged_df = prep_state["staged_df"]

    new_names: list[str] = []
    schema: dict[str, str] = {}

    for col in staged_df.columns:
        c1, c2 = st.columns([2, 1])
        with c1:
            name_val = st.text_input("Column name", value=col, key=f"col_name_{selected}_{col}")
        with c2:
            type_idx = _TYPE_OPTIONS.index(prep_state.get("schema", {}).get(col, "Auto"))
            schema[col] = st.selectbox(
                f"Type: {col}",
                options=_TYPE_OPTIONS,
                index=type_idx,
                key=f"dtype_{selected}_{col}",
                label_visibility="collapsed",
            )
        new_names.append(name_val)

    if st.button("Apply Column Fixes", key=f"apply_fix_{selected}"):
        normalized = normalize_col_names(new_names)
        if any(not name for name in normalized):
            st.error("Column names cannot be empty.")
            return

        unique_names, _ = enforce_unique(normalized)
        if unique_names != normalized:
            st.warning("Duplicate column names were adjusted with suffixes (_2, _3, ...).")

        renamed_df = staged_df.copy()
        rename_map = dict(zip(staged_df.columns, unique_names))
        renamed_df = renamed_df.rename(columns=rename_map)
        remapped_schema = {rename_map[col]: schema[col] for col in staged_df.columns}

        converted_df, errors = apply_type_conversions(renamed_df, remapped_schema)
        prep_state["staged_df"] = converted_df
        prep_state["schema"] = remapped_schema
        prep_state["drops"] = [d for d in prep_state.get("drops", []) if d in converted_df.columns]

        if errors:
            warning_text = ", ".join(f"{k}: {v}" for k, v in errors.items())
            st.warning(f"Conversion coercion warnings (non-convertible values): {warning_text}")
        st.success("Column fixes applied to staged data.")


def _render_remove_section(selected: str, prep_state: dict) -> pd.DataFrame:
    staged_df = prep_state["staged_df"]

    with st.expander("Remove rows/columns", expanded=False):
        prep_state["drops"] = st.multiselect(
            "Columns to remove",
            options=list(staged_df.columns),
            default=[c for c in prep_state.get("drops", []) if c in staged_df.columns],
            key=f"drop_cols_{selected}",
        )

        prep_state["remove_empty_rows"] = st.checkbox(
            "Remove fully empty rows",
            value=prep_state.get("remove_empty_rows", True),
            key=f"rm_empty_rows_{selected}",
        )
        prep_state["remove_duplicates"] = st.checkbox(
            "Remove duplicate rows",
            value=prep_state.get("remove_duplicates", False),
            key=f"rm_dupe_rows_{selected}",
        )

        st.markdown("**Filter rows**")
        filter_state = prep_state.get("filter", {})
        filter_state["column"] = st.selectbox(
            "Column",
            options=list(staged_df.columns) if len(staged_df.columns) else [""],
            index=(list(staged_df.columns).index(filter_state.get("column")) if filter_state.get("column") in staged_df.columns else 0),
            key=f"filter_col_{selected}",
        )
        filter_state["operator"] = st.selectbox(
            "Operator",
            options=_FILTER_OPERATORS,
            index=_FILTER_OPERATORS.index(filter_state.get("operator", "equals")),
            key=f"filter_op_{selected}",
        )

        filter_state["value"] = st.text_input(
            "Value",
            value=str(filter_state.get("value", "")),
            key=f"filter_val_{selected}",
        )

        if filter_state["operator"] == "between":
            filter_state["value2"] = st.text_input(
                "Value (upper bound)",
                value=str(filter_state.get("value2", "")),
                key=f"filter_val2_{selected}",
            )
        else:
            filter_state["value2"] = ""

        if st.button("Apply Filter (preview only)", key=f"apply_filter_preview_{selected}"):
            filter_state["enabled"] = True

        prep_state["filter"] = filter_state

    prep_state["preview_rows"] = st.number_input(
        "Preview rows",
        min_value=1,
        value=int(prep_state.get("preview_rows", 200)),
        step=10,
        key=f"preview_rows_{selected}",
    )

    preview_df = staged_df.copy()
    if prep_state.get("remove_empty_rows", True):
        preview_df = preview_df.dropna(axis=0, how="all")
    if prep_state.get("drops"):
        preview_df = preview_df.drop(columns=prep_state["drops"], errors="ignore")
    if prep_state.get("remove_duplicates", False):
        preview_df = preview_df.drop_duplicates()
    preview_df = apply_filter(preview_df, prep_state.get("filter"))

    return preview_df


def _save_structured_table(selected: str, prep_state: dict) -> None:
    if prep_state.get("theme") != "Custom":
        missing = [field for field in prep_state.get("required_fields", []) if field not in prep_state["staged_df"].columns]
        if missing:
            st.error(f"Cannot save: required themed fields missing from staged data: {', '.join(missing)}")
            return

    df_structured = prep_state["staged_df"].copy()
    df_structured = drop_fully_empty(df_structured)

    if prep_state.get("drops"):
        df_structured = df_structured.drop(columns=prep_state["drops"], errors="ignore")

    if prep_state.get("remove_empty_rows", True):
        df_structured = df_structured.dropna(axis=0, how="all")

    if prep_state.get("remove_duplicates", False):
        df_structured = df_structured.drop_duplicates()

    df_structured = apply_filter(df_structured, prep_state.get("filter"))

    target_name = f"{selected}_structured"
    if selected.endswith("_structured"):
        target_name = f"{selected}_v2"

    st.session_state["tables"][target_name] = df_structured
    st.session_state["prep"][target_name] = _default_prep_state(df_structured)
    st.session_state["selected_table"] = target_name
    st.success(f"Saved structured table: {target_name}")


def render_data_import_page() -> None:
    _init_session_state()

    st.title("Data Import")
    st.caption("Upload Excel (.xlsx) or CSV. Excel sheets become separate tables like Power BI.")

    _load_upload_if_needed()

    tables = st.session_state.get("tables", {})
    if not tables:
        return

    table_names = list(tables.keys())
    current = st.session_state.get("selected_table")
    default_idx = table_names.index(current) if current in table_names else 0
    selected = st.selectbox("Select a table", table_names, index=default_idx)
    st.session_state["selected_table"] = selected

    df = tables[selected]
    prep_state = _ensure_prep_state(selected, df)

    st.subheader(f"Preview: {selected}")
    st.write(f"Rows: **{len(df):,}** | Columns: **{len(df.columns):,}**")
    st.dataframe(df, use_container_width=True, height=320)

    _render_theme_section(selected, prep_state)
    _render_fix_columns(selected, prep_state)
    preview_df = _render_remove_section(selected, prep_state)

    st.markdown("**Prepared preview**")
    st.write(f"Rows: **{len(preview_df):,}** | Columns: **{len(preview_df.columns):,}**")
    st.dataframe(preview_df.head(int(prep_state.get("preview_rows", 200))), use_container_width=True, height=320)

    if st.button("Save Structured Table", key=f"save_structured_{selected}"):
        _save_structured_table(selected, prep_state)

    with st.expander("Column types + missing values"):
        info = pd.DataFrame(
            {
                "column": df.columns,
                "dtype": [str(t) for t in df.dtypes],
                "missing": df.isna().sum().values,
                "missing_%": (df.isna().mean() * 100).round(2).values,
            }
        )
        st.dataframe(info, use_container_width=True)

    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download selected table as CSV",
        data=csv_bytes,
        file_name=f"{selected}.csv",
        mime="text/csv",
    )
