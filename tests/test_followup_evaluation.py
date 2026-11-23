import asyncio
import csv
import json
from collections import Counter

import pytest

from olist import followup_evaluation as e


def test_suite_is_grouped_and_has_separate_development_and_reserved_cases():
    assert e.digest(e.SUITE) == "fe652bdd8453a467f5db201ead16fac5822333f302c2c42c51945ba72af744b1"
    _, dev = e.load_cases("dev");_, held = e.load_cases("holdout")
    assert len(dev) == 40 and len(held) == 80
    assert not {c["family"] for c in dev} & {c["family"] for c in held}
    assert set(Counter(c["family"] for c in dev+held).values()) == {4}


def test_no_network_baseline_exports_blind_unscored_artifacts_and_rejects_overwrite(tmp_path):
    output = tmp_path/"run"
    result = asyncio.run(e.run(output, limit=3))
    assert result["summary"]["rules"]["cases"] == 3
    assert result["summary"]["rules"]["model_calls"] == 0
    assert result["summary"]["rules"]["contract_pass_rate"] == 1
    with (output/"blind_samples.csv").open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream));assert len(rows) == 3 and "strategy" not in rows[0]
    marked = e.score(output, output/"ratings.csv")
    assert not marked["fully_rated"] and not marked["quality_claim_ready"]
    manifest, records = e.read_run(output)
    assert manifest["label_status"] == "engineering_labels_not_expert_reviewed"
    assert len(manifest["source_hashes"]) >= 6 and len(manifest["suite_sha256"]) == 64
    with pytest.raises(ValueError):asyncio.run(e.run(output, limit=3))


def test_model_evaluation_requires_live_flag_and_budget_before_calling_provider(tmp_path):
    with pytest.raises(ValueError, match="--live"):
        asyncio.run(e.run(tmp_path/"no-live", ("groq",), limit=1))
    with pytest.raises(ValueError, match="vượt"):
        asyncio.run(e.run(tmp_path/"over-budget", ("pipeline",), live=True, max_model_calls=1, limit=1))
    assert not (tmp_path/"over-budget").exists()


def test_paired_comparison_and_human_ratings_validation(tmp_path):
    first, second = tmp_path/"a", tmp_path/"b"
    asyncio.run(e.run(first, limit=2));asyncio.run(e.run(second, limit=2))
    compared = e.compare(first, second)
    assert compared["paired_cases"] == 2 and compared["deltas"]["rules"]["contract_pass_rate"] == 0
    assert compared["grounding_versions"] == {"before": e.followup_grounding.VERSION, "after": e.followup_grounding.VERSION}
    with (first/"ratings.csv").open(encoding="utf-8-sig") as stream:rows = list(csv.DictReader(stream))
    for row in rows:row.update(business_correct="1", grounded="1", usable="4", decision="edit", edit_seconds="12")
    def write():
        with (first/"ratings.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=e.RATING_FIELDS);writer.writeheader();writer.writerows(rows)
    write();scored = e.score(first, first/"ratings.csv")
    assert scored["fully_rated"] and scored["strategies"]["rules"]["business_correct"] == 1
    rows.append(rows[0]);write()
    with pytest.raises(ValueError):e.score(first, first/"ratings.csv")
    manifest = json.loads((second/"manifest.json").read_text())
    manifest["suite_sha256"] = "different"
    (second/"manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):e.compare(first, second)


def test_cost_is_unknown_without_pricing_and_uses_only_matching_model_rates():
    trace = [{"provider": "groq", "model": "fixture", "usage": {"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500}}]
    assert e.estimate_cost(trace, None) is None
    pricing = {"currency": "USD", "as_of": "2026-11-23", "source": "fixture only", "groq": {"model": "fixture", "input_per_million": 2, "output_per_million": 4}}
    e.validate_pricing(pricing)
    assert e.estimate_cost(trace, pricing) == .004
    pricing["groq"]["model"] = "different"
    assert e.estimate_cost(trace, pricing) is None


def test_failures_stay_in_denominator_and_partial_runs_cannot_be_scored(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from olist import followups
    original = followups.analyze_strategy
    monkeypatch.setattr(e.llm, "providers", lambda: [SimpleNamespace(name="groq", model="fixture")])
    async def fake(payload, strategy):
        if strategy == "groq":
            raise followups.AnalysisFailure([{"provider": "groq", "model": "fixture", "status": "failed", "usage": None}], "FixtureFailure")
        return await original(payload, strategy)
    monkeypatch.setattr(followups, "analyze_strategy", fake)
    output = tmp_path/"failure"
    result = asyncio.run(e.run(output, ("rules", "groq"), live=True, limit=2))
    assert result["summary"]["groq"]["cases"] == 2 and result["summary"]["groq"]["completed"] == 0
    assert result["summary"]["groq"]["model_calls"] == 2 and result["summary"]["groq"]["tokens_reported"] is None
    assert result["summary"]["groq"]["failures"] == {"FixtureFailure": 2}
    assert result["summary"]["groq"]["http_status_counts"] == {}
    path = output/"results.jsonl"
    path.write_text('\n'.join(path.read_text(encoding="utf-8").splitlines()[:-1])+"\n", encoding="utf-8")
    with pytest.raises(ValueError):e.score(output, output/"ratings.csv")
