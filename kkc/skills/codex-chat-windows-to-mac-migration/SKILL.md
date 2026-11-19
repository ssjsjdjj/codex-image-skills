---
name: codex-chat-windows-to-mac-migration
description: Safely export, transfer, restore, verify, or roll back local Codex chat sessions from Windows to macOS. Use when the user asks to migrate or back up Codex chats from a Windows PC to a Mac; do not use for project-file migration, settings sync, or migrations in another direction.
---

# Codex Chat Windows To Mac Migration

Migrate local Codex conversations from a Windows user profile to a macOS user profile while preserving chats already present on the Mac.

## Route the request

- If the user asks only how migration works, explain the SOP without changing files.
- For Windows source export, use `scripts/export-codex-chats-for-mac.ps1`.
- For Mac restore, use the `restore-codex-chats-mac.sh` embedded in the exported package.
- For detailed human steps, troubleshooting, verification, or rollback, read [references/SOP.md](references/SOP.md).

## Safety invariants

- Require explicit authorization before restoring on the Mac.
- Use `%USERPROFILE%\.codex` on Windows and `$HOME/.codex` on macOS unless the user explicitly provides another safe location.
- Require Codex to be fully closed for a normal export and for every restore. Permit `-AllowRunningCodex` only when the user explicitly accepts a best-effort live snapshot.
- Export `sessions` and `session_index.jsonl`; do not export `archived_sessions` unless the user explicitly changes scope.
- Never export `auth.json`, `.credentials.json`, `secrets`, OAuth data, configuration, plugins, logs, caches, memories, automations, or browser state.
- Never use `sudo` for the Mac restore. Restore under the same macOS user that runs Codex.
- Preserve existing Mac chats. Back up every conflicting session and local index before replacement or index rebuilding.
- Do not copy Windows SQLite state databases to the Mac. Rebuild Mac indexes from the merged session files.
- Do not rewrite conversation contents or embedded Windows paths. Explain that chat text remains viewable, but old `C:\...` project paths do not become valid Mac paths.
- Treat the package as private because chat text may contain sensitive data.

## Export on Windows

Run the script in Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File "<skill>\scripts\export-codex-chats-for-mac.ps1" -DestinationDirectory "<folder>"
```

Honor the user's requested destination and local `AGENTS.md` output rules. Confirm the ZIP and SHA-256 sidecar exist, verify their hashes, and report the session count.

## Restore on macOS

Transfer the ZIP and sidecar, fully extract the ZIP, quit Codex with `Command + Q`, open Terminal, and run the embedded script through Bash:

```bash
bash "/full/path/to/restore-codex-chats-mac.sh"
```

Running the script path directly may return `Permission denied` because ZIP extraction does not preserve executable permission. Prefer `bash <path>`; do not use `sudo`.

## Verify completion

Require all of these:

- Package verification succeeds.
- Restore reports plausible added/replaced/total counts.
- Codex starts and rebuilds its indexes.
- Migrated titles appear and several old chats open correctly.
- Chats previously present on the Mac still open.

Keep the source ZIP and timestamped Mac backup until the user confirms the result.
