import json
from pathlib import Path

import pytest

from medichecksexport import dal


def _sample_export(root: Path) -> None:
    (root / "views.json").write_text(
        json.dumps(
            {
                "data": [
                    {
                        "view_id": 2,
                        "view_name": "Other",
                        "view_gender": "U",
                    },
                    {
                        "view_id": 944,
                        "view_name": "Test Results",
                        "view_gender": "U",
                    },
                ]
            }
        )
    )
    record = root / "health_records" / "20260601_123"
    record.mkdir(parents=True)
    (record / "report.json").write_text(
        json.dumps(
            {
                "health_record_id": 123,
                "date": "2026-06-01",
                "name": "Advanced Blood Test",
            }
        )
    )
    (record / "view_2.json").write_text(
        json.dumps(
            {
                "data": [
                    {
                        "id": 1,
                        "title": "Other",
                        "observations": [
                            {
                                "id": 11,
                                "name": "Other",
                                "value": 1,
                                "unit": "unit",
                                "indicator": 0,
                            }
                        ],
                    }
                ]
            }
        )
    )
    (record / "view_944.json").write_text(
        json.dumps(
            {
                "data": [
                    {
                        "id": 1,
                        "title": "Vitamins",
                        "observations": [
                            {
                                "id": 10,
                                "name": "Vitamin B12",
                                "value": 533.0,
                                "unit": "pmol/L",
                                "indicator": 0,
                            }
                        ],
                    }
                ]
            }
        )
    )


def test_dal_reads_sample_export(tmp_path: Path) -> None:
    _sample_export(tmp_path)

    d = dal.DAL(tmp_path)
    assert d.snapshot.test_results_view_id == 944

    records = list(d.health_records())
    assert len(records) == 1
    record = records[0]
    assert record.id == "123"
    assert record.date == "2026-06-01"
    assert record.name == "Advanced Blood Test"

    observations = list(record.observations())
    assert len(observations) == 1
    observation = observations[0]
    assert observation.id == "10"
    assert observation.name == "Vitamin B12"
    assert observation.value == 533.0
    assert observation.unit == "pmol/L"
    assert observation.label == "normal"
    assert observation.formatted_value() == "533 pmol/L"

    other_observations = list(record.observations(view_id=2))
    assert len(other_observations) == 1
    assert other_observations[0].name == "Other"


def test_dal_requires_record_files(tmp_path: Path) -> None:
    (tmp_path / "views.json").write_text('{"data": [{"view_id": 2, "view_name": "Test Results"}]}')
    (tmp_path / "health_records" / "20260601_123").mkdir(parents=True)

    with pytest.raises(AssertionError):
        dal.DAL(tmp_path)
