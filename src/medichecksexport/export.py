from __future__ import annotations

import argparse
import json
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

from .common import Json, JsonObject

_APP_URL = "https://my.medichecks.com"
_AUTH_URL = "https://authenticate.medichecks.com"

_RETRYABLE_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}


def _load_secrets(path: Path) -> JsonObject:
    secrets = json.loads(path.read_text())
    assert isinstance(secrets, dict), secrets
    return secrets


def _write_json(path: Path, value: Json) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False))


def _safe_file_name(name: str) -> str:
    assert name not in {"", ".", ".."}, name
    assert "/" not in name, name
    assert "\\" not in name, name
    return name


def _record_date(report: JsonObject) -> str:
    value = report.get("date")
    if isinstance(value, str):
        return value[:10].replace("-", "")
    return "unknown"


def _record_id(report: JsonObject) -> str:
    value = report["health_record_id"]
    assert isinstance(value, int | str), value
    return str(value)


def _record_directory_name(report: JsonObject) -> str:
    return f"{_record_date(report)}_{_safe_file_name(_record_id(report))}"


def _retry_delay(response: requests.Response, attempt: int) -> int:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None and retry_after.isdigit():
        return int(retry_after)
    return 1 << attempt


class _LoginFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None
        self.inputs: dict[str, str] = {}
        self._in_form = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        method = attributes.get("method")
        if tag == "form" and method is not None and method.lower() == "post":
            self._in_form = True
            self.action = attributes.get("action")
        if self._in_form and tag == "input":
            name = attributes.get("name")
            if name is not None:
                self.inputs[name] = attributes.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._in_form = False


def _meta_content(html: str, name: str) -> str:
    match = re.search(rf'<meta name="{re.escape(name)}" content="([^"]+)"', html)
    assert match is not None, name
    return match.group(1)


class MedichecksClient:
    def __init__(self) -> None:
        self.http = requests.Session()
        self.http.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": f"{_APP_URL}/",
                "User-Agent": "medichecksexport/1",
            }
        )
        self.uid: str | None = None

    def request(
        self,
        method: str,
        url: str,
        *,
        attempts: int = 4,
        **kwargs: Any,
    ) -> requests.Response:
        for attempt in range(attempts):
            try:
                response = self.http.request(method, url, **kwargs)
            except requests.ConnectionError, requests.Timeout:
                if attempt == attempts - 1:
                    raise
                time.sleep(2**attempt)
                continue

            if response.status_code not in _RETRYABLE_STATUS_CODES:
                return response
            if attempt == attempts - 1:
                return response
            time.sleep(_retry_delay(response, attempt))
        raise AssertionError

    def authenticate(
        self,
        *,
        email: str,
        password: str,
    ) -> JsonObject:
        response = self.request("GET", f"{_APP_URL}/", timeout=30)
        response.raise_for_status()
        parser = _LoginFormParser()
        parser.feed(response.text)
        assert parser.action is not None, response.url

        payload = dict(parser.inputs)
        payload["cd_email"] = email
        payload["password"] = password
        payload["remember"] = payload.get("remember", "0")
        response = self.request(
            "POST",
            parser.action,
            data=payload,
            timeout=30,
        )
        response.raise_for_status()

        dashboard = self.request("GET", f"{_APP_URL}/", timeout=30)
        dashboard.raise_for_status()
        html = dashboard.text
        csrf_token = _meta_content(html, "csrf-token")
        access_token = _meta_content(html, "access-token")
        uid = _meta_content(html, "uid")
        self.uid = uid
        self.http.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Authorization": f"Bearer {access_token}",
                "X-CSRF-TOKEN": csrf_token,
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        return {
            "uid": uid,
            "app_url": _APP_URL,
            "auth_url": _AUTH_URL,
        }

    def get_json(
        self,
        endpoint_or_url: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> JsonObject | list[Json]:
        assert self.uid is not None
        url = endpoint_or_url if endpoint_or_url.startswith("http") else urljoin(f"{_APP_URL}/", endpoint_or_url)
        request_params = dict(params or {})
        request_params.setdefault("mhf", self.uid)
        response = self.request(
            "GET",
            url,
            params=request_params,
            timeout=60,
        )
        response.raise_for_status()
        value = response.json()
        assert isinstance(value, dict | list), value
        return value

    def get_bytes(
        self,
        endpoint_or_url: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> bytes:
        assert self.uid is not None
        url = endpoint_or_url if endpoint_or_url.startswith("http") else urljoin(f"{_APP_URL}/", endpoint_or_url)
        request_params = dict(params or {})
        request_params.setdefault("mhf", self.uid)
        response = self.request(
            "GET",
            url,
            params=request_params,
            timeout=120,
        )
        response.raise_for_status()
        return response.content

    def views(self) -> JsonObject:
        value = self.get_json("/api/views")
        assert isinstance(value, dict), value
        return value

    def reports(self) -> list[JsonObject]:
        value = self.get_json("/api/results/reports")
        assert isinstance(value, list), value
        reports = []
        for report in value:
            assert isinstance(report, dict), report
            reports.append(report)
        return reports

    def health_record_observations(
        self,
        *,
        health_record_id: str,
        view_id: int,
    ) -> JsonObject:
        value = self.get_json(f"/api/observations/health-record/{health_record_id}/view/{view_id}")
        assert isinstance(value, dict), value
        return value


def _test_results_view_id(views: JsonObject) -> int:
    data = views["data"]
    assert isinstance(data, list), data
    for view in data:
        assert isinstance(view, dict), view
        view_name = view["view_name"]
        assert isinstance(view_name, str), view
        if view_name != "Test Results":
            continue
        view_id = view["view_id"]
        assert isinstance(view_id, int), view_id
        return view_id
    raise AssertionError(views)


def _write_pdf(
    *,
    client: MedichecksClient,
    report: JsonObject,
    path: Path,
) -> None:
    url = report.get("url")
    assert isinstance(url, str), report
    content = client.get_bytes(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def export_account(
    *,
    client: MedichecksClient,
    output_directory: Path,
) -> None:
    views = client.views()
    reports = client.reports()
    test_results_view_id = _test_results_view_id(views)

    _write_json(output_directory / "views.json", views)
    _write_json(output_directory / "reports.json", reports)

    print(f"Found {len(reports)} reports", file=sys.stderr)

    for index, report_raw in enumerate(reports, start=1):
        report = report_raw
        record_id = _record_id(report)
        record_dir = output_directory / "health_records" / _record_directory_name(report)
        date = report.get("date", "unknown-date")
        name = report.get("name", "unknown-name")
        prefix = f"[{index}/{len(reports)}] {date} {record_id} {name}"
        if record_dir.exists():
            print(f"{prefix} (skip existing)", file=sys.stderr)
            continue

        print(f"{prefix} (fetch)", file=sys.stderr)

        _write_json(record_dir / "report.json", report)
        path = record_dir / f"view_{test_results_view_id}.json"
        document = client.health_record_observations(
            health_record_id=record_id,
            view_id=test_results_view_id,
        )
        _write_json(path, document)
        _write_pdf(
            client=client,
            report=report,
            path=record_dir / "report.pdf",
        )


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export raw Medichecks results.")
    parser.add_argument(
        "--secrets",
        type=Path,
        required=True,
        help="JSON file containing email and password",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Archive directory",
    )
    return parser


def main() -> None:
    args = _make_parser().parse_args()

    secrets = _load_secrets(args.secrets)
    email = secrets["email"]
    password = secrets["password"]
    assert isinstance(email, str), type(email)
    assert isinstance(password, str), type(password)

    client = MedichecksClient()
    client.authenticate(
        email=email,
        password=password,
    )

    export_account(
        client=client,
        output_directory=args.output,
    )
    print(f"Archive written to {args.output.resolve()}", file=sys.stderr)


if __name__ == "__main__":
    main()
