import uvicorn
from quantpulse_regime.config import settings

if __name__ == "__main__":
    uvicorn.run("quantpulse_regime.app:app", host=settings.service_host, port=settings.service_port, log_config=None, workers=1)
