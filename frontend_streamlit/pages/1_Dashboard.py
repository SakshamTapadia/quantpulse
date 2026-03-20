import streamlit as st
import pandas as pd

st.set_page_config(page_title="Dashboard - QuantPulse", layout="wide")

from lib.auth import require_auth, regime_color  # noqa: E402

client = require_auth()

st.title("Regime Dashboard")

col_refresh, col_auto = st.columns([1, 3])
with col_refresh:
    if st.button("Refresh", use_container_width=True):
        st.rerun()
with col_auto:
    auto = st.checkbox("Auto-refresh every 30s")

if auto:
    import time
    time.sleep(30)
    st.rerun()

try:
    regimes = client.get_all_regimes()
except Exception as e:
    st.error(f"Failed to load regimes: {e}")
    st.stop()

if not regimes:
    st.info("No regime data available. Run inference first.")
    st.stop()

tickers = sorted(regimes.keys())

# Regime cards grid
st.subheader("Current Regimes")
cols = st.columns(min(5, len(tickers)))
for i, ticker in enumerate(tickers):
    data = regimes[ticker]
    regime = str(data.get("regime", "unknown"))
    confidence = float(data.get("confidence", 0.0))
    color = regime_color(regime)
    with cols[i % len(cols)]:
        st.markdown(
            f"""
            <div style="background:{color}1a;border:2px solid {color};border-radius:10px;
                        padding:14px;text-align:center;margin-bottom:10px">
                <div style="font-size:1rem;font-weight:700;color:#f1f5f9">{ticker}</div>
                <div style="font-size:0.8rem;color:{color};text-transform:uppercase;
                            letter-spacing:1px;font-weight:600;margin-top:4px">{regime}</div>
                <div style="font-size:0.75rem;color:#94a3b8;margin-top:6px">
                    {confidence:.1%} confidence
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.divider()

# Summary table
st.subheader("All Tickers")
rows = []
for ticker, data in regimes.items():
    rows.append(
        {
            "Ticker": ticker,
            "Regime": data.get("regime", "-"),
            "Confidence": f"{float(data.get('confidence', 0)):.1%}",
            "Timestamp": data.get("timestamp", "-"),
        }
    )
df = pd.DataFrame(rows).set_index("Ticker")
st.dataframe(df, use_container_width=True)

st.divider()
if st.button("Go to Ticker Detail"):
    st.switch_page("pages/2_Ticker_Detail.py")
