"""Reproducible engineering benchmarks; human quality ratings remain separate from contract checks."""
import csv
import hashlib
import json
import math
import platform
from importlib.metadata import version
import random
import runpy
import subprocess
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from . import agent_skills, followups, followup_privacy, followup_grounding, llm
from .config import ROOT

VERSION = "followup-evaluation-v1"
STRATEGIES = {"rules": 0, "groq": 1, "gemini": 1, "pipeline": 2}
SUITE = ROOT / "tests/fixtures/followup_benchmark_v1.py"
RATING_FIELDS = ["sample_id", "rater", "business_correct", "grounded", "usable", "decision", "edit_seconds"]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_cases(split="dev", limit=None):
    source = runpy.run_path(str(SUITE))
    rows = [c for c in source["cases"]() if c["split"] == split]
    # Small smoke runs cover different families before adding privacy variants of the same family.
    rows.sort(key=lambda c: (int(c["id"].rsplit("-v", 1)[1]), c["family"]))
    if limit is not None:
        representatives = {}
        for row in rows:
            representatives.setdefault(row["expected_action"], row)
        preferred = list(representatives.values())
        preferred_ids = {row["id"] for row in preferred}
        rows = preferred + [row for row in rows if row["id"] not in preferred_ids]
    return source, rows if limit is None else rows[:limit]


def percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    index = (len(values)-1)*p
    low = int(index); high = min(low+1, len(values)-1)
    return round(values[low]+(values[high]-values[low])*(index-low), 2)


def summarize(records):
    result = {}
    for strategy in sorted({r["strategy"] for r in records}):
        rows = [r for r in records if r["strategy"] == strategy]
        traces = [t for r in rows for t in r["trace"]]
        usage_known = all(t.get("usage") is not None for t in traces)
        costs_known = all(r["estimated_cost"] is not None for r in rows)
        result[strategy] = {"cases": len(rows), "completed": sum(r["completed"] for r in rows),
            "completion_rate": mean(r["completed"] for r in rows),
            "contract_pass_rate": mean(r["contract_pass"] for r in rows),
            "elapsed_p50_ms": percentile([r["elapsed_ms"] for r in rows], .5),
            "elapsed_p95_ms": percentile([r["elapsed_ms"] for r in rows], .95),
            "model_calls": len(traces), "http_requests_privacy_checked": sum(t.get("privacy", {}).get("requests_checked", 0) for t in traces),
            "tokens_reported": sum(t["usage"]["total_tokens"] for t in traces) if usage_known else None,
            "estimated_cost": sum(r["estimated_cost"] for r in rows) if costs_known else None,
            "failures": dict(Counter(r["error"] for r in rows if r.get("error"))),
            "http_status_counts": dict(Counter(str(t["http_status"]) for t in traces if "http_status" in t)),
            "http_errors_without_status": sum(r.get("error") == "HTTPStatusError" and not any("http_status" in t for t in r["trace"]) for r in rows),
            "human_quality": "not_scored"}
    return result


def estimate_cost(trace, pricing):
    total = 0
    for entry in trace:
        rate = pricing.get(entry["provider"], {}) if pricing else {}
        usage = entry.get("usage")
        if rate.get("model") != entry["model"] or usage is None:
            return None
        total += (usage["input_tokens"]*rate["input_per_million"]+usage["output_tokens"]*rate["output_per_million"])/1_000_000
    return total


def validate_pricing(pricing):
    if pricing is None:
        return
    if pricing.get("currency") != "USD" or not pricing.get("as_of") or not pricing.get("source"):
        raise ValueError("Bảng giá cần currency=USD, as_of và source để kiểm tra lại.")
    for name, rate in pricing.items():
        if name in {"currency", "as_of", "source"}:
            continue
        if not isinstance(rate, dict) or not rate.get("model") or any(not isinstance(rate.get(k), (int, float)) or not math.isfinite(rate[k]) or rate[k] < 0 for k in ["input_per_million", "output_per_million"]):
            raise ValueError("Bảng giá thiếu model hoặc đơn giá hợp lệ.")


async def run(output, strategies=("rules",), split="dev", limit=None, repeats=1, live=False, max_model_calls=20, seed=41, pricing=None):
    strategies = tuple(strategies)
    if not strategies or len(set(strategies)) != len(strategies) or not set(strategies) <= STRATEGIES.keys():
        raise ValueError("Chọn phương án duy nhất trong rules, groq, gemini, pipeline.")
    if split not in {"dev", "holdout"} or not 1 <= repeats <= 5 or limit is not None and limit <= 0:
        raise ValueError("Tập đánh giá, số tình huống hoặc số lần lặp chưa hợp lệ.")
    if set(strategies) != {"rules"} and not live:
        raise ValueError("Thêm --live để chủ động gọi API; mặc định chỉ chạy baseline không model.")
    validate_pricing(pricing)
    suite, cases = load_cases(split, limit)
    budget = len(cases)*repeats*sum(STRATEGIES[s] for s in strategies)
    if budget > max_model_calls:
        raise ValueError(f"Lượt này cần tối đa {budget} lần gọi model, vượt --max-model-calls={max_model_calls}.")
    providers = {p.name: p for p in llm.providers()} if live else {}
    needed = set().union(*({"groq", "gemini"} if s == "pipeline" else {s} if s != "rules" else set() for s in strategies))
    if not needed <= providers.keys():
        raise ValueError("Chưa cấu hình đủ model; chưa chạy benchmark.")
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Thư mục kết quả đã có dữ liệu; dùng thư mục mới để giữ lịch sử.")
    output.mkdir(parents=True, exist_ok=True)
    code_files = [ROOT / "olist" / name for name in ["followups.py", "followup_privacy.py", "followup_grounding.py", "team_model.py", "followup_evaluation.py"]]
    skill_files = [ROOT / ".agents/skills" / name / "SKILL.md" for name in agent_skills.FOLLOWUP_SKILLS]
    commit = subprocess.run(["git", "-c", "safe.directory="+ROOT.as_posix(), "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.run(["git", "-c", "safe.directory="+ROOT.as_posix(), "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    manifest = {"evaluation_version": VERSION, "suite_version": suite["VERSION"], "suite_sha256": digest(SUITE),
        "run_state": "running",
        "rubric_version": "followup-rubric-v1",
        "label_status": suite["LABEL_STATUS"], "split": split, "selected_case_ids": [c["id"] for c in cases],
        "repeats": repeats, "strategies": strategies, "seed": seed, "privacy_version": followup_privacy.VERSION,
        "grounding_version": followup_grounding.VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "source_commit": commit.stdout.strip(),
        "worktree_dirty": bool(dirty.stdout.strip()), "sampling": "cover_actions_then_variants-v1" if limit is not None else "all",
        "source_hashes": {p.relative_to(ROOT).as_posix(): digest(p) for p in code_files+skill_files},
        "models": {name: p.model for name, p in providers.items() if name in needed},
        "temperature": 0, "max_output_tokens": 4000, "timeout_per_model_seconds": 30,
        "runtime": {"python": platform.python_version(), "platform": platform.system(),
                    "packages": {name: version(name) for name in ["pydantic", "httpx", "langchain-core"]}},
        "pricing": pricing, "maximum_model_calls": budget,
        "limits": ["Synthetic engineering fixtures, not observed customer outcomes.", "Labels await independent business review.",
                   "Contract checks do not establish semantic quality or sales improvement.",
                   "Latency excludes human reading, editing and approval; cost is an estimate using supplied rates.",
                   "Model aliases can change at the provider; failures remain in the denominator."]}
    (output/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    records = []; rng = random.Random(seed)
    for case in cases:
        for repeat in range(repeats):
            order = list(strategies); rng.shuffle(order)
            for strategy in order:
                start = time.monotonic(); trace = []; items = []; error = None
                try:
                    result = await followups.analyze_strategy(followups.AnalysisRequest.model_validate(case["payload"]), strategy)
                    trace = result["trace"]; items = result["items"]
                except Exception as exc:
                    trace = getattr(exc, "trace", [])
                    error = getattr(exc, "reason", type(exc).__name__)
                completed = bool(items) and error is None
                contract = completed and len(items) == 1 and items[0].get("action") == case["expected_action"] and (
                    set(items[0]["reason_codes"]) == set(case["expected_codes"])) and items[0]["activity_type"] in case["allowed_types"]
                record = {"sample_id": uuid.uuid4().hex[:16], "case_id": case["id"], "family": case["family"], "tags": case["tags"],
                    "strategy": strategy, "repeat": repeat, "completed": completed, "contract_pass": bool(contract),
                    "elapsed_ms": round((time.monotonic()-start)*1000, 2), "trace": trace, "items": items,
                    "error": error, "estimated_cost": estimate_cost(trace, pricing) if trace else 0 if strategy == "rules" else None}
                records.append(record)
                with (output/"results.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False)+"\n")
    summary = summarize(records)
    (output/"summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    blinded = list(records); rng.shuffle(blinded)
    lookup = {c["id"]: c for c in cases}
    with (output/"blind_samples.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["sample_id", "facts", "summary", "note", "explanation", "completed"]);writer.writeheader()
        for record in blinded:
            source = lookup[record["case_id"]]
            item = record["items"][0] if record["items"] else {}
            facts = {"state": source["payload"]["orders"][0]["state"], "reason_codes": source["expected_codes"],
                     "has_activity": bool(source["payload"]["orders"][0]["activities"])}
            writer.writerow({"sample_id": record["sample_id"], "facts": json.dumps(facts, ensure_ascii=False), "completed": record["completed"],
                **{k: item.get(k, "") for k in ["summary", "note", "explanation"]}})
    with (output/"ratings.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=RATING_FIELDS);writer.writeheader()
        for record in blinded:
            for rater in ["rater_a", "rater_b"]:writer.writerow({"sample_id": record["sample_id"], "rater": rater})
    manifest["run_state"] = "complete"
    (output/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"output": str(output), "summary": summary, "human_quality": "not_scored"}


def read_run(path):
    path = Path(path)
    manifest = json.loads((path/"manifest.json").read_text(encoding="utf-8"))
    rows = [json.loads(s) for s in (path/"results.jsonl").read_text(encoding="utf-8").splitlines()]
    expected = Counter((s, c, r) for s in manifest["strategies"] for c in manifest["selected_case_ids"] for r in range(manifest["repeats"]))
    actual = Counter((r["strategy"], r["case_id"], r["repeat"]) for r in rows)
    if manifest.get("run_state") != "complete" or expected != actual or len({r["sample_id"] for r in rows}) != len(rows):
        raise ValueError("Lượt chưa đầy đủ hoặc có mẫu lặp; giữ kết quả thô, không chấm hay so sánh như lượt hoàn tất.")
    return manifest, rows


def score(path, ratings):
    manifest, records = read_run(path)
    known = {r["sample_id"]: r for r in records}; marks = {}; seen = set()
    with Path(ratings).open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            ident, rater = row["sample_id"], row["rater"].strip()
            if ident not in known or not rater or (ident, rater) in seen:
                raise ValueError("Mã mẫu/người chấm không hợp lệ hoặc bị lặp.")
            seen.add((ident, rater))
            if any(not row[k].strip() for k in RATING_FIELDS[2:]):
                continue
            try:
                mark = {"business_correct": int(row["business_correct"]), "grounded": int(row["grounded"]),
                        "usable": int(row["usable"]), "edit_seconds": float(row["edit_seconds"]), "decision": row["decision"]}
            except (ValueError, KeyError):
                raise ValueError("Điểm chấm chưa đúng kiểu dữ liệu.") from None
            if mark["business_correct"] not in {0, 1} or mark["grounded"] not in {0, 1} or not 1 <= mark["usable"] <= 5 or not 0 <= mark["edit_seconds"] < 86400 or mark["decision"] not in {"accept", "edit", "reject"}:
                raise ValueError("Điểm chấm vượt thang hoặc quyết định không hợp lệ.")
            if not known[ident]["completed"] and (mark["business_correct"] or mark["grounded"] or mark["usable"] != 1 or mark["decision"] != "reject"):
                raise ValueError("Lượt không có kết quả phải được tính là không đạt và bị từ chối.")
            marks[ident, rater] = mark
    counts = Counter(ident for ident, _ in marks)
    if any(n > 2 for n in counts.values()):
        raise ValueError("Bản đánh giá này dùng đúng hai người chấm mỗi mẫu để giữ trọng số như nhau.")
    complete = all(counts[sample] == 2 for sample in known)
    output = {"evaluation_version": VERSION, "ratings_sha256": digest(ratings), "fully_rated": complete,
              "rubric_version": manifest.get("rubric_version", "legacy"),
              "rated_rows": len(marks), "required_minimum_rows": 2*len(records), "quality_claim_ready": False,
              "fixture_comparison_ready": complete, "strategies": {}}
    for strategy in manifest["strategies"]:
        ids = {r["sample_id"] for r in records if r["strategy"] == strategy}
        selected = [m for (ident, _), m in marks.items() if ident in ids]
        if selected:
            output["strategies"][strategy] = {"business_correct": mean(m["business_correct"] for m in selected),
                "grounded": mean(m["grounded"] for m in selected), "usable": mean(m["usable"] for m in selected),
                "accept_without_edit": mean(m["decision"] == "accept" for m in selected), "edit_seconds": mean(m["edit_seconds"] for m in selected)}
    output["note"] = "Engineering fixtures; full independent ratings and business validation are required before claiming benefit. Rater identities are user supplied."
    (Path(path)/"human_scores.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def compare(before, after):
    left, old = read_run(before);right, new = read_run(after)
    for key in ["evaluation_version", "suite_sha256", "split", "selected_case_ids", "repeats", "seed"]:
        if left[key] != right[key]:
            raise ValueError("Hai lượt khác bộ đánh giá hoặc tập tình huống; không so sánh trực tiếp.")
    if set(left["strategies"]) != set(right["strategies"]):
        raise ValueError("Hai lượt cần cùng các baseline.")
    a, b = summarize(old), summarize(new)
    human = {}
    if all((Path(p)/"human_scores.json").exists() for p in [before, after]):
        first = json.loads((Path(before)/"human_scores.json").read_text(encoding="utf-8"))
        second = json.loads((Path(after)/"human_scores.json").read_text(encoding="utf-8"))
        if first["fully_rated"] and second["fully_rated"]:
            if first.get("rubric_version") != second.get("rubric_version"):
                raise ValueError("Hai bộ phiếu dùng thang chấm khác phiên bản.")
            human = {s: {k: second["strategies"][s][k]-first["strategies"][s][k] for k in first["strategies"][s]} for s in a}
    return {"before": left["source_commit"], "after": right["source_commit"], "paired_cases": len(old), "human_deltas": human,
        "grounding_versions": {"before": left.get("grounding_version"), "after": right.get("grounding_version")},
        "source_hashes_changed": left["source_hashes"] != right["source_hashes"],
        "deltas": {s: {k: b[s][k]-a[s][k] for k in ["completion_rate", "contract_pass_rate", "elapsed_p50_ms", "elapsed_p95_ms"]} for s in a},
        "note": "Fixture ratings and mechanical metrics, not observed sales improvement." if human else
                "Contract and latency changes only; this is not evidence of higher semantic quality or sales improvement."}
