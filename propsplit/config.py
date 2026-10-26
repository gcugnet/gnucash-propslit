"""Paramétrage local, persisté en TOML.

Les comptes sont identifiés par leur GUID GnuCash, qui survit aux renommages ;
le nom n'est conservé que pour l'affichage et resynchronisé à chaque ouverture
du livre.
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w

CONFIG_ENV = "GNC_PROPSPLIT_CONFIG"


def default_path() -> Path:
    if env := os.environ.get(CONFIG_ENV):
        return Path(env)
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "gnc-propsplit" / "config.toml"


@dataclass
class AccountSettings:
    name: str
    proportional: bool = False


@dataclass
class Config:
    path: Path
    book: str | None = None
    default_account: str | None = None
    accounts: dict[str, AccountSettings] = field(default_factory=dict)

    def is_proportional(self, guid: str) -> bool:
        settings = self.accounts.get(guid)
        return settings is not None and settings.proportional

    def set_proportional(self, guid: str, name: str, value: bool) -> None:
        settings = self.accounts.setdefault(guid, AccountSettings(name))
        settings.name = name
        settings.proportional = value

    def rename(self, guid: str, name: str) -> None:
        if guid in self.accounts:
            self.accounts[guid].name = name

    def save(self) -> None:
        data: dict = {}
        if self.book:
            data["book"] = self.book
        if self.default_account:
            data["default_account"] = self.default_account
        if self.accounts:
            data["accounts"] = {
                guid: {"name": s.name, "proportional": s.proportional}
                for guid, s in self.accounts.items()
            }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".toml.tmp")
        tmp.write_text(tomli_w.dumps(data), encoding="utf-8")
        tmp.replace(self.path)


def load(path: Path | None = None) -> Config:
    path = path or default_path()
    if not path.exists():
        return Config(path)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    accounts = {
        guid: AccountSettings(s.get("name", guid), bool(s.get("proportional", False)))
        for guid, s in data.get("accounts", {}).items()
    }
    return Config(path, data.get("book"), data.get("default_account"), accounts)
