import streamlit as st
import pandas as pd

from src.utils.importer import load_tables_from_upload, TableBundle
from src.utils.prepare import prepare_dataframe, auto_detect_fields


def _init_state() -> None:
    st.session_state.setdefault("tables", {})
    st.session_state.setdefault("source_name", None)
    st.session_state.setdefault("prepared_tables", {})
    st.session_state.setdefault("pipeline_reports", {})
    st.session_state.setdefault("field_mappings", {})
    st.session_state.setdefault("pipeline_ready_tables", set())


def _table_key(source_name: str | None, table_name: str) -> str:
    return f"{source_name or 'uploaded'}::{table_name}"


def _render_profile(df: pd.DataFrame) -> None:
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


def render_data_import_page() -> None:
    _init_state()

    st.title("Data Import")
    st.caption("Upload Excel (.xlsx) or CSV. Excel sheets become separate tables like Power BI.")

    uploaded = st.file_uploader(
        "Upload a dataset",
        type=["xlsx", "csv"],
        accept_multiple_files=False,
    )

    if uploaded is None:
        if not st.session_state["tables"]:
            st.info("Upload a file to begin.")
        return

    with st.spinner("Reading file..."):
        bundle: TableBundle = load_tables_from_upload(uploaded)

    if not bundle.tables:
        st.warning("No tables were loaded from this file.")
        return

    st.success(f"Loaded **{len(bundle.tables)}** table(s).")

    # Store raw tables in session for later analytics pages
    st.session_state["tables"] = bundle.tables
    st.session_state["source_name"] = bundle.source_name

    table_names = list(bundle.tables.keys())
    selected = st.selectbox("Select a table", table_names)

    raw_df = bundle.tables[selected]
    table_key = _table_key(bundle.source_name, selected)

    is_ready = table_key in st.session_state["pipeline_ready_tables"]
    status_text = "Pipeline Ready ✅" if is_ready else "Awaiting preparation"
    st.subheader(f"Pipeline status: {status_text}")

    st.subheader(f"Preview: {selected} (raw)")
    st.write(f"Rows: **{len(raw_df):,}** | Columns: **{len(raw_df.columns):,}**")
    st.dataframe(raw_df, use_container_width=True, height=280)

    col1, col2 = st.columns([1, 3])
    with col1:
        run_pipeline = st.button("▶ Run Pipeline", use_container_width=True)
    with col2:
        st.caption("Runs auto cleaning + type inference and prepares a SQL-ready table preview.")

    if run_pipeline:
        prepared_df, report = prepare_dataframe(raw_df)
        st.session_state["prepared_tables"][table_key] = prepared_df
        st.session_state["pipeline_reports"][table_key] = report
        st.session_state["field_mappings"][table_key] = auto_detect_fields(prepared_df)
        st.session_state["pipeline_ready_tables"].discard(table_key)

    prepared_df = st.session_state["prepared_tables"].get(table_key)
    report = st.session_state["pipeline_reports"].get(table_key)

    if prepared_df is not None and report is not None:
        with st.expander("Step A: 🧹 Auto Prepare / Clean", expanded=True):
            st.write("The following corrections were applied automatically:")

            renamed = report.get("renamed_columns", {})
            if renamed:
                st.write("**Renamed columns**")
                st.json(renamed)
            else:
                st.write("**Renamed columns:** None")

            removed_cols = report.get("removed_empty_columns", [])
            st.write(f"**Removed empty columns:** {len(removed_cols)}")
            if removed_cols:
                st.write(", ".join(removed_cols))

            st.write(f"**Removed empty rows:** {report.get('removed_empty_rows_count', 0)}")

            inferred_dates = report.get("inferred_date_columns", [])
            if inferred_dates:
                st.write(f"**Detected date columns:** {', '.join(inferred_dates)}")

        with st.expander("Step B: 📝 Confirm field mapping", expanded=True):
            cols = [str(c) for c in prepared_df.columns]
            mapping = st.session_state["field_mappings"].get(table_key, {"date": None, "location": None, "value": None})

            date_col = st.selectbox(
                "Date column",
                options=["<none>"] + cols,
                index=(["<none>"] + cols).index(mapping.get("date")) if mapping.get("date") in cols else 0,
                key=f"date_map::{table_key}",
            )
            location_col = st.selectbox(
                "Location/Category column",
                options=["<none>"] + cols,
                index=(["<none>"] + cols).index(mapping.get("location")) if mapping.get("location") in cols else 0,
                key=f"location_map::{table_key}",
            )
            value_col = st.selectbox(
                "Value/Metric column",
                options=["<none>"] + cols,
                index=(["<none>"] + cols).index(mapping.get("value")) if mapping.get("value") in cols else 0,
                key=f"value_map::{table_key}",
            )

            st.session_state["field_mappings"][table_key] = {
                "date": None if date_col == "<none>" else date_col,
                "location": None if location_col == "<none>" else location_col,
                "value": None if value_col == "<none>" else value_col,
            }

        with st.expander("Step C: ✅ Validate & Save (SQL-ready)", expanded=True):
            current_map = st.session_state["field_mappings"][table_key]
            missing = [name for name, col in current_map.items() if col is None]

            if missing:
                st.warning(f"Select all mappings before marking pipeline ready: {', '.join(missing)}")
            else:
                st.success("No validation issues found.")

            mark_ready = st.button("Validate and Mark Pipeline Ready", key=f"ready::{table_key}")
            if mark_ready and not missing:
                st.session_state["pipeline_ready_tables"].add(table_key)
                st.success("Pipeline Ready ✅")
            elif mark_ready:
                st.error("Pipeline cannot be marked ready until all fields are mapped.")

        st.subheader(f"Corrected Data Preview: {selected} (SQL-ready)")
        st.write(f"Rows: **{len(prepared_df):,}** | Columns: **{len(prepared_df.columns):,}**")
        st.dataframe(prepared_df, use_container_width=True, height=420)
        _render_profile(prepared_df)

        csv_bytes = prepared_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download corrected table as CSV",
            data=csv_bytes,
            file_name=f"{selected}_sql_ready.csv",
            mime="text/csv",
        )
    else:
        _render_profile(raw_df)
        csv_bytes = raw_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download selected table as CSV",
            data=csv_bytes,
            file_name=f"{selected}.csv",
            mime="text/csv",
        )
