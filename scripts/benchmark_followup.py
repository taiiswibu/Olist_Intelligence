"""Run, blind-score or compare follow-up benchmarks. Outputs stay outside Git by default."""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from olist import followup_evaluation as evaluation
from olist.config import ROOT


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--strategies", default="rules")
    run.add_argument("--split", choices=["dev", "holdout"], default="dev")
    run.add_argument("--limit", type=int)
    run.add_argument("--repeats", type=int, default=1)
    run.add_argument("--live", action="store_true")
    run.add_argument("--max-model-calls", type=int, default=20)
    run.add_argument("--seed", type=int, default=41)
    run.add_argument("--pricing", type=Path)
    run.add_argument("--out", type=Path)
    run.add_argument("--max-attempts", type=int, choices=[1, 2, 3], default=1)
    run.add_argument("--request-interval", type=float, default=0)
    score = commands.add_parser("score")
    score.add_argument("--run", type=Path, required=True);score.add_argument("--ratings", type=Path, required=True)
    compare = commands.add_parser("compare")
    compare.add_argument("--before", type=Path, required=True);compare.add_argument("--after", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "run":
            out = args.out or ROOT / "data/processed/followup_evaluations" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            result = asyncio.run(evaluation.run(out, tuple(args.strategies.split(",")), args.split, args.limit, args.repeats,
                args.live, args.max_model_calls, args.seed, json.loads(args.pricing.read_text()) if args.pricing else None,
                evaluation.followup_transport.Policy(args.max_attempts, args.request_interval)))
        elif args.command == "score":
            result = evaluation.score(args.run, args.ratings)
        else:
            result = evaluation.compare(args.before, args.after)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except ValueError as exc:
        parser.exit(2, str(exc)+"\n")


if __name__ == "__main__":
    main()
