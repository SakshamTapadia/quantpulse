import uvicorn
from quantpulse_ingestion.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "quantpulse_ingestion.app:app",
        host=settings.service_host,
        port=settings.service_port,
        log_config=None,   # we use structlog
        workers=1,         # single worker — scheduler state must not fork
    )
