param(
    [Parameter(Mandatory=$true)][string]$InputImage,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [Parameter(Mandatory=$true)][string]$ConfigPath,
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$OutputStem = 'product_zipper_clear',
    [switch]$SavePsd,
    [string]$PhotoshopProgId = 'Photoshop.Application'
)
$ErrorActionPreference = 'Stop'
$preset = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($preset.review.status -ne 'approved_in_place' -or -not $preset.review.notes) { throw 'Historical/unreviewed zipper presets cannot run automatically. Inspect the current image and record an in-place review.' }
if ((Get-FileHash -LiteralPath (Resolve-Path -LiteralPath $InputImage).Path -Algorithm SHA256).Hash -ne $preset.source_sha256) { throw 'Zipper source identity changed; relocate and recheck the preset.' }
$outDir = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $outDir -Force | Out-Null
$job = @{
    input = (Resolve-Path -LiteralPath $InputImage).Path
    png = Join-Path $outDir ($OutputStem + '.png')
    jpg = Join-Path $outDir ($OutputStem + '.jpg')
    reference_size = $preset.reference_size; zipper = $preset.zipper
}
if ($SavePsd) { $job.psd = Join-Path $outDir ($OutputStem + '.psd') }
foreach ($key in @('png','jpg','psd')) {
    if ($job.ContainsKey($key) -and (Test-Path -LiteralPath $job[$key])) { throw "Output already exists: $($job[$key])" }
}
$jobDir = Join-Path $outDir ('work\zipper_' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $jobDir -Force | Out-Null
$jobPath = Join-Path $jobDir 'photoshop-job.json'
$job | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $jobPath -Encoding UTF8
$native = & (Join-Path $PSScriptRoot 'Invoke-PhotoshopJob.ps1') -TemplatePath (Join-Path $PSScriptRoot 'zipper-in-place.jsx') -ConfigPath $jobPath -PhotoshopProgId $PhotoshopProgId
@{ method = 'Full-canvas original-pixel layers and local masks; no imported zipper'; preset = $preset; photoshop_result = [string]$native; output = $job } | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath (Join-Path $outDir ($OutputStem + '_run.json')) -Encoding UTF8
Write-Output $job.png
Write-Output $job.jpg
