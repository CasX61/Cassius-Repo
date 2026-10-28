#!/bin/bash
# Veröffentlicht die neueste fertige Aura-Deck-ZIP im Kodi-Repo.
#
#   ./publish.sh            ZIP übernehmen, Repo generieren, committen, pushen
#   ./publish.sh --no-push  wie oben, aber ohne push
#
# Aus aura-deck wird nur gelesen (dist/*.zip). Vorher dort wie gewohnt bauen:
#   python3 tools/build.py
set -euo pipefail

cd "$(dirname "$0")"
DIST="../aura-deck/dist"
ADDON="script.auradeck"
REPO_ADDON="repository.cassius"

# 1. Neueste ZIP nach Versionsnummer wählen (1.0.10 > 1.0.9)
ZIP=$(ls "$DIST"/$ADDON-*.zip 2>/dev/null | sort -V | tail -n 1 || true)
if [ -z "$ZIP" ]; then
    echo "Keine ZIP in $DIST gefunden. Erst in aura-deck: python3 tools/build.py" >&2
    exit 1
fi
echo "Übernehme: $ZIP"

# 2. Entpacken (die ZIP enthält den Ordner script.auradeck/)
rm -rf "repo/$ADDON"
unzip -q "$ZIP" -d repo/

# 3. Original-Generator: neue Versionen packen, addons.xml + md5 schreiben
python3 _repo_generator.py

# 4. Installations-ZIP des Repos in den Root legen (für die Dateimanager-Quelle)
REPO_VERSION=$(sed -n 's/.*<addon[^>]* version="\([^"]*\)".*/\1/p' "repo/$REPO_ADDON/addon.xml" | head -n 1)
REPO_ZIP="$REPO_ADDON-$REPO_VERSION.zip"
if [ ! -f "$REPO_ZIP" ]; then
    rm -f "$REPO_ADDON"-*.zip
    cp "repo/zips/$REPO_ADDON/$REPO_ZIP" .
    printf '<!DOCTYPE html>\n<a href="%s">%s</a>\n' "$REPO_ZIP" "$REPO_ZIP" > index.html
fi

# 5. Committen und pushen
git add -A
if git diff --cached --quiet; then
    echo "Nichts Neues. Version in addon.xml erhöht und neu gebaut?"
    exit 0
fi
VERSION=$(basename "$ZIP" .zip); VERSION=${VERSION#$ADDON-}
git commit -q -m "Aura-Deck $VERSION"
echo "Commit: Aura-Deck $VERSION"
if [ "${1:-}" != "--no-push" ]; then
    git push -q origin main
    echo "Gepusht. Kodi sieht das Update nach einigen Minuten."
fi
