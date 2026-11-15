#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$Python = "",
    [string]$ToolRoot = "",
    [string]$InnoCompiler = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = (Get-Item -LiteralPath $PSScriptRoot).FullName
$AppName = "VencordAutoRepair"
$Version = "0.4.0"
$RequiredSources = @("app.py", "gui.py", "app_runtime.py", "main.py", "startup_manager.py")
$BuildRoot = Join-Path $RepositoryRoot "build\pyinstaller"
$DistRoot = Join-Path $RepositoryRoot "dist"
$AppDirectory = Join-Path $DistRoot $AppName
$PortableZip = Join-Path $DistRoot "$AppName-$Version-win64-portable.zip"
$SetupExecutable = Join-Path $DistRoot "VencordAutoRepairSetup.exe"
$ChecksumFile = Join-Path $DistRoot "SHA256SUMS.txt"
$InnoVersion = "7.1.1"
$InnoInstallerUrl = "https://github.com/jrsoftware/issrc/releases/download/is-7_1_1/innosetup-7.1.1-x64.exe"
$InnoInstallerSha256 = "8a5a6711c3766a6e5fb74f280ba0e3551e719ce94538d901fdbd1f8f9920b3f0"

if (-not $ToolRoot) {
    $ToolRoot = Join-Path (Split-Path -Parent $RepositoryRoot) "tools"
}
$ToolRoot = [IO.Path]::GetFullPath($ToolRoot)

function Write-Step {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE"
    }
}

function Remove-RepositoryItem {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)

    $candidate = [IO.Path]::GetFullPath($LiteralPath)
    $repositoryPrefix = $RepositoryRoot.TrimEnd("\") + "\"
    if (-not $candidate.StartsWith($repositoryPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside the repository: $candidate"
    }
    if (Test-Path -LiteralPath $candidate) {
        Remove-Item -LiteralPath $candidate -Recurse -Force
    }
}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)

    return (Get-FileHash -LiteralPath $LiteralPath -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-VerifiedInnoInstaller {
    $cacheDirectory = Join-Path $ToolRoot "cache"
    $cachedInstaller = Join-Path $cacheDirectory "innosetup-$InnoVersion-x64.exe"
    New-Item -ItemType Directory -Force -Path $cacheDirectory | Out-Null

    if (-not (Test-Path -LiteralPath $cachedInstaller)) {
        Write-Step "Downloading official Inno Setup $InnoVersion"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $partial = "$cachedInstaller.partial"
        Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
        Invoke-WebRequest -Uri $InnoInstallerUrl -OutFile $partial -UseBasicParsing
        Move-Item -LiteralPath $partial -Destination $cachedInstaller -Force
    }

    $actualHash = Get-FileSha256 -LiteralPath $cachedInstaller
    if ($actualHash -ne $InnoInstallerSha256) {
        throw "Inno Setup download hash mismatch. Expected $InnoInstallerSha256, got $actualHash"
    }

    $signature = Get-AuthenticodeSignature -LiteralPath $cachedInstaller
    if ($signature.Status -ne "Valid") {
        throw "Inno Setup download has an invalid Authenticode signature: $($signature.Status)"
    }
    if ($signature.SignerCertificate.Subject -notmatch "Pyrsys B\.V\.") {
        throw "Unexpected Inno Setup signer: $($signature.SignerCertificate.Subject)"
    }
    return $cachedInstaller
}

function Find-InnoCompiler {
    if ($InnoCompiler) {
        $explicitCompiler = [IO.Path]::GetFullPath($InnoCompiler)
        if (-not (Test-Path -LiteralPath $explicitCompiler -PathType Leaf)) {
            throw "Inno compiler not found: $explicitCompiler"
        }
        return $explicitCompiler
    }

    $portableDirectory = Join-Path $ToolRoot "inno-$InnoVersion"
    $portableCompiler = Join-Path $portableDirectory "ISCC.exe"
    if (Test-Path -LiteralPath $portableCompiler -PathType Leaf) {
        return $portableCompiler
    }

    $installedCandidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 7\ISCC.exe"),
        (Join-Path ${env:ProgramFiles} "Inno Setup 7\ISCC.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 7\ISCC.exe")
    )
    foreach ($candidate in $installedCandidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            $candidateVersion = (Get-Item -LiteralPath $candidate).VersionInfo.ProductVersion
            if ($candidateVersion -like "$InnoVersion*") {
                return $candidate
            }
        }
    }

    $installer = Get-VerifiedInnoInstaller
    Write-Step "Installing verified Inno Setup $InnoVersion in portable mode"
    $argumentLine = "/PORTABLE=1 /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=`"$portableDirectory`""
    $process = Start-Process -FilePath $installer -ArgumentList $argumentLine -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "Inno Setup portable extraction failed with exit code $($process.ExitCode)"
    }
    if (-not (Test-Path -LiteralPath $portableCompiler -PathType Leaf)) {
        throw "Inno Setup completed but ISCC.exe was not found in $portableDirectory"
    }
    return $portableCompiler
}

try {
    if (-not $Python) {
        $Python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
    } elseif (-not [IO.Path]::IsPathRooted($Python)) {
        $Python = Join-Path $RepositoryRoot $Python
    }
    $Python = [IO.Path]::GetFullPath($Python)
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "Python executable not found: $Python"
    }

    Write-Step "Checking build sources and dependencies"
    foreach ($source in $RequiredSources) {
        $sourcePath = Join-Path $RepositoryRoot $source
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            throw "Required source is missing: $source"
        }
    }
    $requiredArtifacts = @(
        (Join-Path $RepositoryRoot "assets\VencordAutoRepair.ico"),
        (Join-Path $RepositoryRoot "assets\VencordAutoRepair.png"),
        (Join-Path $RepositoryRoot "assets\version_info.txt"),
        (Join-Path $RepositoryRoot "installer\VencordAutoRepair.iss")
    )
    foreach ($artifact in $requiredArtifacts) {
        if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) {
            throw "Required build asset is missing: $artifact"
        }
    }

    $dependencyCheck = @'
from importlib.metadata import version

expected = {
    "pyinstaller": "6.16.0",
    "pyinstaller-hooks-contrib": "2026.10",
    "pillow": "11.3.0",
    "psutil": "7.0.0",
    "requests": "2.34.2",
    "pywin32": "311",
}
actual = {name: version(name) for name in expected}
mismatches = [f"{name}: expected {wanted}, got {actual[name]}" for name, wanted in expected.items() if actual[name] != wanted]
if mismatches:
    raise SystemExit("Dependency mismatch:\n" + "\n".join(mismatches))
print("Pinned build/runtime dependencies verified")
'@
    Invoke-Native -FilePath $Python -Arguments @("-m", "pip", "check")
    Invoke-Native -FilePath $Python -Arguments @("-c", $dependencyCheck)

    Write-Step "Running the test suite"
    Invoke-Native -FilePath $Python -Arguments @(
        "-m", "unittest", "discover",
        "-s", $RepositoryRoot,
        "-p", "test*.py",
        "-v"
    )

    Write-Step "Cleaning generated release outputs"
    Remove-RepositoryItem -LiteralPath $BuildRoot
    Remove-RepositoryItem -LiteralPath $AppDirectory
    Remove-RepositoryItem -LiteralPath $PortableZip
    Remove-RepositoryItem -LiteralPath $SetupExecutable
    Remove-RepositoryItem -LiteralPath $ChecksumFile
    New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null

    $environment = @{
        PYTHONHASHSEED = "0"
        PYTHONUTF8 = "1"
        PYTHONDONTWRITEBYTECODE = "1"
        SOURCE_DATE_EPOCH = "1794700800"
    }
    foreach ($entry in $environment.GetEnumerator()) {
        Set-Item -Path "Env:$($entry.Key)" -Value $entry.Value
    }

    Write-Step "Building windowed PyInstaller onedir application"
    Invoke-Native -FilePath $Python -Arguments @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath", $DistRoot,
        "--workpath", $BuildRoot,
        (Join-Path $RepositoryRoot "VencordAutoRepair.spec")
    )

    $applicationExecutable = Join-Path $AppDirectory "$AppName.exe"
    if (-not (Test-Path -LiteralPath $applicationExecutable -PathType Leaf)) {
        throw "PyInstaller did not create $applicationExecutable"
    }
    $peCheck = @'
import pefile
import sys

image = pefile.PE(sys.argv[1], fast_load=True)
subsystem = image.OPTIONAL_HEADER.Subsystem
if subsystem != 2:
    raise SystemExit(f"Expected Windows GUI subsystem 2, got {subsystem}")
print("PE subsystem is WINDOWS_GUI")
'@
    Invoke-Native -FilePath $Python -Arguments @("-c", $peCheck, $applicationExecutable)
    $versionInfo = (Get-Item -LiteralPath $applicationExecutable).VersionInfo
    if ($versionInfo.FileVersion -notlike "$Version*") {
        throw "Unexpected executable FileVersion: $($versionInfo.FileVersion)"
    }
    if ($versionInfo.ProductVersion -notlike "$Version*") {
        throw "Unexpected executable ProductVersion: $($versionInfo.ProductVersion)"
    }

    Write-Step "Creating deterministic portable ZIP"
    Invoke-Native -FilePath $Python -Arguments @(
        (Join-Path $RepositoryRoot "assets\copy_licenses.py"), $AppDirectory
    )
    Invoke-Native -FilePath $Python -Arguments @(
        (Join-Path $RepositoryRoot "assets\package_portable.py"),
        $AppDirectory,
        $PortableZip
    )

    Write-Step "Locating verified Inno Setup compiler"
    $compiler = Find-InnoCompiler
    Write-Step "Compiling per-user installer"
    Invoke-Native -FilePath $compiler -Arguments @(
        "/DAppVersion=$Version",
        "/DProjectDir=$RepositoryRoot",
        "/DAppDir=$AppDirectory",
        "/DOutputDir=$DistRoot",
        "/DOutputBaseFilename=VencordAutoRepairSetup",
        (Join-Path $RepositoryRoot "installer\VencordAutoRepair.iss")
    )
    if (-not (Test-Path -LiteralPath $SetupExecutable -PathType Leaf)) {
        throw "Inno Setup did not create $SetupExecutable"
    }

    $checksumLines = foreach ($artifact in @($PortableZip, $SetupExecutable, $applicationExecutable)) {
        $relative = [IO.Path]::GetRelativePath($RepositoryRoot, $artifact).Replace("\", "/")
        "$((Get-FileSha256 -LiteralPath $artifact))  $relative"
    }
    Set-Content -LiteralPath $ChecksumFile -Value $checksumLines -Encoding ASCII

    Write-Step "Release artifacts"
    Get-Item -LiteralPath $AppDirectory, $PortableZip, $SetupExecutable, $ChecksumFile |
        Select-Object FullName, Length |
        Format-Table -AutoSize
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
