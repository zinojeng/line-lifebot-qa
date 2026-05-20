#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


DEFAULT_WIKI = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")
DEFAULT_LOCAL_SOURCES = (
    Path("/Users/ander/Documents/medical/guidelines/ada"),
    Path("/Users/ander/Documents/medical/guidelines/kdigo"),
)


@dataclass(frozen=True)
class SourceRecord:
    path: str
    size: int
    mtime: str
    sha256: str


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def local_records(paths: tuple[Path, ...]) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for root in paths:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            stat = path.stat()
            records.append(
                SourceRecord(
                    path=str(path),
                    size=stat.st_size,
                    mtime=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    sha256=sha256(path),
                )
            )
    return records


def network_head(url: str, timeout: int) -> dict[str, str]:
    request = Request(url, method="HEAD", headers={"User-Agent": "LifeBot-Wiki-Freshness/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return {
            "url": url,
            "status": str(response.status),
            "etag": response.headers.get("ETag", ""),
            "last_modified": response.headers.get("Last-Modified", ""),
            "content_length": response.headers.get("Content-Length", ""),
        }


def write_report(root: Path, records: list[SourceRecord], network: list[dict[str, str]]) -> Path:
    today = date.today().isoformat()
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    state_path = reports / "source-freshness-state.json"
    report_path = reports / "source-freshness-watch.md"
    previous = {}
    if state_path.exists():
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
    prev_by_path = {item.get("path"): item for item in previous.get("local_sources", []) if item.get("path")}
    changed = []
    for record in records:
        prev = prev_by_path.get(record.path)
        if prev and prev.get("sha256") != record.sha256:
            changed.append(record.path)
    state = {
        "generated": today,
        "local_sources": [record.__dict__ for record in records],
        "network_sources": network,
    }
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Source Freshness Watch",
        "",
        f"Generated: {today}",
        "",
        "This report watches local guideline Markdown files and optional official source URLs. A changed file is a signal for Hermes to re-run raw verification before changing canonical clinical pages.",
        "",
        "## Summary",
        "",
        f"- Local source files: {len(records)}",
        f"- Changed since last state: {len(changed)}",
        f"- Network sources checked: {len(network)}",
        "",
        "## Changed Local Sources",
        "",
    ]
    lines.extend(f"- `{item}`" for item in changed) if changed else lines.append("- None")
    lines.extend(["", "## Optional Network Source Headers", ""])
    if network:
        for item in network:
            lines.append(
                f"- {item.get('url')}: status={item.get('status')} etag={item.get('etag') or '-'} last_modified={item.get('last_modified') or '-'}"
            )
    else:
        lines.append("- Not checked")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch guideline source freshness for the ADA-KDIGO LLM Wiki.")
    parser.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    parser.add_argument("--source-dir", action="append", default=[])
    parser.add_argument("--url", action="append", default=[])
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--timeout", type=int, default=12)
    args = parser.parse_args()

    source_dirs = tuple(Path(item).expanduser() for item in args.source_dir) if args.source_dir else DEFAULT_LOCAL_SOURCES
    records = local_records(source_dirs)
    urls = args.url or [url.strip() for url in os.getenv("LINE_WIKI_FRESHNESS_URLS", "").split(",") if url.strip()]
    network: list[dict[str, str]] = []
    if not args.no_network:
        for url in urls:
            try:
                network.append(network_head(url, args.timeout))
            except Exception as exc:
                network.append({"url": url, "status": "error", "error": f"{type(exc).__name__}: {exc}"})
    report = write_report(args.wiki, records, network)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
