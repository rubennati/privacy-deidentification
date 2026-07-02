# Windows Local App

## Voraussetzungen

- Windows 10 oder 11 mit PowerShell
- Git for Windows
- Docker Desktop mit Linux-Containern

Der Installer installiert keine Systemsoftware ohne Zustimmung. Fehlt Git oder Docker Desktop,
zeigt er den offiziellen Download und, falls vorhanden, einen optionalen `winget`-Befehl an.

## Setup

PowerShell oeffnen und ausfuehren:

```powershell
irm https://raw.githubusercontent.com/rubennati/privacy-deidentification/main/scripts/windows/install.ps1 | iex
```

Der Installer verwendet immer den freigegebenen Stand auf `main`. Ein erneuter Lauf aktualisiert
eine bestehende, unveraenderte Installation und startet die App erneut.

## Start

```powershell
& "$HOME\PrivacyDeID\deid.ps1" start
```

Falls Docker noch nicht laeuft, startet der Launcher Docker Desktop und wartet bis zu zwei Minuten.

## Update

```powershell
& "$HOME\PrivacyDeID\deid.ps1" update
```

Das Update holt den aktuellen Stand, wechselt auf `main`, akzeptiert nur einen Fast-Forward und
baut die Container neu. Bei lokalen Aenderungen stoppt es, ohne Dateien zu ueberschreiben.

## Stop

```powershell
& "$HOME\PrivacyDeID\deid.ps1" stop
```

Dies stoppt nur die App-Container. Lokale Daten und Docker Desktop bleiben erhalten. Optional kann
`-QuitDocker` angehaengt werden; Docker Desktop wird dann nur beendet, wenn keine anderen Container
laufen.

## Status

```powershell
& "$HOME\PrivacyDeID\deid.ps1" status
```

Der Status zeigt Installation, aktiven Git-Branch, Docker-Zustand, Container und App-URL.

## Was passiert im Hintergrund?

Das Repository wird nach `$HOME\PrivacyDeID\app` geklont. Der Launcher liegt unter
`$HOME\PrivacyDeID\deid.ps1`. Fehlt `.env`, wird sie einmalig aus `.env.example` erstellt. Danach
startet Docker Compose die lokale App. Bestehende `.env`-Dateien und lokale Daten werden nicht
ersetzt oder geloescht.

## Git fehlt

Git for Windows installieren: <https://git-scm.com/download/win>. Wenn `winget` vorhanden ist,
kann nach eigener Bestaetigung `winget install --id Git.Git -e` verwendet werden.

## Docker Desktop fehlt

Docker Desktop installieren: <https://www.docker.com/products/docker-desktop/>. Wenn `winget`
vorhanden ist, kann nach eigener Bestaetigung
`winget install --id Docker.DockerDesktop -e` verwendet werden.

## Port 8080 ist belegt

Die App kann dann nicht starten. Den belegenden Prozess beziehungsweise Container beenden und
`start` erneut ausfuehren. Der Windows-Workflow verwendet bewusst die feste URL
<http://localhost:8080>.

## Update stoppt wegen lokaler Aenderungen

Der Schutz ist beabsichtigt. Das Update ueberschreibt keine lokalen Dateien. Die Aenderungen mit
`git -C "$HOME\PrivacyDeID\app" status` pruefen und bei Unsicherheit sichern beziehungsweise von
einer technischen Person klaeren lassen. Danach `update` erneut ausfuehren.
