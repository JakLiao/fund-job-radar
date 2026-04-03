"""Configuration loader for Fund Job Radar."""

import os
import threading
from pathlib import Path
from typing import Any

import yaml


def _resolve_env_var(value: Any) -> Any:
    """Resolve environment variable placeholders in config values.
    
    Supports ${VAR_NAME} syntax. If the env var is not set, returns empty string.
    """
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_var = value[2:-1]
        return os.environ.get(env_var, "")
    return value


class Config:
    """Configuration manager that loads from config.yaml."""

    _instance = None
    _lock = threading.Lock()
    _data: dict = {}

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._load()
        return cls._instance

    def _load(self) -> None:
        """Load configuration from config.yaml."""
        config_path = self._find_config_file()
        if config_path and config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}
        else:
            self._data = {}

    def _find_config_file(self) -> Path:
        """Find config.yaml in project root."""
        # Try current directory first, then parent directories
        current = Path(__file__).parent.parent
        for _ in range(3):
            candidate = current / "config.yaml"
            if candidate.exists():
                return candidate
            current = current.parent
        return Path("config.yaml")

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by dot-notation key (e.g., 'notification.sckey').
        
        Supports environment variable resolution via ${VAR_NAME} syntax.
        """
        keys = key.split(".")
        value = self._data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        # Resolve environment variables
        return _resolve_env_var(value)

    @property
    def feishu_webhook(self) -> str:
        return self.get("notification.feishu_webhook", "")

    @property
    def push_times(self) -> list:
        return self.get("notification.push_times", ["09:00"])

    @property
    def quiet_hours_start(self) -> str:
        return self.get("notification.quiet_hours_start", "22:00")

    @property
    def quiet_hours_end(self) -> str:
        return self.get("notification.quiet_hours_end", "08:00")

    @property
    def crunchbase_key(self) -> str:
        return self.get("apis.crunchbase_key", "")

    @property
    def window_seed_days(self) -> int:
        return self.get("scoring.window_seed_days", 14)

    @property
    def window_series_a_days(self) -> int:
        return self.get("scoring.window_series_a_days", 45)

    @property
    def window_series_b_days(self) -> int:
        return self.get("scoring.window_series_b_days", 60)

    @property
    def window_series_c_plus_days(self) -> int:
        return self.get("scoring.window_series_c_plus_days", 90)

    @property
    def score_threshold(self) -> float:
        return self.get("scoring.score_threshold", 5.0)

    @property
    def signal_high_threshold(self) -> float:
        return self.get("scoring.signal_high_threshold", 15.0)

    @property
    def signal_medium_threshold(self) -> float:
        return self.get("scoring.signal_medium_threshold", 8.0)

    @property
    def techcrunch_interval(self) -> int:
        return self.get("scheduler.techcrunch_interval_minutes", 30)

    @property
    def edgar_interval(self) -> int:
        return self.get("scheduler.edgar_interval_minutes", 120)

    @property
    def crunchbase_interval(self) -> int:
        return self.get("scheduler.crunchbase_interval_minutes", 60)

    @property
    def edgar_enabled(self) -> bool:
        return self.get("edgar.enabled", True)

    @property
    def edgar_days_lookback(self) -> int:
        return self.get("edgar.days_lookback", 30)

    @property
    def edgar_min_amount(self) -> float:
        return self.get("edgar.min_amount", 250000)

    @property
    def edgar_interval_hours(self) -> int:
        return self.get("scheduler.edgar_interval_hours", 6)

    @property
    def database_path(self) -> str:
        return self.get("database.path", "data/fund_job_radar.db")

    def reload(self) -> None:
        """Reload configuration from file."""
        self._load()


def get_config() -> Config:
    """Get the singleton config instance."""
    return Config()
