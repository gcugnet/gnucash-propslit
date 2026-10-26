"""Recherche floue sur des libellés et des noms de comptes.

Chaque mot saisi doit apparaître dans le choix, sans tenir compte de la casse
ni des accents : « dep cour » trouve « Dépenses:Courses ».
"""

import unicodedata

from prompt_toolkit.completion import Completer, Completion


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def matches(choices: list[str], text: str) -> list[str]:
    """Choix contenant tous les mots saisis, dans l'ordre d'origine."""
    words = _fold(text).split()
    return [c for c in choices if all(w in _fold(c) for w in words)]


def resolve(choices: list[str], text: str) -> str | None:
    """Choix désigné sans ambiguïté par la saisie, sinon None."""
    if text in choices:
        return text
    found = matches(choices, text)
    if len(found) == 1:
        return found[0]
    folded = [c for c in found if _fold(c) == _fold(text)]
    return folded[0] if len(folded) == 1 else None


class FuzzyChoices(Completer):
    def __init__(self, choices: list[str], limit: int = 50):
        self.choices = choices
        self.limit = limit

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        for choice in matches(self.choices, text)[: self.limit]:
            yield Completion(choice, start_position=-len(text))
