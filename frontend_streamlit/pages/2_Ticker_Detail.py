import streamlit as st
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="Ticker Detail - QuantPulse", layout="wide")

from lib.auth import require_auth, regime_color  # noqa: E402

client = require_auth()

st.title("Ticker Detail")

try:
    tickers = client.get_tickers()
except Exception as e:
    st.error(f"Failed to load tickers: {e}")
    st.stop()

if not tickers:
    st.info("No tickers available. Run ingestion first.")
    st.stop()

left, right = st.columns([2, 1])
with left:
    ticker = st.selectbox("Ticker", sorted(tickers))
with right:
    limit = st.slider("Bars", min_value=50, max_value=500, value=252)

if st.button("Refresh"):
    st.rerun()

st.divider()

ohlcv_col, regime_col = st.columns(2)

# OHLCV candlestick chart
with ohlcv_col:
    st.subheader(f"{ticker} - Price")
    try:
        bars = client.get_ohlcv(ticker, limit=limit)
    except Exception as e:
        st.error(f"OHLCV error: {e}")
        bars = []

    if bars:
        df = pd.DataFrame(bars)
        fig = go.Figure(
            go.Candlestick(
                x=df["time"],
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                increasing_line_color="#22c55e",
                decreasing_line_color="#ef4444",
            )
        )
        fig.update_layout(
            xaxis_rangeslider_visible=False,
            height=380,
            margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(gridcolor="#1e293b"),
            yaxis=dict(gridcolor="#1e293b"),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Stats row
        last = df.iloc[-1]
        first = df.iloc[0]
        pct = (last["close"] - first["close"]) / first["close"]
        m1, m2, m3 = st.columns(3)
        m1.metric("Close", f"{last['close']:.2f}")
        m2.metric("High", f"{df['high'].max():.2f}")
        m3.metric("Period Return", f"{pct:+.2%}")
    else:
        st.info("No OHLCV data available.")

# Regime history chart
with regime_col:
    st.subheader(f"{ticker} - Regime History")
    try:
        history = client.get_regime_history(ticker, limit=limit)
    except Exception as e:
        st.error(f"Regime history error: {e}")
        history = []

    if history:
        df_r = pd.DataFrame(history)
        fig_r = go.Figure()
        for regime in df_r["regime"].unique():
            mask = df_r["regime"] == regime
            color = regime_color(str(regime))
            fig_r.add_trace(
                go.Scatter(
                    x=df_r.loc[mask, "time"],
                    y=df_r.loc[mask, "confidence"],
                    mode="markers",
                    name=str(regime),
                    marker=dict(color=color, size=7, opacity=0.85),
                )
            )
        fig_r.update_layout(
            height=380,
            yaxis_title="Confidence",
            yaxis_tickformat=".0%",
            margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(gridcolor="#1e293b"),
            yaxis=dict(gridcolor="#1e293b"),
            legend=dict(orientation="h", y=-0.15),
        )
        st.plotly_chart(fig_r, use_container_width=True)

        # Current regime badge
        latest = history[-1]
        regime = str(latest.get("regime", "unknown"))
        color = regime_color(regime)
        conf = float(latest.get("confidence", 0))
        st.markdown(
            f"""
            <div style="background:{color}1a;border:2px solid {color};border-radius:10px;
                        padding:16px;text-align:center">
                <div style="font-size:0.75rem;color:#94a3b8;text-transform:uppercase;
                            letter-spacing:1px">Current Regime</div>
                <div style="font-size:1.5rem;font-weight:700;color:{color};margin-top:4px">
                    {regime.upper()}
                </div>
                <div style="color:#94a3b8;margin-top:4px">{conf:.1%} confidence</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.info("No regime history available.")
