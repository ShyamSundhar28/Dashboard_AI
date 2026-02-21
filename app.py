import streamlit as st

st.set_page_config(page_title="Agentic AI Dashboard", layout="wide")

st.sidebar.title("Agentic AI Dashboard")
page = st.sidebar.radio("Navigate", ["Home", "Data Import", "Agents", "Runs", "Settings"])

if page == "Home":
    st.title("Home")
    st.write("Welcome to your AI Agentic Dashboard 🚀")

elif page == "Data Import":
    st.title("Data Import")
    st.write("Upload Excel or CSV files here.")

elif page == "Agents":
    st.title("Agents")
    st.write("Run AI agents here.")

elif page == "Runs":
    st.title("Run History")
    st.write("Previous runs will appear here.")

elif page == "Settings":
    st.title("Settings")
    st.write("Configure API keys and preferences here.")