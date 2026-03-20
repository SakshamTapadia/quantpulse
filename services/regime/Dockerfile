FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --upgrade pip hatchling build

COPY shared/ shared/
RUN pip wheel --no-deps --wheel-dir /wheels shared/

RUN python -m venv /venv
RUN /venv/bin/pip install --no-cache-dir --find-links=/wheels shared/

# Install torch CPU-only first (avoids downloading 2.5GB CUDA wheels)
RUN /venv/bin/pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    "torch>=2.2"

COPY services/regime/pyproject.toml .
COPY services/regime/src/ src/
# Install remaining deps; torch already satisfied above
RUN /venv/bin/pip install --no-cache-dir --find-links=/wheels .

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8003 PATH="/venv/bin:$PATH"
WORKDIR /app
RUN addgroup --system qp && adduser --system --ingroup qp qp
COPY --from=builder /venv /venv
COPY services/regime/src/ src/
RUN mkdir -p /app/models && chown qp:qp /app/models
USER qp
EXPOSE 8003
CMD ["python", "-m", "quantpulse_regime"]
