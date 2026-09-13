# Turbovec search trial: 0.6.10rc2

This prerelease adds an opt-in vector backend. The stable package and default
`python` backend remain available. Use an isolated virtual environment for the
trial, with the existing library as its source.

## Install and run

Download the wheel from the GitHub prerelease, then in a dedicated environment:

```powershell
python -m pip install ./unlimited_skills-0.6.10rc2-py3-none-any.whl
python -m pip install 'turbovec==1.0.0' 'fastembed>=0.4' 'fastapi>=0.115' 'uvicorn>=0.30'
$env:UNLIMITED_SKILLS_VECTOR_BACKEND = 'turbovec'
$env:UNLIMITED_SKILLS_WARM_DAEMON_URL = 'http://127.0.0.1:18766'
unlimited-skills --root PATH_TO_LIBRARY serve --host 127.0.0.1 --port 18766
```

In another terminal in the same virtual environment, set the same two variables:

```powershell
unlimited-skills --root PATH_TO_LIBRARY suggest 'проверь производительность WordPress' --json --card --limit 3
```

The daemon's `/health` identifies the package version and `vector_backend`.
The trial client rejects a daemon running a different backend. `numpy` is an
additional exact-search comparison mode; `python` restores the scalar path.
Restart only the trial daemon after changing its backend. Stopping the trial
daemon and returning to the original launcher rolls back the trial.

## Behavior and limits

- Read the existing versioned JSON sidecar. Model, inventory generation and
  record-count checks remain in force. No compressed file replaces that source.
- Retain normalized float32 vectors for exact cosine reranking. TurboQuant uses
  four-bit candidates, with a shortlist of `max(64, 4 * requested_k)`.
- Filter the collection before selecting candidates, including empty filters.
- Cache at most two immutable indexes in each process. Sidecar or manifest
  replacement invalidates the cache; library edits invalidate freshness.
- Cache the count of distinct skill identities against the complete file
  inventory generation. Every search still scans the inventory. This removes
  repeated body parsing when the library contains shadowed copies.
- Preserve the previously deployed non-English vector ranking fix: semantic
  results retain cosine order; English uses existing reciprocal rank fusion.
- No new embedding model, permission system, company-memory integration,
  hosted calls or improved-relevance claim is introduced.

At this small corpus size, retained float32 data plus quantizer overhead means
this is not a demonstrated process-memory reduction. Faster candidate search
does not itself improve relevance. The benchmark measures top-10 agreement with
exact cosine, not human-rated relevance or recall against labeled answers.

## Reproduce the comparison

Local Windows pilot: 524 skills, 384 dimensions, 100 authored queries split
evenly between English and Russian. All first results and top-ten sets matched
the scalar baseline. This is agreement, not proof of improved relevance.

| Measurement | Previous scalar path | NumPy plus cache | Turbovec plus cache |
| --- | ---: | ---: | ---: |
| Retrieval p95, 100 queries, embeddings precomputed | 1537 ms | 390 ms | 394 ms |
| Local query p95, 20 warm queries including embedding | 1892 ms | 885 ms | 743 ms |

The measured local-query p95 improvement was 2.55x. Most of the improvement
came from avoiding repeated identity parsing; the initial turbovec-only run
did not materially improve the full query. The NumPy/turbovec end-to-end
difference is too small and order-dependent to establish a reliable winner.
The original timings were reused from the preceding run on the same host;
this was not a randomized, isolated-host performance study.

The compressed serialization measured 555,603 bytes versus 804,864 bytes for
float32 vectors, but this trial retains both representations for reranking.
No RAM reduction or production latency guarantee is claimed.
Aggregate evidence: [benchmark JSON](reports/turbovec-trial-2026-09-13.json).

```powershell
python scripts/benchmark-turbovec.py --root PATH_TO_LIBRARY --cache .tmp/query-embeddings.json --output .tmp/benchmark.json --e2e
```

The public query set contains 50 authored English/Russian pairs, not a replay
of private production logs. Identical query embeddings are reused across
backends. The scalar timing baseline clears the new identity-count cache to
reproduce the previous installed path. `--reuse-baseline` can reuse timing
statistics from a preceding matching run while recomputing exact rankings.
Run comparisons on an idle host for stronger latency evidence.

`results` measures local retrieval without embedding/HTTP/generation. `kernel`
measures only candidate search and reranking. `e2e_local_ms` includes embedding
for 20 warmed queries, but excludes HTTP and LLM generation. No process RAM
claim should be derived from the serialized vector payload sizes.

Optional-backend tests run on Windows and Linux in `turbovec-trial.yml`.
This prerelease is a trial artifact; it does not promote the stable release.
