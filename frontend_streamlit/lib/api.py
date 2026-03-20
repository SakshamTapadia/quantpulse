import os
from typing import Optional

import requests

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")


class APIClient:
    def __init__(self, token: Optional[str] = None) -> None:
        self.base = API_BASE.rstrip("/")
        self.token = token

    def _headers(self) -> dict:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    def login(self, username: str, password: str) -> Optional[str]:
        try:
            r = requests.post(
                f"{self.base}/auth/token",
                data={"username": username, "password": password},
                timeout=10,
            )
            r.raise_for_status()
            return r.json()["access_token"]
        except Exception:
            return None

    def get_tickers(self) -> list:
        r = requests.get(
            f"{self.base}/api/v1/tickers",
            headers=self._headers(),
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("tickers", [])

    def get_all_regimes(self) -> dict:
        r = requests.get(
            f"{self.base}/api/v1/regime",
            headers=self._headers(),
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("regimes", {})

    def get_regime(self, ticker: str) -> dict:
        r = requests.get(
            f"{self.base}/api/v1/regime/{ticker}",
            headers=self._headers(),
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def get_regime_history(self, ticker: str, limit: int = 100) -> list:
        r = requests.get(
            f"{self.base}/api/v1/regime/{ticker}/history",
            params={"limit": limit},
            headers=self._headers(),
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("history", [])

    def get_ohlcv(self, ticker: str, limit: int = 252, interval: str = "1d") -> list:
        r = requests.get(
            f"{self.base}/api/v1/ohlcv/{ticker}",
            params={"limit": limit, "interval": interval},
            headers=self._headers(),
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("bars", [])

    def get_alerts(self, limit: int = 50, unread_only: bool = False) -> list:
        r = requests.get(
            f"{self.base}/api/v1/alerts",
            params={"limit": limit, "unread_only": unread_only},
            headers=self._headers(),
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("alerts", [])

    def trigger_backfill(self, years: int = 5) -> dict:
        r = requests.post(
            f"{self.base}/trigger/backfill",
            params={"years": years},
            headers=self._headers(),
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    def trigger_eod(self) -> dict:
        r = requests.post(
            f"{self.base}/trigger/eod",
            headers=self._headers(),
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    def trigger_train(self) -> dict:
        r = requests.post(
            f"{self.base}/train",
            headers=self._headers(),
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    def trigger_infer(self) -> dict:
        r = requests.post(
            f"{self.base}/infer",
            headers=self._headers(),
            timeout=60,
        )
        r.raise_for_status()
        return r.json()
