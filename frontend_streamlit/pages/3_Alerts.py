import streamlit as st

st.set_page_config(page_title="Alerts - QuantPulse", layout="wide")

from lib.auth import require_auth  # noqa: E402

client = require_auth()

st.title("Alerts")

SEVERITY_COLORS: dict[str, str] = {
    "critical": "#ef4444",
    "high": "#f97316",
    "medium": "#f59e0b",
    "low": "#22c55e",
    "info": "#3b82f6",
}

# Controls
ctrl1, ctrl2, ctrl3 = st.columns([2, 2, 1])
with ctrl1:
    limit = st.slider("Max alerts", min_value=10, max_value=200, value=50)
with ctrl2:
    unread_only = st.checkbox("Unread only", value=False)
with ctrl3:
    st.write("")
    if st.button("Refresh", use_container_width=True):
        st.rerun()

st.divider()

try:
    alerts = client.get_alerts(limit=limit, unread_only=unread_only)
except Exception as e:
    st.error(f"Failed to load alerts: {e}")
    alerts = []

if not alerts:
    st.info("No alerts found.")
else:
    st.caption(f"{len(alerts)} alert(s)")
    for alert in alerts:
        severity = str(alert.get("severity", "info")).lower()
        color = SEVERITY_COLORS.get(severity, "#64748b")
        ticker = alert.get("ticker", "-")
        message = alert.get("message") or alert.get("rule_name") or "-"
        ts = alert.get("timestamp") or alert.get("created_at") or "-"
        read = alert.get("read", True)
        dot = "" if read else '<span style="color:#f59e0b;margin-right:6px">&#9679;</span>'

        st.markdown(
            f"""
            <div style="border-left:4px solid {color};background:{color}0f;
                        padding:10px 16px;border-radius:4px;margin-bottom:8px">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <span style="font-weight:700;color:{color}">
                        {dot}[{severity.upper()}] {ticker}
                    </span>
                    <span style="color:#64748b;font-size:0.8rem">{ts}</span>
                </div>
                <div style="margin-top:5px;color:#cbd5e1">{message}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
