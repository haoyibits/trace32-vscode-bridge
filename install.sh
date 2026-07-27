#!/usr/bin/env bash
# Copy the VS Code task/launch templates into the project that hosts this
# toolkit. Existing files are backed up, never silently replaced.

set -euo pipefail

TOOLKIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROJECT_ROOT=".."
# shellcheck source=/dev/null
source "$TOOLKIT_DIR/config.env"

case "$PROJECT_ROOT" in
    /*) PROJECT_DIR="$(cd "$PROJECT_ROOT" && pwd)" ;;
    *)  PROJECT_DIR="$(cd "$TOOLKIT_DIR/$PROJECT_ROOT" && pwd)" ;;
esac

TARGET_DIR="$PROJECT_DIR/.vscode"

mkdir -p "$TARGET_DIR"

for name in tasks.json launch.json; do
    target="$TARGET_DIR/$name"
    if [[ -f $target ]]; then
        backup="$target.bak.$(date +%Y%m%d%H%M%S)"
        cp "$target" "$backup"
        echo "backed up $target -> $backup"
    fi
    cp "$TOOLKIT_DIR/vscode/$name" "$target"
    echo "installed $target"
done

echo
echo "Done. Open $PROJECT_DIR in VS Code and run 'T32: Build + Flash + Debug'."
