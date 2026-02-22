import pandas as pd
import streamlit as st

from src.utils.importer import TableBundle, load_tables_from_upload
from src.utils.prepare import (
    auto_detect_fields,
    enforce_unique,
    normalize_col_names,
    prepare_dataframe,
    validate_ready,
)


def _init_state() -> None:
    defaults = {
        "raw_tables": {},
        "prepared_tables": {},
        "prep_reports": {},
        "field_map": {},
        "pipeline_ready": {},
        "show_prep": {},
        "source_name": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _reset_table(table_name: str) -> None:
    st.session_state["prepared_tables"].pop(table_name, None)
    st.session_state["prep_reports"].pop(table_name, None)
    st.session_state["field_map"].pop(table_name, None)
    st.session_state["pipeline_ready"][table_name] = False
    st.session_state["show_prep"][table_name] = False


def _render_report(report: dict) -> None:
    st.markdown("**What changed**")
    removed_cols = report.get("removed_empty_columns", [])
    st.write(f"- Removed empty columns: **{len(removed_cols)}**")
    if removed_cols:
        st.write(f"  - Names: {', '.join(map(str, removed_cols))}")

    st.write(f"- Removed empty rows: **{report.get('removed_empty_rows_count', 0)}**")
    header_row = report.get("detected_header_row")
    st.write(f"- Detected header row: **{header_row if header_row is not None else 'No change'}**")

    renamed = report.get("renamed_columns", {})
    st.write(f"- Renamed columns: **{len(renamed)}**")
    if renamed:
        st.json(renamed)

    inferred_dates = report.get("inferred_date_columns", [])
    st.write(f"- Inferred date columns: **{', '.join(inferred_dates) if inferred_dates else 'None'}**")


def render_data_import_page() -> None:
    _init_state()

    st.title("Data Import")
    st.caption("Upload Excel (.xlsx) or CSV. Excel sheets become separate tables like Power BI.")

    uploaded = st.file_uploader("Upload a dataset", type=["xlsx", "csv"], accept_multiple_files=False)

    if uploaded is None:
        st.info("Upload a file to begin.")
        return

    source_name = getattr(uploaded, "name", None)
    if source_name != st.session_state.get("source_name"):
        with st.spinner("Reading file..."):
            bundle: TableBundle = load_tables_from_upload(uploaded)
        st.session_state["raw_tables"] = bundle.tables
        st.session_state["source_name"] = source_name

        for table in bundle.tables:
            st.session_state["pipeline_ready"][table] = st.session_state["pipeline_ready"].get(table, False)
            st.session_state["show_prep"][table] = st.session_state["show_prep"].get(table, False)

    tables = st.session_state.get("raw_tables", {})
    if not tables:
        st.warning("No tables loaded from uploaded file.")
        return

    st.success(f"Loaded **{len(tables)}** table(s).")

    table_names = list(tables.keys())
    selected = st.selectbox("Select a table", table_names)
    st.session_state["show_prep"].setdefault(selected, False)
    st.session_state["pipeline_ready"].setdefault(selected, False)

    if st.session_state["pipeline_ready"].get(selected, False):
        st.markdown("### Pipeline status: **Pipeline Ready ✅**")
    else:
        st.markdown("### Pipeline status: **Not ready**")

    raw_df = tables[selected]
    st.subheader(f"Preview: {selected}")
    st.write(f"Rows: **{len(raw_df):,}** | Columns: **{len(raw_df.columns):,}**")
    st.dataframe(raw_df, use_container_width=True, height=420)

    start_pipeline = st.button(
        "✅ Start Pipeline (Prepare Data)",
        key=f"start_pipeline_{selected}",
        type="primary",
        use_container_width=True,
    )
    if start_pipeline:
        st.session_state["show_prep"][selected] = True

    if st.button(f"Reset prepared data for {selected}", key=f"reset_{selected}"):
        _reset_table(selected)
        st.success(f"Reset prepared state for {selected}.")

    with st.expander("Column types + missing values"):
        info = pd.DataFrame(
            {
                "column": raw_df.columns,
                "dtype": [str(t) for t in raw_df.dtypes],
                "missing": raw_df.isna().sum().values,
                "missing_%": (raw_df.isna().mean() * 100).round(2).values,
            }
        )
        st.dataframe(info, use_container_width=True)

    csv_bytes = raw_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download selected table as CSV",
        data=csv_bytes,
        file_name=f"{selected}.csv",
        mime="text/csv",
    )

    if not st.session_state["show_prep"].get(selected, False):
        return

    with st.expander("Step A: 🚿 Auto Prepare / Clean", expanded=True):
        if st.button("Run Auto Prepare", key=f"run_prepare_{selected}"):
            prepared_df, report = prepare_dataframe(raw_df)
            st.session_state["prepared_tables"][selected] = prepared_df
            st.session_state["prep_reports"][selected] = report
            st.session_state["field_map"][selected] = auto_detect_fields(prepared_df)
            st.session_state["pipeline_ready"][selected] = False

        prepared_df = st.session_state["prepared_tables"].get(selected)
        report = st.session_state["prep_reports"].get(selected)
        if prepared_df is not None:
            st.subheader("Prepared Preview")
            st.dataframe(prepared_df, use_container_width=True, height=320)
            if report:
                _render_report(report)
        else:
            st.info("Click 'Run Auto Prepare' to create cleaned table.")

    prepared_df = st.session_state["prepared_tables"].get(selected)
    if prepared_df is None:
        return

    with st.expander("Step B: 📝 Rename / Map Columns (User Confirmation)", expanded=True):
        st.markdown("**Rename columns**")
        existing_cols = list(prepared_df.columns)
        rename_inputs: dict[str, str] = {}
        for col in existing_cols:
            rename_inputs[col] = st.text_input(
                f"Rename '{col}'",
                value=col,
                key=f"rename_{selected}_{col}",
            )

        if st.button("Apply Rename", key=f"apply_rename_{selected}"):
            renamed_cols = [rename_inputs[col] for col in existing_cols]
            final_cols = enforce_unique(normalize_col_names(renamed_cols))
            renamed_df = prepared_df.copy()
            renamed_df.columns = final_cols
            st.session_state["prepared_tables"][selected] = renamed_df
            st.session_state["field_map"][selected] = auto_detect_fields(renamed_df)
            st.success("Renamed columns applied with normalization and uniqueness enforcement.")

        prepared_df = st.session_state["prepared_tables"][selected]
        cols = list(prepared_df.columns)
        current_map = st.session_state["field_map"].get(selected, auto_detect_fields(prepared_df))

        st.markdown("**Field mapping**")
        date_default = cols.index(current_map.get("date_col")) if current_map.get("date_col") in cols else 0
        loc_default = cols.index(current_map.get("location_col")) if current_map.get("location_col") in cols else 0
        value_default = cols.index(current_map.get("value_col")) if current_map.get("value_col") in cols else 0

        date_col = st.selectbox("Date column", cols, index=date_default, key=f"date_map_{selected}")
        location_col = st.selectbox("Location/Category column", cols, index=loc_default, key=f"loc_map_{selected}")
        value_col = st.selectbox("Value/Metric column", cols, index=value_default, key=f"value_map_{selected}")

        st.session_state["field_map"][selected] = {
            "date_col": date_col,
            "location_col": location_col,
            "value_col": value_col,
        }

    with st.expander("Step C: ✅ Validate & Save (SQL-ready)", expanded=True):
        st.markdown("**Validation**")
        active_map = st.session_state["field_map"].get(selected, {})
        ready, issues = validate_ready(st.session_state["prepared_tables"][selected], active_map)

        if issues:
            st.error("Validation issues found:")
            for issue in issues:
                st.write(f"- {issue}")
        else:
            st.success("No validation issues found.")

        if st.button("Validate and Mark Pipeline Ready", key=f"validate_save_{selected}", type="primary"):
            ready, issues = validate_ready(st.session_state["prepared_tables"][selected], active_map)
            st.session_state["pipeline_ready"][selected] = ready
            if ready:
                st.success("Pipeline Ready ✅")
            else:
                st.error("Cannot mark ready until validation passes.")
                for issue in issues:
                    st.write(f"- {issue}")

    st.session_state["tables"] = st.session_state["prepared_tables"] or st.session_state["raw_tables"]
