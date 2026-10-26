"""Interface en ligne de commande de gnc-propsplit."""

import argparse
import datetime
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from prompt_toolkit import HTML, prompt
from prompt_toolkit.completion import PathCompleter
from prompt_toolkit.history import InMemoryHistory

from . import config, split_math
from .book import BookError, Line, UnsupportedTransaction, guid_of, open_book
from .completion import FuzzyChoices, matches, resolve


class Cancel(Exception):
    """L'utilisateur abandonne la saisie en cours."""


# Saisie


def ask(message: str, default: str = "", completer=None, history=None) -> str:
    """Pose une question ; une réponse vide renvoie la valeur par défaut."""
    placeholder = HTML("<style fg='ansibrightblack'>{}</style>").format(default) if default else None
    try:
        answer = prompt(
            f"{message} : ",
            completer=completer,
            complete_while_typing=completer is not None,
            placeholder=placeholder,
            history=history,
        ).strip()
    except KeyboardInterrupt:
        raise Cancel from None
    return answer or default


def ask_yes_no(message: str, default: bool) -> bool:
    hint = "O/n" if default else "o/N"
    while True:
        answer = ask(f"{message} [{hint}]").casefold()
        if not answer:
            return default
        if answer in ("o", "oui", "y", "yes"):
            return True
        if answer in ("n", "non", "no"):
            return False


def ask_account(ledger, message: str, default=None, choices: list | None = None):
    accounts = choices if choices is not None else ledger.postable_accounts()
    names = [a.get_full_name() for a in accounts]
    default_name = default.get_full_name() if default is not None else ""
    while True:
        text = ask(message, default_name, FuzzyChoices(names))
        name = resolve(names, text)
        if name:
            return accounts[names.index(name)]
        found = matches(names, text)
        if found:
            print(f"  Ambigu : {', '.join(found[:5])}{' …' if len(found) > 5 else ''}")
        else:
            print(f"  Aucun compte ne correspond à « {text} ».")


def parse_date(text: str, today: datetime.date) -> datetime.date:
    """Accepte JJ, JJ/MM, JJ/MM/AAAA et AAAA-MM-JJ."""
    text = text.strip()
    try:
        if "-" in text:
            return datetime.date.fromisoformat(text)
        parts = [int(p) for p in text.split("/")]
        if len(parts) == 1:
            return today.replace(day=parts[0])
        if len(parts) == 2:
            return today.replace(day=parts[0], month=parts[1])
        if len(parts) == 3:
            year = parts[2] + 2000 if parts[2] < 100 else parts[2]
            return datetime.date(year, parts[1], parts[0])
    except ValueError:
        pass
    raise ValueError(f"date illisible : {text!r}")


def ask_date(default: datetime.date) -> datetime.date:
    while True:
        text = ask("Date", default.strftime("%d/%m/%Y"))
        try:
            return parse_date(text, default)
        except ValueError as e:
            print(f"  {e}")


def ask_total(scu: int, default: int | None, sign: int) -> int:
    """Montant signé de la répartition du compte de saisie.

    Sans signe, le montant suit le sens du modèle (une sortie pour un libellé
    nouveau) ; « + » force une entrée d'argent, « - » une sortie.
    """
    default_text = split_math.format_amount(abs(default), scu) if default else ""
    while True:
        text = ask("Montant", default_text)
        if not text:
            continue
        try:
            value = split_math.parse_amount(text, scu)
        except ValueError as e:
            print(f"  {e}")
            continue
        if value == 0:
            print("  Le montant doit être non nul.")
            continue
        if text.lstrip().startswith(("+", "-")):
            return value
        return sign * abs(value)


def ask_shares(ledger, anchor_account) -> list[tuple[object, Fraction]]:
    """Saisie libre des contreparties, en pourcentage du montant."""
    result = []
    remaining = Fraction(1)
    choices = [a for a in ledger.postable_accounts() if guid_of(a) != guid_of(anchor_account)]
    while remaining > 0:
        account = ask_account(ledger, f"Contrepartie {len(result) + 1}", choices=choices)
        while True:
            text = ask("Part en %", split_math.format_percent(remaining).removesuffix(" %"))
            try:
                share = split_math.parse_percent(text)
            except ValueError as e:
                print(f"  {e}")
                continue
            if 0 < share <= remaining:
                break
            print(f"  La part doit être comprise entre 0 et {split_math.format_percent(remaining)}.")
        result.append((account, share))
        remaining -= share
    return result


# Brouillon de transaction


@dataclass
class Draft:
    date: datetime.date
    description: str
    currency: object
    scu: int
    lines: list[Line]
    notes: str
    scalable: bool

    @property
    def values(self) -> list[int]:
        return [line.value for line in self.lines]

    def show(self) -> None:
        anchor = self.lines[0]
        width = max(len(line.account.get_full_name()) for line in self.lines)
        shares = split_math.shares(self.values, 0)
        mnemonic = self.currency.get_mnemonic()
        print()
        print(f"  {self.date:%d/%m/%Y}  {self.description}")
        print(f"     {anchor.account.get_full_name():<{width}}  "
              f"{split_math.format_amount(anchor.value, self.scu):>12} {mnemonic}")
        for i, (line, share) in enumerate(zip(self.lines[1:], shares[1:]), start=1):
            print(f"  {i:>2} {line.account.get_full_name():<{width}}  "
                  f"{split_math.format_amount(line.value, self.scu):>12} {mnemonic}"
                  f"  {split_math.format_percent(share):>8}")
        print()

    def rescale(self, total: int) -> None:
        values = split_math.scale(self.values, 0, total)
        self.lines = [line.with_value(v) for line, v in zip(self.lines, values)]

    def reshare(self, anchor_line: Line, counterparts: list[tuple[object, Fraction]]) -> None:
        values = split_math.from_shares(anchor_line.value, [s for _, s in counterparts])
        self.lines = [anchor_line.with_value(values[0])] + [
            Line(account, value) for (account, _), value in zip(counterparts, values[1:])
        ]
        self.scalable = True


class Entry:
    """Saisie d'une transaction dans le compte de saisie."""

    def __init__(self, ledger, account, proportional: bool, descriptions: list[str]):
        self.ledger = ledger
        self.account = account
        self.proportional = proportional
        self.descriptions = descriptions
        self.description_history = InMemoryHistory()

    def run(self, date: datetime.date) -> Draft | None:
        date = ask_date(date)
        description = ""
        while not description:
            description = ask("Libellé", completer=FuzzyChoices(self.descriptions),
                              history=self.description_history)
        trans = self.ledger.find_template(self.account, description)
        draft = self.from_template(date, description, trans) if trans else self.from_scratch(date, description)
        if draft is None:
            return None
        return self.review(draft)

    def from_template(self, date, description, trans) -> Draft | None:
        try:
            tpl = self.ledger.template(trans, self.account)
        except UnsupportedTransaction as e:
            print(f"  {e}")
            return None
        scalable = self.proportional or len(tpl.lines) == 2
        draft = Draft(date, description, tpl.currency, tpl.scu, list(tpl.lines), tpl.notes, scalable)
        draft.show()
        anchor = tpl.lines[0].value
        if not scalable:
            print("  Ce compte n'est pas en mode proportionnel : les montants sont recopiés tels quels.")
            return draft
        total = ask_total(tpl.scu, anchor, -1 if anchor < 0 else 1)
        draft.rescale(total)
        return draft

    def from_scratch(self, date, description) -> Draft:
        currency = self.account.GetCommodity()
        scu = currency.get_fraction()
        total = ask_total(scu, None, -1)
        anchor_line = Line(self.account, total)
        draft = Draft(date, description, currency, scu, [anchor_line], "", True)
        pattern = self.last_pattern()
        if pattern:
            # Même répartition que la dernière saisie ; on confirme chaque compte.
            print("  Libellé nouveau : répartition de la dernière transaction du compte.")
            counterparts = [
                (ask_account(self.ledger, f"Contrepartie {i} ({split_math.format_percent(share)})", account), share)
                for i, (account, share) in enumerate(pattern, start=1)
            ]
        else:
            counterparts = ask_shares(self.ledger, self.account)
        draft.reshare(anchor_line, counterparts)
        return draft

    def last_pattern(self) -> list[tuple[object, Fraction]] | None:
        """Répartition de la dernière transaction exploitable du compte."""
        for trans in self.ledger.recent_transactions(self.account):
            try:
                tpl = self.ledger.template(trans, self.account)
                shares = split_math.shares(tpl.values, 0)
            except (UnsupportedTransaction, ValueError):
                continue
            return [(line.account, share) for line, share in zip(tpl.lines[1:], shares[1:])]
        return None

    def review(self, draft: Draft) -> Draft | None:
        n = len(draft.lines) - 1
        while True:
            draft.show()
            choice = ask(f"Entrée valide · 1-{n} compte · m montant · r répartition · a abandon").casefold()
            if not choice:
                return draft
            if choice == "a":
                return None
            if choice == "m":
                if not draft.scalable:
                    print("  Montants absolus : activez le mode proportionnel avec "
                          "« gnc-propsplit account enable ».")
                    continue
                anchor = draft.lines[0].value
                draft.rescale(ask_total(draft.scu, anchor, -1 if anchor < 0 else 1))
            elif choice == "r":
                draft.reshare(draft.lines[0], ask_shares(self.ledger, self.account))
                n = len(draft.lines) - 1
            elif choice.isdigit() and 1 <= int(choice) <= n:
                i = int(choice)
                choices = [a for a in self.ledger.postable_accounts() if guid_of(a) != guid_of(self.account)]
                account = ask_account(self.ledger, "Compte", draft.lines[i].account, choices)
                draft.lines[i] = draft.lines[i].with_account(account)


# Commandes


def load_book_path(cfg: config.Config) -> str:
    if not cfg.book:
        raise BookError(f"aucun livre configuré ({cfg.path}) : lancez « gnc-propsplit config init »")
    return cfg.book


def pick_account(ledger, cfg: config.Config, name: str | None):
    if name:
        names = [a.get_full_name() for a in ledger.accounts]
        found = resolve(names, name)
        if not found:
            raise BookError(f"compte introuvable ou ambigu : {name}")
        return ledger.account_by_name(found)
    if cfg.default_account:
        account = ledger.account(cfg.default_account)
        if account is None:
            raise BookError("le compte de saisie configuré n'existe plus dans le livre")
        return account
    raise BookError("aucun compte de saisie : précisez --account ou lancez « gnc-propsplit config init »")


def sync_names(ledger, cfg: config.Config) -> None:
    changed = False
    for guid, settings in cfg.accounts.items():
        account = ledger.account(guid)
        if account is not None and settings.name != account.get_full_name():
            cfg.rename(guid, account.get_full_name())
            changed = True
    if changed:
        cfg.save()


def cmd_add(cfg: config.Config, args) -> int:
    with open_book(load_book_path(cfg)) as ledger:
        sync_names(ledger, cfg)
        account = pick_account(ledger, cfg, args.account)
        proportional = cfg.is_proportional(guid_of(account))
        mode = "répartition en %" if proportional else "montants absolus"
        print(f"Livre : {ledger.path}")
        print(f"Compte de saisie : {account.get_full_name()} ({mode})")
        print("Ctrl-C annule la saisie en cours, Ctrl-D termine.")

        entry = Entry(ledger, account, proportional, ledger.descriptions(account))
        created: list[Draft] = []
        date = datetime.date.today()
        while True:
            print()
            try:
                draft = entry.run(date)
            except Cancel:
                print("  Saisie annulée.")
                continue
            except EOFError:
                break
            if draft is None:
                print("  Saisie abandonnée.")
                continue
            ledger.create_transaction(draft.currency, draft.date, draft.description, draft.lines, draft.notes)
            created.append(draft)
            date = draft.date
            if draft.description in entry.descriptions:
                entry.descriptions.remove(draft.description)
            entry.descriptions.insert(0, draft.description)
            print(f"  Transaction ajoutée ({len(created)} en attente d'enregistrement).")

        print()
        if not created:
            print("Aucune transaction saisie.")
            return 0
        for draft in created:
            print(f"  {draft.date:%d/%m/%Y}  {draft.description:<30} "
                  f"{split_math.format_amount(draft.lines[0].value, draft.scu):>12}")
        if args.dry_run:
            print("Mode --dry-run : rien n'est enregistré.")
            return 0
        try:
            save = ask_yes_no(f"Enregistrer ces {len(created)} transaction(s) dans le livre ?", False)
        except (Cancel, EOFError):
            save = False
        if not save:
            print("Rien n'a été enregistré.")
            return 0
        ledger.save()
        print("Enregistré. GnuCash a gardé l'ancienne version du livre en sauvegarde horodatée.")
    return 0


def cmd_config_init(cfg: config.Config, args) -> int:
    print(f"Configuration : {cfg.path}")
    while True:
        book = ask("Livre GnuCash", cfg.book or "", PathCompleter(expanduser=True))
        if book:
            break
    book = str(Path(book).expanduser().resolve())
    with open_book(book, readonly=True) as ledger:
        current = ledger.account(cfg.default_account) if cfg.default_account else None
        account = ask_account(ledger, "Compte de saisie par défaut", current)
        guid = guid_of(account)
        proportional = ask_yes_no("Retenir la répartition en pourcentage pour ce compte ?",
                                  cfg.is_proportional(guid) or guid not in cfg.accounts)
        cfg.book = book
        cfg.default_account = guid
        cfg.set_proportional(guid, account.get_full_name(), proportional)
        sync_names(ledger, cfg)
    cfg.save()
    print(f"Configuration enregistrée dans {cfg.path}")
    return 0


def cmd_config_show(cfg: config.Config, args) -> int:
    print(f"Configuration : {cfg.path}{'' if cfg.path.exists() else ' (absente)'}")
    print(f"Livre : {cfg.book or '—'}")
    default = cfg.accounts.get(cfg.default_account) if cfg.default_account else None
    print(f"Compte de saisie : {default.name if default else cfg.default_account or '—'}")
    proportional = [s.name for s in cfg.accounts.values() if s.proportional]
    print("Comptes en répartition % : " + (", ".join(proportional) if proportional else "aucun"))
    return 0


def cmd_account(cfg: config.Config, args) -> int:
    enable = args.action == "enable"
    with open_book(load_book_path(cfg), readonly=True) as ledger:
        if args.name:
            account = pick_account(ledger, cfg, args.name)
        else:
            account = ask_account(ledger, "Compte", choices=ledger.postable_accounts())
        cfg.set_proportional(guid_of(account), account.get_full_name(), enable)
    cfg.save()
    state = "activée" if enable else "désactivée"
    print(f"Répartition en pourcentage {state} pour {account.get_full_name()}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gnc-propsplit",
        description="Saisie GnuCash avec auto-complétion proportionnelle des transactions réparties.",
    )
    parser.add_argument("--config", type=Path, help=f"fichier de configuration (ou ${config.CONFIG_ENV})")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="saisir des transactions")
    add.add_argument("--account", help="compte de saisie (par défaut celui de la configuration)")
    add.add_argument("--dry-run", action="store_true", help="ne rien enregistrer")
    add.set_defaults(func=cmd_add)

    cfg = sub.add_parser("config", help="paramétrage")
    cfg_sub = cfg.add_subparsers(dest="config_command", required=True)
    cfg_sub.add_parser("init", help="assistant de configuration").set_defaults(func=cmd_config_init)
    cfg_sub.add_parser("show", help="afficher la configuration").set_defaults(func=cmd_config_show)

    account = sub.add_parser("account", help="option « répartition en pourcentage » d'un compte")
    account.add_argument("action", choices=["enable", "disable"])
    account.add_argument("name", nargs="?", help="nom complet du compte (recherche floue)")
    account.set_defaults(func=cmd_account)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load(args.config)
    try:
        return args.func(cfg, args)
    except BookError as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    except (Cancel, EOFError):
        print("Abandon.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
