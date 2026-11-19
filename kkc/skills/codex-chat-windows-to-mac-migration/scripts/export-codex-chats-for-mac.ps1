[CmdletBinding()]
param(
    [string]$CodexHome = (Join-Path $env:USERPROFILE '.codex'),
    [string]$DestinationDirectory = ([Environment]::GetFolderPath('Desktop')),
    [switch]$AllowRunningCodex
)

$ErrorActionPreference = 'Stop'

if ((Get-Process -Name 'Codex' -ErrorAction SilentlyContinue) -and (-not $AllowRunningCodex)) {
    throw 'Quit Codex completely before exporting chats. Use -AllowRunningCodex only for an explicitly accepted best-effort live snapshot.'
}
if ((Get-Process -Name 'Codex' -ErrorAction SilentlyContinue) -and $AllowRunningCodex) {
    Write-Warning 'Codex is running. The active conversation may not include its final messages in this snapshot.'
}

$codexHomeFull = [IO.Path]::GetFullPath($CodexHome).TrimEnd('\')
$sourceSessions = Join-Path $codexHomeFull 'sessions'
if (-not (Test-Path -LiteralPath $sourceSessions -PathType Container)) {
    throw "Codex sessions directory was not found: $sourceSessions"
}

if (-not $DestinationDirectory) {
    $DestinationDirectory = (Get-Location).Path
}
New-Item -ItemType Directory -Path $DestinationDirectory -Force | Out-Null
$destinationFull = (Resolve-Path -LiteralPath $DestinationDirectory).Path

$sessionFiles = @(Get-ChildItem -LiteralPath $sourceSessions -Recurse -File -Filter '*.jsonl')
if ($sessionFiles.Count -eq 0) {
    throw 'No Codex session JSONL files were found.'
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$baseName = "CodexChats_Windows_to_Mac_$stamp"
$zipPath = Join-Path $destinationFull "$baseName.zip"
$suffix = 2
while (Test-Path -LiteralPath $zipPath) {
    $zipPath = Join-Path $destinationFull "${baseName}_$suffix.zip"
    $suffix++
}

$temporaryParent = [IO.Path]::GetTempPath().TrimEnd('\')
$stage = Join-Path $temporaryParent ("CodexChatWindowsToMac_" + [Guid]::NewGuid().ToString('N'))
$stageFull = [IO.Path]::GetFullPath($stage)
if (-not $stageFull.StartsWith($temporaryParent + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe temporary path: $stageFull"
}

try {
    $nativeSessions = Join-Path $stageFull 'native\sessions'
    New-Item -ItemType Directory -Path $nativeSessions -Force | Out-Null
    $sourceRoot = (Resolve-Path -LiteralPath $sourceSessions).Path.TrimEnd('\')
    $totalBytes = 0L
    foreach ($sourceFile in $sessionFiles) {
        $relative = $sourceFile.FullName.Substring($sourceRoot.Length).TrimStart('\')
        $targetFile = Join-Path $nativeSessions $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $targetFile) -Force | Out-Null
        Copy-Item -LiteralPath $sourceFile.FullName -Destination $targetFile
        $totalBytes += $sourceFile.Length
    }

    $sourceIndex = Join-Path $codexHomeFull 'session_index.jsonl'
    if (Test-Path -LiteralPath $sourceIndex -PathType Leaf) {
        Copy-Item -LiteralPath $sourceIndex -Destination (Join-Path $stageFull 'native\session_index.jsonl')
    }

    $restoreScript = Join-Path $PSScriptRoot 'restore-codex-chats-mac.sh'
    if (-not (Test-Path -LiteralPath $restoreScript -PathType Leaf)) {
        throw "Mac restore script was not found: $restoreScript"
    }
    Copy-Item -LiteralPath $restoreScript -Destination (Join-Path $stageFull 'restore-codex-chats-mac.sh')

    $sop = Join-Path (Split-Path -Parent $PSScriptRoot) 'references\SOP.md'
    if (Test-Path -LiteralPath $sop -PathType Leaf) {
        Copy-Item -LiteralPath $sop -Destination (Join-Path $stageFull 'SOP_Windows_to_Mac.md')
    }

    $manifest = [ordered]@{
        Format = 'codex-chat-windows-to-mac-migration-v1'
        CreatedAt = (Get-Date).ToString('o')
        SourcePlatform = 'Windows'
        TargetPlatform = 'macOS'
        SourceCodexHome = $codexHomeFull
        SessionFiles = $sessionFiles.Count
        SessionBytes = $totalBytes
        ArchivedSessionsIncluded = $false
        CredentialsIncluded = $false
        LiveSnapshot = [bool](Get-Process -Name 'Codex' -ErrorAction SilentlyContinue)
    }
    $manifestJson = $manifest | ConvertTo-Json -Depth 4
    [IO.File]::WriteAllText((Join-Path $stageFull 'manifest.json'), $manifestJson + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))

    $readme = @(
        'Codex chat migration package for Windows-to-macOS transfer.',
        '',
        '1. Transfer this ZIP and its SHA-256 sidecar to the Mac.',
        '2. Fully extract the ZIP.',
        '3. Quit Codex on the Mac with Command-Q.',
        '4. Open Terminal.',
        '5. Run: bash "/full/path/to/restore-codex-chats-mac.sh"',
        '',
        'Do not run with sudo.',
        'This package excludes archived sessions, credentials, secrets, settings, plugins, logs, caches, and browser state.',
        'Treat the package as private because chat text may contain sensitive information.'
    )
    [IO.File]::WriteAllLines((Join-Path $stageFull 'README.txt'), $readme, (New-Object Text.UTF8Encoding($false)))

    $hashLines = New-Object 'System.Collections.Generic.List[string]'
    $stageRoot = (Resolve-Path -LiteralPath $stageFull).Path.TrimEnd('\')
    foreach ($file in Get-ChildItem -LiteralPath $stageFull -Recurse -File | Sort-Object FullName) {
        if ($file.Name -eq 'SHA256SUMS.txt') { continue }
        $relative = $file.FullName.Substring($stageRoot.Length).TrimStart('\').Replace('\', '/')
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $hashLines.Add("$hash  $relative")
    }
    [IO.File]::WriteAllLines((Join-Path $stageFull 'SHA256SUMS.txt'), $hashLines, (New-Object Text.UTF8Encoding($false)))

    Compress-Archive -Path (Join-Path $stageFull '*') -DestinationPath $zipPath -CompressionLevel Optimal
    $zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $sidecarPath = "$zipPath.sha256.txt"
    [IO.File]::WriteAllText($sidecarPath, "$zipHash  $([IO.Path]::GetFileName($zipPath))`r`n", (New-Object Text.UTF8Encoding($false)))

    [pscustomobject]@{
        ZipPath = $zipPath
        Sha256Path = $sidecarPath
        Sha256 = $zipHash
        SessionFiles = $sessionFiles.Count
        SessionMB = [math]::Round($totalBytes / 1MB, 2)
        ArchivedSessionsIncluded = $false
        CredentialsIncluded = $false
    }
}
finally {
    if (Test-Path -LiteralPath $stageFull -PathType Container) {
        $resolvedStage = [IO.Path]::GetFullPath($stageFull)
        if ($resolvedStage.StartsWith($temporaryParent + '\', [StringComparison]::OrdinalIgnoreCase) -and
            ([IO.Path]::GetFileName($resolvedStage) -like 'CodexChatWindowsToMac_*')) {
            Remove-Item -LiteralPath $resolvedStage -Recurse -Force
        }
    }
}
