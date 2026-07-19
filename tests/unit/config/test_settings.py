from pathlib import Path

from config.settings import Settings


def test_defaults_apply_without_env(monkeypatch) -> None:
    monkeypatch.delenv("QTP_DATA_DIR", raising=False)
    settings = Settings(_env_file=None)
    assert settings.data_dir == Path("./data")
    assert settings.historical_data_dir == Path("./data/historical")


def test_env_prefix_overrides_defaults(monkeypatch) -> None:
    monkeypatch.setenv("QTP_DATA_DIR", "/tmp/qtp-data")
    settings = Settings(_env_file=None)
    assert settings.data_dir == Path("/tmp/qtp-data")
