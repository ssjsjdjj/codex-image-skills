#!/bin/bash

set -euo pipefail

fail() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 1
}

verify_only=0
if [ "${1:-}" = "--verify-only" ]; then
    verify_only=1
    shift
fi
if [ "$#" -ne 0 ]; then
    fail "Unknown argument. Supported option: --verify-only"
fi

package_root="$(cd "$(dirname "$0")" && pwd -P)"
source_sessions="$package_root/native/sessions"
source_index="$package_root/native/session_index.jsonl"
hash_list="$package_root/SHA256SUMS.txt"
codex_home="${CODEX_HOME:-$HOME/.codex}"

[ -d "$source_sessions" ] || fail "native/sessions was not found. Run this script from the extracted migration-package folder."
[ -f "$hash_list" ] || fail "SHA256SUMS.txt was not found. Run this script from the extracted migration-package folder."
command -v shasum >/dev/null 2>&1 || fail "The macOS shasum command is unavailable."

printf 'Verifying the migration package...\n'
verified=0
while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in
        [0-9a-fA-F][0-9a-fA-F]*) ;;
        *) continue ;;
    esac
    [ "${#line}" -ge 67 ] || continue
    expected="${line:0:64}"
    separator="${line:64:2}"
    [ "$separator" = "  " ] || continue
    relative="${line:66}"
    file_path="$package_root/$relative"
    [ -f "$file_path" ] || fail "Package file is missing: $relative"
    actual="$(shasum -a 256 "$file_path" | awk '{print $1}')"
    expected_lower="$(printf '%s' "$expected" | tr '[:upper:]' '[:lower:]')"
    if [ "$actual" != "$expected_lower" ]; then
        fail "SHA-256 mismatch: $relative"
    fi
    verified=$((verified + 1))
done < "$hash_list"

package_session_count="$(find "$source_sessions" -type f -name '*.jsonl' | wc -l | tr -d '[:space:]')"
[ "$package_session_count" -gt 0 ] || fail "No session JSONL files were found in the package."

if [ "$verify_only" -eq 1 ]; then
    printf 'Package verification complete: %s files verified, %s sessions found.\n' "$verified" "$package_session_count"
    exit 0
fi

if [ "$(id -u)" -eq 0 ]; then
    fail "Do not run this migration with sudo or as root."
fi

case "$codex_home" in
    /*) ;;
    *) fail "CODEX_HOME must be an absolute path." ;;
esac
if [ "$codex_home" = "/" ] || [ "$codex_home" = "$HOME" ]; then
    fail "Refusing to use an unsafe CODEX_HOME target: $codex_home"
fi

if pgrep -f '[C]odex.app' >/dev/null 2>&1; then
    fail "Quit Codex completely with Command-Q before restoring chats."
fi

mkdir -p "$codex_home"
target_sessions="$codex_home/sessions"
mkdir -p "$target_sessions"
pre_migration_count="$(find "$target_sessions" -type f -name '*.jsonl' | wc -l | tr -d '[:space:]')"

documents="$HOME/Documents"
mkdir -p "$documents"
stamp="$(date '+%Y%m%d_%H%M%S')"
backup_root="$documents/CodexMigrationBackup_$stamp"
suffix=2
while [ -e "$backup_root" ]; do
    backup_root="$documents/CodexMigrationBackup_${stamp}_$suffix"
    suffix=$((suffix + 1))
done
mkdir -p "$backup_root"

printf 'Target: %s\n' "$codex_home"
printf 'Pre-migration backup: %s\n' "$backup_root"

copied=0
replaced=0
unchanged=0
while IFS= read -r -d '' source_file; do
    relative="${source_file#"$source_sessions"/}"
    target_file="$target_sessions/$relative"
    target_directory="$(dirname "$target_file")"
    mkdir -p "$target_directory"

    if [ -f "$target_file" ]; then
        source_hash="$(shasum -a 256 "$source_file" | awk '{print $1}')"
        target_hash="$(shasum -a 256 "$target_file" | awk '{print $1}')"
        if [ "$source_hash" = "$target_hash" ]; then
            unchanged=$((unchanged + 1))
            continue
        fi
        conflict_backup="$backup_root/conflicting_sessions/$relative"
        mkdir -p "$(dirname "$conflict_backup")"
        cp -p "$target_file" "$conflict_backup"
        cp -p "$source_file" "$target_file"
        replaced=$((replaced + 1))
    else
        cp -p "$source_file" "$target_file"
        copied=$((copied + 1))
    fi
done < <(find "$source_sessions" -type f -name '*.jsonl' -print0)

if [ -f "$source_index" ]; then
    target_index="$codex_home/session_index.jsonl"
    temporary_index="$codex_home/.session_index.migration.$$"
    trap 'rm -f "$temporary_index"' EXIT
    if [ -f "$target_index" ]; then
        cp -p "$target_index" "$backup_root/session_index.jsonl"
        { cat "$target_index"; cat "$source_index"; } | awk '!seen[$0]++' > "$temporary_index"
    else
        awk '!seen[$0]++' "$source_index" > "$temporary_index"
    fi
    mv "$temporary_index" "$target_index"
    trap - EXIT
fi

for name in \
    state_5.sqlite state_5.sqlite-shm state_5.sqlite-wal \
    thread_history_1.sqlite thread_history_1.sqlite-shm thread_history_1.sqlite-wal
do
    source_file="$codex_home/$name"
    if [ -f "$source_file" ]; then
        mv "$source_file" "$backup_root/$name"
    fi
done

post_migration_count="$(find "$target_sessions" -type f -name '*.jsonl' | wc -l | tr -d '[:space:]')"
cat > "$backup_root/migration-result.txt" <<EOF
PackageSessions=$package_session_count
PreMigrationSessions=$pre_migration_count
Added=$copied
Replaced=$replaced
Unchanged=$unchanged
PostMigrationSessions=$post_migration_count
Target=$codex_home
Backup=$backup_root
EOF

printf '\nMigration complete: added %s sessions, replaced %s conflicts, and kept %s identical sessions.\n' "$copied" "$replaced" "$unchanged"
printf 'The target sessions directory now contains %s JSONL files.\n' "$post_migration_count"
printf 'Start Codex now. The first launch may take a moment while indexes are rebuilt.\n'
printf 'To roll back, quit Codex and restore files from: %s\n' "$backup_root"

