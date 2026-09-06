"""
app/config.py — Centralized settings loaded from environment variables.
Never hardcode secrets; everything here is read from .env / real env vars.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql://sentinel:sentinel_pw@localhost:5432/sentinel_db"
    REDIS_URL: str = "redis://localhost:6379/0"

    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_TOPIC_RETURNS: str = "returns.incoming"
    KAFKA_TOPIC_SCORED: str = "returns.scored"
    KAFKA_CONSUMER_GROUP: str = "sentinel-scorer"

    JWT_SECRET_KEY: str = "dev-only-insecure-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_SECONDS: int = 3600

    MODEL_ARTIFACT_PATH: str = "./artifacts/model_current.pkl"
    MODEL_MIN_GREEN_SHARE: float = 0.55

    DEFAULT_COST_MANUAL_REVIEW: float = 150.0
    DEFAULT_COST_INSPECTION: float = 40.0
    DEFAULT_COST_FRICTION: float = 5.0
    DEFAULT_FRACTION_LOST_ON_MISS: float = 0.6

    PROMETHEUS_PORT: int = 9100
    LOG_LEVEL: str = "INFO"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"

    PSI_ALERT_THRESHOLD: float = 0.2
    PRECISION_DROP_ALERT_PCT: float = 10.0

    APP_ENV: str = "development"
    API_PORT: int = 8000


settings = Settings()
