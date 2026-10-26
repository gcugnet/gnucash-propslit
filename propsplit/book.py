"""Accès au livre GnuCash via les bindings officiels.

C'est la seule couche qui importe `gnucash`. Elle reproduit ce que fait le
registre de GnuCash lors d'une auto-complétion (`gnc_copy_trans_onto_trans`),
à la répartition des montants près.
"""

import datetime
from contextlib import contextmanager
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Iterator

from gnucash import GncNumeric, Session, SessionOpenMode, Split, Transaction
from gnucash import gnucash_core_c as gc
from gnucash.gnucash_core import GnuCashBackendException

SEPARATOR = ":"


class BookError(Exception):
    pass


class BookLockedError(BookError):
    pass


class UnsupportedTransaction(BookError):
    pass


@dataclass(frozen=True)
class Line:
    """Une répartition à écrire : compte, valeur dans l'unité de la devise."""

    account: object  # gnucash.Account
    value: int
    memo: str = ""
    action: str = ""

    def with_account(self, account) -> "Line":
        return replace(self, account=account)

    def with_value(self, value: int) -> "Line":
        return replace(self, value=value)


@dataclass(frozen=True)
class Template:
    """Une transaction existante, vue depuis le compte de saisie.

    `lines[0]` est l'ancrage, la répartition du compte de saisie.
    """

    currency: object  # gnucash.GncCommodity
    scu: int
    lines: list[Line]
    notes: str = ""

    @property
    def values(self) -> list[int]:
        return [line.value for line in self.lines]


def guid_of(instance) -> str:
    return instance.GetGUID().to_string()


def _uri(path: Path) -> str:
    with path.open("rb") as f:
        head = f.read(16)
    scheme = "sqlite3" if head.startswith(b"SQLite format 3") else "xml"
    return f"{scheme}://{path}"


@contextmanager
def open_book(path: str | Path, readonly: bool = False) -> Iterator["Ledger"]:
    """Ouvre le livre et le referme quoi qu'il arrive.

    En écriture, l'ouverture respecte le verrou posé par GnuCash : si le livre
    est ouvert dans l'interface, on échoue au lieu d'écraser ses données. Rien
    n'est écrit sur disque sans appel explicite à `Ledger.save()`.
    """
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise BookError(f"livre introuvable : {path}")
    gc.gnc_set_account_separator(SEPARATOR)
    mode = SessionOpenMode.SESSION_READ_ONLY if readonly else SessionOpenMode.SESSION_NORMAL_OPEN
    try:
        session = Session(_uri(path), mode)
    except GnuCashBackendException as e:
        if gc.ERR_BACKEND_LOCKED in e.errors:
            raise BookLockedError(
                f"le livre est verrouillé, sans doute ouvert dans GnuCash : {path}\n"
                "Fermez-le dans GnuCash puis relancez."
            ) from e
        raise BookError(f"ouverture impossible de {path} : {e}") from e
    try:
        yield Ledger(session, path, readonly)
    finally:
        session.end()


class Ledger:
    def __init__(self, session, path: Path, readonly: bool):
        self.session = session
        self.book = session.book
        self.path = path
        self.readonly = readonly
        root = self.book.get_root_account()
        self.accounts = list(root.get_descendants_sorted())
        self._by_guid = {guid_of(a): a for a in self.accounts}
        self._by_name = {a.get_full_name(): a for a in self.accounts}

    # Comptes

    def account(self, guid: str):
        return self._by_guid.get(guid)

    def account_by_name(self, name: str):
        return self._by_name.get(name)

    def postable_accounts(self) -> list:
        """Comptes qui peuvent recevoir une écriture (ni placeholder, ni masqués)."""
        return [a for a in self.accounts if not a.GetPlaceholder() and not a.GetHidden()]

    # Historique

    def descriptions(self, account) -> list[str]:
        """Libellés des transactions du compte, du plus récent au plus ancien."""
        seen: dict[str, None] = {}
        for split in reversed(account.GetSplitList()):
            desc = split.GetParent().GetDescription()
            if desc:
                seen.setdefault(desc, None)
        return list(seen)

    def find_template(self, account, description: str) -> Transaction | None:
        """Dernière transaction du compte portant ce libellé, comme le registre."""
        return account.FindTransByDesc(description)

    def recent_transactions(self, account) -> Iterator[Transaction]:
        """Transactions du compte, de la plus récente à la plus ancienne."""
        for split in reversed(account.GetSplitList()):
            yield split.GetParent()

    def template(self, trans, account) -> Template:
        """Décompose une transaction existante en répartitions entières.

        L'ancrage (la répartition du compte de saisie) passe en tête, les
        contreparties suivent dans l'ordre de GnuCash.
        """
        currency = trans.GetCurrency()
        scu = currency.get_fraction()
        anchor_guid = guid_of(account)
        lines: list[Line] = []
        anchored = False
        for split in trans.GetSplitList():
            acc = split.GetAccount()
            if not _same_commodity(acc.GetCommodity(), currency):
                raise UnsupportedTransaction(
                    f"« {trans.GetDescription()} » touche {acc.get_full_name()}, "
                    f"dans une autre devise ou commodité que {currency.get_mnemonic()} : "
                    "à saisir dans GnuCash."
                )
            line = Line(acc, _to_units(split.GetValue(), scu), split.GetMemo() or "", split.GetAction() or "")
            if not anchored and guid_of(acc) == anchor_guid:
                anchored = True
                lines.insert(0, line)
            else:
                lines.append(line)
        if not anchored:
            raise UnsupportedTransaction("la transaction ne touche pas le compte de saisie")
        if len(lines) < 2:
            raise UnsupportedTransaction("la transaction n'a qu'une répartition")
        return Template(currency, scu, lines, trans.GetNotes() or "")

    # Écriture

    def create_transaction(
        self,
        currency,
        date: datetime.date,
        description: str,
        lines: list[Line],
        notes: str = "",
    ) -> Transaction:
        """Crée la transaction en mémoire ; elle n'est écrite qu'au `save()`."""
        if self.readonly:
            raise BookError("livre ouvert en lecture seule")
        if sum(line.value for line in lines) != 0:
            raise BookError("transaction déséquilibrée")
        for line in lines:
            if not _same_commodity(line.account.GetCommodity(), currency):
                raise UnsupportedTransaction(
                    f"{line.account.get_full_name()} n'est pas en {currency.get_mnemonic()}"
                )
        scu = currency.get_fraction()
        trans = Transaction(self.book)
        trans.BeginEdit()
        trans.SetCurrency(currency)
        trans.SetDate(date.day, date.month, date.year)
        trans.SetDescription(description)
        if notes:
            trans.SetNotes(notes)
        for line in lines:
            split = Split(self.book)
            split.SetParent(trans)
            split.SetAccount(line.account)
            value = GncNumeric(line.value, scu)
            split.SetValue(value)
            split.SetAmount(value)
            if line.memo:
                split.SetMemo(line.memo)
            if line.action:
                split.SetAction(line.action)
        trans.CommitEdit()
        return trans

    def save(self) -> None:
        if self.readonly:
            raise BookError("livre ouvert en lecture seule")
        self.session.save()


def _same_commodity(a, b) -> bool:
    return a.get_unique_name() == b.get_unique_name()


def _to_units(value, scu: int) -> int:
    units = Fraction(value.num(), value.denom()) * scu
    if units.denominator != 1:
        raise UnsupportedTransaction("montant plus précis que l'unité de la devise")
    return int(units)
