# gnc-propsplit

Saisie de transactions GnuCash en ligne de commande, avec une auto-complétion
qui retient **la répartition en pourcentage** d'une ancienne transaction plutôt
que ses montants.

Dans GnuCash, retaper un libellé connu recopie l'ancienne transaction, montants
compris. Si « Carrefour » valait 90 € réparti 45/45 entre `Passif:Compagne` et
`Dépenses:Courses`, saisir 110 € oblige à corriger chaque répartition à la
main. Avec gnc-propsplit, sur un compte où l'option est activée, on tape 110 et
la transaction devient 55/55.

C'est le prototype d'une fonctionnalité qui pourrait être proposée à GnuCash :
une option par compte, réglée dans « Modifier le compte ».

## Installation

Le module Python `gnucash` vient de GnuCash lui-même (il n'est pas sur PyPI) et
doit avoir été compilé pour la même version de Python. Le flake s'en charge :

```sh
nix build                 # ./result/bin/gnc-propsplit
nix develop -c pytest     # tests
```

## Utilisation

```sh
gnc-propsplit config init                     # livre, compte de saisie, option %
gnc-propsplit config show
gnc-propsplit account enable "Compte commun"  # recherche floue sur le nom
gnc-propsplit account disable "Compte commun"
gnc-propsplit add [--account NOM] [--dry-run]
```

`add` enchaîne les saisies : date, libellé (complété à partir de l'historique du
compte), montant, puis un récapitulatif où l'on peut :

| Touche   | Effet                                                                  |
|----------|------------------------------------------------------------------------|
| Entrée   | valider la transaction                                                 |
| `1`…`n`  | changer le compte d'une contrepartie, sans toucher aux parts           |
| `m`      | changer le montant (recalcul au prorata)                               |
| `r`      | saisir une autre répartition, en pourcentages                          |
| `a`      | abandonner cette transaction                                           |

Ctrl-C annule la saisie en cours, Ctrl-D termine la boucle. Rien n'est écrit
avant la confirmation finale ; GnuCash garde alors l'ancienne version du livre
en sauvegarde horodatée.

Montants : sans signe, le montant suit le sens du modèle (une sortie pour un
libellé nouveau) ; `+` force une entrée d'argent, `-` une sortie.

### Règles de complétion

- **Libellé connu** : modèle = la dernière transaction du compte qui porte ce
  libellé (la même recherche que le registre de GnuCash).
  - Compte en mode proportionnel : le nouveau montant est réparti au prorata.
  - Sinon : montants recopiés tels quels, comme dans GnuCash. Une transaction à
    deux répartitions suit quand même le nouveau montant.
- **Libellé nouveau** : on reprend les parts de la dernière transaction du
  compte et on confirme chaque compte (pratique pour un 50/50 où seul le compte
  de dépense change), ou l'on saisit une répartition libre.
- **Centimes** : méthode du plus fort reste ; en cas d'égalité, la première
  contrepartie prend le centime (10,01 € en 50/50 → 5,01 / 5,00).

## Sécurité du livre

- Le livre est ouvert en respectant le verrou de GnuCash : s'il est ouvert dans
  l'interface, gnc-propsplit refuse d'écrire. Fermez GnuCash avant `add`.
- `config` et `account` ouvrent le livre en lecture seule.
- Limite : les transactions qui touchent un compte dans une autre devise ou
  commodité (titres, multidevise) sont refusées et restent à saisir dans GnuCash.

## Configuration

`~/.config/gnc-propsplit/config.toml`, ou le fichier désigné par `--config` ou
`$GNC_PROPSPLIT_CONFIG`. Les comptes y sont identifiés par leur GUID, ce qui
résiste aux renommages :

```toml
book = "/chemin/vers/livre.gnucash"
default_account = "0123456789abcdef0123456789abcdef"

[accounts.0123456789abcdef0123456789abcdef]
name = "Actif:Compte commun"
proportional = true
```

Les bindings Python n'exposent pas les slots KVP des comptes ; dans la version
intégrée à GnuCash, l'option vivrait dans le compte lui-même.
