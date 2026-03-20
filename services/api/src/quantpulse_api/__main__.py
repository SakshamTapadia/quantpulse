import uvicorn
if __name__ == "__main__":
    uvicorn.run("quantpulse_api.app:app", host="0.0.0.0", port=8000, log_config=None, workers=1)
