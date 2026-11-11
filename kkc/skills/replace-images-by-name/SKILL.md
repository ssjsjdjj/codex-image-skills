---
name: replace-images-by-name
description: Replace selected small, thumbnail, low-resolution, or temporary images with matching source/original/high-resolution images by filename. Use when the user asks to swap images in one folder with corresponding images from another folder, especially Chinese workflows like “小图替换成大图”, “白底图替换原图”, “按同名图片覆盖”, “选图换成源文件”, or similar batch image replacement tasks that require backup and verification.
---

# Replace Images By Name

## Overview

Use this skill to replace images in a target folder with same-name images from a source folder. Default to exact filename matching, backup every target file before overwriting, then verify that every replaced target file is byte-identical to the source file.

## Workflow

1. Resolve the source and target folders from the user's message. If a pasted path includes extra description after punctuation, inspect nearby folders to find the real directory.
2. List both folders before changing anything. Report the number of image files and common extensions.
3. Match target files to source files by exact filename unless the user explicitly asks for another rule.
4. Stop before overwriting if any target file has no source match, or if basename matching would be ambiguous.
5. Before copying, create a new confirmation manifest using `scripts/create_confirmation_manifest.ps1`. Record target/source path, file size, last-write time, SHA256, match type, confirmation requirement, decision, confirmer, and confirmation time. Writing requires a manifest; `-DryRun` may preview without one. Keep the manifest and results in separate new `.csv` files; existing files are never overwritten.
6. For standard original-name, unique-match pairs, use `ConfirmationRequired=No` and `Decision=Auto`. Reference, copy, crop, retouched, version-suffixed, and non-exact mappings require `ConfirmationRequired=Yes`, `Decision=Approved`, a nonempty `ConfirmedBy`, and a valid `ConfirmedAt` recording actual authorization for the exact source snapshot. Existing explicit user authorization counts; never invent it or repeat a confirmation already given. `Pending`, `Skip`, and `Rejected` always block that pair, including ordinary matches. Do not change the confirmation flag to bypass special-name checks.
7. The script validates required columns, unique target names, decisions, absolute source/target paths, timestamps, sizes and SHA256 snapshots. It locks the manifest read-only during the run and re-checks each eligible pair immediately before backup and overwrite. Missing/invalid pair evidence or changed content blocks that pair; malformed schema or duplicate target names abort the run. Source files must be in the selected source folder and match the selected extensions. Linked image files are blocked. Unchanged ordinary pairs may continue; missing/ambiguous mappings still stop the run unless `-SkipUnmatched` was explicitly selected.
8. Create a unique backup folder before copying. Pass `-BackupRoot` for the task's process-file area. The default root is `E:\AI文件\99_临时待整理\YYYY-MM-DD_replace-images-by-name_process`. Each run adds `backup_before_replacement_yyyyMMdd_HHmmss_fff_<GUID>`; directory creation refuses collisions.
9. Copy each eligible target into its backup file with overwrite disabled, then verify the backup SHA256 against the approved original target snapshot. A collision or mismatch stops execution before that target is overwritten.
10. Copy the matched source file over the target file.
11. Verify each replaced file with SHA256 against the approved source snapshot, and export the post-replacement result with `-ResultsCsv`. The script does not write execution status back into the confirmation manifest; after a successful run, preserve the results and generate a fresh manifest for any new batch. A failed or changed pair needs a refreshed snapshot and any applicable authorization.
12. In the final response, include the target folder, source folder, confirmation-manifest path, backup folder, count replaced, blocked/pending files, and verification result. Runtime logs must record `START_TIME`, `END_TIME`, and `ELAPSED_SECONDS`; report automatic execution time separately from designer confirmation wait and manual post-check time.

## Script

Generate the manifest before invoking the replacement script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "<skill>\scripts\create_confirmation_manifest.ps1" `
  -SourceDir "<source image folder>" `
  -TargetDir "<target image folder>" `
  -OutputCsv "<process folder>\confirmation.csv"

# Resolve pending special pairs using actual authorization before execution.
powershell -NoProfile -ExecutionPolicy Bypass -File "<skill>\scripts\replace_images_by_name.ps1" `
  -SourceDir "<source image folder>" `
  -TargetDir "<target image folder>" `
  -ConfirmationManifest "<process folder>\confirmation.csv" `
  -BackupRoot "<process folder>\backups" `
  -ResultsCsv "<process folder>\results.csv"
```

Useful options:

```powershell
# Preview matches and missing files without copying.
powershell -NoProfile -ExecutionPolicy Bypass -File "<skill>\scripts\replace_images_by_name.ps1" -SourceDir "<source>" -TargetDir "<target>" -DryRun

# Continue eligible matches while recording unmatched/reference files as skipped.
powershell -NoProfile -ExecutionPolicy Bypass -File "<skill>\scripts\replace_images_by_name.ps1" -SourceDir "<source>" -TargetDir "<target>" -ConfirmationManifest "<manifest.csv>" -SkipUnmatched

# Save the post-replacement hashes and verification result.
powershell -NoProfile -ExecutionPolicy Bypass -File "<skill>\scripts\replace_images_by_name.ps1" -SourceDir "<source>" -TargetDir "<target>" -ConfirmationManifest "<manifest.csv>" -SkipUnmatched -ResultsCsv "<results.csv>"

# Match by basename when extensions differ; aborts on ambiguity.
powershell -NoProfile -ExecutionPolicy Bypass -File "<skill>\scripts\replace_images_by_name.ps1" -SourceDir "<source>" -TargetDir "<target>" -MatchMode BaseName -ConfirmationManifest "<manifest.csv>"

# Restrict file types.
& "<skill>\scripts\replace_images_by_name.ps1" -SourceDir "<source>" -TargetDir "<target>" -Extensions @(".jpg", ".png") -ConfirmationManifest "<manifest.csv>"
```

## Safety Rules

- Never delete source, target, or backup files as part of this skill.
- Never overwrite backup, confirmation-manifest or results files. Use new output names for each run.
- Never overwrite until all intended target files have a source match.
- Treat paths with Chinese characters, full-width punctuation, spaces, and network shares as normal; always use literal paths.
- If the target already contains a mix of large and small files, still replace every matched target file unless the user asks to replace only smaller files.
- If the user says “对应图” without more detail, infer exact filename matching first and verify by listing sample names.
- If multiple source files could match one target in basename mode, stop and ask for a rule instead of guessing.

## 简介与真实使用案例

- 用户需要了解目的、适用场景、输入、流程和交付时，阅读[精简介绍](references/overview-zh.md)。
- 用户需要参考真实使用示例时，阅读[暖兜兜连帽羽绒服图片替换聊天记录](references/case-2026-11-02-warm-hooded-jacket.md)。该记录按原顺序保留本次业务操作的用户消息与助手最终回复。
