# Research

## Export design

The implementation follows the split described in
<https://beepb00p.xyz/exports.html>:

| Layer     | Responsibility                                          |
|-----------|---------------------------------------------------------|
| Export    | Fetch raw data from Medichecks and persist it unchanged |
| DAL       | Read local files and expose small typed helpers         |
| Consumers | Analyse or display data using the DAL                   |

The exporter checks the Medichecks report list on every run. Existing
health-record directories are left untouched; new records get one raw JSON
observation file and a report PDF.

## Existing public work

I searched GitHub and the web for reusable public attempts before implementing
this:

| Query                         | Result                                                                    |
|-------------------------------|---------------------------------------------------------------------------|
| `medichecks exporter`         | No repository matches                                                     |
| `my.medichecks.com`           | No repository matches                                                     |
| `my medichecks`               | No repository matches                                                     |
| `medichecks api`              | Only unrelated "MediCheck" health/demo apps surfaced                      |
| `medichecks scraper`          | Found `stupidpupil/medichecks_scraper`, for public product/biomarker data |
| `site:github.com Medichecks`  | No account-data exporter surfaced                                         |

`stupidpupil/medichecks_scraper` scrapes public Medichecks product and
biomarker catalog data:

<https://github.com/stupidpupil/medichecks_scraper>

It does not log in to `my.medichecks.com` or export user result data. Its
sibling `stupidpupil/medichecks_optimiser` uses catalog-style data to suggest
sets of tests, and is also not an account exporter:

<https://github.com/stupidpupil/medichecks_optimiser>

GitHub code search for exact `my.medichecks.com` references requires
authentication through the API in this environment, so the code-level part of
the search could not be completed unauthenticated.

## Observed Medichecks application

`https://my.medichecks.com/` redirects unauthenticated users to:

```text
https://authenticate.medichecks.com/login
```

The login form posts to `https://authenticate.medichecks.com/login` with:

```text
_token
cd_email
password
remember
```

Successful login follows an OAuth authorization redirect back to:

```text
https://my.medichecks.com/login/medichecks/callback
```

The authenticated dashboard exposes the values needed by the frontend in meta
tags:

```text
csrf-token
access-token
uid
```

The main frontend bundle configures Axios as follows:

```text
X-Requested-With: XMLHttpRequest
X-CSRF-TOKEN: <csrf-token>
Authorization: Bearer <access-token>
```

It also adds `mhf=<uid>` to every GET request. Without this `mhf` parameter,
several app endpoints return `403 Permission denied` or server errors.

## Observed endpoints

The dashboard exposes these API bases:

```text
https://my.medichecks.com/api
https://api.medichecks.com/v1
https://results.api.medichecks.com
https://fulfillment.api.medichecks.com/graphql
https://clients.api.medichecks.com/graphql
```

The useful result-export endpoints are app-local JSON routes under
`https://my.medichecks.com/api`:

| Endpoint                                      | Purpose                              |
|-----------------------------------------------|--------------------------------------|
| `/views`                                      | Available result views               |
| `/results/reports`                            | Report list and PDF URLs             |
| `/observations/health-record/<id>/view/<vid>` | Observations for one health record   |
| `/results/history/<observation-id>/<id>`      | History for a marker and record      |

The observed `/api/views` response exposed four views:

| ID  | Name         | Observed account data                                     |
|-----|--------------|-----------------------------------------------------------|
| 2   | Test Results | Full lab-result sections and observations                 |
| 944 | Everything   | Identical to view 2 for every exported report             |
| 945 | Vital Stats  | Empty `{"data": []}` for every exported report            |
| 946 | Lifestyle    | Empty `{"data": []}` for every exported report            |

The exporter keeps top-level `views.json` as raw archive metadata, then exports
only the view named `Test Results`. With the current archive shape that is view
2, which avoids duplicating the same observations from view 944.

The frontend also uses `https://results.api.medichecks.com` for PDF streaming:

```text
/v1/results/stream/pdf/<health-record-id>/<view-id>?token=<access-token>
/v1/results/download/pdf/<health-record-id>/<view-id>
```

The report list already returns same-origin PDF URLs, so the exporter uses
those URLs for PDF downloads.

## Network blocking

Medichecks appears to block some VPS or datacenter egress paths before requests
reach the application. On one tested VPS, both `https://my.medichecks.com/` and
`https://authenticate.medichecks.com/login` returned:

```text
HTTP/2 403
server: awselb/2.0
```

The same response was returned from the host and from the Docker container, and
browser-like request headers did not change it. This looks like AWS load
balancer-level blocking, so the exporter may need to run from a different
network or through an allowed proxy/VPN.

## Archived PDF comparison

The exported JSON and PDFs under `data/` were compared against previously
downloaded Medichecks PDFs kept outside this repository. Most comparable
numeric values matched the old downloaded PDFs exactly.

One older report differed: the old downloaded PDF contained numeric chemistry,
hormone, prostate, vitamin, and other results, while the current Medichecks
export for the matching health record returned `Sample error` in the newly
downloaded PDF and `No Sample`/`Not tested` values in the JSON view for many of
those same biomarkers. This appears to be historical Medichecks data drift
rather than an exporter parsing problem, because both current raw outputs from
Medichecks show missing-sample style values.

## Live smoke test

A live authenticated smoke test on 2026-06-26 confirmed:

| Request                                      | Result                         |
|----------------------------------------------|--------------------------------|
| `/api/views?mhf=<uid>`                       | HTTP 200, 4 views              |
| `/api/results/reports?mhf=<uid>`             | HTTP 200, 8 report records     |
| `/api/observations/health-record/...`        | HTTP 200, structured sections  |
| Report PDF URL from `/api/results/reports`   | HTTP 200, `application/pdf`    |

The API is undocumented and may change.
