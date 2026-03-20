import uvicorn
if __name__ == "__main__":
    uvicorn.run("quantpulse_alert.app:app", host="0.0.0.0", port=8004, log_config=None, workers=1)
