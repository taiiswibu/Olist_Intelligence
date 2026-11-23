import csv

import pytest

from olist import followup_trials as t


def row(n, method, outcome="approved", seconds=30):
    finished = "2026-11-23 10:00:" + f"{seconds:02d}" if outcome != "unfinished" else ""
    return dict(zip(t.FIELDS, [t.SCHEMA, f"{n:032x}", "P_0123456789ab", "T_0123456789ab", str(n), "cyclic-v1", method,
        "pipeline" if method == "ai" else method, outcome, "2026-11-23 10:00:00",
        "2026-11-23 10:00:10" if outcome == "approved" else "", finished,
        str(seconds) if finished else "", str(seconds-10) if outcome == "approved" else "", "draft", "False"]))


def write(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=t.FIELDS)
        writer.writeheader(); writer.writerows(rows)


def test_counts_failures_and_unfinished_without_imputing_times(tmp_path):
    path = tmp_path / "trials.csv"
    write(path, [row(1,"manual",seconds=40), row(2,"rules",seconds=20), row(3,"ai"),
                 row(4,"ai","failed",5), row(5,"ai","unfinished")])
    result = t.summarize(path)
    assert result["trials"] == 5 and result["participants"] == 1
    assert result["participant_case_groups_with_all_methods"] == 1
    ai = result["methods"]["ai"]
    assert ai["outcomes"] == {"approved":1,"failed":1,"unfinished":1}
    assert ai["approved_rate"] == 1/3 and ai["approved_total_p50_seconds"] == 30
    assert ai["all_finished_total_p50_seconds"] == 17.5
    assert not result["benefit_claim_ready"] and len(result["source_sha256"]) == 64


def test_empty_export_stays_unmeasured_and_actual_rules_is_not_ai(tmp_path):
    path = tmp_path / "trials.csv"
    write(path, [])
    result = t.summarize(path)
    assert result["assessment"] == "awaiting_participants"
    assert result["methods"]["ai"]["approved_rate"] is None
    sample = row(1,"ai"); sample["actual_strategy"] = "rules"
    write(path, [sample])
    assert t.summarize(path)["methods"]["ai"]["approved_strategy_mismatches"] == 1


@pytest.mark.parametrize("change", [
    {"total_seconds":"0"}, {"total_seconds":"nan"}, {"finished_at_utc":""},
    {"ready_at_utc":"2026-11-23 09:59:00"}, {"outcome":"unfinished"},
    {"participant":"Customer real name"}, {"sequence":"0"}, {"schema_version":"unknown"},
])
def test_invalid_or_inconsistent_source_is_rejected(tmp_path, change):
    path = tmp_path / "trials.csv"
    write(path, [{**row(1,"manual"), **change}])
    with pytest.raises(ValueError): t.summarize(path)


def test_duplicate_id_or_participant_sequence_cannot_inflate_sample(tmp_path):
    path = tmp_path / "trials.csv"
    for second in [row(1,"manual"), {**row(2,"rules"), "sequence":"1"}]:
        write(path,[row(1,"manual"),second])
        with pytest.raises(ValueError): t.summarize(path)
