import streamlit as st

st.set_page_config(
    page_title="QuantPulse",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
    initial_sidebar_state="expanded",
)

from lib.auth import require_auth  # noqa: E402

client = require_auth()

st.title("QuantPulse")
st.write("Market regime detection and alerting platform.")
st.divider()

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("Dashboard", use_container_width=True, type="primary"):
        st.switch_page("pages/1_Dashboard.py")
with col2:
    if st.button("Alerts", use_container_width=True):
        st.switch_page("pages/3_Alerts.py")
with col3:
    if st.button("Training", use_container_width=True):
        st.switch_page("pages/4_Training.py")

st.divider()
if st.button("Sign out", type="secondary"):
    st.session_state.token = None
    st.rerun()
