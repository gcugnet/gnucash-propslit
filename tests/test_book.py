import datetime

import pytest

from propsplit import split_math
from propsplit.book import BookError, BookLockedError, UnsupportedTransaction, guid_of, open_book
from sample_book import COMMUN, COMPAGNE, COURSES, DOLLARS, LOISIRS, make_book


@pytest.fixture
def book_path(tmp_path):
    return make_book(tmp_path / "test.gnucash")


def test_accounts_and_descriptions(book_path):
    with open_book(book_path, readonly=True) as ledger:
        commun = ledger.account_by_name(COMMUN)
        assert ledger.account(guid_of(commun)).get_full_name() == COMMUN
        names = [a.get_full_name() for a in ledger.postable_accounts()]
        assert COURSES in names and "Dépenses" not in names
        assert ledger.descriptions(commun) == ["Change", "Cinéma", "Carrefour"]


def test_template_is_latest_and_anchored(book_path):
    with open_book(book_path, readonly=True) as ledger:
        commun = ledger.account_by_name(COMMUN)
        tpl = ledger.template(ledger.find_template(commun, "Carrefour"), commun)
        assert tpl.lines[0].account.get_full_name() == COMMUN
        assert sorted(tpl.values) == [-9000, 4500, 4500]
        assert tpl.values[0] == -9000
        assert tpl.notes == "hebdo"
        assert tpl.scu == 100


def test_template_rejects_other_commodity(book_path):
    with open_book(book_path, readonly=True) as ledger:
        commun = ledger.account_by_name(COMMUN)
        with pytest.raises(UnsupportedTransaction, match=DOLLARS):
            ledger.template(ledger.find_template(commun, "Change"), commun)


def test_write_scaled_transaction_and_reopen(book_path):
    with open_book(book_path) as ledger:
        commun = ledger.account_by_name(COMMUN)
        tpl = ledger.template(ledger.find_template(commun, "Carrefour"), commun)
        values = split_math.scale(tpl.values, 0, -11000)
        lines = [line.with_value(v) for line, v in zip(tpl.lines, values)]
        ledger.create_transaction(tpl.currency, datetime.date(2026, 10, 20), "Carrefour", lines, tpl.notes)
        ledger.save()

    with open_book(book_path, readonly=True) as ledger:
        commun = ledger.account_by_name(COMMUN)
        trans = ledger.find_template(commun, "Carrefour")
        assert trans.GetDate().date() == datetime.date(2026, 10, 20)
        assert trans.GetCurrency().get_mnemonic() == "EUR"
        assert trans.GetImbalanceValue().zero_p()
        assert trans.GetNotes() == "hebdo"
        got = {
            s.GetAccount().get_full_name(): (s.GetValue().num(), s.GetAmount().num(), s.GetMemo(), s.GetReconcile())
            for s in trans.GetSplitList()
        }
        assert got == {
            COMMUN: (-11000, -11000, "", "n"),
            COMPAGNE: (5500, 5500, "part compagne", "n"),
            COURSES: (5500, 5500, "", "n"),
        }
    # GnuCash garde l'ancienne version du fichier en sauvegarde horodatée.
    assert list(book_path.parent.glob("test.gnucash.*.gnucash"))


def test_nothing_written_without_save(book_path):
    before = book_path.read_bytes()
    with open_book(book_path) as ledger:
        commun = ledger.account_by_name(COMMUN)
        tpl = ledger.template(ledger.find_template(commun, "Cinéma"), commun)
        ledger.create_transaction(tpl.currency, datetime.date(2026, 10, 21), "Cinéma", tpl.lines)
    assert book_path.read_bytes() == before


def test_unbalanced_and_foreign_lines_rejected(book_path):
    with open_book(book_path) as ledger:
        commun = ledger.account_by_name(COMMUN)
        tpl = ledger.template(ledger.find_template(commun, "Cinéma"), commun)
        day = datetime.date(2026, 10, 21)
        with pytest.raises(BookError, match="déséquilibrée"):
            ledger.create_transaction(tpl.currency, day, "x", [tpl.lines[0], tpl.lines[1].with_value(1)])
        dollars = ledger.account_by_name(DOLLARS)
        with pytest.raises(UnsupportedTransaction):
            ledger.create_transaction(tpl.currency, day, "x", [tpl.lines[0], tpl.lines[1].with_account(dollars)])


def test_locked_book_is_refused(book_path):
    with open_book(book_path):
        with pytest.raises(BookLockedError, match="GnuCash"):
            with open_book(book_path):
                pass
        # La lecture seule reste possible, sans toucher au verrou.
        with open_book(book_path, readonly=True) as ro:
            assert ro.account_by_name(LOISIRS) is not None


def test_readonly_cannot_save(book_path):
    with open_book(book_path, readonly=True) as ledger:
        with pytest.raises(BookError):
            ledger.save()


def test_missing_book(tmp_path):
    with pytest.raises(BookError, match="introuvable"):
        with open_book(tmp_path / "absent.gnucash"):
            pass
