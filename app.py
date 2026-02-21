import streamlit as st
from src.pages.data_import import render_data_import_page


def main() -> None:
    st.set_page_config(page_title="Agentic AI Dashboard", layout="wide")

    st.sidebar.title("Agentic AI Dashboard")
    page = st.sidebar.radio(
        "Navigate",
        ["Home", "Data Import"],
        index=0,
    )

    if page == "Home":
        st.title("Home")
        st.write("Welcome to your AI Agentic Dashboard 🚀")
        st.info("Go to **Data Import** to upload Excel/CSV and create tables.")
    else:
        render_data_import_page()


if __name__ == "__main__":
    main()