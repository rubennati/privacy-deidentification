Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryUrl = "https://github.com/rubennati/privacy-deidentification.git"
$RootPath = Join-Path $HOME "PrivacyDeID"
$AppPath = Join-Path $RootPath "app"
$LauncherPath = Join-Path $RootPath "deid.ps1"
$AppUrl = "http://localhost:8080"

function Test-CommandAvailable {
    param([Parameter(Mandatory = $true)][string]$Name)

    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Show-GitHelp {
    Write-Host "Git ist noch nicht installiert."
    Write-Host "Download: https://git-scm.com/download/win"
    if (Test-CommandAvailable "winget") {
        Write-Host "Optionale Installation nach Ihrer Bestaetigung:"
        Write-Host "  winget install --id Git.Git -e"
    }
}

function Show-DockerHelp {
    Write-Host "Docker Desktop ist noch nicht installiert."
    Write-Host "Download: https://www.docker.com/products/docker-desktop/"
    if (Test-CommandAvailable "winget") {
        Write-Host "Optionale Installation nach Ihrer Bestaetigung:"
        Write-Host "  winget install --id Docker.DockerDesktop -e"
    }
}

function Test-DockerRunning {
    & docker info *> $null
    return $LASTEXITCODE -eq 0
}

function Find-DockerDesktop {
    $Candidates = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"),
        (Join-Path $env:LOCALAPPDATA "Docker\Docker Desktop.exe")
    )

    foreach ($Candidate in $Candidates) {
        if (Test-Path $Candidate) {
            return $Candidate
        }
    }

    return $null
}

function Ensure-DockerRunning {
    if (Test-DockerRunning) {
        return $true
    }

    $DockerDesktop = Find-DockerDesktop
    if ($null -eq $DockerDesktop) {
        Show-DockerHelp
        return $false
    }

    Write-Host "Docker Desktop wird gestartet. Das kann einen Moment dauern."
    Start-Process -FilePath $DockerDesktop
    $Deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $Deadline) {
        Start-Sleep -Seconds 2
        if (Test-DockerRunning) {
            return $true
        }
    }

    Write-Host "Docker wurde nicht innerhalb von 120 Sekunden verfuegbar."
    return $false
}

function Test-LastCommandSucceeded {
    param([Parameter(Mandatory = $true)][string]$Message)

    if ($LASTEXITCODE -eq 0) {
        return $true
    }

    Write-Host $Message
    return $false
}

if (-not (Test-CommandAvailable "git")) {
    Show-GitHelp
    return
}

if (-not (Test-CommandAvailable "docker")) {
    Show-DockerHelp
    return
}

New-Item -ItemType Directory -Path $RootPath -Force | Out-Null

if (-not (Test-Path $AppPath)) {
    Write-Host "Die lokale App wird eingerichtet."
    & git clone --branch main $RepositoryUrl $AppPath
    if (-not (Test-LastCommandSucceeded "Das Repository konnte nicht geklont werden.")) {
        return
    }
}
elseif (-not (Test-Path (Join-Path $AppPath ".git"))) {
    Write-Host "$AppPath existiert, ist aber kein gueltiges App-Repository."
    Write-Host "Es wurde nichts veraendert."
    return
}

$OriginUrl = & git -C $AppPath remote get-url origin
if (-not (Test-LastCommandSucceeded "Das Git-Remote konnte nicht gelesen werden.")) {
    return
}
if ($OriginUrl -ne $RepositoryUrl) {
    Write-Host "$AppPath verwendet nicht das erwartete App-Repository."
    Write-Host "Erwartet: $RepositoryUrl"
    Write-Host "Gefunden: $OriginUrl"
    Write-Host "Es wurde nichts veraendert."
    return
}

$Changes = & git -C $AppPath status --porcelain
if (-not (Test-LastCommandSucceeded "Der lokale Git-Status konnte nicht gelesen werden.")) {
    return
}
if ($Changes) {
    Write-Host "Das Setup wurde gestoppt, weil lokale Aenderungen vorhanden sind."
    Write-Host "Es wurde nichts ueberschrieben. Nutzen Sie den vorhandenen Launcher oder lassen Sie die Aenderungen pruefen."
    return
}

& git -C $AppPath checkout main
if (-not (Test-LastCommandSucceeded "Der Wechsel auf main ist fehlgeschlagen.")) {
    return
}
& git -C $AppPath pull --ff-only
if (-not (Test-LastCommandSucceeded "main konnte nicht als Fast-Forward aktualisiert werden.")) {
    return
}

$EnvPath = Join-Path $AppPath ".env"
if (-not (Test-Path $EnvPath)) {
    Copy-Item -Path (Join-Path $AppPath ".env.example") -Destination $EnvPath
    Write-Host ".env wurde aus .env.example erstellt."
}

Copy-Item -Path (Join-Path $AppPath "scripts\windows\deid.ps1") -Destination $LauncherPath -Force

if (-not (Ensure-DockerRunning)) {
    return
}

Push-Location $AppPath
try {
    & docker compose up -d --build
    if (-not (Test-LastCommandSucceeded "Die App konnte nicht gebaut und gestartet werden.")) {
        return
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Die lokale App laeuft unter:"
Write-Host $AppUrl
Write-Host ""
Write-Host "Spaetere Befehle:"
Write-Host "  & `"$LauncherPath`" start"
Write-Host "  & `"$LauncherPath`" update"
Write-Host "  & `"$LauncherPath`" stop"
Write-Host "  & `"$LauncherPath`" status"
