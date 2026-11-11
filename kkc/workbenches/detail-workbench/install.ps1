[CmdletBinding()]
param([switch]$CheckOnly)

$ErrorActionPreference = 'Stop'
# Prefer this PowerShell's inbox modules when called through a .cmd from PowerShell 7.
$env:PSModulePath = [IO.Path]::Combine($PSHOME, 'Modules') + [IO.Path]::PathSeparator + $env:PSModulePath
$appFolder = $PSScriptRoot
$venvFolder = Join-Path $appFolder '.venv'
$venvPython = Join-Path $venvFolder 'Scripts\python.exe'
$localPrograms = Join-Path $env:LOCALAPPDATA 'Programs'
$managedPythonFolder = Join-Path $localPrograms 'KocoDetailWorkbench\Python314'
$managedPython = Join-Path $managedPythonFolder 'python.exe'
$pythonProbe = "import sys, tkinter, venv, ensurepip; assert sys.implementation.name == 'cpython' and (3, 10) <= sys.version_info[:2] < (3, 15); tkinter.Tcl().eval('info patchlevel'); print(sys.version.split()[0])"
$pillowProbe = "import PIL; from PIL import Image, ImageTk; assert PIL.__version__ == '12.3.0'; print(PIL.__version__)"
$fontFolder = Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\Fonts'
$userFontKey = 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts'
$machineFontKey = 'HKLM:\Software\Microsoft\Windows NT\CurrentVersion\Fonts'
$fonts = @(
    @{ File = 'cn.ttf'; ValueName = 'FZLanTingHei-DB-GBK (TrueType)'; RegisteredFile = 'fzltzhk.ttf'; PostScript = 'FZLTZHK--GBK1-0' },
    @{ File = 'latin.otf'; ValueName = 'G8321 Medium (TrueType)'; RegisteredFile = 'G8321-Medium.otf'; PostScript = 'G8321-Medium' },
    @{ File = 'digit.ttf'; ValueName = 'Koco Detail FangYuan (TrueType)'; RegisteredFile = 'KocoDetailFangYuan-SemiBold.ttf'; PostScript = 'KocoDetailFangYuan-SemiBold' }
)

$additionalFonts = Join-Path $appFolder 'fonts\additional-fonts.json'
if (Test-Path -LiteralPath $additionalFonts -PathType Leaf) {
    $fontEntries = ConvertFrom-Json -InputObject (Get-Content -LiteralPath $additionalFonts -Raw -Encoding UTF8)
    foreach ($font in $fontEntries) {
        if ($font.File -isnot [string] -or $font.File -notmatch '^[a-zA-Z0-9_-]+\.(ttf|otf|ttc)$' -or
            !$font.ValueName -or !$font.RegisteredFile -or !$font.PostScript) {
            throw 'The bundled additional-fonts.json contains an invalid font entry.'
        }
        $fonts += @{ File = $font.File; ValueName = $font.ValueName;
            RegisteredFile = $font.RegisteredFile; PostScript = $font.PostScript }
    }
}

function Invoke-PythonProbe($Executable, $Code) {
    if (!$Executable -or !(Test-Path -LiteralPath $Executable -PathType Leaf)) { return }
    $ErrorActionPreference = 'Continue'
    $output = & $Executable -I -B -c $Code 2>$null
    if ($LASTEXITCODE -eq 0) { return $output }
}

function Find-BasePython {
    $candidates = @($managedPython)
    $candidates += @(Get-Command python.exe -All -CommandType Application -ErrorAction SilentlyContinue |
        ForEach-Object { $_.Source })
    $pythonKeys = @('HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore',
        'HKLM:\Software\WOW6432Node\Python\PythonCore')
    foreach ($key in $pythonKeys) {
        foreach ($entry in Get-ChildItem -LiteralPath $key -ErrorAction SilentlyContinue) {
            $installed = Get-Item -LiteralPath ($entry.PSPath + '\InstallPath') -ErrorAction SilentlyContinue
            if (!$installed) { continue }
            $path = $installed.GetValue('ExecutablePath')
            if (!$path -and $installed.GetValue('')) { $path = Join-Path ($installed.GetValue('')) 'python.exe' }
            if ($path) { $candidates += $path }
        }
    }
    foreach ($path in $candidates | Select-Object -Unique) {
        # Skip the Windows Store alias. Probing an alias can open the Store.
        if ($path -match '\\Microsoft\\WindowsApps\\') { continue }
        if (Invoke-PythonProbe $path $pythonProbe) { return $path }
    }
}

function Install-BasePython {
    $arch = $env:PROCESSOR_ARCHITEW6432
    if (!$arch) { $arch = $env:PROCESSOR_ARCHITECTURE }
    # Official Windows release downloads and SHA-256 checksums:
    # https://www.python.org/downloads/release/python-31410/
    $downloads = @{
        AMD64 = @('python-3.14.10-amd64.exe', '92480239264744fe0386a1bd8275786fefa126e3129e56a68e22b52c73329965')
        ARM64 = @('python-3.14.10-arm64.exe', '5b9547e4edae2f6fb2fbfec5e26cf91b4ea191e3b07f7727d5a2c5c2cca93ed3')
        x86 = @('python-3.14.10.exe', 'c8f1a16db9afd76ca74b5f8e28eeaad408bca10894c9d080443bde83def3ed09')
    }
    if (!$arch -or !$downloads.ContainsKey($arch)) { throw "Unsupported Windows architecture: $arch" }
    $file, $hash = $downloads[$arch]
    $installer = Join-Path ([IO.Path]::GetTempPath()) ('KocoWorkbench-' + [Guid]::NewGuid().ToString('N') + '-' + $file)
    try {
        Write-Host "Downloading official Python 3.14.10 ($arch)..."
        $ProgressPreference = 'SilentlyContinue'
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/ftp/python/3.14.10/$file" -OutFile $installer
        if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne $hash) {
            throw 'The Python installer did not match the official SHA-256 checksum.'
        }
        Write-Host 'Installing Python for the current Windows user...'
        $arguments = '/quiet InstallAllUsers=0 Include_launcher=0 Include_test=0 Include_doc=0 Include_tcltk=1 Include_pip=1 PrependPath=0 Shortcuts=0 TargetDir="' + $managedPythonFolder + '"'
        $process = Start-Process -FilePath $installer -ArgumentList $arguments -WindowStyle Hidden -PassThru -Wait
        if ($process.ExitCode -ne 0) { throw "Python installer exited with code $($process.ExitCode)." }
        $installed = Find-BasePython
        if (!$installed) { throw 'Python installation completed, but Python with working Tcl/Tk was not found.' }
        return $installed
    } finally {
        if (Test-Path -LiteralPath $installer -PathType Leaf) { Remove-Item -LiteralPath $installer }
    }
}

function Get-FontRegistration($Font) {
    foreach ($keyPath in @($userFontKey, $machineFontKey)) {
        $key = Get-Item -LiteralPath $keyPath -ErrorAction SilentlyContinue
        if (!$key) { continue }
        $value = $key.GetValue($Font.ValueName)
        if (!$value) {
            # Windows can use a localized label when the same face was installed manually.
            $value = $key.GetValueNames() | ForEach-Object { $key.GetValue($_) } |
                Where-Object { $_ -is [string] -and [IO.Path]::GetFileName($_) -eq $Font.RegisteredFile } |
                Select-Object -First 1
        }
        if (!$value) { continue }
        $path = [Environment]::ExpandEnvironmentVariables([string]$value)
        if (![IO.Path]::IsPathRooted($path)) {
            $directory = if ($keyPath -eq $userFontKey) { $fontFolder } else { Join-Path $env:WINDIR 'Fonts' }
            $path = Join-Path $directory $path
        }
        if (Test-Path -LiteralPath $path -PathType Leaf) { return $path }
    }
}

function Install-WorkbenchFonts {
    if (!('KocoWorkbench.NativeFonts' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace KocoWorkbench {
    public static class NativeFonts {
        [DllImport("gdi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern int AddFontResourceExW(string path, uint flags, IntPtr reserved);
        [DllImport("user32.dll", SetLastError = true)]
        public static extern IntPtr SendMessageTimeoutW(IntPtr window, uint message, UIntPtr wparam,
            IntPtr lparam, uint flags, uint timeout, out UIntPtr result);
    }
}
'@
    }
    $null = New-Item -ItemType Directory -Path $fontFolder -Force
    if (!(Test-Path -LiteralPath $userFontKey)) { $null = New-Item -Path $userFontKey -Force }
    $changed = $false
    foreach ($font in $fonts) {
        $source = Join-Path $appFolder ('fonts\' + $font.File)
        $expected = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
        $destination = Join-Path $fontFolder ('KocoDetailWorkbench-' + $font.File)
        $registration = Get-FontRegistration $font
        if ($registration) {
            if ($registration -eq $destination -and (Get-FileHash -LiteralPath $registration -Algorithm SHA256).Hash -ne $expected) {
                throw "Existing workbench font file differs: $destination"
            }
            Write-Host "Font already installed: $($font.PostScript)"
            continue
        }
        if (Test-Path -LiteralPath $destination -PathType Leaf) {
            if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $expected) {
                throw "Existing font file differs: $destination"
            }
        } else {
            Copy-Item -LiteralPath $source -Destination $destination
        }
        if ([KocoWorkbench.NativeFonts]::AddFontResourceExW($destination, 0, [IntPtr]::Zero) -le 0) {
            throw "Windows did not load font $($font.PostScript)."
        }
        $null = New-ItemProperty -LiteralPath $userFontKey -Name $font.ValueName -Value $destination -PropertyType String -Force
        $changed = $true
        Write-Host "Installed font: $($font.PostScript)"
    }
    if ($changed) {
        $result = [UIntPtr]::Zero
        $null = [KocoWorkbench.NativeFonts]::SendMessageTimeoutW([IntPtr]0xffff, 0x001d, [UIntPtr]::Zero,
            [IntPtr]::Zero, 2, 250, [ref]$result)
    }
}

$log = Join-Path $appFolder 'install.log'
$transcript = $false
$exitCode = 0
try {
    if (!$CheckOnly) {
        $null = Start-Transcript -Path $log -Force
        $transcript = $true
    }
    foreach ($font in $fonts) {
        if (!(Test-Path -LiteralPath (Join-Path $appFolder ('fonts\' + $font.File)) -PathType Leaf)) {
            throw "Missing bundled font: fonts\$($font.File). Extract the entire ZIP before running setup."
        }
    }
    $pythonVersion = Invoke-PythonProbe $venvPython $pythonProbe
    if ($CheckOnly) {
        $base = if ($pythonVersion) { $venvPython } else { Find-BasePython }
        if ($base) { Write-Host "Compatible Python: $base" } else { Write-Host 'Compatible Python with Tcl/Tk: not found' }
        $pillowVersion = Invoke-PythonProbe $venvPython $pillowProbe
        if ($pythonVersion -and $pillowVersion) { Write-Host "Workbench environment: Python $pythonVersion, Pillow $pillowVersion" }
        else { Write-Host 'Workbench environment: run install.cmd'; $exitCode = 1 }
        foreach ($font in $fonts) {
            $registered = Get-FontRegistration $font
            $source = Join-Path $appFolder ('fonts\' + $font.File)
            $destination = Join-Path $fontFolder ('KocoDetailWorkbench-' + $font.File)
            if ($registered -and ($registered -ne $destination -or (Get-FileHash -LiteralPath $registered).Hash -eq (Get-FileHash -LiteralPath $source).Hash)) {
                Write-Host "Font ready: $($font.PostScript)"
            } else { Write-Host "Font needs setup: $($font.PostScript)"; $exitCode = 1 }
        }
    } else {
        if (!$pythonVersion) {
            $base = Find-BasePython
            if (!$base) { $base = Install-BasePython }
            Write-Host "Preparing a workbench environment from $base ..."
            & $base -I -m venv $venvFolder
            if ($LASTEXITCODE -ne 0) { throw 'Could not create the workbench environment in this folder.' }
            $pythonVersion = Invoke-PythonProbe $venvPython $pythonProbe
            if (!$pythonVersion) { throw 'The workbench environment could not load Tcl/Tk.' }
        }
        if (!(Invoke-PythonProbe $venvPython $pillowProbe)) {
            Write-Host 'Installing Pillow 12.3.0 from PyPI...'
            & $venvPython -I -m pip --isolated install --disable-pip-version-check --only-binary=:all: --index-url https://pypi.org/simple 'Pillow==12.3.0'
            if ($LASTEXITCODE -ne 0 -or !(Invoke-PythonProbe $venvPython $pillowProbe)) { throw 'Could not install Pillow 12.3.0.' }
        }
        Install-WorkbenchFonts
        Write-Host 'Setup complete. Double-click start.cmd to open the workbench.'
        Write-Host 'Restart desktop Photoshop if it was open during font setup.'
    }
} catch {
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    if ($transcript) { Write-Host "Setup log: $log" }
    $exitCode = 1
} finally {
    if ($transcript) { $null = Stop-Transcript }
}
exit $exitCode
