#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from section12_routing import REQUIRED_SECTION12_WIKI_FILES, SECTION12_REQUIRED_TERMS


def main() -> int:
    parser = argparse.ArgumentParser(description="Check required LLM Wiki files for Section 12 evidence-grade routing.")
    parser.add_argument("--wiki", type=Path, required=True)
    args = parser.parse_args()

    missing_files = [rel for rel in REQUIRED_SECTION12_WIKI_FILES if not (args.wiki / rel).exists()]
    combined = ""
    for rel in REQUIRED_SECTION12_WIKI_FILES:
        path = args.wiki / rel
        if path.exists():
            combined += "\n" + path.read_text(encoding="utf-8", errors="ignore")
    missing_terms = [term for term in SECTION12_REQUIRED_TERMS if term.lower() not in combined.lower()]

    if missing_files or missing_terms:
        if missing_files:
            print("missing files:")
            for rel in missing_files:
                print(f"- {rel}")
        if missing_terms:
            print("missing terms:")
            for term in missing_terms:
                print(f"- {term}")
        return 1
    print("Section 12 wiki contract OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
