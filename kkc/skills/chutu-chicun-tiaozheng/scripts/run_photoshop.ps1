[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$RequestPath)
$ErrorActionPreference='Stop'
$utf8=New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding=$utf8
$OutputEncoding=$utf8
$requestAbsolute=[IO.Path]::GetFullPath($RequestPath)
$workerAbsolute=Join-Path (Split-Path -Parent $PSScriptRoot) 'assets\psd_source_worker.jsx'
$application=$null
$connected=$false
$response=$null
$mutex=$null
$ownsMutex=$false
$selectedProgId=$env:CHUTU_PHOTOSHOP_PROGID
if(-not $selectedProgId){$selectedProgId='Photoshop.Application'}
if($selectedProgId -notmatch '^Photoshop\.Application(?:\.[0-9]+)?$'){throw 'CHUTU_PHOTOSHOP_PROGID must be Photoshop.Application or a numeric version ProgID.'}
# PowerShell 7/.NET removed Marshal.GetActiveObject. The fixed P/Invoke shim
# attaches to the ROT in both Windows PowerShell and modern PowerShell.
if(-not ('CodexNativePhotoshopCom' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class CodexNativePhotoshopCom {
    [DllImport("ole32.dll", CharSet=CharSet.Unicode)]
    private static extern int CLSIDFromProgID(string progId, out Guid clsid);
    [DllImport("oleaut32.dll", PreserveSig=false)]
    private static extern void GetActiveObject(ref Guid clsid, IntPtr reserved, [MarshalAs(UnmanagedType.IUnknown)] out object value);
    public static object Get(string progId) {
        Guid clsid;
        Marshal.ThrowExceptionForHR(CLSIDFromProgID(progId, out clsid));
        object value; GetActiveObject(ref clsid, IntPtr.Zero, out value); return value;
    }
}
'@
}
try {
    if(-not (Test-Path -LiteralPath $requestAbsolute -PathType Leaf)){throw 'Native PSD request JSON does not exist.'}
    if(-not (Test-Path -LiteralPath $workerAbsolute -PathType Leaf)){throw 'Fixed native PSD JSX worker is missing.'}
    $request=Get-Content -LiteralPath $requestAbsolute -Raw -Encoding UTF8 | ConvertFrom-Json
    $response=[IO.Path]::GetFullPath([string]$request.response_path)
    if([IO.Path]::GetDirectoryName($response) -ne [IO.Path]::GetDirectoryName($requestAbsolute)){throw 'Native PSD response must stay beside the request.'}
    if($request.action -notin @('render','group','test_fixture')){throw 'Unsupported native PSD worker action.'}
    if($request.photoshop_progid -and $request.photoshop_progid -ne $selectedProgId){throw 'Photoshop ProgID changed after the request was prepared.'}
    $mutex=New-Object System.Threading.Mutex($false,'Local\CodexChutuNativePhotoshop')
    $ownsMutex=$mutex.WaitOne(150000)
    if(-not $ownsMutex){throw 'Another native Photoshop task is still running.'}
    try {$application=[CodexNativePhotoshopCom]::Get($selectedProgId)}
    catch {$application=New-Object -ComObject $selectedProgId}
    $connected=$true
    # Paths are separate COM arguments; no request text is interpolated as JSX.
    $arguments=[object[]]@($requestAbsolute)
    $null=$application.DoJavaScriptFile($workerAbsolute,$arguments,3)
    if(-not (Test-Path -LiteralPath $response -PathType Leaf)){throw 'Photoshop did not create a response JSON.'}
    $result=Get-Content -LiteralPath $response -Raw -Encoding UTF8 | ConvertFrom-Json
    if(-not $result.ok){throw ([string]$result.error)}
    Write-Output (@{ok=$true;progid=$selectedProgId;photoshop_version=[string]$application.Version}|ConvertTo-Json -Compress)
}
catch {
    if($response -and -not (Test-Path -LiteralPath $response)) {
        $code=if($connected){'PHOTOSHOP_COM_ERROR'}else{'PHOTOSHOP_UNAVAILABLE'}
        $failure=@{ok=$false;code=$code;error=$_.Exception.Message}
        [IO.File]::WriteAllText($response,($failure|ConvertTo-Json -Depth 20),$utf8)
    }
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 2
}
finally {
    if($application -and [Runtime.InteropServices.Marshal]::IsComObject($application)) {
        $null=[Runtime.InteropServices.Marshal]::FinalReleaseComObject($application)
    }
    if($ownsMutex){$mutex.ReleaseMutex()}
    if($mutex){$mutex.Dispose()}
}
