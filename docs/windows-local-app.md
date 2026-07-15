# Windows Local App

## Voraussetzungen

- Windows 11 mit PowerShell
- Git for Windows
- Docker Desktop mit Linux-Containern (wsl: <https://learn.microsoft.com/en-us/windows/wsl/install>)
- Docker Desktop mit **mindestens 4 GB RAM** (Settings → Resources), damit das GLiNER-PII-Modell passt
- Einmalig etwa **1,3 GB Download** und einige Minuten fuer die lokalen Modelle beim ersten Setup

Der Installer installiert keine Systemsoftware ohne Zustimmung. Fehlt Git oder Docker Desktop,
zeigt er den offiziellen Download und, falls vorhanden, einen optionalen `winget`-Befehl an.

## Setup

PowerShell oeffnen und ausfuehren:

```powershell
irm https://raw.githubusercontent.com/rubennati/privacy-deidentification/main/scripts/windows/install.ps1 | iex
```

Der Installer verwendet immer den freigegebenen Stand auf `main`. Ein erneuter Lauf aktualisiert
eine bestehende, unveraenderte Installation und startet die App erneut.

### Skriptausfuehrung

Windows blockiert das Ausfuehren lokaler Skripte standardmaessig (`ExecutionPolicy Restricted`). Der
Installer setzt die Richtlinie fuer den aktuellen Benutzer einmalig auf `RemoteSigned` (ohne
Admin-Rechte), damit die Modell-Bereitstellung und die `deid.ps1`-Befehle laufen. Es ist also kein
manueller Schritt noetig.

Ist die Richtlinie per Firmen-Gruppenrichtlinie gesperrt, den Installer und den Launcher jeweils mit
Bypass starten:

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://raw.githubusercontent.com/rubennati/privacy-deidentification/main/scripts/windows/install.ps1 | iex"
powershell -ExecutionPolicy Bypass -File "$HOME\PrivacyDeID\deid.ps1" start
```

### Privates Repository (Anmeldung)

Der Installer erkennt selbst, ob das Repository oeffentlich oder privat ist, und waehlt den passenden
Weg. Solange es **oeffentlich** ist, gilt der Einzeiler oben unveraendert.

Ist das Repository **privat**, braucht es eine einmalige GitHub-Anmeldung. Man muss dazu als
Collaborator eingeladen sein (und die Einladung angenommen haben). Zwei Dinge aendern sich:

1. **Der erste Abruf** kann nicht mehr anonym von `raw.githubusercontent.com` laden (private Dateien
   liefert GitHub dort nicht aus). Stattdessen zuerst anmelden und `install.ps1` ueber die
   angemeldete GitHub-CLI holen:

   ```powershell
   winget install --id GitHub.cli -e   # nur falls 'gh' fehlt
   gh auth login --hostname github.com --git-protocol https --web
   gh api -H "Accept: application/vnd.github.raw" /repos/rubennati/privacy-deidentification/contents/scripts/windows/install.ps1 | iex
   ```

   Beim `gh auth login` oeffnet sich ein Browserfenster zum Bestaetigen.

2. **Danach laeuft alles gleich weiter.** Der Installer klont mit deiner Anmeldung, richtet Git so
   ein, dass auch `deid.ps1 update` spaeter zieht, und startet die App wie gewohnt.

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
baut die Container neu. Bei lokalen Aenderungen stoppt es, ohne Dateien zu ueberschreiben. `update`
und `start` loeschen nie Docker-Volumes, Uploads oder Dokumentdaten unter `volumes/`.

Wachsen die Docker-Images ueber die Zeit an (mehrere Rebuilds), kann im geklonten Repository unter
`$HOME\PrivacyDeID\app` `docker image prune -f` sicher ausgefuehrt werden: das entfernt nur alte,
ungenutzte Images, niemals Volumes oder lokale Daten.

## Stop

```powershell
& "$HOME\PrivacyDeID\deid.ps1" stop
```

Dies stoppt nur die App-Container. Lokale Daten und Docker Desktop bleiben erhalten. Optional kann
`-QuitDocker` angehaengt werden; Docker Desktop wird dann nur beendet, wenn keine anderen Container
laufen.

## Alte Version vollstaendig entfernen

Um eine bestehende Installation vollstaendig zu entfernen — etwa vor einer sauberen Neuinstallation
einer aelteren Version — zuerst die App stoppen und dann den Installationsordner loeschen. **Achtung:**
Schritt 3 loescht auch alle lokalen Daten: hochgeladene Dokumente, Ergebnisse und die
heruntergeladenen Modelle unter `volumes/`.

```powershell
# 1) App stoppen und Container entfernen (Daten bleiben zunaechst erhalten):
& "$HOME\PrivacyDeID\deid.ps1" stop

# 2) Optional: auch die gebauten Images dieses Projekts entfernen:
Set-Location "$HOME\PrivacyDeID\app"; docker compose down --rmi local

# 3) Installation inklusive aller lokalen Daten (Uploads, Ergebnisse, Modelle, .env) loeschen:
Remove-Item -Recurse -Force "$HOME\PrivacyDeID"
```

Docker Desktop selbst bleibt dabei installiert. Nach einer vollstaendigen Entfernung ist ein
erneutes Setup jederzeit ueber den `irm ... | iex`-Befehl aus dem Abschnitt **Setup** moeglich; die
Modelle werden dann wieder heruntergeladen (einmalig ~1,3 GB).

## Status

```powershell
& "$HOME\PrivacyDeID\deid.ps1" status
```

Der Status zeigt Installation, aktiven Git-Branch, Docker-Zustand, Container und App-URL.

## Was passiert im Hintergrund?

Das Repository wird nach `$HOME\PrivacyDeID\app` geklont. Der Launcher liegt unter
`$HOME\PrivacyDeID\deid.ps1`. Fehlt `.env`, wird sie einmalig aus `.env.example` erstellt. Danach
werden die lokalen Modelle bereitgestellt — die PaddleOCR-Modelle (fuer gescannte Seiten) und das
GLiNER-PII-Modell samt Backbone — und Docker Compose startet die lokale App. Die Modelle werden nur
beim ersten Mal heruntergeladen; danach laeuft alles vollstaendig offline (`start` provisioniert nur
nach, wenn Modelle fehlen). Bestehende `.env`-Dateien und lokale Daten werden nicht ersetzt oder
geloescht. Ist die Maschine zu schwach oder ohne Internet beim ersten Setup, bricht die
Bereitstellung mit einer klaren Meldung ab.

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
