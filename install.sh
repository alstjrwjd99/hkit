#!/usr/bin/env bash
# Safe non-overwriting install into an existing task workspace. No network, git, or external writes.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
TARGET="${1:-.}"
if [ ! -d "$TARGET" ]; then
  echo "Target directory does not exist: $TARGET" >&2
  exit 2
fi
TARGET="$(cd "$TARGET" && pwd -P)"
if [ "$ROOT" = "$TARGET" ]; then
  echo "Run against a separate task workspace, not the kit's own directory." >&2
  exit 2
fi
copy_if_missing() {
  local src="$1" dest="$2"
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    echo "KEEP   $dest (already exists)"
    return 0
  fi
  local parent="${dest%/*}"
  while [ "$parent" != "$TARGET" ]; do
    if [ -L "$parent" ]; then
      echo "SKIP   $dest (linked parent: $parent)"
      return 0
    fi
    parent="${parent%/*}"
  done
  mkdir -p "${dest%/*}"
  cp -R "$src" "$dest"
  echo "CREATE $dest"
}
install_working_contract() {
  local src="$ROOT/AGENTS.md"
  local primary="$TARGET/AGENTS.md"
  local fallback="$TARGET/HYNIX_KIT_GUIDE.md"

  if [ ! -e "$primary" ] && [ ! -L "$primary" ]; then
    copy_if_missing "$src" "$primary"
  elif [ -f "$primary" ] && cmp -s "$src" "$primary"; then
    echo "KEEP   $primary (kit contract already installed)"
  else
    echo "KEEP   $primary (existing project instructions)"
    copy_if_missing "$src" "$fallback"
  fi
}
install_working_contract
copy_if_missing "$ROOT/templates/SPEC.md" "$TARGET/SPEC.md"
copy_if_missing "$ROOT/templates/EVIDENCE.md" "$TARGET/EVIDENCE.md"
for doc in "$ROOT"/templates/docs/*.md; do
  copy_if_missing "$doc" "$TARGET/docs/$(basename "$doc")"
done
for d in "$ROOT"/.agents/skills/*; do
  [ -d "$d" ] || continue
  name="$(basename "$d")"
  copy_if_missing "$d" "$TARGET/.agents/skills/$name"
done
for agent in "$ROOT"/.codex/agents/*.toml; do
  copy_if_missing "$agent" "$TARGET/.codex/agents/$(basename "$agent")"
done
cat <<'MSG'

Installation complete. Existing files were preserved.
- Review existing project instructions before using the new kit.
- If HYNIX_KIT_GUIDE.md was created, ask Codex to read it after AGENTS.md as a secondary reference; never override official rules.
- Run `codex` from the actual task root, check /status and /skills if supported.
- Do not git push, modify platform protections, or use AI during the follow-up written phase.
MSG
