from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Data sources
    polygon_api_key: str = Field(default="", alias="POLYGON_API_KEY")
    alpha_vantage_key: str = Field(default="", alias="ALPHA_VANTAGE_KEY")
    fred_base_url: str = "https://api.stlouisfed.org/fred"
    fred_api_key: str = Field(default="", alias="FRED_API_KEY")  # optional, public endpoints work without

    # Ticker universe
    ticker_universe: str = Field(
        default="SPY,QQQ,IWM,GLD,TLT,HYG,XLE,XLF,XLK,AAPL,MSFT,NVDA,TSLA,AMZN,GOOGL",
        alias="TICKER_UNIVERSE",
    )

    @property
    def tickers(self) -> list[str]:
        return [t.strip() for t in self.ticker_universe.split(",")]

    # FRED series to ingest
    fred_series: list[str] = [
        "VIXCLS",       # VIX
        "DGS10",        # 10Y Treasury
        "DGS2",         # 2Y Treasury
        "DFF",          # Fed funds rate
        "BAMLH0A0HYM2", # HY spread (OAS)
        "T10Y2Y",       # Yield curve slope (10Y-2Y)
    ]

    # Kafka
    kafka_bootstrap_servers: str = Field(default="localhost:9092", alias="KAFKA_BOOTSTRAP_SERVERS")
    kafka_topic_raw_ohlcv: str = Field(default="raw-ohlcv", alias="KAFKA_TOPIC_RAW_OHLCV")
    kafka_topic_macro: str = Field(default="macro-data", alias="KAFKA_TOPIC_MACRO")
    kafka_topic_options: str = Field(default="options-flow", alias="KAFKA_TOPIC_OPTIONS")

    # Database
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_user: str = Field(default="quantpulse", alias="POSTGRES_USER")
    postgres_password: str = Field(default="changeme", alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="quantpulse", alias="POSTGRES_DB")

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # Scheduling
    ingest_cron_daily: str = Field(default="0 18 * * 1-5", alias="INGEST_CRON_DAILY")
    ingest_cron_intraday: str = Field(default="*/15 9-16 * * 1-5", alias="INGEST_CRON_INTRADAY")

    # Service
    service_host: str = "0.0.0.0"
    service_port: int = 8001

    # Retry / rate limits
    max_retries: int = 3
    retry_wait_seconds: float = 2.0
    yfinance_delay_seconds: float = 0.5   # polite delay between ticker fetches
    polygon_rps: int = 5                  # requests/sec on free tier


settings = Settings()
