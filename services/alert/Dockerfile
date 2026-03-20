FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --upgrade pip hatchling build

COPY shared/ shared/
RUN pip wheel --no-deps --wheel-dir /wheels shared/

RUN python -m venv /venv
RUN /venv/bin/pip install --no-cache-dir --find-links=/wheels shared/

COPY services/alert/pyproject.toml .
COPY services/alert/src/ src/
RUN /venv/bin/pip install --no-cache-dir --find-links=/wheels .

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8004 PATH="/venv/bin:$PATH"
WORKDIR /app
RUN addgroup --system qp && adduser --system --ingroup qp qp
COPY --from=builder /venv /venv
COPY services/alert/src/ src/
USER qp
EXPOSE 8004
CMD ["python", "-m", "quantpulse_alert"]
