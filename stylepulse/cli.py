"""
StylePulse AI CLI — entry point.

Usage:
  python -m stylepulse run [--data-dir PATH] [--output-dir PATH]
"""

import argparse
import sys

from .engine import run


def main():
    parser = argparse.ArgumentParser(
        prog="stylepulse",
        description="StylePulse AI — Retail intelligence for Lebanese sportswear retailers",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run full analysis and generate report")
    run_parser.add_argument("--data-dir", help="Path to data/real/ directory")
    run_parser.add_argument("--output-dir", help="Path to write reports")

    args = parser.parse_args()

    if args.command == "run":
        run(data_dir=args.data_dir, output_dir=args.output_dir)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
