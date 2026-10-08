<#
.SYNOPSIS
Builds dist\CodexHark.exe: clean venv, pinned dependencies, verified Vosk model,
tests, then a one-file PyInstaller exe with the model inside.

.EXAMPLE
./build.ps1
./build.ps1 -Python "py -3.13"
#>
param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

$build = Join-Path $root "build"
$dist = Join-Path $root "dist"
$venv = Join-Path $build "venv"
$py = Join-Path $venv "Scripts\python.exe"
$modelName = "vosk-model-small-ru-0.22"
$modelUrl = "https://alphacephei.com/vosk/models/$modelName.zip"
$modelSha256 = "961D5FF98A17F4AA6DE69864D0AA71FA5BAC682301D2B5D17A3F24C5C99A46D4"
New-Item -ItemType Directory -Force $build, $dist | Out-Null

function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe $($Arguments -join ' ') failed with exit code $LASTEXITCODE" }
}

Write-Host "1/6 clean virtual environment"
$pythonParts = $Python -split " "
Invoke-Checked $pythonParts[0] (@($pythonParts | Select-Object -Skip 1) + @("-m", "venv", "--clear", $venv))
Invoke-Checked $py @("-m", "pip", "install", "--quiet", "--disable-pip-version-check",
    "-r", "requirements.txt", "-r", "requirements-build.txt")
# sounddevice ships ASIO-enabled PortAudio builds (Steinberg ASIO API) that are used only when SD_ENABLE_ASIO is set.
# Hark never sets it, so drop them and do not distribute them in the exe.
Get-ChildItem (Join-Path $venv "Lib\site-packages\_sounddevice_data\portaudio-binaries") -Filter "*-asio.dll" | Remove-Item

Write-Host "2/6 speech model"
$model = Join-Path $root $modelName
if (-not (Test-Path (Join-Path $model "am\final.mdl"))) {
    $zip = Join-Path $build "$modelName.zip"
    Invoke-WebRequest $modelUrl -OutFile $zip
    $hash = (Get-FileHash $zip -Algorithm SHA256).Hash
    if ($hash -ne $modelSha256) { throw "model checksum mismatch: $hash" }
    Expand-Archive $zip -DestinationPath $root -Force
}

Write-Host "3/6 tests"
Invoke-Checked $py @("-m", "unittest", "discover", "-s", "tests")

Write-Host "4/6 UI Automation wrapper, icon and version info"
# comtypes cannot generate wrappers inside a frozen app, so generate them here and bundle them.
Invoke-Checked $py @("-c", "import comtypes.client; comtypes.client.GetModule('UIAutomationCore.dll')")
$icon = Join-Path $build "icon.ico"
Invoke-Checked $py @("-c", "import app; app.save_icon(r'$icon')")
$version = (& $py -c "import wakeword; print(wakeword.__version__)").Trim()
$v = ($version.Split(".") + @("0", "0", "0", "0"))[0..3] -join ", "
$versionFile = Join-Path $build "version_info.txt"
$versionInfo = @"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($v), prodvers=($v), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'ID-Yo'),
      StringStruct('FileDescription', 'Codex Listener - wake word for Codex Desktop voice chat and dictation'),
      StringStruct('FileVersion', '$version'),
      StringStruct('InternalName', 'CodexHark'),
      StringStruct('OriginalFilename', 'CodexHark.exe'),
      StringStruct('ProductName', 'Codex Listener'),
      StringStruct('ProductVersion', '$version')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@
[IO.File]::WriteAllText($versionFile, $versionInfo, (New-Object Text.UTF8Encoding $false))

Write-Host "5/6 PyInstaller (version $version)"
Invoke-Checked $py @("-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
    "--onefile", "--noconsole", "--name", "CodexHark",
    "--icon", $icon, "--version-file", $versionFile,
    "--add-data", "$model;$modelName",
    "--add-data", "$(Join-Path $root 'ui');ui",
    "--hidden-import", "comtypes.gen.UIAutomationClient",
    "--collect-all", "vosk",
    "--collect-all", "webview",
    "--distpath", $dist, "--workpath", (Join-Path $build "pyinstaller"), "--specpath", $build,
    (Join-Path $root "app.py"))

Write-Host "6/6 checksum"
$exe = Join-Path $dist "CodexHark.exe"
$sum = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText((Join-Path $dist "SHA256SUMS.txt"), "$sum  CodexHark.exe" + [char]10)
"{0} ({1:N1} MB, version {2})" -f $exe, ((Get-Item $exe).Length / 1MB), $version
