import pytest

from propsplit import config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Aucun test ne doit lire ni écrire la vraie configuration."""
    path = tmp_path / "config.toml"
    monkeypatch.setenv(config.CONFIG_ENV, str(path))
    return path
