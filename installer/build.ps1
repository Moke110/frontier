param(
    [Parameter(Mandatory=$true)][string]$Zig,
    [Parameter(Mandatory=$true)][string]$ISCC,
    [string]$Version = '0.1.0-preview.1'
)
$ErrorActionPreference = 'Stop'
if ($Version -notmatch '^([0-9]+)\.([0-9]+)\.([0-9]+)(-[A-Za-z0-9.-]+)?$') { throw 'Invalid version' }
$NumericVersion = "$($Matches[1]).$($Matches[2]).$($Matches[3]).0"
if ((& $Zig version) -ne '0.13.0') { throw 'Zig 0.13.0 required' }
Push-Location $PSScriptRoot
try {
    New-Item -ItemType Directory -Force build | Out-Null
    $VersionNumbers = $NumericVersion.Replace('.', ',')
    & $Zig rc /fo build/frontier.res "/dVERSION_TEXT=`"$Version`"" "/dVERSION_NUMBERS=$VersionNumbers" frontier.rc
    if ($LASTEXITCODE) { throw 'Version resource compilation failed' }
    & $Zig cc -target x86_64-windows-gnu -O2 -s frontier.c build/frontier.res -o build/Frontier.exe
    if ($LASTEXITCODE) { throw 'Native compilation failed' }
    $CompilerOutput = & $ISCC "/DAppVersion=$Version" "/DNumericVersion=$NumericVersion" frontier.iss
    $CompilerOutput | Write-Output
    if ($LASTEXITCODE) { throw 'Installer compilation failed' }
    if (($CompilerOutput -join "
") -notmatch 'Compiler engine version: Inno Setup 6\.4\.3(?:\r?\n|$)') { throw 'Inno Setup 6.4.3 required' }
    Get-ChildItem output/*.exe | Get-FileHash -Algorithm SHA256
} finally { Pop-Location }




