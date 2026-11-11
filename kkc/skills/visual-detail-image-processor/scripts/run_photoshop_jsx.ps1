param(
    [Parameter(Mandatory = $true)]
    [string]$JsxPath
)

$resolved = Resolve-Path -LiteralPath $JsxPath -ErrorAction Stop
$app = New-Object -ComObject Photoshop.Application
$app.Visible = $true
$app.DoJavaScriptFile($resolved.Path)
