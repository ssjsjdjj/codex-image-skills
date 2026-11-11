$ForwardArgs = @($args)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$SkillDirectory = Split-Path -Parent $PSScriptRoot
$Config = Get-Content -LiteralPath (Join-Path $SkillDirectory 'runtime.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not (Test-Path -LiteralPath $Config.python)) { throw '专用Python不存在，请先修复本技能安装环境。' }
& $Config.python (Join-Path $PSScriptRoot 'user_profile.py') @ForwardArgs
exit $LASTEXITCODE
