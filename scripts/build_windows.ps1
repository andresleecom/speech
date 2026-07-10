param(
    [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "python"
}

$version = $env:SPEECH_VERSION
if ([string]::IsNullOrWhiteSpace($version)) {
    $version = & $Python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
}
if (-not $version) {
    throw "Could not determine project version."
}

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

function Invoke-PyInstaller {
    & $Python -m PyInstaller --noconfirm --clean packaging\Speech.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed."
    }
}

if (-not [string]::IsNullOrWhiteSpace($env:SPEECH_VERSION)) {
    $buildVersionPath = [System.IO.Path]::GetFullPath(
        (Join-Path $PSScriptRoot "..\src\winwhisper\_build_version.py")
    )
    $originalBuildVersion = [System.IO.File]::ReadAllText($buildVersionPath)
    try {
        & $Python (Join-Path $PSScriptRoot "write_build_version.py") $version
        if ($LASTEXITCODE -ne 0) {
            throw "Could not write the packaged build version."
        }
        Invoke-PyInstaller
    } finally {
        [System.IO.File]::WriteAllText(
            $buildVersionPath,
            $originalBuildVersion,
            [System.Text.UTF8Encoding]::new($false)
        )
    }
} else {
    Invoke-PyInstaller
}

$env:APP_VERSION = $version
& $iscc installer\Speech.iss

$installer = Get-ChildItem -Path dist\installer -Filter "Speech-Setup-$version.exe" | Select-Object -First 1
if ($null -eq $installer) {
    throw "Installer was not created."
}

function Write-InstallerChecksum {
    param(
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$InstallerFile
    )

    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $InstallerFile.FullName).Hash.ToLowerInvariant()
    $checksumPath = "$($InstallerFile.FullName).sha256"
    "$hash  $($InstallerFile.Name)" | Set-Content -LiteralPath $checksumPath -Encoding ascii
    return $checksumPath
}

$versionedChecksumPath = Write-InstallerChecksum -InstallerFile $installer

$stableInstallerPath = Join-Path $installer.DirectoryName "Speech-Setup.exe"
Copy-Item -LiteralPath $installer.FullName -Destination $stableInstallerPath -Force
$stableInstaller = Get-Item -LiteralPath $stableInstallerPath
$stableChecksumPath = Write-InstallerChecksum -InstallerFile $stableInstaller

Write-Host "Built $($installer.FullName)"
Write-Host "Built $($stableInstaller.FullName)"
Write-Host "Wrote $versionedChecksumPath"
Write-Host "Wrote $stableChecksumPath"
