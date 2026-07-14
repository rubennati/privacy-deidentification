"""Synthetic committed-artifact helpers for tests that bypass workstation APIs."""

from __future__ import annotations

from app.config import Settings
from app.schemas import PiiArtifact, TextArtifact
from app.services.artifact_lifecycle import publish_artifact_files
from app.services.job_models import JobContext, JobExecutionMode, JobKind, JobRecord
from app.services.job_store import get_job_store


def save_text_artifact(settings: Settings, artifact: TextArtifact) -> None:
    """Persist synthetic OCR output with a real durable successful job proof."""
    record = _running_job(settings, artifact.document_id, JobKind.OCR_TEXT)
    publish_artifact_files(
        settings,
        artifact.document_id,
        {artifact.artifact_type: (artifact.id, artifact.model_dump_json())},
        authority_job_id=record.job_id,
        authority_job_result=(artifact.id, artifact.artifact_type),
    )
    _succeed(settings, record, artifact.id, artifact.artifact_type)


def save_pii_artifact(settings: Settings, artifact: PiiArtifact) -> None:
    """Persist synthetic PII output with a real durable successful job proof."""
    record = _running_job(settings, artifact.document_id, JobKind.PII_DETECTION)
    publish_artifact_files(
        settings,
        artifact.document_id,
        {artifact.artifact_type: (artifact.id, artifact.model_dump_json())},
        authority_job_id=record.job_id,
        authority_job_result=(artifact.id, artifact.artifact_type),
    )
    _succeed(settings, record, artifact.id, artifact.artifact_type)


def _running_job(settings: Settings, document_id: str, kind: JobKind) -> JobRecord:
    record = JobRecord.from_context(
        JobContext.create(
            kind=kind,
            document_id=document_id,
            execution_mode=JobExecutionMode.SYNCHRONOUS_INLINE,
        )
    )
    store = get_job_store(settings)
    store.create_job(record)
    record.mark_running()
    store.mark_running(record)
    return record


def _succeed(
    settings: Settings,
    record: JobRecord,
    artifact_id: str,
    artifact_type: str,
) -> None:
    record.mark_succeeded(artifact_id=artifact_id, artifact_type=artifact_type)
    get_job_store(settings).mark_succeeded(record)
