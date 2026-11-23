param(
    [Parameter(Mandatory=$true)][string]$InputImage,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$OutputStem = 'skc_ai_candidate',
    [ValidateRange(1,4)][double]$FinalScale = 2,
    [ValidateSet(64,128,256,512)][int]$TileSize = 256,
    [int]$GpuId = 0,
    [string]$PhotoshopProgId = 'Photoshop.Application'
)
$ErrorActionPreference = 'Stop'
$inputPath = (Resolve-Path -LiteralPath $InputImage).Path
$extension = [IO.Path]::GetExtension($inputPath).ToLowerInvariant()
if ($extension -notin @('.png','.jpg','.jpeg')) { throw 'Use a flattened RGB PNG or JPG input.' }
$outDir = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $outDir -Force | Out-Null
$png = Join-Path $outDir ($OutputStem + '.png')
$jpg = Join-Path $outDir ($OutputStem + '.jpg')
if ((Test-Path -LiteralPath $png) -or (Test-Path -LiteralPath $jpg)) { throw 'Output already exists. Choose a new OutputStem.' }
Add-Type -AssemblyName System.Drawing
$probe = [Drawing.Image]::FromFile($inputPath)
try { $width = $probe.Width; $height = $probe.Height } finally { $probe.Dispose() }
$finalWidth = [int][Math]::Round($width * $FinalScale)
$finalHeight = [int][Math]::Round($height * $FinalScale)
$runDir = Join-Path $outDir ('work\whole_' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $runDir 'models') -Force | Out-Null
$runtime = Join-Path (Split-Path $PSScriptRoot -Parent) 'runtime\windows-x64'
foreach ($name in @('realesrgan-ncnn-vulkan.exe','vcomp140.dll')) {
    Copy-Item -LiteralPath (Join-Path $runtime $name) -Destination (Join-Path $runDir $name)
}
foreach ($name in @('ultrasharp-4x.bin','ultrasharp-4x.param')) {
    Copy-Item -LiteralPath (Join-Path $runtime ('models\' + $name)) -Destination (Join-Path $runDir ('models\' + $name))
}
$sourceName = 'source' + $extension
Copy-Item -LiteralPath $inputPath -Destination (Join-Path $runDir $sourceName)
Write-Output "Running native 4x AI on full source $width x $height. Logs: $runDir"
$process = Start-Process -FilePath (Join-Path $runDir 'realesrgan-ncnn-vulkan.exe') -ArgumentList @('-i',$sourceName,'-o','native4x.png','-m','models','-n','ultrasharp-4x','-s','4','-t',"$TileSize",'-g',"$GpuId",'-j','1:1:1') -WorkingDirectory $runDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runDir 'stdout.log') -RedirectStandardError (Join-Path $runDir 'stderr.log') -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "AI engine failed (exit $($process.ExitCode)). Read logs in $runDir" }
$raw = Join-Path $runDir 'native4x.png'
if (-not (Test-Path -LiteralPath $raw)) { throw 'AI engine did not produce native4x.png.' }
$config = @{
    input = $raw; png = $png; jpg = $jpg
    expected_width = $width * 4; expected_height = $height * 4
    width = $finalWidth; height = $finalHeight
}
$configPath = Join-Path $runDir 'photoshop-job.json'
$config | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $configPath -Encoding UTF8
$native = & (Join-Path $PSScriptRoot 'Invoke-PhotoshopJob.ps1') -TemplatePath (Join-Path $PSScriptRoot 'resize-export.jsx') -ConfigPath $configPath -PhotoshopProgId $PhotoshopProgId
@{
    source = $inputPath; source_size = @($width,$height); final_size = @($finalWidth,$finalHeight)
    native_scale = 4; final_scale = $FinalScale; model = 'UltraSharp 4x'; processed_locally = $true; candidate_only = $true; visual_status = 'unreviewed'
    photoshop_result = [string]$native; work_directory = $runDir; png = $png; jpg = $jpg
} | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $outDir ($OutputStem + '_run.json')) -Encoding UTF8
Write-Output $png
Write-Output $jpg
Write-Output 'Candidate only. Inspect materials and use Invoke-WholeImage.ps1 with a reviewed region profile before delivery.'
