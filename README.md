# Medichecks exporter

This repository follows the export/DAL split described in
[Building data liberation infrastructure](https://beepb00p.xyz/exports.html):

- the **export layer** communicates with Medichecks and preserves raw JSON data;
- the **data access layer (DAL)** works offline and interprets exported data.

The implementation lives under `src/medichecksexport`:

```text
src/medichecksexport/
  common.py   shared archive primitives
  export.py   login, API access, and raw export
  dal.py      offline access and typed Medichecks bindings
```

## Exporting

Create `secrets.json`:

```json
{
  "email": "name@example.com",
  "password": "your Medichecks password"
}
```

Run the exporter:

```console
uv run --extra export -m medichecksexport.export \
  --secrets secrets.json \
  --output exports/medichecks
```

For incremental updates, reuse the same output directory. Existing health-record
directories are left untouched; new records are fetched and logged in the
terminal.

## Raw archive

The exporter writes:

```text
medichecks-export/
  reports.json
  views.json
  health_records/
    <date>_<health-record-id>/
      view_<view-id>.json
      report.pdf
```

Each `view_<view-id>.json` is the raw
`/api/observations/health-record/<id>/view/<view-id>` response.
The exporter writes the view named `Test Results` from `views.json`.
The currently observed account views are documented in
[docs/research.md](docs/research.md).

## Offline DAL

Inspect an archive without `requests` or network access:

```console
uv run --extra dal -m medichecksexport.dal --source exports/medichecks
```

Programmatic access from the repository root:

```python
from medichecksexport.dal import DAL

dal = DAL("exports/medichecks")

for record in dal.health_records():
    print(record.date, record.id, record.name)

    for observation in record.observations():
        print(observation.name, observation.value, observation.unit, observation.label)
```

`record.observations()` reads the view named `Test Results` from `views.json`.
For the current Medichecks archive that is view 2.

## Verification

```console
uv run --extra export -m medichecksexport.export --help
uv run --extra dal -m medichecksexport.dal --source exports/medichecks
uv run pytest
uv run ruff check .
uv run mypy src
```

The API is undocumented and may change. See [docs/research.md](docs/research.md)
for research and protocol details.
