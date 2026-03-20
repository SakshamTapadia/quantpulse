from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Kafka
    kafka_bootstrap_servers: str = Field(default="localhost:9092", alias="KAFKA_BOOTSTRAP_SERVERS")
    kafka_topic_raw_ohlcv: str = Field(default="raw-ohlcv", alias="KAFKA_TOPIC_RAW_OHLCV")
    kafka_topic_macro: str = Field(default="macro-data", alias="KAFKA_TOPIC_MACRO")
    kafka_topic_options: str = Field(default="options-flow", alias="KAFKA_TOPIC_OPTIONS")
    kafka_topic_features: str = Field(default="computed-features", alias="KAFKA_TOPIC_FEATURES")
    kafka_consumer_group: str = "feature-service"

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

    # Feature store (parquet)
    feature_store_path: str = Field(default="/data/features", alias="FEATURE_STORE_PATH")

    # Indicator windows
    rv_windows: list[int] = [5, 21, 63]       # realized vol lookbacks in days
    rsi_period: int = 14
    atr_period: int = 14
    tsi_fast: int = 13
    tsi_slow: int = 25
    tsi_signal: int = 7
    normalisation_window: int = 252           # rolling z-score window

    # Service
    service_host: str = "0.0.0.0"
    service_port: int = 8002

    # Minimum bars required before computing features
    min_history_bars: int = 126              # ~6 months


settings = Settings()
