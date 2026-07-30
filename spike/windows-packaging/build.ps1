[CmdletBinding()]
param(
    [string]$OutputRoot
)

$ErrorActionPreference = "Stop"
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $PSScriptRoot "out"
}
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$workRoot = Join-Path $PSScriptRoot "build"
$specPath = Join-Path $PSScriptRoot "serverops.spec"
$distPath = [System.IO.Path]::GetFullPath($OutputRoot)
$env:PYINSTALLER_CONFIG_DIR = Join-Path $workRoot "pyinstaller-cache"

uv run --locked --with "pyinstaller==6.21.0" pyinstaller `
    --noconfirm `
    --clean `
    --distpath $distPath `
    --workpath $workRoot `
    $specPath
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller spike build failed."
}

$runtime = Join-Path $distPath "ServerOps"
$smokeRoot = Join-Path $env:TEMP ("serverops-packaging-smoke-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $smokeRoot | Out-Null
try {
    Copy-Item -Recurse -LiteralPath $runtime -Destination $smokeRoot
    $savedPath = $env:PATH
    try {
        $env:PATH = "$env:WINDIR\System32"
        & (Join-Path $smokeRoot "ServerOps\serverops-install.exe") --version
        if ($LASTEXITCODE -ne 0) {
            throw "Frozen installer version smoke test failed."
        }
    }
    finally {
        $env:PATH = $savedPath
    }
}
finally {
    Remove-Item -Recurse -Force -LiteralPath $smokeRoot
}

Write-Host "Non-shipping ServerOps runtime spike built at $runtime"
