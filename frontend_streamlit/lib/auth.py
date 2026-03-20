import streamlit as st

from lib.api import APIClient

REGIME_COLORS: dict[str, str] = {
    "bull": "#22c55e",
    "bullish": "#22c55e",
    "uptrend": "#22c55e",
    "bear": "#ef4444",
    "bearish": "#ef4444",
    "downtrend": "#ef4444",
    "sideways": "#f59e0b",
    "range": "#f59e0b",
    "neutral": "#94a3b8",
    "crisis": "#dc2626",
    "volatile": "#a855f7",
}


def regime_color(regime: str) -> str:
    return REGIME_COLORS.get(str(regime).lower(), "#64748b")


def require_auth() -> APIClient:
    """Return an authenticated APIClient, or show the login form and stop."""
    if st.session_state.get("token"):
        return APIClient(token=st.session_state.token)
    _show_login()
    st.stop()


def _show_login() -> None:
    st.title("QuantPulse")
    st.subheader("Sign in to continue")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", use_container_width=True)
    if submitted:
        client = APIClient()
        token = client.login(username, password)
        if token:
            st.session_state.token = token
            st.rerun()
        else:
            st.error("Invalid credentials.")
