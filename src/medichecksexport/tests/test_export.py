import logging
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from medichecksexport import export


class FakeResponse:
    def __init__(self, value: Any, *, status_code: int = 200) -> None:
        self.value = value
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self.content = b"%PDF"
        self.text = ""
        self.url = "https://my.medichecks.com/"

    def json(self) -> Any:
        return self.value

    def raise_for_status(self) -> None:
        return None


def test_record_directory_name_uses_stable_date_and_id() -> None:
    assert (
        export._record_directory_name(
            {
                "health_record_id": 1225027,
                "date": "2026-06-01",
            }
        )
        == "20260601_1225027"
    )


def test_login_form_parser_extracts_action_and_inputs() -> None:
    parser = export._LoginFormParser()
    parser.feed(
        """
        <form method="POST" action="https://authenticate.medichecks.com/login">
          <input type="hidden" name="_token" value="csrf">
          <input name="cd_email">
          <input name="password">
          <input name="remember" value="0">
        </form>
        """
    )

    assert parser.action == "https://authenticate.medichecks.com/login"
    assert parser.inputs == {
        "_token": "csrf",
        "cd_email": "",
        "password": "",
        "remember": "0",
    }


def test_get_json_adds_mhf_parameter(monkeypatch: pytest.MonkeyPatch) -> None:
    client = export.MedichecksClient.__new__(export.MedichecksClient)
    client.uid = "2017057989"
    request = Mock(return_value=FakeResponse({"data": []}))
    monkeypatch.setattr(client, "request", request)

    assert client.get_json("/api/views") == {"data": []}

    request.assert_called_once()
    assert request.call_args.args == ("GET", "https://my.medichecks.com/api/views")
    assert request.call_args.kwargs["params"] == {"mhf": "2017057989"}


def test_test_results_view_id_uses_view_name() -> None:
    assert (
        export._test_results_view_id(
            {
                "data": [
                    {
                        "view_id": 944,
                        "view_name": "Everything",
                    },
                    {
                        "view_id": 2,
                        "view_name": "Test Results",
                    },
                ]
            }
        )
        == 2
    )


def test_export_account_writes_metadata_and_record_views(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = export.MedichecksClient.__new__(export.MedichecksClient)
    client.uid = "user"
    monkeypatch.setattr(
        client,
        "views",
        Mock(
            return_value={
                "data": [
                    {
                        "view_id": 944,
                        "view_name": "Everything",
                    },
                    {
                        "view_id": 2,
                        "view_name": "Test Results",
                    },
                ]
            }
        ),
    )
    monkeypatch.setattr(
        client,
        "reports",
        Mock(
            return_value=[
                {
                    "health_record_id": 123,
                    "date": "2026-06-01",
                    "name": "Test",
                    "url": "/results/report.pdf",
                }
            ]
        ),
    )
    monkeypatch.setattr(client, "health_record_observations", Mock(return_value={"data": []}))
    monkeypatch.setattr(client, "get_bytes", Mock(return_value=b"%PDF"))

    export.export_account(
        client=client,
        output_directory=tmp_path,
    )

    assert (tmp_path / "views.json").exists()
    assert (tmp_path / "reports.json").exists()
    assert not (tmp_path / "index").exists()
    assert (tmp_path / "health_records" / "20260601_123" / "report.json").exists()
    assert (tmp_path / "health_records" / "20260601_123" / "view_2.json").exists()
    assert not (tmp_path / "health_records" / "20260601_123" / "view_944.json").exists()
    assert (tmp_path / "health_records" / "20260601_123" / "report.pdf").exists()


def test_export_account_skips_existing_record_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = export.MedichecksClient.__new__(export.MedichecksClient)
    client.uid = "user"
    monkeypatch.setattr(
        client,
        "views",
        Mock(return_value={"data": [{"view_id": 2, "view_name": "Test Results"}]}),
    )
    monkeypatch.setattr(
        client,
        "reports",
        Mock(
            return_value=[
                {
                    "health_record_id": 123,
                    "date": "2026-06-01",
                    "name": "Test",
                    "url": "/results/report.pdf",
                }
            ]
        ),
    )
    health_record_observations = Mock()
    get_bytes = Mock()
    monkeypatch.setattr(client, "health_record_observations", health_record_observations)
    monkeypatch.setattr(client, "get_bytes", get_bytes)
    record_dir = tmp_path / "health_records" / "20260601_123"
    record_dir.mkdir(parents=True)
    marker = record_dir / "marker.txt"
    marker.write_text("keep")

    caplog.set_level(logging.INFO)
    export.export_account(
        client=client,
        output_directory=tmp_path,
    )

    assert marker.read_text() == "keep"
    health_record_observations.assert_not_called()
    get_bytes.assert_not_called()
    assert "(skip existing)" in caplog.text
