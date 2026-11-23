import argparse
import json
from olist.config import init_env


def main():
    init_env()
    parser = argparse.ArgumentParser(description="Olist Intelligence local management")
    parser.add_argument("command", choices=["setup", "download", "ingest", "train", "status", "odoo-seed", "odoo-check", "embed", "models", "agent-lab", "agent-team"])
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--provider", default="groq")
    parser.add_argument("--question")
    parser.add_argument("--thread")
    parser.add_argument("--allow-proposals", action="store_true")
    parser.add_argument("--local-summary", action="store_true")
    args = parser.parse_args()
    if args.command in {"setup", "download", "ingest"}:
        from olist.ingest import download, ingest
        from olist.database import ready
        if args.command == "setup" and ready():
            print("Existing analytical database kept. Use ingest to rebuild explicitly.")
        else:
            download()
            if args.command != "download":
                ingest()
    elif args.command == "train":
        from olist.ml import train
        train()
    elif args.command == "embed":
        from olist.rag import build_embeddings
        print(build_embeddings())
    elif args.command == "odoo-check":
        from scripts.check_odoo import check_odoo
        result = check_odoo()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if not result["ok"]:
            raise SystemExit(1)
    elif args.command == "agent-team":
        from olist.agent_team import cli
        cli(args.question, args.thread, args.local_summary, args.allow_proposals)
    elif args.command == "agent-lab":
        try:
            from olist.agent_lab import cli
        except ModuleNotFoundError:
            parser.exit(1, "Cần cài thêm: python -m pip install -r requirements-agent.txt\n")
        cli(args.provider, args.question, args.thread, args.allow_proposals)
    elif args.command == "odoo-seed":
        from scripts.seed_odoo import seed
        if not 1 <= args.limit <= 50:
            parser.error("--limit must be 1..50")
        print(json.dumps(seed(args.limit), indent=2))
    elif args.command == "models":
        from scripts.list_models import list_models
        print(json.dumps(list_models(args.provider), indent=2))
    else:
        from olist.database import ready
        from olist.llm import provider_status
        print(json.dumps({"data_ready": ready(), "providers": provider_status()}, indent=2))


if __name__ == "__main__":
    main()
