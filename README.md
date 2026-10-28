# Cassius Repo

Kodi-Repository für [Aura-Deck](https://github.com/CasX61/Aura-Deck--Navidrome-Client-for-Kodi).

## Installation in Kodi

1. *Einstellungen → System → Add-ons*: „Unbekannte Quellen“ erlauben.
2. *Einstellungen → Dateimanager → Quelle hinzufügen*: `https://casx61.github.io/Cassius-Repo/`
   eintragen, Name z. B. `cassius`.
3. *Einstellungen → Add-ons → Aus ZIP-Datei installieren → cassius →*
   `repository.cassius-….zip`.
4. *Aus Repository installieren → Cassius Repo → Musik-Add-ons → Aura-Deck*.

Updates kommen danach automatisch.

## Neue Version veröffentlichen

```
cd ../aura-deck            # Version in script.auradeck/addon.xml erhöhen
python3 tools/build.py     # baut dist/script.auradeck-<version>.zip
cd ../Cassius-Repo
./publish.sh               # übernimmt die neueste ZIP, generiert, pusht
```

Ohne höhere Versionsnummer passiert nichts: Der Generator baut nur neue Versionen,
und Kodi aktualisiert nur auf höhere Versionen.
