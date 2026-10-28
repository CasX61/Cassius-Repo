# Cassius Repo

Kodi-Repository für die Add-ons von CasX61.

## Enthaltene Add-ons

| Add-on | Beschreibung |
|---|---|
| [Aura-Deck](https://github.com/CasX61/Aura-Deck--Navidrome-Client-for-Kodi) | Moderner Navidrome-Client für Kodi |

## Installation in Kodi

1. *Einstellungen → System → Add-ons*: „Unbekannte Quellen“ erlauben.
2. *Einstellungen → Dateimanager → Quelle hinzufügen*: `https://casx61.github.io/Cassius-Repo/`
   eintragen, Name z. B. `cassius`.
3. *Einstellungen → Add-ons → Aus ZIP-Datei installieren → cassius →*
   `repository.cassius-….zip`.
4. *Aus Repository installieren → Cassius Repo* und das gewünschte Add-on wählen.

Updates kommen danach automatisch.

## Neue Version veröffentlichen

1. Im Add-on die Version in `addon.xml` erhöhen und die ZIP bauen.
2. Hier `./publish.sh` ausführen: übernimmt die neueste ZIP jedes Add-ons und generiert
   `repo/zips/`, `addons.xml` und `addons.xml.md5`.
3. Selbst committen und pushen.

Ohne höhere Versionsnummer passiert nichts: Der Generator baut nur neue Versionen,
und Kodi aktualisiert nur auf höhere Versionen.

## Neues Add-on aufnehmen

In `publish.sh` unter `ADDONS` eine Zeile ergänzen:

```
"<addon-id>  <Ordner mit den fertigen ZIPs>"
```

Die ZIP muss `<addon-id>-<version>.zip` heißen und oben den Ordner `<addon-id>/` enthalten.
