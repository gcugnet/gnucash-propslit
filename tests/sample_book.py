"""Construit un petit livre GnuCash jetable pour les tests."""

from gnucash import Account, GncNumeric, Session, SessionOpenMode, Split, Transaction
from gnucash import gnucash_core_c as gc

COMMUN = "Actif:Compte commun"
COMPAGNE = "Passif:Compagne"
COURSES = "Dépenses:Courses"
LOISIRS = "Dépenses:Loisirs"
DOLLARS = "Actif:Compte USD"


def make_book(path):
    gc.gnc_set_account_separator(":")
    session = Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE)
    book = session.book
    table = book.get_table()
    eur = table.lookup("CURRENCY", "EUR")
    usd = table.lookup("CURRENCY", "USD")
    root = book.get_root_account()

    def account(name, kind, parent, commodity=eur, placeholder=False):
        a = Account(book)
        a.BeginEdit()
        a.SetName(name)
        a.SetType(kind)
        a.SetCommodity(commodity)
        a.SetPlaceholder(placeholder)
        parent.append_child(a)
        a.CommitEdit()
        return a

    actif = account("Actif", gc.ACCT_TYPE_ASSET, root, placeholder=True)
    passif = account("Passif", gc.ACCT_TYPE_LIABILITY, root, placeholder=True)
    depenses = account("Dépenses", gc.ACCT_TYPE_EXPENSE, root, placeholder=True)
    commun = account("Compte commun", gc.ACCT_TYPE_BANK, actif)
    dollars = account("Compte USD", gc.ACCT_TYPE_BANK, actif, commodity=usd)
    compagne = account("Compagne", gc.ACCT_TYPE_LIABILITY, passif)
    courses = account("Courses", gc.ACCT_TYPE_EXPENSE, depenses)
    loisirs = account("Loisirs", gc.ACCT_TYPE_EXPENSE, depenses)

    def trans(day, desc, splits, notes=""):
        t = Transaction(book)
        t.BeginEdit()
        t.SetCurrency(eur)
        t.SetDate(day, 10, 2026)
        t.SetDescription(desc)
        if notes:
            t.SetNotes(notes)
        for acc, value, amount, memo in splits:
            s = Split(book)
            s.SetParent(t)
            s.SetAccount(acc)
            s.SetValue(GncNumeric(value, 100))
            s.SetAmount(GncNumeric(amount, 100))
            if memo:
                s.SetMemo(memo)
        t.CommitEdit()

    trans(1, "Carrefour", [(commun, -6000, -6000, ""), (compagne, 3000, 3000, ""), (courses, 3000, 3000, "")])
    trans(5, "Carrefour", [(commun, -9000, -9000, ""), (compagne, 4500, 4500, "part compagne"),
                           (courses, 4500, 4500, "")], notes="hebdo")
    trans(7, "Cinéma", [(commun, -2000, -2000, ""), (loisirs, 2000, 2000, "")])
    trans(9, "Change", [(commun, -10000, -10000, ""), (dollars, 10000, 11500, "")])
    session.save()
    session.end()
    return path
