param(
    [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "python"
}

$version = & $Python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
if (-not $version) {
    throw "Could not determine project version."
}

& $Python -m PyInstaller --noconfirm --clean packaging\Speech.spec

$isccCommand = Get-Command iscc.exe -ErrorAction SilentlyContinue
if ($null -eq $isccCommand) {
    $candidate = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (Test-Path -LiteralPath $candidate) {
        $iscc = $candidate
    } else {
        throw "Inno Setup ISCC.exe was not found. Install Inno Setup 6 first."
    }
} else {
    $iscc = $isccCommand.Source
}

$env:APP_VERSION = $version
& $iscc installer\Speech.iss

$installer = Get-ChildItem -Path dist\installer -Filter "Speech-Setup-$version.exe" | Select-Object -First 1
if ($null -eq $installer) {
    throw "Installer was not created."
}

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installer.FullName).Hash.ToLowerInvariant()
$checksumPath = "$($installer.FullName).sha256"
"$hash  $($installer.Name)" | Set-Content -LiteralPath $checksumPath -Encoding ascii

Write-Host "Built $($installer.FullName)"
Write-Host "Wrote $checksumPath"
