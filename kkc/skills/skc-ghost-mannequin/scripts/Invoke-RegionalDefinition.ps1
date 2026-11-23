param(
    [Parameter(Mandatory=$true)][string]$InputPsd,
    [Parameter(Mandatory=$true)][string]$InputPng,
    [Parameter(Mandatory=$true)][string]$ConfigPath,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$OutputStem='skc_regional_definition',
    [switch]$PreviewOnly,
    [string]$PhotoshopProgId='Photoshop.Application'
)
$ErrorActionPreference='Stop'
$profile=Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
if($profile.schema -ne 3 -or $profile.source_review.status -ne 'reviewed_baseline' -or -not $profile.source_review.notes) { throw 'Inspect and identify the accepted current baseline first.' }
$psd=(Resolve-Path -LiteralPath $InputPsd).Path
$png=(Resolve-Path -LiteralPath $InputPng).Path
if((Get-FileHash -LiteralPath $psd -Algorithm SHA256).Hash -ne $profile.baseline_psd_sha256) { throw 'PSD identity changed; review the current version.' }
if((Get-FileHash -LiteralPath $png -Algorithm SHA256).Hash -ne $profile.baseline_png_sha256) { throw 'PNG identity changed; review the current version.' }
if(@($profile.regions).Count -eq 0) { throw 'No authorized definition regions.' }
foreach($region in $profile.regions) {
    if(-not $region.id -or -not $region.notes -or @($region.polygons).Count -eq 0) { throw 'Each region needs identity, observations and actual polygons.' }
    if($region.blend -ne 'DARKEN') { throw 'This highlight-safe module requires DARKEN to prevent new bright fringes.' }
    if($region.amount -lt 0 -or $region.amount -gt 500 -or $region.radius_px -le 0 -or $region.radius_px -gt 5) { throw 'Unsupported local deblur parameters.' }
}
$out=[IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $out -Force | Out-Null
$jobDir=Join-Path $out ('work\regional_' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $jobDir -Force | Out-Null
$job=@{input_psd=$psd;input_png=$png;profile=$profile;preview_only=[bool]$PreviewOnly;png=(Join-Path $out ($OutputStem+'.png'));psd=(Join-Path $out ($OutputStem+'.psd'))}
foreach($path in @($job.png,$job.psd)) { if(Test-Path -LiteralPath $path) { throw "Output exists: $path" } }
$jobPath=Join-Path $jobDir 'job.json'
$job | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $jobPath -Encoding UTF8
$native=& (Join-Path $PSScriptRoot 'Invoke-PhotoshopJob.ps1') -TemplatePath (Join-Path $PSScriptRoot 'regional-definition.jsx') -ConfigPath $jobPath -PhotoshopProgId $PhotoshopProgId
@{skill='skc-ghost-mannequin';schema=3;method='Existing-pixel regional lens deblur with darken-only contribution';job=$job;photoshop_result=[string]$native;visual_status='pending_actual_file_review'} | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath (Join-Path $jobDir 'run.json') -Encoding UTF8
Write-Output $job.png
if(-not $PreviewOnly) { Write-Output $job.psd }
Write-Output (Join-Path $jobDir 'run.json')
