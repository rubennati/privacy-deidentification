# ADR-0038: Artifact and document lifecycle integrity v1

## Status

Accepted — cross-cutting stabilization; no engine maturity-level advance.

## Context

Derived artifacts were individually renamed into a shared directory and implicit-current reads
scanned for the newest artifact that still validated. OCR published `text_result` before its
matching `quality_report`; a failure between those writes exposed a partial run. Validation also
filtered corrupt or incompatible newer files out of the candidate list, silently presenting an
older result as current. Finally, document deletion removed job rows and the document directory,
but a worker that had already claimed a job could later recreate the directory and publish output.

## Decision

Every new artifact publication uses a per-document, cross-process lifecycle lock. Publication
writes and fsyncs every artifact in a coherent run before atomically replacing the text-free
`artifacts/current-artifacts` authority map. OCR publishes `text_result` and `quality_report`
together. Other current artifact kinds use the same authority mechanism.

Implicit-current reads resolve the exact id in that map. A missing, malformed, incompatible, or
wrong-document pointed artifact is an explicit `409`; it never causes an older artifact to become
current. Exact historical OCR and PII reads remain artifact-id based. A directory containing JSON
artifacts without an authority map is invalid current state and is never scanned for a fallback.
This intentionally breaks implicit-current reads for pre-v1 installations until a new coherent run
publishes authority; their exact historical artifacts remain addressable where supported.

Job-backed publications bind each current entry to the producing job id and the job's declared
result artifact identity. The artifact files and authority entry are made durable first, but an
implicit reader accepts that entry only after the exact job is durably `succeeded` with matching
document, artifact id, and artifact type. A running, failed, missing, or mismatched job leaves the
pointed state explicitly invalid. Thus a failed job-store completion cannot accidentally make its
files consumable. Older id-only authority maps remain readable because they were explicit atomic
publication commits under lifecycle v1; absence of the map is not treated the same way.

Deletion takes the same lifecycle lock, writes a persistent text-free tombstone below the separate
job-state root, removes job metadata, originals, and document-owned data, then releases the lock.
All later publishers check the tombstone under that lock and refuse publication. Worker and inline
job finalization treat a job row removed by concurrent document deletion as a terminal discard.

The authority-map replacement makes a run a current *candidate*: before it, none of that run is
selected; after it, all run-owned files are durable and exact. Job-backed candidates become
authoritative only when the matching succeeded job metadata is durable. Artifacts stay immutable
JSON; the authority map, job metadata, and tombstone contain ids/state only and no document text or
PII.

## Consequences and limitations

- A failed/incomplete new run leaves the previous coherent run current, while its partial files are
  removed when publication itself fails.
- Corruption of the current map or pointed file is visible and fail-closed.
- Successful deletion is terminal even for already-claimed work and across process restarts.
- Legacy directories without an authority map cannot retroactively prove which historic run was
  intended as current, so implicit reads fail closed until a new run publishes explicit authority.
- The lifecycle lock uses POSIX `flock`, matching the Linux container runtime. Sharing the data
  roots with non-POSIX filesystems that do not preserve advisory locking is unsupported.
