"""Command line: python -m goldenrecord {generate,run,review,all}"""
from __future__ import annotations

import argparse
import json
from datetime import date

from . import pipeline, synth


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="goldenrecord")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="create synthetic multi-ERP extracts with seeded defects")
    gen.add_argument("--vendors", type=int, default=3000)
    gen.add_argument("--invoices", type=int, default=45000)
    gen.add_argument("--seed", type=int, default=42)

    run = sub.add_parser("run", help="run Bronze -> Silver -> Gold locally and write reports")
    run.add_argument("--as-of", type=date.fromisoformat, default=None)

    review = sub.add_parser("review", help="label the review queue from ground truth (simulated steward)")
    review.add_argument("--limit", type=int, default=None)

    sub.add_parser("all", help="generate, run, simulate review, run again")

    args = parser.parse_args(argv)
    if args.command == "generate":
        print(json.dumps(synth.generate(args.vendors, args.invoices, args.seed), indent=2))
    elif args.command == "run":
        print(json.dumps(pipeline.run(args.as_of), indent=2, default=str))
    elif args.command == "review":
        print(f"labelled {pipeline.simulate_review(args.limit)} pairs")
    else:
        print(json.dumps(synth.generate(), indent=2))
        first = pipeline.run()
        print(f"labelled {pipeline.simulate_review()} pairs")
        second = pipeline.run()
        print(json.dumps({"first_run": first, "after_review": second}, indent=2, default=str))


if __name__ == "__main__":
    main()
