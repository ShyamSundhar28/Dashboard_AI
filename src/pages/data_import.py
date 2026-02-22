from __future__ import annotations

import pandas as pd
import streamlit as st

from src.utils.importer import TableBundle, load_tables_from_upload
from src.utils.prepare import auto_detect_fields, drop_empty_columns, enforce_unique, normalize_col_names, prepare_dataframe


REQUIRED_FIELD_KEYS = ["date", "location", "value"]


def _init_state() -> None:
    st.session_state.setdefault("tables", {})
    st.session_state.setdefault("source_name", "")
    st.session_state.setdefault("selected_table", None)
    st.session_state.setdefault("last_upload_signature", None)

    st.session_state.setdefault("prepared_tables", {})
    st.session_state.setdefault("prep_reports", {})
    st.session_state.setdefault("field_map", {})
    st.session_state.setdefault("pipeline_ready", {})
    st.session_state.setdefault("pipeline_payload", {})


def _load_upload_if_needed() -> None:
    uploaded = st.file_uploader("Upload a dataset", type=["xlsx", "csv"], accept_multiple_files=False)

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
    st.session_state["selected_table"] = next(iter(bundle.tables), None)
    st.session_state["last_upload_signature"] = signature

    st.session_state["prepared_tables"] = {}
    st.session_state["prep_reports"] = {}
    st.session_state["field_map"] = {}
    st.session_state["pipeline_ready"] = {}
    st.session_state["pipeline_payload"] = {}

    st.success(f"Loaded **{len(bundle.tables)}** table(s).")


def validate_ready(df: pd.DataFrame, field_map: dict[str, str | None]) -> tuple[bool, list[str]]:
    issues: list[str] = []

    if any(not str(c).strip() for c in df.columns):
        issues.append("One or more column names are empty.")

    unnamed_cols = [str(c) for c in df.columns if str(c).strip().startswith("unnamed")]
    if unnamed_cols:
        issues.append(f"Unnamed columns found: {', '.join(unnamed_cols)}")

    _, removed_empty_cols = drop_empty_columns(df)
    if removed_empty_cols:
        issues.append(f"All-null/empty columns still present: {', '.join(removed_empty_cols)}")

    for key in REQUIRED_FIELD_KEYS:
        mapped_col = field_map.get(key)
        if not mapped_col:
            issues.append(f"{key.title()} field is not mapped.")
        elif mapped_col not in df.columns:
            issues.append(f"Mapped {key.title()} column '{mapped_col}' does not exist.")

    date_col = field_map.get("date")
    if date_col in df.columns:
        parsed_date = pd.to_datetime(df[date_col], errors="coerce")
        if float(parsed_date.notna().mean()) < 0.8:
            issues.append("Date column parse rate is below 80%.")

    value_col = field_map.get("value")
    if value_col in df.columns:
        numeric = pd.to_numeric(df[value_col], errors="coerce")
        if float(numeric.notna().mean()) < 0.8:
            issues.append("Value column numeric conversion rate is below 80%.")

    return len(issues) == 0, issues


def _render_prepare_button(table_name: str, raw_df: pd.DataFrame) -> None:
    if st.button("🚿 Prepare / Clean Data", key=f"prepare_btn_{table_name}"):
        cleaned, report = prepare_dataframe(raw_df)
        st.session_state["prepared_tables"][table_name] = cleaned
        st.session_state["prep_reports"][table_name] = report

        auto_map = auto_detect_fields(cleaned)
        st.session_state["field_map"][table_name] = auto_map
        st.session_state["pipeline_ready"][table_name] = False
        st.success("Data preparation completed. Review prepared preview and validation before starting pipeline.")


def _render_report(table_name: str) -> None:
    report = st.session_state["prep_reports"].get(table_name)
    if not report:
        return

    st.markdown("### What changed")
    st.write(f"- Empty columns removed: **{len(report.get('removed_empty_columns', []))}**")
    st.write(f"- Empty rows removed: **{report.get('removed_empty_rows_count', 0)}**")
    st.write(f"- Detected header row: **{report.get('detected_header_row')}**")

    renamed = report.get("renamed_columns", {})
    if renamed:
        st.write("- Renamed columns:")
        st.json(renamed)
    else:
        st.write("- Renamed columns: none")


def _render_rename_editor(table_name: str) -> None:
    prepared_df = st.session_state["prepared_tables"][table_name]

    st.markdown("### Rename / Map Columns")
    st.caption("Rename columns, then map required fields for pipeline gating.")

    st.markdown("**Column rename editor**")
    rename_values: list[str] = []
    for col in prepared_df.columns:
        rename_values.append(
            st.text_input(
                f"Rename '{col}'",
                value=str(col),
                key=f"rename_input_{table_name}_{col}",
            )
        )

    if st.button("Apply Column Renames", key=f"apply_renames_{table_name}"):
        normalized = normalize_col_names(rename_values)
        normalized = enforce_unique(normalized)
        rename_map = dict(zip(prepared_df.columns, normalized))
        renamed_df = prepared_df.rename(columns=rename_map)
        st.session_state["prepared_tables"][table_name] = renamed_df

        current_map = st.session_state["field_map"].get(table_name, {})
        refreshed_map: dict[str, str | None] = {}
        for field in REQUIRED_FIELD_KEYS:
            old_col = current_map.get(field)
            refreshed_map[field] = rename_map.get(old_col) if old_col in rename_map else None
        for field, detected in auto_detect_fields(renamed_df).items():
            if not refreshed_map.get(field):
                refreshed_map[field] = detected
        st.session_state["field_map"][table_name] = refreshed_map

        st.session_state["pipeline_ready"][table_name] = False
        st.success("Column names updated.")


def _render_field_map(table_name: str) -> None:
    prepared_df = st.session_state["prepared_tables"][table_name]
    options = list(prepared_df.columns)
    detected = auto_detect_fields(prepared_df)

    existing = st.session_state["field_map"].get(table_name, detected)

    def _index_for(col: str | None) -> int:
        if col in options:
            return options.index(col)
        return 0 if options else -1

    if not options:
        st.warning("No columns available for mapping.")
        st.session_state["field_map"][table_name] = {"date": None, "location": None, "value": None}
        return

    st.markdown("**Field mapping (required)**")
    date_col = st.selectbox("Date Column", options, index=_index_for(existing.get("date")), key=f"map_date_{table_name}")
    location_col = st.selectbox(
        "Location Column", options, index=_index_for(existing.get("location")), key=f"map_location_{table_name}"
    )
    value_col = st.selectbox("Value Column", options, index=_index_for(existing.get("value")), key=f"map_value_{table_name}")

    st.session_state["field_map"][table_name] = {
        "date": date_col,
        "location": location_col,
        "value": value_col,
    }


def _render_validation_and_gate(table_name: str) -> None:
    prepared_df = st.session_state["prepared_tables"][table_name]
    field_map = st.session_state["field_map"].get(table_name, {})

    ready, issues = validate_ready(prepared_df, field_map)

    st.markdown("### Validation")
    if ready:
        st.success("All validation checks passed.")
    else:
        st.error("Validation failed. Resolve issues before starting pipeline.")
        for issue in issues:
            st.write(f"- {issue}")

    if st.button("✅ Start Pipeline", key=f"start_pipeline_{table_name}", disabled=not ready):
        st.session_state["pipeline_ready"][table_name] = True
        st.session_state["pipeline_payload"][table_name] = {
            "prepared_df": prepared_df.copy(),
            "field_map": field_map.copy(),
        }
        st.success("Pipeline ready. You can now run analytics.")


def render_data_import_page() -> None:
    _init_state()

    st.title("Data Import")
    st.caption("Upload Excel (.xlsx) or CSV. Excel sheets become separate tables like Power BI.")

    _load_upload_if_needed()

    tables = st.session_state.get("tables", {})
    if not tables:
        return

    names = list(tables.keys())
    selected = st.session_state.get("selected_table")
    default_idx = names.index(selected) if selected in names else 0

    selected = st.selectbox("Select a table", options=names, index=default_idx)
    st.session_state["selected_table"] = selected

    raw_df = tables[selected]

    st.subheader("Raw Preview")
    st.write(f"Rows: **{len(raw_df):,}** | Columns: **{len(raw_df.columns):,}**")
    st.dataframe(raw_df, use_container_width=True, height=300)

    _render_prepare_button(selected, raw_df)

    has_prepared = selected in st.session_state["prepared_tables"]
    view_options = ["Raw", "Prepared"] if has_prepared else ["Raw"]
    view_mode = st.radio("View", options=view_options, horizontal=True, key=f"view_mode_{selected}")

    if has_prepared:
        _render_report(selected)
        prepared_df = st.session_state["prepared_tables"][selected]

        if view_mode == "Prepared":
            st.subheader("Prepared Preview")
            st.write(f"Rows: **{len(prepared_df):,}** | Columns: **{len(prepared_df.columns):,}**")
            st.dataframe(prepared_df, use_container_width=True, height=300)

        _render_rename_editor(selected)
        _render_field_map(selected)
        _render_validation_and_gate(selected)
    else:
        st.info("Run 🚿 Prepare / Clean Data to unlock mapping, validation, and pipeline start.")
