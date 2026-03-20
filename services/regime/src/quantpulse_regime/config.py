from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    kafka_bootstrap_servers: str = Field(default="localhost:9092", alias="KAFKA_BOOTSTRAP_SERVERS")
    kafka_topic_features: str = Field(default="computed-features", alias="KAFKA_TOPIC_FEATURES")
    kafka_topic_regime: str = Field(default="regime-signals", alias="KAFKA_TOPIC_REGIME")
    kafka_consumer_group: str = "regime-service"

    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_user: str = Field(default="quantpulse", alias="POSTGRES_USER")
    postgres_password: str = Field(default="changeme", alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="quantpulse", alias="POSTGRES_DB")

    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_password: str = Field(default="changeme", alias="REDIS_PASSWORD")

    mlflow_tracking_uri: str = Field(default="http://localhost:5000", alias="MLFLOW_TRACKING_URI")
    mlflow_experiment_name: str = Field(default="regime-detection", alias="MLFLOW_EXPERIMENT_NAME")

    feature_store_path: str = Field(default="/data/features", alias="FEATURE_STORE_PATH")
    model_store_path: str = Field(default="/app/models", alias="MODEL_STORE_PATH")

    # HMM config
    hmm_n_states: int = 4
    hmm_n_iter: int = 200
    hmm_covariance_type: str = "full"

    # Transformer config
    transformer_d_model: int = 64
    transformer_nhead: int = 4
    transformer_num_layers: int = 3
    transformer_lookback: int = 60
    transformer_dropout: float = 0.1
    transformer_n_classes: int = 4

    # Training
    train_start_date: str = "2010-01-01"
    train_val_split: float = 0.8
    batch_size: int = 64
    learning_rate: float = 1e-3
    max_epochs: int = 100
    early_stopping_patience: int = 10

    # Ensemble weights
    hmm_weight: float = 0.4
    transformer_weight: float = 0.6

    # Regime labels
    regime_names: list[str] = ["trending", "mean_reverting", "choppy", "high_vol"]

    service_host: str = "0.0.0.0"
    service_port: int = 8003

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}"


settings = Settings()
