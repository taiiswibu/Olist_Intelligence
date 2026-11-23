"""Inspect native Odoo timing exports without inventing human ratings or missing times."""
import csv
import hashlib
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

SCHEMA = "followup-task-times-v1"
FIELDS = ["schema_version", "trial_id", "participant", "case", "sequence", "assignment_version", "method", "actual_strategy", "outcome",
          "started_at_utc", "ready_at_utc", "finished_at_utc", "total_seconds", "after_ready_seconds", "quotation_state", "has_activity"]
METHODS = ("manual", "rules", "ai")


def read(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise ValueError("Dùng CSV nguyên bản từ Lượt đo thao tác; cột hoặc phiên bản chưa đúng.")
        rows = list(reader)
    seen, sequences = set(), set()
    def date(value):
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) if value else None
    for row in rows:
        try:
            if None in row or any(v is None for v in row.values()): raise ValueError()
            if row["schema_version"] != SCHEMA or row["assignment_version"] != "cyclic-v1": raise ValueError()
            if not re.fullmatch(r"[a-f0-9]{32}", row["trial_id"]) or row["trial_id"] in seen: raise ValueError()
            if not re.fullmatch(r"P_[a-f0-9]{12}", row["participant"]) or not re.fullmatch(r"T_[a-f0-9]{12}", row["case"]): raise ValueError()
            sequence = int(row["sequence"])
            if sequence < 1 or (row["participant"], sequence) in sequences: raise ValueError()
            if row["method"] not in METHODS or row["outcome"] not in {"approved", "failed", "cancelled", "unfinished"}: raise ValueError()
            if row["actual_strategy"] not in {"manual", "rules", "groq", "gemini", "pipeline", "unknown"}: raise ValueError()
            if row["quotation_state"] not in {"draft", "sent"} or row["has_activity"] not in {"True", "False"}: raise ValueError()
            start, ready, end = (date(row[k]) for k in ("started_at_utc", "ready_at_utc", "finished_at_utc"))
            if not start or ready and ready < start or end and end < (ready or start): raise ValueError()
            if bool(end) != (row["outcome"] != "unfinished"): raise ValueError()
            for key, expected in [("total_seconds", (end-start).total_seconds() if end else None),
                                  ("after_ready_seconds", (end-ready).total_seconds() if end and ready else None)]:
                if expected is None:
                    if row[key] != "": raise ValueError()
                    row[key] = None
                else:
                    value = float(row[key])
                    if not math.isfinite(value) or abs(value-expected) > .01: raise ValueError()
                    row[key] = value
            if row["outcome"] == "approved" and ready is None: raise ValueError()
            seen.add(row["trial_id"]); sequences.add((row["participant"], sequence))
        except (ValueError, TypeError, KeyError):
            raise ValueError("CSV có lượt trùng, mã/thời gian/kết quả không hợp lệ; chưa tính báo cáo.") from None
    return rows


def summarize(path):
    rows = read(path)
    methods = {}
    paired = defaultdict(set)
    for row in rows: paired[row["participant"], row["case"]].add(row["method"])
    for method in METHODS:
        selected = [r for r in rows if r["method"] == method]
        approved = [r for r in selected if r["outcome"] == "approved"]
        completed_times = [r["total_seconds"] for r in selected if r["total_seconds"] is not None]
        matching = {"manual"} if method == "manual" else {"rules"} if method == "rules" else {"groq", "gemini", "pipeline"}
        methods[method] = {"assigned_trials": len(selected), "outcomes": dict(Counter(r["outcome"] for r in selected)),
            "approved_rate": len(approved)/len(selected) if selected else None,
            "approved_total_p50_seconds": median(r["total_seconds"] for r in approved) if approved else None,
            "all_finished_total_p50_seconds": median(completed_times) if completed_times else None,
            "actual_strategies": dict(Counter(r["actual_strategy"] for r in selected)),
            "approved_strategy_mismatches": sum(r["actual_strategy"] not in matching for r in approved)}
    return {"schema_version": SCHEMA, "source_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "trials": len(rows), "participants": len({r["participant"] for r in rows}),
        "participant_case_groups_with_all_methods": sum(m == set(METHODS) for m in paired.values()),
        "methods": methods, "human_business_ratings": "not_in_timing_export", "benefit_claim_ready": False,
        "assessment": "awaiting_participants" if not rows else "descriptive_pilot_only",
        "limits": ["Exported selection only; cannot establish coverage of all assigned tasks.",
                   "Cyclic assignment, changing ERP sources and learning effects do not establish causality.",
                   "Approved-only times may favor a method with many failures. Compare outcomes alongside times.",
                   "Finished times include failed/cancelled attempts; a quick failure is not a successful fast task.",
                   "Wall-clock time includes waiting and time away, not attention alone.",
                   "No independent business quality ratings or sufficient sample-size evidence in this export."]}
