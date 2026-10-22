from __future__ import annotations

import argparse
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from hpikit.json import Json, loads


def _data(document: Json) -> list[Json]:
    value = document["data"]
    assert isinstance(value, list), value
    result = []
    for item in value:
        assert isinstance(item, dict), item
        result.append(item)
    return result


def _format_value(*, value: float | str | bool | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int | float):
        return f"{value:g}"
    return value


def _test_results_view_id(root: Path) -> int:
    document = loads((root / "views.json").read_bytes())
    assert isinstance(document, dict), document
    for view in _data(document):
        name = view["view_name"]
        assert isinstance(name, str), view
        if name == "Test Results":
            view_id = view["view_id"]
            assert isinstance(view_id, int), view
            return view_id
    raise AssertionError(document)


@dataclass(frozen=True)
class Snapshot:
    root: Path
    record_dirs: list[Path]
    test_results_view_id: int

    @classmethod
    def load(cls, source: Path | str) -> Snapshot:
        root = Path(source)
        if root.is_file():
            root = root.parent
        root = root.resolve()

        test_results_view_id = _test_results_view_id(root)
        records_root = root / "health_records"
        assert records_root.exists(), root
        record_dirs = sorted(path for path in records_root.iterdir() if path.is_dir())
        assert len(record_dirs) > 0, root
        for path in record_dirs:
            assert (path / "report.json").exists(), path
            assert len(list(path.glob("view_*.json"))) > 0, path

        return cls(
            root=root,
            record_dirs=record_dirs,
            test_results_view_id=test_results_view_id,
        )


@dataclass(frozen=True)
class Observation:
    raw: Json
    section: Json
    record: HealthRecord

    @property
    def id(self) -> str:
        value = self.raw.get("id", self.raw.get("observation_id"))
        assert isinstance(value, int | str), value
        return str(value)

    @property
    def name(self) -> str:
        value = self.raw["name"]
        assert isinstance(value, str), self.raw
        return value

    @property
    def value(self) -> float | str | bool | None:
        value = self.raw.get("value")
        assert value is None or isinstance(value, int | float | str | bool), value
        return value

    @property
    def unit(self) -> str | None:
        value = self.raw.get("unit")
        assert value is None or isinstance(value, str), value
        return value

    @property
    def label(self) -> str | None:
        value = self.raw.get("label")
        if value is None:
            indicator = self.raw.get("indicator")
            if indicator == 0:
                return "normal"
            if indicator in {-1, -2}:
                return "low"
            if indicator in {1, 2}:
                return "high"
        assert value is None or isinstance(value, str), value
        return value

    def formatted_value(self) -> str:
        value = _format_value(value=self.value)
        if value == "":
            return ""
        if self.unit is None:
            return value
        return f"{value} {self.unit}"


@dataclass(frozen=True)
class HealthRecord:
    path: Path
    report: Json
    views: dict[int, Json]
    test_results_view_id: int

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        test_results_view_id: int,
    ) -> HealthRecord:
        report = loads((path / "report.json").read_bytes())
        assert isinstance(report, dict), report
        views = {}
        for view_path in sorted(path.glob("view_*.json")):
            view_id = int(view_path.stem.removeprefix("view_"))
            document = loads(view_path.read_bytes())
            assert isinstance(document, dict), document
            views[view_id] = document
        assert len(views) > 0, path
        return cls(
            path=path,
            report=report,
            views=views,
            test_results_view_id=test_results_view_id,
        )

    @property
    def id(self) -> str:
        value = self.report["health_record_id"]
        assert isinstance(value, int | str), value
        return str(value)

    @property
    def date(self) -> str | None:
        value = self.report.get("date")
        assert value is None or isinstance(value, str), value
        return value

    @property
    def name(self) -> str | None:
        value = self.report.get("name")
        assert value is None or isinstance(value, str), value
        return value

    def observations(
        self,
        *,
        view_id: int | None = None,
    ) -> Iterator[Observation]:
        if view_id is None:
            view_id = self.test_results_view_id
        document = self.views[view_id]
        for section in _data(document):
            observations = section.get("observations", [])
            assert isinstance(observations, list), observations
            for observation in observations:
                assert isinstance(observation, dict), observation
                yield Observation(
                    raw=observation,
                    section=section,
                    record=self,
                )


class DAL:
    """Offline access to one Medichecks export snapshot."""

    def __init__(self, source: Path | str) -> None:
        self.snapshot = Snapshot.load(source)

    def health_records(self) -> Iterator[HealthRecord]:
        records = [
            HealthRecord.load(
                path,
                test_results_view_id=self.snapshot.test_results_view_id,
            )
            for path in self.snapshot.record_dirs
        ]
        yield from sorted(records, key=lambda record: (record.date or "", record.id))


def _summary_table(records: list[HealthRecord]) -> tuple[list[str], list[list[str]]]:
    names = sorted({observation.name for record in records for observation in record.observations()})
    headers = ["date", "name", *names]
    rows = []
    for record in records:
        observations = {observation.name: observation.formatted_value() for observation in record.observations()}
        rows.append(
            [
                record.date or "",
                record.name or "",
                *[observations.get(name, "") for name in names],
            ]
        )
    return headers, rows


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Medichecks exports offline through the DAL.")
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Medichecks export directory or a file within it",
    )
    return parser


def main() -> None:
    from tabulate import tabulate

    args = _make_parser().parse_args()
    dal = DAL(args.source)

    records = list(dal.health_records())
    print(f"Source: {dal.snapshot.root}")
    print(f"Health records: {len(records)}")
    if len(records) > 0:
        print(f"Range: {records[0].date} to {records[-1].date}")
        print(f"Observations: {sum(1 for record in records for _ in record.observations())}")
        headers, rows = _summary_table(records)
        print()
        print(tabulate(rows, headers=headers, tablefmt="github"))


if __name__ == "__main__":
    main()
