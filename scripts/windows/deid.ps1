param(
    [ValidateSet("start", "update", "stop", "status")]
    [string]$Command = "status",
    [switch]$QuitDocker
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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

function Assert-GitAvailable {
    if (-not (Test-CommandAvailable "git")) {
        Show-GitHelp
        throw "Git wird fuer diesen Befehl benoetigt."
    }
}

function Assert-AppAvailable {
    if (-not (Test-Path (Join-Path $AppPath ".git"))) {
        throw "Die App wurde noch nicht eingerichtet. Fuehren Sie zuerst install.ps1 aus."
    }
}

function Test-DockerRunning {
    if (-not (Test-CommandAvailable "docker")) {
        return $false
    }

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

function Wait-ForDocker {
    param([int]$TimeoutSeconds = 120)

    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $Deadline) {
        if (Test-DockerRunning) {
            return
        }
        Start-Sleep -Seconds 2
    }

    throw "Docker wurde nicht innerhalb von $TimeoutSeconds Sekunden verfuegbar."
}

function Ensure-DockerRunning {
    if (-not (Test-CommandAvailable "docker")) {
        Show-DockerHelp
        throw "Docker wird fuer diesen Befehl benoetigt."
    }

    if (Test-DockerRunning) {
        return
    }

    $DockerDesktop = Find-DockerDesktop
    if ($null -eq $DockerDesktop) {
        Show-DockerHelp
        throw "Docker Desktop wurde nicht gefunden."
    }

    Write-Host "Docker Desktop wird gestartet. Das kann einen Moment dauern."
    Start-Process -FilePath $DockerDesktop
    Wait-ForDocker
}

function Assert-LastCommandSucceeded {
    param([Parameter(Mandatory = $true)][string]$Message)

    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

function Initialize-EnvironmentFile {
    $EnvPath = Join-Path $AppPath ".env"
    $ExamplePath = Join-Path $AppPath ".env.example"
    if (-not (Test-Path $EnvPath)) {
        Copy-Item -Path $ExamplePath -Destination $EnvPath
        Write-Host ".env wurde aus .env.example erstellt."
    }
}

function Start-App {
    Assert-GitAvailable
    Assert-AppAvailable
    Ensure-DockerRunning
    Initialize-EnvironmentFile

    Push-Location $AppPath
    try {
        & docker compose up -d
        Assert-LastCommandSucceeded "Die App konnte nicht gestartet werden."
    }
    finally {
        Pop-Location
    }

    Write-Host "Die lokale App laeuft unter:"
    Write-Host $AppUrl
}

function Update-App {
    Assert-GitAvailable
    Assert-AppAvailable

    $Changes = & git -C $AppPath status --porcelain
    Assert-LastCommandSucceeded "Der lokale Git-Status konnte nicht gelesen werden."
    if ($Changes) {
        Write-Host "Das Update wurde gestoppt, weil lokale Aenderungen vorhanden sind."
        Write-Host "Es wurde nichts ueberschrieben. Bitte lassen Sie die Aenderungen zuerst pruefen."
        return
    }

    & git -C $AppPath fetch --prune
    Assert-LastCommandSucceeded "Git fetch ist fehlgeschlagen."
    & git -C $AppPath checkout main
    Assert-LastCommandSucceeded "Der Wechsel auf main ist fehlgeschlagen."
    & git -C $AppPath pull --ff-only
    Assert-LastCommandSucceeded "Das Update konnte nicht als Fast-Forward eingespielt werden."

    Copy-Item -Path (Join-Path $AppPath "scripts\windows\deid.ps1") -Destination $LauncherPath -Force

    Ensure-DockerRunning
    Initialize-EnvironmentFile
    Push-Location $AppPath
    try {
        & docker compose up -d --build
        Assert-LastCommandSucceeded "Die aktualisierte App konnte nicht gestartet werden."
    }
    finally {
        Pop-Location
    }

    Write-Host "Die lokale App laeuft unter:"
    Write-Host $AppUrl
}

function Stop-App {
    Assert-AppAvailable
    if (-not (Test-DockerRunning)) {
        Write-Host "Docker laeuft nicht; die App ist bereits gestoppt."
        return
    }

    Push-Location $AppPath
    try {
        & docker compose down
        Assert-LastCommandSucceeded "Die App konnte nicht sauber gestoppt werden."
    }
    finally {
        Pop-Location
    }

    Write-Host "Die App wurde gestoppt. Lokale Daten bleiben erhalten."
    if (-not $QuitDocker) {
        return
    }

    $OtherContainers = & docker ps -q
    Assert-LastCommandSucceeded "Andere Docker-Container konnten nicht geprueft werden."
    if ($OtherContainers) {
        Write-Host "Docker Desktop bleibt aktiv, weil noch andere Container laufen."
        return
    }

    Write-Host "Es laufen keine anderen Container. Docker Desktop wird jetzt beendet."
    Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue | Stop-Process
}

function Show-Status {
    Write-Host "App-Ordner: $AppPath"
    if (Test-Path (Join-Path $AppPath ".git")) {
        Write-Host "App installiert: ja"
        if (Test-CommandAvailable "git") {
            $Branch = & git -C $AppPath branch --show-current
            if ($LASTEXITCODE -eq 0) {
                Write-Host "Aktiver Branch: $Branch"
            }
        }
    }
    else {
        Write-Host "App installiert: nein"
    }

    if (Test-DockerRunning) {
        Write-Host "Docker: laeuft"
        if (Test-Path (Join-Path $AppPath "docker-compose.yml")) {
            Push-Location $AppPath
            try {
                & docker compose ps
            }
            finally {
                Pop-Location
            }
        }
    }
    else {
        Write-Host "Docker: nicht verfuegbar oder nicht gestartet"
    }

    Write-Host "App-URL: $AppUrl"
}

switch ($Command) {
    "start" { Start-App }
    "update" { Update-App }
    "stop" { Stop-App }
    "status" { Show-Status }
}
