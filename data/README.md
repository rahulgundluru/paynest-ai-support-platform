# Data

| Path | Committed | Contents |
|---|---|---|
| `source/` | **No** | Exact mirror of the upstream case repository at the pinned commit (simulated data, treat as confidential) |
| `source_manifest.json` | Yes | Upstream URL, commit, and SHA-256 of every source file |
| `processed/` | No | Local pipeline outputs |

```bash
python scripts/source_data.py fetch    # clone pinned upstream commit into data/source/
python scripts/source_data.py verify   # verify hashes against the manifest
```

Rules:
- Never edit files under `source/`; the pipeline reads them read-only and records the source file + hash on every ingested record.
- `trainer/` (answer key) is never fetched. `generator/generate.py` must not be used to derive evaluation labels.
- All identifiers in the data are synthetic, but are handled as real PII.
