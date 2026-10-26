"""Arithmétique des répartitions, sans dépendance à GnuCash.

Tous les montants sont des entiers exprimés dans la plus petite unité de la
devise (la « SCU » de GnuCash : 100 pour l'euro). Une transaction est une liste
de valeurs signées dont la somme vaut 0 ; l'« ancrage » est la répartition du
compte dans lequel on saisit (le compte commun), les autres sont ses
contreparties.
"""

from decimal import Decimal, InvalidOperation
from fractions import Fraction


def _apportion(exact: list[Fraction], anchor: int) -> list[int]:
    """Arrondit les contreparties au centime sans casser l'équilibre.

    Méthode du plus fort reste : chaque montant est tronqué, puis les centimes
    manquants vont aux contreparties qui ont perdu le plus à la troncature. En
    cas d'égalité, c'est la première qui prend le centime, pour que le résultat
    ne dépende que de l'ordre des répartitions.
    """
    result = [int(x) for x in exact]  # int() tronque vers zéro
    remainder = -sum(result)
    step = 1 if remainder > 0 else -1
    others = sorted(
        (i for i in range(len(exact)) if i != anchor),
        key=lambda i: (-(exact[i] - result[i]) * step, i),
    )
    # Chaque troncature perd moins d'un centime : il y a toujours assez de candidats.
    assert abs(remainder) <= len(others)
    for i in others[: abs(remainder)]:
        result[i] += step
    return result


def _check(values: list[int], anchor: int) -> None:
    if len(values) < 2:
        raise ValueError("une transaction répartie a au moins deux répartitions")
    if not 0 <= anchor < len(values):
        raise ValueError("ancrage hors de la transaction")
    if sum(values) != 0:
        raise ValueError("la transaction modèle n'est pas équilibrée")
    if values[anchor] == 0:
        raise ValueError("le montant du compte de saisie est nul : pas de proportion possible")


def scale(values: list[int], anchor: int, new_anchor: int) -> list[int]:
    """Met la transaction à l'échelle d'un nouveau montant d'ancrage.

    Chaque contrepartie garde sa part relative : 90 réparti en 45/45 devient
    55/55 pour 110.
    """
    _check(values, anchor)
    factor = Fraction(new_anchor, values[anchor])
    exact = [v * factor for v in values]
    exact[anchor] = Fraction(new_anchor)
    return _apportion(exact, anchor)


def shares(values: list[int], anchor: int) -> list[Fraction]:
    """Part de chaque répartition, rapportée au montant d'ancrage.

    Les contreparties d'une dépense ordinaire ont des parts positives dont la
    somme vaut 1 ; l'ancrage vaut toujours -1.
    """
    _check(values, anchor)
    return [Fraction(-v, values[anchor]) for v in values]


def from_shares(anchor_value: int, counterpart_shares: list[Fraction]) -> list[int]:
    """Construit une transaction à partir des parts de ses contreparties.

    Renvoie `[ancrage, contrepartie1, contrepartie2, ...]`. Les parts doivent
    totaliser 1.
    """
    if not counterpart_shares:
        raise ValueError("il faut au moins une contrepartie")
    if sum(counterpart_shares) != 1:
        raise ValueError("les parts des contreparties doivent totaliser 100 %")
    if anchor_value == 0:
        raise ValueError("le montant doit être non nul")
    exact = [Fraction(anchor_value)] + [-anchor_value * s for s in counterpart_shares]
    return _apportion(exact, 0)


def parse_amount(text: str, scu: int) -> int:
    """Lit un montant saisi (« 110 », « 12,5 », « 1 234.56 ») en unités de la devise."""
    cleaned = text.strip().replace(" ", "").replace("\xa0", "").replace(" ", "")
    cleaned = cleaned.replace(",", ".")
    try:
        amount = Fraction(Decimal(cleaned)) * scu
    except (InvalidOperation, ValueError):
        raise ValueError(f"montant illisible : {text!r}") from None
    if amount.denominator != 1:
        raise ValueError(f"trop de décimales pour cette devise : {text!r}")
    return int(amount)


def parse_percent(text: str) -> Fraction:
    """Lit un pourcentage saisi (« 50 », « 33,33 », « 12.5 % ») en fraction."""
    cleaned = text.strip().rstrip("%").strip().replace(",", ".")
    try:
        return Fraction(Decimal(cleaned)) / 100
    except (InvalidOperation, ValueError):
        raise ValueError(f"pourcentage illisible : {text!r}") from None


def format_amount(value: int, scu: int) -> str:
    """Affiche un montant à la française : -1 234,50."""
    digits = len(str(scu)) - 1 if scu > 1 else 0
    units, cents = divmod(abs(value), scu)
    text = f"{units:,}".replace(",", " ")
    if digits:
        text += "," + str(cents).rjust(digits, "0")
    return ("-" if value < 0 else "") + text


def format_percent(share: Fraction) -> str:
    """Affiche une part en pourcentage, avec deux décimales au plus : 33,33 %."""
    text = f"{float(share * 100):.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") + " %"
