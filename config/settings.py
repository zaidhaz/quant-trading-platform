from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QTP_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    binance_futures_base_url: str = "https://fapi.binance.com"
    log_level: str = "INFO"

    @property
    def historical_data_dir(self) -> Path:
        return self.data_dir / "historical"


@lru_cache
def get_settings() -> Settings:
    return Settings()
