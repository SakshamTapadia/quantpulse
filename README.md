# QuantPulse — Market Regime Intelligence Platform

A distributed, production-grade fintech platform that ingests real-time market data,
computes financial indicators, and classifies market regimes using an HMM + Transformer
ensemble — built entirely on open-source tools.

## What it does

Watches 15 major stocks and ETFs every day, uses machine learning to classify what "mode" the market is in — **Trending**, **Mean-Reverting**, **Choppy**, or **High-Volatility** — and alerts you when the market shifts between modes.

## Quick Start

```bash
# 1. Copy and fill in your API keys
cp .env.example .env

# 2. Start everything
docker compose up --build -d

# 3. Seed 5 years of historical data + train models
#    Open http://localhost:3000/dashboard/training and click:
#    → Historical Backfill (5y)  (wait ~3 min)
#    → Retrain Models            (wait ~10 min)
#    → Run Inference

# 4. View the dashboard
open http://localhost:3000
```

> **API keys:** yfinance works with no key. Get a free [FRED API key](https://fred.stlouisfed.org/docs/api/api_key.html) for macro data. [Polygon.io](https://polygon.io) free tier is optional.

## Service Map

| Service       | Port  | Role |
|---------------|-------|------|
| Frontend      | 3000  | Next.js dashboard |
| API Gateway   | 8000  | FastAPI + JWT auth + WebSocket |
| Ingestion     | 8001  | yfinance / FRED / Polygon fetchers |
| Feature       | 8002  | Polars indicator pipeline |
| Regime ML     | 8003  | HMM + Transformer ensemble |
| Alert         | 8004  | Rule-based alert engine |
| MLflow        | 5000  | Experiment tracking |
| Kafka UI      | 9080  | Topic browser |
| Grafana       | 3001  | Metrics — `admin` / `changeme` |
| Prometheus    | 9090  | Raw metrics scrape |

## Architecture

```
Polygon/yfinance/FRED
        │
   [Ingestion]──► Kafka (raw-ohlcv, raw-macro)
                       │
                  [Feature] ──► Parquet feature store
                       │            │
                  Kafka (features-computed)
                       │
                  [Regime ML] ──► Redis cache ──► [API Gateway] ──► Frontend
                       │
                  [Alert] ──► TimescaleDB alerts table
```

## Regime Classes

| # | Name | Characteristics |
|---|------|-----------------|
| 0 | Trending | High momentum, directional, moderate vol |
| 1 | Mean-Reverting | RSI extremes revert, low trend-R² |
| 2 | Choppy | Low momentum, random-walk-like |
| 3 | High-Vol | Elevated realised vol, crisis or spike regime |

## Tech Stack

Python 3.12 · Polars · PyTorch · hmmlearn · MLflow · Apache Kafka · TimescaleDB · Redis ·
FastAPI · Next.js 14 · Tailwind CSS · Lightweight Charts · Docker Compose · Prometheus · Grafana

## Data Sources

- **yfinance** — OHLCV bars, options chains (free, no key needed)
- **FRED API** — VIX, yield curve, HY spread, fed funds rate (free key)
- **Polygon.io** — EOD data, delayed quotes (free tier, optional)

## Features Computed (41 total)

| Category | Features |
|----------|----------|
| Volatility | Realised vol 5/21/63d (annualised), vol ratio, ATR, RV z-score |
| Momentum | RSI-14, TSI, ROC 5/21/63d, trend strength (rolling Pearson R²) |
| Macro | VIX z-score, yield curve slope, HY spread z-score, inversion flag |
| Options | IV skew proxy, put/call OI ratio, GEX proxy |

All features are rolling z-score normalised (252-day window, clipped ±4) before ML.

## ML Model

**HMM** (hmmlearn, 4 states, full covariance) identifies latent market regimes from macro+vol features.
**Transformer encoder** (PyTorch, 4 heads, 2 layers) learns sequence patterns over a 63-day lookback.
Outputs are **ensemble-averaged** into a final 4-class probability distribution.

Training is triggered manually from the dashboard or via API. MLflow tracks every run.

## API

```bash
# Get a token
curl -X POST http://localhost:8000/auth/token \
  -d "username=admin&password=changeme"

# Get all regime signals
curl http://localhost:8000/api/v1/regime \
  -H "Authorization: Bearer <token>"

# Trigger inference
curl -X POST http://localhost:8000/infer \
  -H "Authorization: Bearer <token>"
```

Full Swagger docs at `http://localhost:8000/docs`.

## Make Commands

```bash
make up              # start all services
make down            # stop all services
make build           # rebuild images
make logs            # tail all logs
make logs-regime     # tail a specific service
make shell-api       # bash into a container
make test            # run all test suites
make lint            # ruff + mypy
make clean           # destroy all volumes (destructive)
```

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for instructions on deploying to a cloud VM with Docker Compose, or adapting to Kubernetes.

## License

MIT — see [LICENSE](LICENSE).
