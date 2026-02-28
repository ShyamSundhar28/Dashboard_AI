import pandas as pd
import streamlit as st


def _table_key(source_name: str | None, table_name: str) -> str:
    return f"{source_name or 'uploaded'}::{table_name}"


def _parse_table_key(table_key: str) -> tuple[str | None, str]:
    if "::" not in table_key:
        return None, table_key
    source_name, table_name = table_key.split("::", 1)
    return source_name, table_name


def _get_ready_table_options() -> list[tuple[str, str]]:
    prepared_tables: dict[str, pd.DataFrame] = st.session_state.get("prepared_tables", {})
    ready_tables: set[str] = st.session_state.get("pipeline_ready_tables", set())

    options: list[tuple[str, str]] = []
    for table_key in sorted(ready_tables):
        if table_key not in prepared_tables:
            continue

        source_name, table_name = _parse_table_key(table_key)
        source_label = source_name or "uploaded"
        label = f"{table_name} ({source_label})"
        options.append((label, table_key))

    return options


def _safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _safe_datetime(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def render_analytics_page() -> None:
    st.title("Analytics")
    st.caption("Explore only validated tables that are marked Pipeline Ready.")

    options = _get_ready_table_options()
    if not options:
        st.info("No pipeline-ready tables yet. Complete Step C in Data Import first.")
        return

    labels = [label for label, _ in options]
    selected_label = st.selectbox("Select a pipeline-ready table", labels)
    selected_key = next(key for label, key in options if label == selected_label)

    prepared_tables: dict[str, pd.DataFrame] = st.session_state.get("prepared_tables", {})
    mappings: dict[str, dict[str, str | None]] = st.session_state.get("field_mappings", {})

    df = prepared_tables.get(selected_key)
    mapping = mappings.get(selected_key, {})

    if df is None or df.empty:
        st.warning("Selected table has no prepared data.")
        return

    date_col = mapping.get("date")
    location_col = mapping.get("location")
    value_col = mapping.get("value")

    missing_mappings = [
        name
        for name, col in {"date": date_col, "location": location_col, "value": value_col}.items()
        if not col
    ]
    if missing_mappings:
        st.warning(f"Missing mapping(s): {', '.join(missing_mappings)}. Please re-validate in Data Import.")
        return

    missing_columns = [
        name
        for name, col in {"date": date_col, "location": location_col, "value": value_col}.items()
        if col not in df.columns
    ]
    if missing_columns:
        st.warning(
            "Mapped columns are missing from the prepared table "
            f"({', '.join(missing_columns)}). Please re-run Data Import validation."
        )
        return

    date_series = _safe_datetime(df[date_col])
    value_series = _safe_numeric(df[value_col])

    valid_mask = date_series.notna() & value_series.notna()
    valid_df = pd.DataFrame(
        {
            "date": date_series[valid_mask],
            "location": df[location_col][valid_mask].astype(str),
            "value": value_series[valid_mask],
        }
    )

    if valid_df.empty:
        st.warning("No valid rows for analytics after parsing date/value columns.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows", f"{len(valid_df):,}")
    c2.metric("Locations", f"{valid_df['location'].nunique():,}")
    c3.metric("Total Value", f"{valid_df['value'].sum():,.2f}")
    c4.metric("Avg Value", f"{valid_df['value'].mean():,.2f}")

    st.subheader("Trend over time")
    trend = valid_df.groupby("date", as_index=False)["value"].sum().sort_values("date")
    st.line_chart(trend.set_index("date"))

    st.subheader("Top categories")
    top_locations = (
        valid_df.groupby("location", as_index=False)["value"]
        .sum()
        .sort_values("value", ascending=False)
        .head(15)
    )
    st.bar_chart(top_locations.set_index("location"))

    st.subheader("Filtered data preview")
    available_locations = sorted(valid_df["location"].unique())
    selected_locations = st.multiselect(
        "Filter locations",
        options=available_locations,
        default=available_locations[: min(5, len(available_locations))],
    )

    filtered = valid_df if not selected_locations else valid_df[valid_df["location"].isin(selected_locations)]
    st.dataframe(filtered.sort_values("date"), use_container_width=True, height=320)
