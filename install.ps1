# FLIR Research Interface — one-command operator install for Windows 10/11 (x64).
#   irm https://raw.githubusercontent.com/mattlmccoy/flir-research-interface/main/install.ps1 | iex
# Re-running updates the checkout and restarts the service. Never prints secrets.
$ErrorActionPreference = "Stop"
$Repo = "https://github.com/mattlmccoy/flir-research-interface.git"
$Dest = if ($env:FRI_HOME) { $env:FRI_HOME } else { Join-Path $HOME "flir-research-interface" }
$SdkBase = if ($env:FRI_SDK_BASE_URL) { $env:FRI_SDK_BASE_URL } else { "https://github.com/mattlmccoy/flir-research-interface/releases/download/sdk-4.4.0.246" }
$SdkExe = "SpinnakerSDK_FULL_4.4.0.246_x64.exe"
$PySpinZip = "spinnaker_python-4.4.0.246-cp312-cp312-win_amd64.zip"
function Say($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }

Say "Tools (git, Python 3.12, uv, ffmpeg) via winget"
foreach ($pkg in @("Git.Git", "Python.Python.3.12", "astral-sh.uv", "Gyan.FFmpeg")) {
  winget install --id $pkg --exact --silent --accept-package-agreements --accept-source-agreements 2>$null | Out-Null
}
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")

Say "Checkout at $Dest"
if (Test-Path (Join-Path $Dest ".git")) { git -C $Dest pull --ff-only } else { git clone $Repo $Dest }

Say "Python environment"
Push-Location (Join-Path $Dest "backend"); uv sync --inexact -q; Pop-Location

Say "Spinnaker SDK"
$pyspinOk = $false
try { Push-Location (Join-Path $Dest "backend"); uv run python -c "import PySpin" 2>$null; $pyspinOk = ($LASTEXITCODE -eq 0) } finally { Pop-Location }
if (-not $pyspinOk) {
  $tmp = Join-Path $env:TEMP "fri-sdk"; New-Item -ItemType Directory -Force $tmp | Out-Null
  try {
    Write-Host "downloading $SdkExe (~270 MB) from the internal mirror…"
    Invoke-WebRequest "$SdkBase/$SdkExe" -OutFile (Join-Path $tmp $SdkExe)
    Write-Host "installing Spinnaker silently (a UAC prompt may appear)…"
    Start-Process (Join-Path $tmp $SdkExe) -ArgumentList '/S','/v"/qn"' -Wait
    Invoke-WebRequest "$SdkBase/$PySpinZip" -OutFile (Join-Path $tmp $PySpinZip)
    Expand-Archive (Join-Path $tmp $PySpinZip) -DestinationPath (Join-Path $tmp "pyspin") -Force
    $whl = Get-ChildItem (Join-Path $tmp "pyspin") -Recurse -Filter "*.whl" | Select-Object -First 1
    Push-Location (Join-Path $Dest "backend"); uv pip install $whl.FullName; Pop-Location
  } catch {
    Write-Warning "Could not fetch the SDK from $SdkBase ($($_.Exception.Message))."
    Write-Warning "Download 'Spinnaker 4.4 Full SDK (Windows x64)' and 'PySpin cp312 win_amd64' from"
    Write-Warning "https://www.teledynevisionsolutions.com/products/spinnaker-sdk/ then re-run this script."
  }
}

Say "Camera credentials"
Push-Location (Join-Path $Dest "backend"); uv run fri-install --no-service; Pop-Location

Say "Background service (Task Scheduler, at logon)"
$uv = (Get-Command uv).Source
$action = New-ScheduledTaskAction -Execute $uv -Argument "run --directory `"$Dest\backend`" fri-serve --host 127.0.0.1 --port 8000 --site-origin https://mattlmccoy.github.io" -WorkingDirectory (Join-Path $Dest "backend")
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "FLIR Research Interface operator" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "FLIR Research Interface operator"

Say "Done"
Write-Host "Open https://mattlmccoy.github.io/flir-research-interface/ on this PC; it finds the operator at http://127.0.0.1:8000 by itself."
