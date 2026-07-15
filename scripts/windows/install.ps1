Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Windows blocks running local .ps1 files by default (ExecutionPolicy "Restricted"), which stops this
# installer's helper scripts (provision-models.ps1) and the deid.ps1 launcher from loading. Relax it
# safely, without admin rights:
#   - CurrentUser -> RemoteSigned so the deid.ps1 launcher keeps working in future sessions
#     (locally created / git-cloned scripts run; scripts downloaded-and-marked still need a signature).
#   - Process    -> Bypass so THIS session can load the helper scripts even where the CurrentUser
#     change is blocked (e.g. corporate Group Policy).
try {
    if ((Get-ExecutionPolicy) -in @("Restricted", "AllSigned")) {
        Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
        Write-Host "Skriptausfuehrung fuer diesen Benutzer auf 'RemoteSigned' gesetzt (noetig fuer die App-Befehle)."
    }
}
catch {
    Write-Host "Hinweis: Die dauerhafte Skriptausfuehrung konnte nicht gesetzt werden (evtl. Firmenrichtlinie)."
}
try { Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force } catch { }

$RepositoryUrl = "https://github.com/rubennati/privacy-deidentification.git"
$RepoSlug = "rubennati/privacy-deidentification"
$RootPath = Join-Path $HOME "PrivacyDeID"
$AppPath = Join-Path $RootPath "app"
$LauncherPath = Join-Path $RootPath "deid.ps1"
$AppUrl = "http://localhost:8080"

# --- Guided, coloured output -------------------------------------------------
function Write-Step { param([string]$Message) Write-Host ""; Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok { param([string]$Message) Write-Host "    [OK] $Message" -ForegroundColor Green }
function Write-Note { param([string]$Message) Write-Host "    [i]  $Message" -ForegroundColor Yellow }
function Write-ErrLine { param([string]$Message) Write-Host "    [X]  $Message" -ForegroundColor Red }

function Test-CommandAvailable {
    param([Parameter(Mandatory = $true)][string]$Name)

    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Show-GitHelp {
    Write-ErrLine "Git ist noch nicht installiert."
    Write-Host "    Download: https://git-scm.com/download/win"
    if (Test-CommandAvailable "winget") {
        Write-Host "    Optionale Installation nach Ihrer Bestaetigung:"
        Write-Host "      winget install --id Git.Git -e"
    }
}

function Show-DockerHelp {
    Write-ErrLine "Docker Desktop ist noch nicht installiert."
    Write-Host "    Download: https://www.docker.com/products/docker-desktop/"
    if (Test-CommandAvailable "winget") {
        Write-Host "    Optionale Installation nach Ihrer Bestaetigung:"
        Write-Host "      winget install --id Docker.DockerDesktop -e"
    }
}

function Show-GhHelp {
    Write-ErrLine "Fuer ein privates Repository wird die GitHub CLI ('gh') benoetigt."
    Write-Host "    Download: https://cli.github.com/"
    if (Test-CommandAvailable "winget") {
        Write-Host "    Optionale Installation nach Ihrer Bestaetigung:"
        Write-Host "      winget install --id GitHub.cli -e"
    }
    Write-Host "    Danach dieses Setup erneut ausfuehren."
}

function Ensure-GhAuth {
    # Ensure gh is present and authenticated (browser sign-in if needed), and wire git to reuse its
    # credentials so later `git pull` updates work too. Returns $true on success.
    if (-not (Test-CommandAvailable "gh")) {
        Show-GhHelp
        return $false
    }

    & gh auth status *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Step "GitHub-Anmeldung - es oeffnet sich ein Browserfenster, bitte dort bestaetigen ..."
        & gh auth login --hostname github.com --git-protocol https --web
        if ($LASTEXITCODE -ne 0) {
            Write-ErrLine "Die GitHub-Anmeldung ist fehlgeschlagen."
            return $false
        }
    }

    & gh auth setup-git *> $null
    return $true
}

function Invoke-RepoClone {
    # Clone the app repo. Try an anonymous clone first (works for a PUBLIC repo). If that fails the
    # repo is PRIVATE -> sign in via the GitHub CLI and clone with credentials. Returns $true on
    # success. This lets the same installer serve both a public and a (later) private repository.
    Write-Step "App-Code wird geholt ..."

    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $env:GIT_TERMINAL_PROMPT = "0"  # fail fast on a private repo instead of popping a login dialog
    & git -c credential.helper= clone --branch main $RepositoryUrl $AppPath 2>&1 | Out-Null
    $cloned = ($LASTEXITCODE -eq 0)
    Remove-Item Env:\GIT_TERMINAL_PROMPT -ErrorAction SilentlyContinue
    $ErrorActionPreference = $previousPreference

    if ($cloned) {
        Write-Ok "Repository geklont (oeffentlich)."
        return $true
    }

    Write-Note "Repository nicht oeffentlich erreichbar - es ist privat und braucht eine einmalige Anmeldung."
    if (-not (Ensure-GhAuth)) {
        return $false
    }

    & gh repo clone $RepoSlug $AppPath -- --branch main
    if ($LASTEXITCODE -ne 0) {
        Write-ErrLine "Der Clone mit GitHub-Anmeldung ist fehlgeschlagen."
        return $false
    }
    Write-Ok "Repository geklont (privat, angemeldet)."
    return $true
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

    Write-Note "Docker Desktop wird gestartet. Das kann einen Moment dauern."
    Start-Process -FilePath $DockerDesktop
    $Deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $Deadline) {
        Start-Sleep -Seconds 2
        if (Test-DockerRunning) {
            return $true
        }
    }

    Write-ErrLine "Docker wurde nicht innerhalb von 120 Sekunden verfuegbar."
    return $false
}

function Test-LastCommandSucceeded {
    param([Parameter(Mandatory = $true)][string]$Message)

    if ($LASTEXITCODE -eq 0) {
        return $true
    }

    Write-ErrLine $Message
    return $false
}

Write-Step "Voraussetzungen werden geprueft (Git, Docker) ..."
if (-not (Test-CommandAvailable "git")) {
    Show-GitHelp
    return
}
if (-not (Test-CommandAvailable "docker")) {
    Show-DockerHelp
    return
}
Write-Ok "Git und Docker gefunden."

New-Item -ItemType Directory -Path $RootPath -Force | Out-Null

if (-not (Test-Path $AppPath)) {
    if (-not (Invoke-RepoClone)) {
        return
    }
}
elseif (-not (Test-Path (Join-Path $AppPath ".git"))) {
    Write-ErrLine "$AppPath existiert, ist aber kein gueltiges App-Repository. Es wurde nichts veraendert."
    return
}

$OriginUrl = & git -C $AppPath remote get-url origin
if (-not (Test-LastCommandSucceeded "Das Git-Remote konnte nicht gelesen werden.")) {
    return
}
$NormalizedOrigin = ($OriginUrl -replace '\.git$', '').TrimEnd('/')
$NormalizedExpected = ($RepositoryUrl -replace '\.git$', '').TrimEnd('/')
if ($NormalizedOrigin -ne $NormalizedExpected) {
    Write-ErrLine "$AppPath verwendet nicht das erwartete App-Repository."
    Write-Host "    Erwartet: $RepositoryUrl"
    Write-Host "    Gefunden: $OriginUrl"
    return
}

$Changes = & git -C $AppPath status --porcelain
if (-not (Test-LastCommandSucceeded "Der lokale Git-Status konnte nicht gelesen werden.")) {
    return
}
if ($Changes) {
    Write-Note "Setup gestoppt: lokale Aenderungen vorhanden. Es wurde nichts ueberschrieben."
    return
}

Write-Step "Aktuellen Stand von 'main' holen ..."
& git -C $AppPath checkout main
if (-not (Test-LastCommandSucceeded "Der Wechsel auf main ist fehlgeschlagen.")) {
    return
}
& git -C $AppPath pull --ff-only
if ($LASTEXITCODE -ne 0) {
    # A repo that turned private after a public clone needs auth to pull. Try once with sign-in.
    if (Ensure-GhAuth) {
        & git -C $AppPath pull --ff-only
    }
}
if (-not (Test-LastCommandSucceeded "main konnte nicht als Fast-Forward aktualisiert werden.")) {
    return
}
Write-Ok "App-Code aktuell."

$EnvPath = Join-Path $AppPath ".env"
if (-not (Test-Path $EnvPath)) {
    Copy-Item -Path (Join-Path $AppPath ".env.example") -Destination $EnvPath
    Write-Ok ".env aus .env.example erstellt."
}

Copy-Item -Path (Join-Path $AppPath "scripts\windows\deid.ps1") -Destination $LauncherPath -Force

Write-Step "Docker wird geprueft/gestartet ..."
if (-not (Ensure-DockerRunning)) {
    return
}
Write-Ok "Docker laeuft."

# Provision the local OCR + GLiNER models before first start, so the default GLiNER PII backend and
# scanned-page OCR work fully offline. One-time download; the runtime never fetches models.
Write-Step "Lokale Modelle werden bereitgestellt (einmalig, ca. 1,3 GB - das dauert etwas) ..."
Write-Note "pip- und HuggingFace-Hinweise im folgenden Download sind normal (kein Fehler)."
. (Join-Path $AppPath "scripts\windows\provision-models.ps1")
try {
    Invoke-ModelProvisioning -AppPath $AppPath
}
catch {
    Write-ErrLine $_.Exception.Message
    return
}
Write-Ok "Modelle bereit."

Write-Step "App wird gebaut und gestartet (der erste Build dauert ein paar Minuten) ..."
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
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Die lokale App laeuft unter:  $AppUrl" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Spaetere Befehle:"
Write-Host "  & `"$LauncherPath`" start"
Write-Host "  & `"$LauncherPath`" update"
Write-Host "  & `"$LauncherPath`" stop"
Write-Host "  & `"$LauncherPath`" status"
