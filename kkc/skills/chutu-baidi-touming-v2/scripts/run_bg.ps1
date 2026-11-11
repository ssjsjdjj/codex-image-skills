$ForwardArgs = @($args)
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$SkillDirectory = Split-Path -Parent $PSScriptRoot
$ConfigFile = Join-Path $SkillDirectory 'runtime.json'
if (-not (Test-Path -LiteralPath $ConfigFile)) { throw '缺少 runtime.json，请先完成本技能安装和验收。' }
$RuntimeConfig = Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not (Test-Path -LiteralPath $RuntimeConfig.python)) { throw '专用 Python 不存在，请重新运行安装流程。' }
& $RuntimeConfig.python (Join-Path $PSScriptRoot 'launch.py') @ForwardArgs
exit $LASTEXITCODE
