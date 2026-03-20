import streamlit as st

st.set_page_config(page_title="Training - QuantPulse", layout="wide")

from lib.auth import require_auth  # noqa: E402

client = require_auth()

st.title("Model Training & Inference")

# --- Data Ingestion ---
st.subheader("Data Ingestion")
ing1, ing2 = st.columns(2)

with ing1:
    st.markdown("**Historical Backfill**")
    st.caption("Fetch and store historical OHLCV data from your data provider.")
    years = st.number_input("Years of history", min_value=1, max_value=20, value=5)
    if st.button("Run Backfill", use_container_width=True):
        with st.spinner(f"Fetching {years} years of data..."):
            try:
                result = client.trigger_backfill(years=int(years))
                st.success(str(result))
            except Exception as e:
                st.error(str(e))

with ing2:
    st.markdown("**End-of-Day Ingestion**")
    st.caption("Ingest the latest EOD bars for all tracked tickers.")
    st.write("")
    st.write("")
    if st.button("Run EOD Ingestion", use_container_width=True):
        with st.spinner("Running EOD ingestion..."):
            try:
                result = client.trigger_eod()
                st.success(str(result))
            except Exception as e:
                st.error(str(e))

st.divider()

# --- Model ---
st.subheader("Model")
mod1, mod2 = st.columns(2)

with mod1:
    st.markdown("**Train**")
    st.caption("Re-train the ensemble model (HMM + Transformer) on current feature data.")
    if st.button("Train Model", use_container_width=True, type="primary"):
        with st.spinner("Training... this may take several minutes."):
            try:
                result = client.trigger_train()
                st.success(str(result))
            except Exception as e:
                st.error(str(e))

with mod2:
    st.markdown("**Infer**")
    st.caption("Run inference on all tickers using the latest trained model.")
    if st.button("Run Inference", use_container_width=True):
        with st.spinner("Running inference on all tickers..."):
            try:
                result = client.trigger_infer()
                st.success(str(result))
            except Exception as e:
                st.error(str(e))
