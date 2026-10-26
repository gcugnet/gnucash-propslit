from prompt_toolkit.document import Document

from propsplit.completion import FuzzyChoices, matches, resolve

ACCOUNTS = ["Actif:Compte commun", "Dépenses:Courses", "Dépenses:Loisirs", "Passif:Compagne"]


def test_matches_words_without_accents():
    assert matches(ACCOUNTS, "dep cour") == ["Dépenses:Courses"]
    assert matches(ACCOUNTS, "COMP") == ["Actif:Compte commun", "Passif:Compagne"]
    assert matches(ACCOUNTS, "") == ACCOUNTS


def test_resolve():
    assert resolve(ACCOUNTS, "Dépenses:Loisirs") == "Dépenses:Loisirs"
    assert resolve(ACCOUNTS, "loisirs") == "Dépenses:Loisirs"
    assert resolve(ACCOUNTS, "comp") is None
    assert resolve(ACCOUNTS, "inconnu") is None


def test_resolve_prefers_exact_name_among_several():
    choices = ["Courses", "Courses bio"]
    assert resolve(choices, "courses") == "Courses"


def test_completer_replaces_whole_input():
    completions = list(FuzzyChoices(ACCOUNTS).get_completions(Document("dép lo"), None))
    assert [c.text for c in completions] == ["Dépenses:Loisirs"]
    assert completions[0].start_position == -len("dép lo")
