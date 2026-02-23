import streamlit as st
import pandas as pd

from src.utils.importer import load_tables_from_upload, TableBundle


def render_data_import_page() -> None:
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

    st.success(f"Loaded **{len(bundle.tables)}** table(s).")

    # Store in session for other pages later
    st.session_state["tables"] = bundle.tables
    st.session_state["source_name"] = bundle.source_name

    # Table selector
    table_names = list(bundle.tables.keys())
    selected = st.selectbox("Select a table", table_names)

    df = bundle.tables[selected]
    st.subheader(f"Preview: {selected}")
    st.write(f"Rows: **{len(df):,}** | Columns: **{len(df.columns):,}**")
    st.dataframe(df, use_container_width=True, height=420)

    # Basic profiling
    with st.expander("Column types + missing values"):
        info = pd.DataFrame({
            "column": df.columns,
            "dtype": [str(t) for t in df.dtypes],
            "missing": df.isna().sum().values,
            "missing_%": (df.isna().mean() * 100).round(2).values,
        })
        st.dataframe(info, use_container_width=True)

    # Download cleaned table
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download selected table as CSV",
        data=csv_bytes,
        file_name=f"{selected}.csv",
        mime="text/csv",
    )