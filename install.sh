#!/usr/bin/env bash
# Merge the VS Code task/launch templates into the project that hosts this
# toolkit. Existing files are backed up and non-TRACE32 entries are retained.

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
NODE_BIN="${T32_NODE:-node}"

mkdir -p "$TARGET_DIR"

for spec in "tasks:tasks.json" "launch:launch.json"; do
    kind="${spec%%:*}"
    name="${spec#*:}"
    target="$TARGET_DIR/$name"
    if [[ -f $target ]]; then
        backup="$target.bak.$(date +%Y%m%d%H%M%S)"
        suffix=0
        while [[ -e $backup ]]; do
            suffix=$((suffix + 1))
            backup="$target.bak.$(date +%Y%m%d%H%M%S).$suffix"
        done
        cp "$target" "$backup"
        echo "backed up $target -> $backup"
        "$NODE_BIN" "$TOOLKIT_DIR/scripts/merge_vscode_json.js" \
            "$kind" "$TOOLKIT_DIR/vscode/$name" "$target"
        echo "merged $target"
    else
        cp "$TOOLKIT_DIR/vscode/$name" "$target"
        echo "installed $target"
    fi
done

echo
echo "Done. Flash/Load/RTT are visible tasks; 'TRACE32: Attach' starts the hidden adapter."
