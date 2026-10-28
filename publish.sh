#!/bin/bash
# Übernimmt die neueste fertige ZIP jedes Add-ons und generiert das Kodi-Repo.
# Committen und pushen machst du danach selbst.
#
# Aus den Quellordnern wird nur gelesen. Vorher dort wie gewohnt die ZIP bauen.
set -euo pipefail

cd "$(dirname "$0")"
REPO_ADDON="repository.cassius"

# Add-ons im Repo: "<addon-id>  <Ordner mit den fertigen ZIPs>"
# Neues Add-on = neue Zeile.
ADDONS=(
    "script.auradeck  ../aura-deck/dist"
)

for entry in "${ADDONS[@]}"; do
    read -r ID DIST <<< "$entry"
    # Neueste ZIP nach Versionsnummer wählen (1.0.10 > 1.0.9)
    ZIP=$(ls "$DIST"/"$ID"-*.zip 2>/dev/null | sort -V | tail -n 1 || true)
    if [ -z "$ZIP" ]; then
        echo "Keine ZIP für $ID in $DIST gefunden, übersprungen." >&2
        continue
    fi
    echo "Übernehme: $ZIP"
    # Die ZIP enthält den Ordner <addon-id>/
    rm -rf "repo/$ID"
    unzip -q "$ZIP" -d repo/
done

# Original-Generator: neue Versionen packen, addons.xml + md5 schreiben
python3 _repo_generator.py

# Installations-ZIP des Repos in den Root legen (für die Dateimanager-Quelle)
REPO_VERSION=$(sed -n 's/.*<addon[^>]* version="\([^"]*\)".*/\1/p' "repo/$REPO_ADDON/addon.xml" | head -n 1)
REPO_ZIP="$REPO_ADDON-$REPO_VERSION.zip"
if [ ! -f "$REPO_ZIP" ]; then
    rm -f "$REPO_ADDON"-*.zip
    cp "repo/zips/$REPO_ADDON/$REPO_ZIP" .
    printf '<!DOCTYPE html>\n<a href="%s">%s</a>\n' "$REPO_ZIP" "$REPO_ZIP" > index.html
fi

echo
git status --short
