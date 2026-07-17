from copy import deepcopy

from scripts.sqlalchemy_schema import compare_snapshots, local_snapshot, normalize_default


def test_local_snapshot_contains_complete_schema() -> None:
    snapshot = local_snapshot()

    assert len(snapshot["tables"]) == 30
    assert len(snapshot["enums"]) == 27


def test_schema_comparison_accepts_identical_snapshots(capsys) -> None:
    snapshot = local_snapshot()

    assert compare_snapshots(snapshot, snapshot) == 0
    assert "matches" in capsys.readouterr().out


def test_schema_comparison_reports_normalized_drift(capsys) -> None:
    expected = local_snapshot()
    actual = deepcopy(expected)
    actual["tables"]["Holding"]["columns"][4]["type"] = "numeric:28:8"

    assert compare_snapshots(expected, actual) == 1
    captured = capsys.readouterr()
    assert "SQLAlchemy metadata drift detected" in captured.err
    assert "numeric:28:10" in captured.err
    assert "numeric:28:8" in captured.err


def test_default_normalization_removes_schema_qualification() -> None:
    assert (
        normalize_default("'viewer'::\"public\".\"AccountMemberRole\"")
        == "'viewer'::accountmemberrole"
    )
