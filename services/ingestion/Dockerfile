FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --upgrade pip hatchling build

COPY shared/ shared/
RUN pip wheel --no-deps --wheel-dir /wheels shared/

RUN python -m venv /venv
RUN /venv/bin/pip install --no-cache-dir --find-links=/wheels shared/

COPY services/ingestion/pyproject.toml .
COPY services/ingestion/src/ src/
RUN /venv/bin/pip install --no-cache-dir --find-links=/wheels .

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8001 PATH="/venv/bin:$PATH"
WORKDIR /app
RUN addgroup --system qp && adduser --system --ingroup qp qp
COPY --from=builder /venv /venv
COPY services/ingestion/src/ src/
USER qp
EXPOSE 8001
CMD ["python", "-m", "quantpulse_ingestion"]
