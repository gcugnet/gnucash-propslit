from propsplit import config


def test_missing_file_gives_empty_config(tmp_path):
    cfg = config.load(tmp_path / "absent.toml")
    assert cfg.book is None
    assert cfg.accounts == {}


def test_roundtrip(tmp_path):
    path = tmp_path / "sub" / "config.toml"
    cfg = config.load(path)
    cfg.book = "/livres/test.gnucash"
    cfg.default_account = "abc"
    cfg.set_proportional("abc", "Actif:Compte commun", True)
    cfg.save()

    again = config.load(path)
    assert again.book == "/livres/test.gnucash"
    assert again.default_account == "abc"
    assert again.is_proportional("abc")
    assert not again.is_proportional("autre")
    assert again.accounts["abc"].name == "Actif:Compte commun"


def test_env_variable_overrides_path(tmp_path, monkeypatch):
    target = tmp_path / "dev.toml"
    monkeypatch.setenv(config.CONFIG_ENV, str(target))
    assert config.default_path() == target
