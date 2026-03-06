"""Streamlit main application."""

import streamlit as st

st.set_page_config(
    page_title="Frontier AI Radar",
    page_icon="📡",
    layout="wide",
)

st.title("📡 Frontier AI Radar")
st.markdown("**Fully agentic multi-agent intelligence system**")

# Sidebar navigation
st.sidebar.title("Navigation")
page = st.sidebar.selectbox(
    "Go to",
    ["Dashboard", "Sources", "Runs", "Findings", "Archive"],
)

if page == "Dashboard":
    st.header("Dashboard")
    st.info("Dashboard page - teammate will implement")
    st.write("Last run status, top findings, download PDF button")

elif page == "Sources":
    st.header("Sources")
    st.info("Sources page - teammate will implement")
    st.write("Add/edit URLs, assign to agent")

elif page == "Runs":
    st.header("Runs")
    st.info("Runs page - teammate will implement")
    st.write("Timeline, per-agent error logs")

elif page == "Findings":
    st.header("Findings Explorer")
    st.info("Findings page - teammate will implement")
    st.write("Filter by provider/topic, diff view")

elif page == "Archive":
    st.header("Digest Archive")
    st.info("Archive page - teammate will implement")
    st.write("Past PDFs, search")
