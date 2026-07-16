# Release Strategy

## Smysl dokumentu

Tento dokument popisuje release etapy produktu a co od nich cekame.

---

## Faze releasu

### Development

- aktivni vyvoj
- caste rozbite casti jsou jeste prijatelne
- fokus na rozhodnuti a implementaci zakladu

### Internal

- tym pouziva aplikaci sam
- overuje architekturu, data a workflow

### Alpha

- velmi omezena skupina uzivatelu
- vysoka tolerance k chybam
- cilem je odhalit nejvetsi produktove a datove mezery

### Private Beta

- prvni realni uzivatele mimo vyvoj
- fokus na stabilitu, auth boundary a support

### Public Beta

- sirsi pristup
- stale jeste ne finalni slib produktu
- monitoring a release disciplina musi byt silnejsi

### Production

- produkt je jasne podporovany
- scope je explicitni
- kriticke workflow musi byt spolehlive

---

## Release pravidla

- dalsi release faze nesmi zacit na neuzavrenem predchozim zakladu
- produktova duvera ma prednost pred tempem releasu
- pokud data nejsou duveryhodna, release se neposouva dal
