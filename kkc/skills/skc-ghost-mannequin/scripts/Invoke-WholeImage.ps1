param(
    [Parameter(Mandatory=$true)][string]$InputImage,
    [Parameter(Mandatory=$true)][string]$AiCandidateImage,
    [Parameter(Mandatory=$true)][string]$ConfigPath,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$OutputStem = 'skc_material_safe',
    [string]$ProblemImage,
    [string]$PhotoshopProgId = 'Photoshop.Application'
)
$ErrorActionPreference = 'Stop'
$originalPath = (Resolve-Path -LiteralPath $InputImage).Path
$candidatePath = (Resolve-Path -LiteralPath $AiCandidateImage).Path
$profile = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($profile.schema -ne 2) { throw 'Use a schema 2 material-region profile.' }
if ($profile.candidate_review.status -ne 'approved_for_regions') { throw 'Candidate is unreviewed or rejected. No Photoshop edit performed.' }
if (-not $profile.candidate_review.notes) { throw 'Record actual visual observations before using a candidate.' }
if ((Get-FileHash -LiteralPath $originalPath -Algorithm SHA256).Hash -ne $profile.source_sha256) { throw 'Source identity changed. Recheck regions and references.' }
if ((Get-FileHash -LiteralPath $candidatePath -Algorithm SHA256).Hash -ne $profile.candidate_sha256) { throw 'Candidate identity changed. Repeat visual review.' }
if (@($profile.ai_regions).Count -eq 0) { throw 'No reviewed material regions. Do not apply AI globally.' }
foreach ($region in $profile.ai_regions) {
    if ($region.review -ne 'approved' -or -not $region.notes) { throw "Region requires visual review: $($region.id)" }
    if (@($region.polygon).Count -lt 3) { throw "Missing region polygon: $($region.id)" }
}
if ($profile.ai_opacity -lt 0 -or $profile.ai_opacity -gt 100) { throw 'AI opacity must be between 0 and 100.' }
if ($profile.reference_size.Count -ne 2 -or $profile.output_size.Count -ne 2) { throw 'Need reference and output pixel dimensions.' }
$outDir = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $outDir -Force | Out-Null
$jobDir = Join-Path $outDir ('work\material_safe_' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $jobDir -Force | Out-Null
$job = @{
    input=$originalPath; candidate=$candidatePath; profile=$profile
    png=(Join-Path $outDir ($OutputStem + '.png'))
    psd=(Join-Path $outDir ($OutputStem + '.psd'))
    baseline_png=(Join-Path $jobDir 'baseline.png')
}
if ($ProblemImage) { $job.problem=(Resolve-Path -LiteralPath $ProblemImage).Path }
foreach ($path in @($job.png,$job.psd)) { if (Test-Path -LiteralPath $path) { throw "Output already exists: $path" } }
$jobPath = Join-Path $jobDir 'photoshop-job.json'
$job | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $jobPath -Encoding UTF8
$native = & (Join-Path $PSScriptRoot 'Invoke-PhotoshopJob.ps1') -TemplatePath (Join-Path $PSScriptRoot 'material-safe.jsx') -ConfigPath $jobPath -PhotoshopProgId $PhotoshopProgId
$record = @{
    schema=2; skill='skc-ghost-mannequin'; method='Full-frame original smart object, reviewed AI material masks, optional in-place original zipper filter'
    source_sha256=$profile.source_sha256; candidate_sha256=$profile.candidate_sha256
    profile=$profile; job=$job; photoshop_result=[string]$native; visual_final_status='pending_final_file_review'
}
$record | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath (Join-Path $jobDir 'run.json') -Encoding UTF8
Write-Output $job.png
Write-Output $job.psd
Write-Output (Join-Path $jobDir 'run.json')
