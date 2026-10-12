param(
    [Parameter(Mandatory=$true)][string]$BuildRoot,
    [Parameter(Mandatory=$true)][string]$SwiftSdk,
    [Parameter(Mandatory=$true)][string]$VisualStudioDirectory
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$sourceRoot = Join-Path $BuildRoot 'myime/src/swift-engine'
$swiftRoot = Join-Path $BuildRoot 'swift'
$swiftBin = Join-Path $swiftRoot 'LocalApp/Programs/Swift/Toolchains/6.3.3+Asserts/usr/bin'
$vcvars = (Resolve-Path (Join-Path $VisualStudioDirectory 'VC/Auxiliary/Build/vcvarsall.bat')).Path
$SwiftSdk = (Resolve-Path $SwiftSdk).Path
$versions = Get-Content (Join-Path $projectRoot 'versions.json') -Raw | ConvertFrom-Json
$commit = & git -C (Join-Path $BuildRoot 'myime') rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $commit -ne $versions.myime.commit) { throw 'Unexpected source checkout.' }
if ((Get-FileHash (Join-Path $sourceRoot 'Package.resolved')).Hash -ne
    (Get-FileHash (Join-Path $projectRoot 'tools/swift-Package.resolved')).Hash) {
    throw 'Swift dependency lock differs from the recorded build.'
}
$names = @('PATH','SDKROOT','INCLUDE','LIB','LIBPATH','VCToolsInstallDir','VCToolsVersion',
           'WindowsSdkDir','WindowsSDKVersion','UniversalCRTSdkDir','UCRTVersion',
           'VSINSTALLDIR','VCINSTALLDIR','VSCMD_ARG_TGT_ARCH')
$saved = @{}
foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    $environment = & cmd.exe /d /s /c ('"' + $vcvars + '" x64 >nul && set')
    if ($LASTEXITCODE -ne 0) { throw 'Visual Studio environment preparation failed.' }
    foreach ($line in $environment) {
        $pair = $line -split '=', 2
        if ($pair.Count -eq 2 -and $pair[0] -in $names) {
            [Environment]::SetEnvironmentVariable($pair[0], $pair[1], 'Process')
        }
    }
    $env:PATH = "$swiftBin;$swiftRoot;$env:PATH"
    $env:SDKROOT = $SwiftSdk # Package manifest compilation also needs this.
    Push-Location $sourceRoot
    try {
        & (Join-Path $swiftBin 'swift.exe') build -c release --sdk $SwiftSdk --jobs 16 -Xswiftc -suppress-warnings
        if ($LASTEXITCODE -ne 0) { throw 'Swift conversion engine build failed.' }
    } finally { Pop-Location }
    $dll = Join-Path $sourceRoot '.build/x86_64-unknown-windows-msvc/release/azookey-engine.dll'
    Copy-Item -LiteralPath $dll -Destination (Join-Path $BuildRoot 'myime/build/x64/release/azookey-engine.dll') -Force
    Get-FileHash -Algorithm SHA256 $dll
    # The result is staged only in the build directory; it is not installed or adopted here.
} finally {
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
}
