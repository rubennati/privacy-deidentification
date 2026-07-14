# Shared model provisioning for the Windows local app. Provisions the OCR and NER (GLiNER) models
# into the repo's volumes so the default GLiNER PII backend and image/scanned-page OCR work fully
# offline. It runs the same cross-platform scripts/provision_*.py inside a throwaway
# python:3.12-slim container — exactly what `make ocr-models` / `make ner-models` do on Linux/macOS,
# so there is one provisioning mechanism. The api/ocr-worker never download at runtime. Idempotent.
#
# Dot-sourced by install.ps1 and deid.ps1.

function Test-ModelsProvisioned {
    param([Parameter(Mandatory = $true)][string]$AppPath)

    $NerConfig = Join-Path $AppPath "volumes\ner-models\gliner_multi-v2.1\gliner_config.json"
    $OcrRec = Join-Path $AppPath "volumes\ocr-models\text_recognition\inference.pdiparams"
    return (Test-Path $NerConfig) -and (Test-Path $OcrRec)
}

function Invoke-ModelProvisioning {
    param([Parameter(Mandatory = $true)][string]$AppPath)

    $ScriptsDir = Join-Path $AppPath "scripts"
    $NerDir = Join-Path $AppPath "volumes\ner-models"
    $OcrDir = Join-Path $AppPath "volumes\ocr-models"
    New-Item -ItemType Directory -Path $NerDir, $OcrDir -Force | Out-Null

    Write-Host "OCR-Modelle werden bereitgestellt (einmalig) ..."
    & docker run --rm `
        -e MODELS_ROOT=/models `
        -v "${OcrDir}:/models" `
        -v "${ScriptsDir}:/work:ro" `
        python:3.12-slim python /work/provision_ocr_models.py
    if ($LASTEXITCODE -ne 0) {
        throw "Die OCR-Modelle konnten nicht bereitgestellt werden. Bitte Internetzugang pruefen und erneut versuchen."
    }

    Write-Host "PII-Modell (GLiNER) wird bereitgestellt (einmalig, ca. 1,3 GB Download) ..."
    & docker run --rm `
        -e MODELS_ROOT=/models `
        -v "${NerDir}:/models" `
        -v "${ScriptsDir}:/work:ro" `
        python:3.12-slim sh -lc "pip install --quiet huggingface_hub && python /work/provision_ner_models.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Das PII-Modell (GLiNER) konnte nicht bereitgestellt werden. Bitte Internetzugang pruefen und erneut versuchen."
    }

    Write-Host "Modelle sind bereit."
}

function Confirm-ModelsProvisioned {
    param([Parameter(Mandatory = $true)][string]$AppPath)

    if (Test-ModelsProvisioned -AppPath $AppPath) {
        return
    }
    Invoke-ModelProvisioning -AppPath $AppPath
}
