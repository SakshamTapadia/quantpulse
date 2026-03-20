import uvicorn
from quantpulse_feature.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "quantpulse_feature.app:app",
        host=settings.service_host,
        port=settings.service_port,
        log_config=None,
        workers=1,
    )
