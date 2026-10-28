# Windows PowerShell 5.1 / PowerShell 7. Offline wrapper for Dell's signed updater.
# Examples (Administrator PowerShell):
#   .\flash_tb16.ps1 -Action Info
#   .\flash_tb16.ps1 -Action Update
[CmdletBinding()]
param(
    [ValidateSet('Info', 'Update')]
    [string]$Action = 'Info',
    [string]$LogPath = (Join-Path ([IO.Path]::GetTempPath()) ('TB16-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log'))
)

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'This wrapper requires Windows. The extractor can run on macOS/Linux.'
}
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$updater = Join-Path $repoRoot 'official\DellDockingStationFwUp_1.0.0_03192018_TB16.exe'
$expectedHash = 'ff9f2fa9b6a56ba000b57d1cbe29b0a5fbe3e563b3d0ac95c67198e7649db4e1'
if (!(Test-Path -LiteralPath $updater -PathType Leaf)) {
    throw "Missing original Dell updater: $updater"
}
if ((Get-FileHash -LiteralPath $updater -Algorithm SHA256).Hash -ne $expectedHash) {
    throw 'Updater SHA-256 differs from Dell release H3YG7. Refusing to run it.'
}
$system = Get-CimInstance Win32_ComputerSystem
$os = Get-CimInstance Win32_OperatingSystem
Write-Host ("Host: {0} {1}; OS: {2}" -f $system.Manufacturer, $system.Model, $os.Caption)
if ($system.Manufacturer -notmatch '^Dell\b') {
    throw 'The TB16 PD/EC BIOS update path requires Dell host firmware. A Windows wrapper cannot enable it on a non-Dell host. No updater was launched.'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script from an Administrator PowerShell window; the Dell utility requires administrator rights.'
}
if ($LogPath.Contains('"') -or $LogPath.Contains("`r") -or $LogPath.Contains("`n")) {
    throw 'LogPath cannot contain quotes or newlines.'
}
$LogPath = [IO.Path]::GetFullPath($LogPath)
if (!(Test-Path -LiteralPath (Split-Path $LogPath -Parent) -PathType Container)) {
    throw 'The log directory must already exist.'
}
Write-Host 'Uses the original signed package. Standalone extracted BINs are not flash inputs.'
Write-Host 'Dell model/BIOS compatibility is checked by the vendor utility; Windows 11 is unvalidated.'
$updaterArgs = @('/l="' + $LogPath + '"')
if ($Action -eq 'Info') {
    $updaterArgs = @('/componentsvers') + $updaterArgs
    Write-Host 'Requesting component versions only.'
} else {
    Write-Host 'Opening the interactive Dell updater. Keep dock AC and its host cable connected through the requested restart.'
    Write-Host 'The utility may update other packaged components too. No force/downgrade or automatic restart switches are used.'
}
$process = Start-Process -FilePath $updater -ArgumentList $updaterArgs -Wait -PassThru
Write-Host ("Dell utility exit code: {0}. Log: {1}" -f $process.ExitCode, $LogPath)
Write-Host 'Use the vendor result and log to determine success; a process exit alone does not verify a BIOS-stage flash.'
if ($Action -eq 'Update') {
    Write-Host 'After any requested restart and completed update, power-cycle the dock and run -Action Info again.'
}
exit $process.ExitCode
