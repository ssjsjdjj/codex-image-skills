param(
  [Parameter(Mandatory = $true)]
  [string]$SourceDir,

  [Parameter(Mandatory = $true)]
  [string]$TargetDir,

  [Parameter(Mandatory = $true)]
  [string]$OutputCsv,

  [string[]]$Extensions = @(".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $SourceDir -PathType Container)) { throw "SourceDir not found: $SourceDir" }
if (-not (Test-Path -LiteralPath $TargetDir -PathType Container)) { throw "TargetDir not found: $TargetDir" }
$SourceDir = (Get-Item -LiteralPath $SourceDir).FullName
$TargetDir = (Get-Item -LiteralPath $TargetDir).FullName
if ($SourceDir -eq $TargetDir) { throw "SourceDir and TargetDir must be different folders." }
if ([System.IO.Path]::GetExtension($OutputCsv) -ne '.csv' -or (Test-Path -LiteralPath $OutputCsv)) {
  throw "OutputCsv must be a new .csv file; existing files will not be overwritten."
}

function Test-SpecialImageName {
  param([string]$Name)
  $pattern = '(?i)(?:\u53c2\u8003|\u62f7\u8d1d|\u526f\u672c|\u88c1\u5207|\u88c1\u526a|\u8c03\u8272|\u7cbe\u4fee|\u4fee\u56fe|\u7248\u672c|(?:^|[\s_.()\-])(?:reference|copy|crop(?:ped)?|retouch(?:ed)?|edit(?:ed)?|version)(?:$|[\s_.()\-]|\d)|(?:^|[\s_.()\-])v\d+(?:$|[\s_.()\-]))'
  return [regex]::IsMatch([System.IO.Path]::GetFileNameWithoutExtension($Name), $pattern)
}

$extensionSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($extension in $Extensions) {
  if (-not [string]::IsNullOrWhiteSpace($extension)) {
    $value = $extension.Trim()
    if (-not $value.StartsWith(".")) { $value = "." + $value }
    [void]$extensionSet.Add($value)
  }
}

$sourceFiles = @(Get-ChildItem -LiteralPath $SourceDir -File | Where-Object { $extensionSet.Contains($_.Extension) } | Sort-Object Name)
$targetFiles = @(Get-ChildItem -LiteralPath $TargetDir -File | Where-Object { $extensionSet.Contains($_.Extension) } | Sort-Object Name)
if ($targetFiles.Count -eq 0) { throw "No target image files found: $TargetDir" }
$sourceByName = @{}
foreach ($sourceFile in $sourceFiles) { $sourceByName[$sourceFile.Name] = $sourceFile }

$rows = @()
foreach ($targetFile in $targetFiles) {
  $sourceFile = $null
  $matchType = ""
  $confirmationRequired = ""
  $decision = ""
  $riskReason = ""
  $precheckStatus = ""

  if ($sourceByName.ContainsKey($targetFile.Name)) {
    $sourceFile = $sourceByName[$targetFile.Name]
    $matchType = "ExactName"
    if (Test-SpecialImageName $targetFile.Name) {
      $confirmationRequired = 'Yes'
      $decision = 'Pending'
      $riskReason = 'Reference, copy, crop, retouched or versioned name; explicit confirmation required'
      $precheckStatus = 'PENDING_CONFIRMATION'
    } else {
      $confirmationRequired = "No"
      $decision = "Auto"
      $riskReason = "Standard original name; unique source match"
      $precheckStatus = "READY_AUTO"
    }
  } else {
    $tokenMatch = [regex]::Match($targetFile.BaseName, "20\d{6}(?:cocotree|KKS)\d+")
    if ($tokenMatch.Success) {
      $candidateName = $tokenMatch.Value + ".jpg"
      if ($sourceByName.ContainsKey($candidateName)) {
        $sourceFile = $sourceByName[$candidateName]
        $matchType = "EmbeddedOriginalNameCandidate"
        $confirmationRequired = "Yes"
        $decision = "Pending"
        $riskReason = "Generated/scene prefix; confirm source correspondence before overwrite"
        $precheckStatus = "PENDING_CONFIRMATION"
      } else {
        $matchType = "NoExactSource"
        $confirmationRequired = "Yes"
        $decision = "Skip"
        $riskReason = "Original capture token found, but no source image exists"
        $precheckStatus = "SKIP_NO_SOURCE"
      }
    } else {
      $matchType = "NoOriginalName"
      $confirmationRequired = "Yes"
      $decision = "Skip"
      $riskReason = "Reference/action/generated file; no original capture name"
      $precheckStatus = "SKIP_REFERENCE"
    }
  }

  $targetHash = (Get-FileHash -LiteralPath $targetFile.FullName -Algorithm SHA256).Hash
  $sourcePath = ""
  $sourceName = ""
  $sourceSize = ""
  $sourceTime = ""
  $sourceHash = ""
  if ($null -ne $sourceFile) {
    $sourcePath = $sourceFile.FullName
    $sourceName = $sourceFile.Name
    $sourceSize = $sourceFile.Length
    $sourceTime = $sourceFile.LastWriteTimeUtc.ToString("o")
    $sourceHash = (Get-FileHash -LiteralPath $sourceFile.FullName -Algorithm SHA256).Hash
  }

  $rows += [PSCustomObject]@{
    TargetName = $targetFile.Name
    TargetPath = $targetFile.FullName
    TargetSizeAtScan = $targetFile.Length
    TargetLastWriteTimeUtc = $targetFile.LastWriteTimeUtc.ToString("o")
    TargetHashAtScan = $targetHash
    SourcePath = $sourcePath
    SourceName = $sourceName
    SourceSizeAtScan = $sourceSize
    SourceLastWriteTimeUtc = $sourceTime
    SourceHashAtScan = $sourceHash
    MatchType = $matchType
    ConfirmationRequired = $confirmationRequired
    Decision = $decision
    ConfirmedBy = ""
    ConfirmedAt = ""
    RiskReason = $riskReason
    PrecheckStatus = $precheckStatus
    ExecutionStatus = "NotRun"
    PostReplaceHash = ""
  }
}

$parent = Split-Path -Parent $OutputCsv
if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
$rows | Export-Csv -LiteralPath $OutputCsv -NoTypeInformation -Encoding UTF8 -NoClobber

Write-Output "TARGET_IMAGES $($targetFiles.Count)"
Write-Output "READY_AUTO $(@($rows | Where-Object { $_.PrecheckStatus -eq 'READY_AUTO' }).Count)"
Write-Output "PENDING_CONFIRMATION $(@($rows | Where-Object { $_.PrecheckStatus -eq 'PENDING_CONFIRMATION' }).Count)"
Write-Output "SKIPPED $(@($rows | Where-Object { $_.PrecheckStatus -like 'SKIP*' }).Count)"
Write-Output "MANIFEST $OutputCsv"
