"""
TemporalTransformer — sequence-to-label classifier for regime detection.

Architecture:
  Input:  (batch, seq_len=60, n_features)
  Layers: Linear projection → Positional encoding → N × TransformerEncoder layers
          → Global average pool → Linear classifier
  Output: (batch, 4) logits over [trending, mean_reverting, choppy, high_vol]

Design choices:
  - Global average pooling (not CLS token) — more stable for financial time series
  - Pre-norm (LayerNorm before attention) — better gradient flow for short sequences
  - No causal masking — we're doing offline labelling, not autoregressive prediction
  - Small model (d_model=64) — avoids overfitting on limited labelled data
"""
import math
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import structlog

from quantpulse_regime.config import settings

logger = structlog.get_logger(__name__)


class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 512, dropout: float = 0.1) -> None:
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)
        pe = torch.zeros(max_len, d_model)
        pos = torch.arange(0, max_len).unsqueeze(1).float()
        div = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(pos * div)
        pe[:, 1::2] = torch.cos(pos * div)
        self.register_buffer("pe", pe.unsqueeze(0))  # (1, max_len, d_model)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.pe[:, : x.size(1)]
        return self.dropout(x)


class TemporalTransformer(nn.Module):
    def __init__(self, n_features: int) -> None:
        super().__init__()
        d = settings.transformer_d_model
        self.input_proj = nn.Linear(n_features, d)
        self.pos_enc = PositionalEncoding(d, dropout=settings.transformer_dropout)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d,
            nhead=settings.transformer_nhead,
            dim_feedforward=d * 4,
            dropout=settings.transformer_dropout,
            batch_first=True,
            norm_first=True,     # pre-norm
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=settings.transformer_num_layers)
        self.classifier = nn.Sequential(
            nn.LayerNorm(d),
            nn.Linear(d, d // 2),
            nn.GELU(),
            nn.Dropout(settings.transformer_dropout),
            nn.Linear(d // 2, settings.transformer_n_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.input_proj(x)
        x = self.pos_enc(x)
        x = self.encoder(x)
        x = x.mean(dim=1)       # global average pool over sequence dim
        return self.classifier(x)


class TransformerRegimeModel:
    """Wrapper around TemporalTransformer with fit/predict interface."""

    def __init__(self, n_features: int) -> None:
        self.n_features = n_features
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.net = TemporalTransformer(n_features).to(self.device)
        self.is_fitted = False
        self.log = structlog.get_logger(self.__class__.__name__)

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
    ) -> "TransformerRegimeModel":
        """
        X: (n_samples, lookback, n_features)
        y: (n_samples,) int labels 0-3
        """
        self.log.info("transformer_fit_start", samples=len(X), features=self.n_features)
        optimizer = torch.optim.AdamW(self.net.parameters(), lr=settings.learning_rate, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=settings.max_epochs)

        X_t = torch.tensor(X, dtype=torch.float32)
        y_t = torch.tensor(y, dtype=torch.long)
        dataset = torch.utils.data.TensorDataset(X_t, y_t)
        loader  = torch.utils.data.DataLoader(dataset, batch_size=settings.batch_size, shuffle=True)

        best_val_loss = float("inf")
        patience_count = 0

        for epoch in range(settings.max_epochs):
            self.net.train()
            train_loss = 0.0
            for xb, yb in loader:
                xb, yb = xb.to(self.device), yb.to(self.device)
                optimizer.zero_grad()
                logits = self.net(xb)
                loss = F.cross_entropy(logits, yb)
                loss.backward()
                nn.utils.clip_grad_norm_(self.net.parameters(), 1.0)
                optimizer.step()
                train_loss += loss.item()
            scheduler.step()

            if X_val is not None and y_val is not None:
                val_loss = self._eval_loss(X_val, y_val)
                if val_loss < best_val_loss - 1e-4:
                    best_val_loss = val_loss
                    patience_count = 0
                else:
                    patience_count += 1
                if patience_count >= settings.early_stopping_patience:
                    self.log.info("early_stopping", epoch=epoch)
                    break

            if epoch % 10 == 0:
                self.log.info("epoch", epoch=epoch, train_loss=round(train_loss / len(loader), 4))

        self.is_fitted = True
        self.log.info("transformer_fit_complete")
        return self

    def _eval_loss(self, X: np.ndarray, y: np.ndarray) -> float:
        self.net.eval()
        with torch.no_grad():
            xb = torch.tensor(X, dtype=torch.float32).to(self.device)
            yb = torch.tensor(y, dtype=torch.long).to(self.device)
            return float(F.cross_entropy(self.net(xb), yb).item())

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Returns softmax probabilities, shape (n_samples, 4)."""
        self.net.eval()
        with torch.no_grad():
            xb = torch.tensor(X, dtype=torch.float32).to(self.device)
            logits = self.net(xb)
            return F.softmax(logits, dim=-1).cpu().numpy()

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.predict_proba(X).argmax(axis=1)

    def save(self, path: str) -> None:
        torch.save({"state_dict": self.net.state_dict(), "n_features": self.n_features}, path)

    def load(self, path: str) -> "TransformerRegimeModel":
        data = torch.load(path, map_location=self.device)
        self.n_features = data["n_features"]
        self.net = TemporalTransformer(self.n_features).to(self.device)
        self.net.load_state_dict(data["state_dict"])
        self.is_fitted = True
        return self
