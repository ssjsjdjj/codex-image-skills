param(
  [Parameter(Mandatory = $true)]
  [string]$SourceDir,

  [Parameter(Mandatory = $true)]
  [string]$TargetDir,

  [string]$BackupRoot = "",

  [ValidateSet("ExactName", "BaseName")]
  [string]$MatchMode = "ExactName",

  [string[]]$Extensions = @(".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"),

  [string]$ConfirmationManifest = "",

  [switch]$SkipUnmatched,

  [string]$ResultsCsv = "",

  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$runStartedAt = Get-Date
Write-Output ("START_TIME " + $runStartedAt.ToString("o"))
$manifestGuard = $null
try {
if (-not $DryRun -and [string]::IsNullOrWhiteSpace($ConfirmationManifest)) {
  throw "ConfirmationManifest is required before any replacement. Generate and review a manifest first."
}

function Resolve-ExistingDirectory {
  param(
    [string]$Path,
    [string]$Label
  )

  if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
    throw "$Label not found or is not a folder: $Path"
  }

  return (Get-Item -LiteralPath $Path).FullName
}

function Normalize-ExtensionSet {
  param([string[]]$Values)

  $set = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
  foreach ($value in $Values) {
    if ([string]::IsNullOrWhiteSpace($value)) { continue }
    $ext = $value.Trim()
    if (-not $ext.StartsWith(".")) { $ext = ".$ext" }
    [void]$set.Add($ext)
  }
  return ,$set
}

function Get-ImageFiles {
  param(
    [string]$Directory,
    [System.Collections.Generic.HashSet[string]]$ExtensionSet
  )

  return @(Get-ChildItem -LiteralPath $Directory -File | Where-Object {
    $ExtensionSet.Contains($_.Extension)
  } | Sort-Object Name)
}

function Test-SpecialImageName {
  param([string]$Name)
  $pattern = '(?i)(?:\u53c2\u8003|\u62f7\u8d1d|\u526f\u672c|\u88c1\u5207|\u88c1\u526a|\u8c03\u8272|\u7cbe\u4fee|\u4fee\u56fe|\u7248\u672c|(?:^|[\s_.()\-])(?:reference|copy|crop(?:ped)?|retouch(?:ed)?|edit(?:ed)?|version)(?:$|[\s_.()\-]|\d)|(?:^|[\s_.()\-])v\d+(?:$|[\s_.()\-]))'
  return [regex]::IsMatch([System.IO.Path]::GetFileNameWithoutExtension($Name), $pattern)
}

function Read-ValidatedManifest {
  param([string]$Path)
  $rows = @(Import-Csv -LiteralPath $Path)
  if ($rows.Count -eq 0) { throw "Confirmation manifest is empty. Generate a fresh manifest." }
  $requiredColumns = @('TargetName','TargetPath','TargetSizeAtScan','TargetLastWriteTimeUtc','TargetHashAtScan',
    'SourcePath','SourceName','SourceSizeAtScan','SourceLastWriteTimeUtc','SourceHashAtScan','MatchType',
    'ConfirmationRequired','Decision','ConfirmedBy','ConfirmedAt','ExecutionStatus','PostReplaceHash')
  foreach ($column in $requiredColumns) {
    if ($rows[0].PSObject.Properties.Name -notcontains $column) { throw "Missing manifest column: $column" }
  }
  $byName = @{}
  foreach ($row in $rows) {
    if ([string]::IsNullOrWhiteSpace($row.TargetName) -or
        [System.IO.Path]::GetFileName($row.TargetName) -ne $row.TargetName) {
      throw "Invalid TargetName in confirmation manifest."
    }
    if ($byName.ContainsKey($row.TargetName)) { throw "Duplicate TargetName in manifest: $($row.TargetName)" }
    $row.ConfirmationRequired = ([string]$row.ConfirmationRequired).Trim()
    $row.Decision = ([string]$row.Decision).Trim()
    $row.ExecutionStatus = ([string]$row.ExecutionStatus).Trim()
    $row.MatchType = ([string]$row.MatchType).Trim()
    if ($row.ConfirmationRequired -notin @('Yes','No')) { throw "Invalid ConfirmationRequired: $($row.TargetName)" }
    if ($row.Decision -notin @('Auto','Approved','Pending','Skip','Rejected')) { throw "Invalid Decision: $($row.TargetName)" }
    if ($row.ExecutionStatus -notin @('NotRun','Replaced')) { throw "Invalid ExecutionStatus: $($row.TargetName)" }
    if ($row.MatchType -notin @('ExactName','BaseName','EmbeddedOriginalNameCandidate','NoExactSource','NoOriginalName')) {
      throw "Invalid MatchType: $($row.TargetName)"
    }
    $byName[$row.TargetName] = $row
  }
  return [PSCustomObject]@{ Rows = $rows; ByName = $byName }
}

function Assert-PairSnapshot {
  param($Pair, $Row, [string]$SourceDirectory, $ExtensionSet)
  if ($Row.Decision -notin @('Auto','Approved')) { throw "Decision does not permit replacement" }
  $source = Get-Item -LiteralPath $Pair.Source.FullName
  $target = Get-Item -LiteralPath $Pair.Target.FullName
  if ($source.PSIsContainer -or $target.PSIsContainer) { throw "Source and target must be files" }
  if (($source.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or
      ($target.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { throw "Linked image files require a separate review" }
  if ($source.Directory.FullName -ne $SourceDirectory -or -not $ExtensionSet.Contains($source.Extension)) {
    throw "Source is outside the selected source directory or file types"
  }
  foreach ($field in @('TargetPath','SourcePath')) {
    $pathValue = [string]$Row.$field
    if ([string]::IsNullOrWhiteSpace($pathValue) -or $pathValue -notmatch '^(?:[A-Za-z]:[\\/]|\\\\)') {
      throw "Missing or non-absolute $field"
    }
  }
  if ([System.IO.Path]::GetFullPath($Row.TargetPath) -ne $target.FullName -or $Row.TargetName -ne $target.Name) {
    throw "Target path changed"
  }
  if ([System.IO.Path]::GetFullPath($Row.SourcePath) -ne $source.FullName -or $Row.SourceName -ne $source.Name) {
    throw "Source path changed"
  }
  foreach ($field in @('SourceHashAtScan','TargetHashAtScan')) {
    if (([string]$Row.$field).Trim() -notmatch '^[A-Fa-f0-9]{64}$') { throw "Missing or invalid $field" }
  }
  foreach ($field in @('SourceSizeAtScan','TargetSizeAtScan')) {
    [int64]$parsedSize = 0
    if (-not [int64]::TryParse(([string]$Row.$field).Trim(), [ref]$parsedSize) -or $parsedSize -lt 0) {
      throw "Missing or invalid $field"
    }
  }
  foreach ($field in @('SourceLastWriteTimeUtc','TargetLastWriteTimeUtc')) {
    $parsedTime = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse([string]$Row.$field, [ref]$parsedTime)) { throw "Missing or invalid $field" }
  }
  $special = (Test-SpecialImageName $target.Name) -or (Test-SpecialImageName $source.Name) -or
    ($source.Name -ne $target.Name) -or ($Row.MatchType -ne 'ExactName')
  if (($special -or $Row.ConfirmationRequired -eq 'Yes') -and
      ($Row.ConfirmationRequired -ne 'Yes' -or $Row.Decision -ne 'Approved')) {
    throw "Explicit confirmation is required for this pair"
  }
  if ($Row.Decision -eq 'Approved') {
    $approvalTime = [DateTimeOffset]::MinValue
    if ([string]::IsNullOrWhiteSpace($Row.ConfirmedBy) -or
        -not [DateTimeOffset]::TryParse([string]$Row.ConfirmedAt, [ref]$approvalTime)) {
      throw "Approved pair must record ConfirmedBy and a valid ConfirmedAt"
    }
  }
  $sourceHash = (Get-FileHash -LiteralPath $source.FullName -Algorithm SHA256).Hash
  $targetHash = (Get-FileHash -LiteralPath $target.FullName -Algorithm SHA256).Hash
  if ($sourceHash -ne $Row.SourceHashAtScan.Trim() -or $source.Length -ne [int64]$Row.SourceSizeAtScan) {
    throw "Source changed"
  }
  $alreadyReplaced = ($Row.ExecutionStatus -eq 'Replaced')
  if ($alreadyReplaced) {
    if (([string]$Row.PostReplaceHash).Trim() -ne $sourceHash -or $targetHash -ne $sourceHash) {
      throw "Previously replaced target hash mismatch"
    }
  } elseif ($targetHash -ne $Row.TargetHashAtScan.Trim() -or $target.Length -ne [int64]$Row.TargetSizeAtScan) {
    throw "Target changed"
  }
  return [PSCustomObject]@{
    SourceHash=$sourceHash; TargetHash=$targetHash; SourceSize=$source.Length; TargetSize=$target.Length
    AlreadyReplaced=$alreadyReplaced
  }
}

$resolvedSource = Resolve-ExistingDirectory -Path $SourceDir -Label "SourceDir"
$resolvedTarget = Resolve-ExistingDirectory -Path $TargetDir -Label "TargetDir"
if ($resolvedSource -eq $resolvedTarget) { throw "SourceDir and TargetDir must be different folders." }
$extensionSet = Normalize-ExtensionSet -Values $Extensions
$sourceFiles = Get-ImageFiles -Directory $resolvedSource -ExtensionSet $extensionSet
$targetFiles = Get-ImageFiles -Directory $resolvedTarget -ExtensionSet $extensionSet

if ($sourceFiles.Count -eq 0) { throw "No source image files found in: $resolvedSource" }
if ($targetFiles.Count -eq 0) { throw "No target image files found in: $resolvedTarget" }

$sourceByName = @{}
$sourceByBaseName = @{}
foreach ($file in $sourceFiles) {
  $sourceByName[$file.Name] = $file

  if (-not $sourceByBaseName.ContainsKey($file.BaseName)) {
    $sourceByBaseName[$file.BaseName] = @()
  }
  $sourceByBaseName[$file.BaseName] += $file
}

$matchedPairs = @()
$missing = @()
$ambiguous = @()

foreach ($target in $targetFiles) {
  if ($MatchMode -eq "ExactName") {
    if ($sourceByName.ContainsKey($target.Name)) {
      $matchedPairs += [PSCustomObject]@{ Target = $target; Source = $sourceByName[$target.Name] }
    } else {
      $missing += $target.Name
    }
  } else {
    if (-not $sourceByBaseName.ContainsKey($target.BaseName)) {
      $missing += $target.Name
    } elseif ($sourceByBaseName[$target.BaseName].Count -gt 1) {
      $ambiguous += [PSCustomObject]@{
        Target = $target.Name
        Candidates = (($sourceByBaseName[$target.BaseName] | Select-Object -ExpandProperty Name) -join "; ")
      }
    } else {
      $matchedPairs += [PSCustomObject]@{ Target = $target; Source = $sourceByBaseName[$target.BaseName][0] }
    }
  }
}

$manifestRowsForMatch = @()
$manifestByNameForMatch = @{}
if (-not [string]::IsNullOrWhiteSpace($ConfirmationManifest)) {
  if (-not (Test-Path -LiteralPath $ConfirmationManifest -PathType Leaf)) {
    throw "ConfirmationManifest not found: $ConfirmationManifest"
  }
  # Hold a read-only share lock so decisions cannot change during this run.
  $manifestGuard = [System.IO.File]::Open((Get-Item -LiteralPath $ConfirmationManifest).FullName,
    [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
  $validatedManifest = Read-ValidatedManifest -Path $ConfirmationManifest
  $manifestRowsForMatch = $validatedManifest.Rows
  $manifestByNameForMatch = $validatedManifest.ByName

  foreach ($missingName in @($missing)) {
    if (-not $manifestByNameForMatch.ContainsKey($missingName)) { continue }
    $row = $manifestByNameForMatch[$missingName]
    if (([string]$row.Decision).Trim() -ne "Approved") { continue }
    $approvedSourcePath = ([string]$row.SourcePath).Trim()
    if ([string]::IsNullOrWhiteSpace($approvedSourcePath) -or -not (Test-Path -LiteralPath $approvedSourcePath -PathType Leaf)) { continue }
    $targetObject = $targetFiles | Where-Object { $_.Name -eq $missingName } | Select-Object -First 1
    $sourceObject = Get-Item -LiteralPath $approvedSourcePath
    if ($null -ne $targetObject -and $null -ne $sourceObject) {
      $matchedPairs += [PSCustomObject]@{ Target = $targetObject; Source = $sourceObject }
      $missing = @($missing | Where-Object { $_ -ne $missingName })
    }
  }
}

$summary = [PSCustomObject]@{
  SourceDir = $resolvedSource
  TargetDir = $resolvedTarget
  SourceImageCount = $sourceFiles.Count
  TargetImageCount = $targetFiles.Count
  MatchedCount = $matchedPairs.Count
  MissingCount = $missing.Count
  AmbiguousCount = $ambiguous.Count
  DryRun = [bool]$DryRun
}

Write-Output "SUMMARY"
$summary | Format-List

if ($missing.Count -gt 0) {
  Write-Output "MISSING"
  $missing | ForEach-Object { Write-Output $_ }
}

if ($ambiguous.Count -gt 0) {
  Write-Output "AMBIGUOUS"
  $ambiguous | Format-Table -AutoSize
}

if (($missing.Count -gt 0 -or $ambiguous.Count -gt 0) -and -not $SkipUnmatched) {
  throw "Replacement aborted because not every target file has exactly one source match."
}

if ($SkipUnmatched -and ($missing.Count -gt 0 -or $ambiguous.Count -gt 0)) {
  Write-Output "SKIPPED_UNMATCHED"
  if ($missing.Count -gt 0) { $missing | ForEach-Object { Write-Output $_ } }
  if ($ambiguous.Count -gt 0) { $ambiguous | Format-Table -AutoSize }
}

if (-not [string]::IsNullOrWhiteSpace($ConfirmationManifest)) {
  if (-not (Test-Path -LiteralPath $ConfirmationManifest -PathType Leaf)) {
    throw "ConfirmationManifest not found: $ConfirmationManifest"
  }

  $manifestByName = $manifestByNameForMatch

  $approvedPairs = @()
  $completedPairs = @()
  $blockedPairs = @()
  foreach ($match in $matchedPairs) {
    if (-not $manifestByName.ContainsKey($match.Target.Name)) {
      $blockedPairs += [PSCustomObject]@{ Name = $match.Target.Name; Reason = "No manifest row" }
      continue
    }

    $row = $manifestByName[$match.Target.Name]
    if ($row.Decision -in @('Pending','Skip','Rejected')) {
      $blockedPairs += [PSCustomObject]@{ Name = $match.Target.Name; Reason = ("Decision: " + $row.Decision) }
      continue
    }
    try {
      $snapshot = Assert-PairSnapshot -Pair $match -Row $row -SourceDirectory $resolvedSource -ExtensionSet $extensionSet
    } catch {
      $blockedPairs += [PSCustomObject]@{ Name = $match.Target.Name; Reason = $_.Exception.Message }
      continue
    }
    if ($snapshot.AlreadyReplaced) {
      $completedPairs += [PSCustomObject]@{ Name = $match.Target.Name; Status = 'AlreadyReplaced' }
      continue
    }
    $approvedPairs += [PSCustomObject]@{ Target=$match.Target; Source=$match.Source; Row=$row }
  }

  if ($blockedPairs.Count -gt 0) {
    Write-Output "CONFIRMATION_BLOCKED"
    $blockedPairs | Format-Table -AutoSize
  }
  if ($completedPairs.Count -gt 0) {
    Write-Output "ALREADY_REPLACED"
    $completedPairs | Format-Table -AutoSize
  }

  $matchedPairs = @($approvedPairs)
  if ($matchedPairs.Count -eq 0) {
    if ($completedPairs.Count -gt 0 -and $blockedPairs.Count -eq 0) { return }
    throw "No confirmed and unchanged pairs are eligible for replacement."
  }
}

if ($DryRun) {
  Write-Output "MATCHES"
  $matchedPairs | ForEach-Object {
    [PSCustomObject]@{
      Name = $_.Target.Name
      TargetSize = $_.Target.Length
      SourceSize = $_.Source.Length
    }
  } | Format-Table -AutoSize
  return
}

if (-not [string]::IsNullOrWhiteSpace($ResultsCsv)) {
  if ([System.IO.Path]::GetExtension($ResultsCsv) -ne '.csv' -or (Test-Path -LiteralPath $ResultsCsv)) {
    throw "ResultsCsv must be a new .csv file; existing files will not be overwritten."
  }
  if ([System.IO.Path]::GetFullPath($ResultsCsv) -eq [System.IO.Path]::GetFullPath($ConfirmationManifest)) {
    throw "ResultsCsv cannot replace the confirmation manifest."
  }
}

if ([string]::IsNullOrWhiteSpace($BackupRoot)) {
  $dateSlug = Get-Date -Format "yyyy-MM-dd"
  $aiFilesRoot = Join-Path "E:\" ("AI" + [char]0x6587 + [char]0x4EF6)
  $tempRoot = Join-Path $aiFilesRoot ("99_" + [char]0x4E34 + [char]0x65F6 + [char]0x5F85 + [char]0x6574 + [char]0x7406)
  $BackupRoot = Join-Path $tempRoot "${dateSlug}_replace-images-by-name_process"
}

$runId = (Get-Date -Format 'yyyyMMdd_HHmmss_fff') + '_' + [guid]::NewGuid().ToString('N')
$backupDir = Join-Path $BackupRoot ("backup_before_replacement_" + $runId)
New-Item -ItemType Directory -Path $backupDir -ErrorAction Stop | Out-Null
Write-Output "BACKUP $backupDir"

$results = @()
foreach ($match in $matchedPairs) {
  # Re-check the approved snapshots immediately before touching this target.
  $snapshot = Assert-PairSnapshot -Pair $match -Row $match.Row -SourceDirectory $resolvedSource -ExtensionSet $extensionSet
  $backupFile = Join-Path $backupDir $match.Target.Name

  # File.Copy(overwrite:false) refuses existing files, including collisions.
  [System.IO.File]::Copy($match.Target.FullName, $backupFile, $false)
  $backupHash = (Get-FileHash -LiteralPath $backupFile -Algorithm SHA256).Hash
  if ($backupHash -ne $snapshot.TargetHash) { throw "Backup snapshot mismatch: $($match.Target.Name). Target was not overwritten." }
  if ((Get-FileHash -LiteralPath $match.Target.FullName -Algorithm SHA256).Hash -ne $snapshot.TargetHash -or
      (Get-FileHash -LiteralPath $match.Source.FullName -Algorithm SHA256).Hash -ne $snapshot.SourceHash) {
    throw "Source or target changed after backup: $($match.Target.Name). Target was not overwritten."
  }
  Copy-Item -LiteralPath $match.Source.FullName -Destination $match.Target.FullName -Force

  $targetHash = (Get-FileHash -LiteralPath $match.Target.FullName -Algorithm SHA256).Hash

  $results += [PSCustomObject]@{
    Name = $match.Target.Name
    OriginalSize = $snapshot.TargetSize
    SourceSize = $snapshot.SourceSize
    NewSize = (Get-Item -LiteralPath $match.Target.FullName).Length
    OriginalTargetHash = $backupHash
    SourceHash = $snapshot.SourceHash
    PostReplaceHash = $targetHash
    BackupHash = $backupHash
    Verified = ($snapshot.SourceHash -eq $targetHash)
  }
}

$failed = @($results | Where-Object { -not $_.Verified })

Write-Output "BACKUP"
Write-Output $backupDir
Write-Output "RESULTS"
$results | Select-Object Name,OriginalSize,SourceSize,NewSize,Verified | Format-Table -AutoSize

if ($failed.Count -gt 0) {
  throw "Replacement completed but hash verification failed for $($failed.Count) file(s)."
}

if (-not [string]::IsNullOrWhiteSpace($ResultsCsv)) {
  $resultsParent = Split-Path -Parent $ResultsCsv
  if ($resultsParent) { New-Item -ItemType Directory -Path $resultsParent -Force | Out-Null }
  $results | Export-Csv -LiteralPath $ResultsCsv -NoTypeInformation -Encoding UTF8 -NoClobber
  Write-Output "RESULTS_CSV $ResultsCsv"
}

Write-Output "HASH_MATCHED $($results.Count)"
} finally {
if ($null -ne $manifestGuard) { $manifestGuard.Dispose() }
$runEndedAt = Get-Date
Write-Output ("END_TIME " + $runEndedAt.ToString("o"))
Write-Output ("ELAPSED_SECONDS " + [math]::Round(($runEndedAt - $runStartedAt).TotalSeconds, 3))
}
