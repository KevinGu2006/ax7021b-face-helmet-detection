param([string]$Vivado = 'vivado')
$ErrorActionPreference = 'Stop'
if ($Vivado -eq 'vivado') {
    $tool = Get-Command vivado -ErrorAction SilentlyContinue
    if (-not $tool) { throw 'Vivado is not in PATH; pass -Vivado with the Vivado 2025.2 executable path.' }
    $Vivado = $tool.Source
}
if (-not (Test-Path -LiteralPath $Vivado)) { throw "Vivado executable not found: $Vivado" }
Push-Location $PSScriptRoot
try {
    & $Vivado -mode batch -source (Join-Path $PSScriptRoot 'verify.tcl')
    if ($LASTEXITCODE -ne 0) { throw "Vivado failed with exit code $LASTEXITCODE" }
} finally { Pop-Location }
