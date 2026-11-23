param(
    [Parameter(Mandatory=$true)][string]$TemplatePath,
    [Parameter(Mandatory=$true)][string]$ConfigPath,
    [string]$PhotoshopProgId = 'Photoshop.Application'
)
$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$template = Get-Content -LiteralPath $TemplatePath -Raw -Encoding UTF8
$script = 'var SUPER_CLARITY_CONFIG = ' + ($config | ConvertTo-Json -Depth 30 -Compress) + ";`n" + $template
try { $photoshop = [Runtime.InteropServices.Marshal]::GetActiveObject($PhotoshopProgId) }
catch { $photoshop = New-Object -ComObject $PhotoshopProgId }
$nativeResult = $photoshop.DoJavaScript($script)
if (-not ([string]$nativeResult).StartsWith('OK|')) { throw "Unexpected Photoshop result: $nativeResult" }
Write-Output $nativeResult
