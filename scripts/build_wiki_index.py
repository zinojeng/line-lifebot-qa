#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_WIKI = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")
MAINTAINED_PREFIXES = {
    "claims",
    "comparisons",
    "concepts",
    "drugs",
    "evidence-cards",
    "evidence-ledger",
    "evals",
    "guidelines",
    "mocs",
    "patient-education",
    "queries",
    "teaching",
}


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, flags=re.S)
    if not match:
        return "", text
    return match.group(1), text[match.end() :]


def field(frontmatter: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:[ \t]*(.*)$", frontmatter, flags=re.M)
    return match.group(1).strip().strip("'\"") if match else ""


def list_field(frontmatter: str, key: str) -> list[str]:
    values: list[str] = []
    inline = field(frontmatter, key)
    if inline.startswith("[") and inline.endswith("]"):
        values.extend(part.strip().strip("'\"") for part in inline[1:-1].split(",") if part.strip())
    elif inline and inline not in {"[]", "{}"}:
        values.append(inline)
    block = re.search(rf"^{re.escape(key)}:\s*\n((?:\s+- .+\n?)+)", frontmatter, flags=re.M)
    if block:
        values.extend(line.split("-", 1)[1].strip().strip("'\"") for line in block.group(1).splitlines() if "-" in line)
    return [value for value in values if value]


def strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def sections(body: str) -> list[str]:
    return [match.group(1).strip() for match in re.finditer(r"^#{1,3}\s+(.+)$", body, flags=re.M)]


def wikilinks(text: str) -> list[str]:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    ignored = {"...", "wikilinks", "related-page-1", "related-page-2", "related-concept-a", "related-concept-b"}
    links = []
    for match in re.findall(r"\[\[([^\]|#]+)", text):
        link = match.strip()
        if link and link not in ignored:
            links.append(link)
    return sorted(set(links))


def page_record(root: Path, path: Path) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    text = path.read_text(encoding="utf-8", errors="ignore")
    frontmatter, body = split_frontmatter(text)
    title = field(frontmatter, "title") or path.stem.replace("-", " ")
    summary = strip_markdown(body)[:420]
    prefix = rel.split("/", 1)[0] if "/" in rel else ""
    return {
        "path": rel,
        "stem": path.stem,
        "title": title,
        "type": field(frontmatter, "type") or prefix or "root",
        "status": field(frontmatter, "status"),
        "evidence_level": field(frontmatter, "evidence_level"),
        "clinical_use": list_field(frontmatter, "clinical_use"),
        "confidence": field(frontmatter, "confidence"),
        "last_verified": field(frontmatter, "last_verified"),
        "updated": field(frontmatter, "updated"),
        "tags": list_field(frontmatter, "tags"),
        "aliases": list_field(frontmatter, "aliases"),
        "entities": list_field(frontmatter, "entities"),
        "sources": list_field(frontmatter, "sources"),
        "wikilinks": wikilinks(text),
        "sections": sections(body)[:40],
        "summary": summary,
        "wordish_count": len(re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", body)),
    }


def claim_records(root: Path, page_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for record in page_records:
        if record.get("type") != "claim" and not str(record.get("path", "")).startswith("claims/"):
            continue
        path = root / str(record["path"])
        text = path.read_text(encoding="utf-8", errors="ignore")
        for table_line in text.splitlines():
            if not table_line.strip().startswith("| `"):
                continue
            cells = [cell.strip().strip("`") for cell in table_line.strip().strip("|").split("|")]
            if len(cells) < 6 or cells[0] == "claim_id":
                continue
            claims.append(
                {
                    "claim_id": cells[0],
                    "source": cells[1],
                    "grade": cells[2],
                    "population": cells[3],
                    "action": strip_markdown(cells[4]),
                    "answer_role": strip_markdown(cells[5]),
                    "page": record["path"],
                    "page_title": record["title"],
                }
            )
    return claims


def build(root: Path) -> dict[str, Any]:
    records = []
    for path in sorted(root.rglob("*.md")):
        if not path.is_file() or path.name.startswith("Icon") or "/.obsidian/" in path.as_posix():
            continue
        rel = path.relative_to(root).as_posix()
        prefix = rel.split("/", 1)[0] if "/" in rel else ""
        if prefix == "raw":
            continue
        records.append(page_record(root, path))
    maintained = [record for record in records if str(record["path"]).split("/", 1)[0] in MAINTAINED_PREFIXES]
    claims = claim_records(root, records)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # Keep wiki_root backwards-compatible for existing operators that treat
        # it as absolute. Portable consumers can use wiki_root_portable instead.
        "wiki_root": str(root.resolve()),
        "wiki_root_portable": ".",
        "wiki_root_absolute": str(root.resolve()),
        "page_count": len(records),
        "maintained_page_count": len(maintained),
        "claim_count": len(claims),
        "pages": records,
        "claims": claims,
        "top_level_counts": top_level_counts(records),
    }


def top_level_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        prefix = str(record["path"]).split("/", 1)[0] if "/" in str(record["path"]) else "root"
        counts[prefix] = counts.get(prefix, 0) + 1
    return dict(sorted(counts.items()))


def write_outputs(root: Path, payload: dict[str, Any]) -> tuple[Path, Path, Path]:
    meta = root / "_meta"
    meta.mkdir(parents=True, exist_ok=True)
    index_path = meta / "INDEX.json"
    page_registry_path = meta / "page-registry.json"
    claim_registry_path = meta / "claim-registry.json"
    index_payload = {
        key: payload[key]
        for key in (
            "generated_at",
            "wiki_root",
            "wiki_root_portable",
            "wiki_root_absolute",
            "page_count",
            "maintained_page_count",
            "claim_count",
            "top_level_counts",
        )
    }
    index_payload["pages"] = [
        {
            key: page[key]
            for key in (
                "path",
                "title",
                "type",
                "status",
                "evidence_level",
                "confidence",
                "last_verified",
                "tags",
                "aliases",
                "entities",
                "summary",
            )
        }
        for page in payload["pages"]
    ]
    index_path.write_text(json.dumps(index_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    page_registry_path.write_text(json.dumps(payload["pages"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    claim_registry_path.write_text(json.dumps(payload["claims"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return index_path, page_registry_path, claim_registry_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build machine-readable JSON registries for the LLM Wiki.")
    parser.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build(args.wiki)
    outputs = write_outputs(args.wiki, payload)
    result = {
        "page_count": payload["page_count"],
        "maintained_page_count": payload["maintained_page_count"],
        "claim_count": payload["claim_count"],
        "outputs": [str(path) for path in outputs],
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"pages={result['page_count']} maintained={result['maintained_page_count']} claims={result['claim_count']}")
        for path in outputs:
            print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
