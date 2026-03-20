"""Tests for alert rule evaluation."""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch


def test_regime_shift_generates_alert():
    """Regime change from 0→3 should generate a REGIME_SHIFT alert with severity 3."""
    from quantpulse_alert.app import _evaluate, _last_regime, _persist_alert
    _last_regime.clear()
    _last_regime["SPY"] = 0  # was trending

    alerts_captured = []
    async def fake_persist(alert):
        alerts_captured.append(alert)

    signal = {"ticker": "SPY", "regime": 3, "regime_name": "high_vol", "confidence": 0.85, "ensemble_prob": []}

    with patch("quantpulse_alert.app._persist_alert", side_effect=fake_persist):
        asyncio.get_event_loop().run_until_complete(_evaluate(signal))

    regime_shift = [a for a in alerts_captured if a["alert_type"] == "REGIME_SHIFT"]
    assert len(regime_shift) == 1
    assert regime_shift[0]["severity"] == 3


def test_low_confidence_generates_alert():
    """Confidence below 0.5 should always generate CONFIDENCE_LOW alert."""
    from quantpulse_alert.app import _evaluate, _last_regime, _persist_alert
    _last_regime.clear()
    _last_regime["QQQ"] = 1

    alerts_captured = []
    async def fake_persist(alert):
        alerts_captured.append(alert)

    signal = {"ticker": "QQQ", "regime": 1, "regime_name": "mean_reverting", "confidence": 0.35, "ensemble_prob": []}

    with patch("quantpulse_alert.app._persist_alert", side_effect=fake_persist):
        asyncio.get_event_loop().run_until_complete(_evaluate(signal))

    conf_alerts = [a for a in alerts_captured if a["alert_type"] == "CONFIDENCE_LOW"]
    assert len(conf_alerts) == 1


def test_no_shift_no_alert():
    """Same regime repeated should not generate a REGIME_SHIFT alert."""
    from quantpulse_alert.app import _evaluate, _last_regime, _persist_alert
    _last_regime.clear()
    _last_regime["AAPL"] = 0

    alerts_captured = []
    async def fake_persist(alert):
        alerts_captured.append(alert)

    signal = {"ticker": "AAPL", "regime": 0, "regime_name": "trending", "confidence": 0.92, "ensemble_prob": []}

    with patch("quantpulse_alert.app._persist_alert", side_effect=fake_persist):
        asyncio.get_event_loop().run_until_complete(_evaluate(signal))

    regime_shifts = [a for a in alerts_captured if a["alert_type"] == "REGIME_SHIFT"]
    assert len(regime_shifts) == 0
