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
current. Exact historical OCR and PII reads remain artifact-id based. Directories without an
authority map retain the legacy newest-valid read path so pre-v1 installations remain readable;
the first new publication creates the map and makes later authority explicit.

Deletion takes the same lifecycle lock, writes a persistent text-free tombstone below the separate
job-state root, removes job metadata, originals, and document-owned data, then releases the lock.
All later publishers check the tombstone under that lock and refuse publication. Worker and inline
job finalization treat a job row removed by concurrent document deletion as a terminal discard.

The authority-map replacement is the run publication commit: before it, none of that run is
current; after it, all run-owned files are durable and exact. The job's succeeded metadata is then
recorded with the returned artifact id. Artifacts stay immutable JSON; the authority map and
tombstone contain ids/state only and no document text or PII.

## Consequences and limitations

- A failed/incomplete new run leaves the previous coherent run current, while its partial files are
  removed when publication itself fails.
- Corruption of the current map or pointed file is visible and fail-closed.
- Successful deletion is terminal even for already-claimed work and across process restarts.
- Legacy directories without an authority map cannot retroactively prove which historic run was
  intended as current; they keep the old compatibility selector until a new run is published.
- The lifecycle lock uses POSIX `flock`, matching the Linux container runtime. Sharing the data
  roots with non-POSIX filesystems that do not preserve advisory locking is unsupported.
