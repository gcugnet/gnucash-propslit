"""Scénarios de bout en bout : frappes clavier simulées sur un livre jetable."""

import datetime

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from propsplit import config
from propsplit.book import guid_of, open_book
from propsplit.cli import main, parse_date
from sample_book import COMMUN, COMPAGNE, COURSES, LOISIRS, make_book

ENTER = "\r"
EOF = "\x04"
TODAY = datetime.date.today()


@pytest.fixture
def book_path(tmp_path):
    return make_book(tmp_path / "test.gnucash")


@pytest.fixture
def configured(book_path, isolated_config):
    def setup(proportional=True):
        with open_book(book_path, readonly=True) as ledger:
            guid = guid_of(ledger.account_by_name(COMMUN))
        cfg = config.load(isolated_config)
        cfg.book = str(book_path)
        cfg.default_account = guid
        cfg.set_proportional(guid, COMMUN, proportional)
        cfg.save()
        return book_path

    return setup


def run(argv, *keys):
    with create_pipe_input() as inp:
        inp.send_text("".join(keys))
        with create_app_session(input=inp, output=DummyOutput()):
            return main(argv)


def splits_of(book_path, description, date=TODAY):
    with open_book(book_path, readonly=True) as ledger:
        trans = ledger.find_template(ledger.account_by_name(COMMUN), description)
        assert trans is not None and trans.GetDate().date() == date
        assert trans.GetImbalanceValue().zero_p()
        return {s.GetAccount().get_full_name(): s.GetValue().num() for s in trans.GetSplitList()}


def test_proportional_autocomplete(configured):
    book = configured()
    code = run(["add"],
               ENTER, "Carrefour" + ENTER, "110" + ENTER, ENTER,  # date du jour, libellé, total, valider
               EOF, "o" + ENTER)
    assert code == 0
    assert splits_of(book, "Carrefour") == {COMMUN: -11000, COMPAGNE: 5500, COURSES: 5500}


def test_change_counterpart_account_keeps_shares(configured):
    book = configured()
    run(["add"],
        ENTER, "Carrefour" + ENTER, "50,01" + ENTER,
        "2" + ENTER, "loisirs" + ENTER, ENTER,  # contrepartie 2 (Courses) → Loisirs
        EOF, "o" + ENTER)
    assert splits_of(book, "Carrefour") == {COMMUN: -5001, COMPAGNE: 2501, LOISIRS: 2500}


def test_new_description_reuses_last_split_pattern(configured):
    book = configured()
    run(["add"],
        ENTER, "Carrefour" + ENTER, "110" + ENTER, ENTER,
        # Libellé nouveau : on reprend 50/50 de la saisie précédente,
        # en gardant la compagne et en changeant le compte de dépense.
        ENTER, "Boulangerie" + ENTER, "12,40" + ENTER, ENTER, "loisirs" + ENTER, ENTER,
        EOF, "o" + ENTER)
    assert splits_of(book, "Boulangerie") == {COMMUN: -1240, COMPAGNE: 620, LOISIRS: 620}


def test_new_description_free_shares(configured):
    book = configured()
    run(["add"],
        "15/10/2026" + ENTER, "Pharmacie" + ENTER, "30" + ENTER,
        # La dernière transaction exploitable est « Cinéma » (100 % Loisirs) ;
        # on passe en répartition libre : 25 % compagne, le reste en courses.
        ENTER, "r" + ENTER, "compagne" + ENTER, "25" + ENTER, "courses" + ENTER, ENTER, ENTER,
        EOF, "o" + ENTER)
    assert splits_of(book, "Pharmacie", datetime.date(2026, 10, 15)) == {
        COMMUN: -3000, COMPAGNE: 750, COURSES: 2250}


def test_absolute_mode_copies_amounts(configured):
    book = configured(proportional=False)
    run(["add"],
        ENTER, "Carrefour" + ENTER, "m" + ENTER, ENTER,  # « m » est refusé en montants absolus
        EOF, "o" + ENTER)
    assert splits_of(book, "Carrefour") == {COMMUN: -9000, COMPAGNE: 4500, COURSES: 4500}


def test_two_splits_scale_even_in_absolute_mode(configured):
    book = configured(proportional=False)
    run(["add"], ENTER, "Cinéma" + ENTER, "23,50" + ENTER, ENTER, EOF, "o" + ENTER)
    assert splits_of(book, "Cinéma") == {COMMUN: -2350, LOISIRS: 2350}


def test_refusing_save_leaves_book_untouched(configured):
    book = configured()
    before = book.read_bytes()
    assert run(["add"], ENTER, "Carrefour" + ENTER, "110" + ENTER, ENTER, EOF, ENTER) == 0
    assert book.read_bytes() == before


def test_dry_run_never_asks_nor_saves(configured):
    book = configured()
    before = book.read_bytes()
    assert run(["add", "--dry-run"], ENTER, "Carrefour" + ENTER, "110" + ENTER, ENTER, EOF) == 0
    assert book.read_bytes() == before


def test_cancelled_entry_is_dropped(configured):
    book = configured()
    run(["add"],
        ENTER, "Carrefour" + ENTER, "110" + ENTER, "a" + ENTER,  # abandon
        ENTER, "Cinéma" + ENTER, "8" + ENTER, ENTER,
        EOF, "o" + ENTER)
    assert splits_of(book, "Carrefour", datetime.date(2026, 10, 5))[COMMUN] == -9000
    assert splits_of(book, "Cinéma")[COMMUN] == -800


def test_locked_book(configured, capsys):
    book = configured()
    with open_book(book):
        assert run(["add"]) == 1
    assert "verrouillé" in capsys.readouterr().err


def test_account_enable_disable(configured, isolated_config):
    configured(proportional=False)
    assert run(["account", "enable", "compte commun"]) == 0
    cfg = config.load(isolated_config)
    assert cfg.is_proportional(cfg.default_account)
    assert run(["account", "disable", "compte commun"]) == 0
    assert not config.load(isolated_config).is_proportional(cfg.default_account)


def test_config_init(book_path, isolated_config):
    assert run(["config", "init"], str(book_path) + ENTER, "commun" + ENTER, ENTER) == 0
    cfg = config.load(isolated_config)
    assert cfg.book == str(book_path)
    assert cfg.accounts[cfg.default_account].name == COMMUN
    assert cfg.is_proportional(cfg.default_account)


def test_missing_config(capsys):
    assert run(["add"]) == 1
    assert "config init" in capsys.readouterr().err


@pytest.mark.parametrize(
    "text, expected",
    [("3", datetime.date(2026, 10, 3)), ("3/9", datetime.date(2026, 9, 3)),
     ("03/09/25", datetime.date(2025, 9, 3)), ("2024-02-29", datetime.date(2024, 2, 29))],
)
def test_parse_date(text, expected):
    assert parse_date(text, datetime.date(2026, 10, 26)) == expected


def test_parse_date_rejects():
    with pytest.raises(ValueError):
        parse_date("31/02", datetime.date(2026, 10, 26))
