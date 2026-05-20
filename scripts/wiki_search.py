#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_WIKI = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")


@dataclass(frozen=True)
class Hit:
    score: float
    path: str
    title: str
    section: str
    excerpt: str


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, flags=re.S)
    if not match:
        return "", text
    return match.group(1), text[match.end() :]


def field(frontmatter: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:\s*(.*)$", frontmatter, flags=re.M)
    return match.group(1).strip() if match else ""


def tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9+\-.]*|[0-9]+(?:\.[0-9]+)?|[\u4e00-\u9fff]{1,4}", text.lower())
    stop = {"and", "or", "the", "with", "for", "of", "to", "in", "a", "an", "請問", "是否", "怎麼"}
    return [token for token in tokens if token not in stop and len(token.strip()) > 0]


def sections(body: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"^(#{1,3})\s+(.+)$", body, flags=re.M))
    if not matches:
        return [("", body)]
    out: list[tuple[str, str]] = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        out.append((match.group(2).strip(), body[start:end].strip()))
    return out


def score_text(query_tokens: list[str], title: str, frontmatter: str, section_title: str, body: str) -> float:
    title_l = title.lower()
    fm_l = frontmatter.lower()
    section_l = section_title.lower()
    body_l = body.lower()
    score = 0.0
    for token in query_tokens:
        if token in title_l:
            score += 8
        if token in section_l:
            score += 5
        if token in fm_l:
            score += 4
        count = body_l.count(token)
        if count:
            score += min(6, count) * 1.2
    phrase = " ".join(query_tokens[:6])
    if phrase and phrase in (title_l + " " + fm_l + " " + body_l):
        score += 12
    return score


def excerpt_for(body: str, query_tokens: list[str], max_chars: int) -> str:
    body_one_line = re.sub(r"\s+", " ", body).strip()
    lower = body_one_line.lower()
    positions = [lower.find(token) for token in query_tokens if lower.find(token) >= 0]
    if not positions:
        return body_one_line[:max_chars]
    center = min(positions)
    start = max(0, center - max_chars // 3)
    return body_one_line[start : start + max_chars]


def search(root: Path, query: str, limit: int, include_raw: bool) -> list[Hit]:
    query_tokens = tokenize(query)
    hits: list[Hit] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if not include_raw and rel.startswith("raw/"):
            continue
        if "/.obsidian/" in rel or path.name.startswith("Icon"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        fm, body = split_frontmatter(text)
        title = field(fm, "title") or path.stem.replace("-", " ")
        for section_title, section_body in sections(body):
            score = score_text(query_tokens, title, fm, section_title, section_body)
            if score <= 0:
                continue
            hits.append(
                Hit(
                    score=round(score, 2),
                    path=rel,
                    title=title,
                    section=section_title or title,
                    excerpt=excerpt_for(section_body, query_tokens, 500),
                )
            )
    return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Small local search engine for the ADA-KDIGO LLM Wiki.")
    parser.add_argument("query")
    parser.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--include-raw", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    hits = search(args.wiki, args.query, args.limit, args.include_raw)
    if args.json:
        print(json.dumps([hit.__dict__ for hit in hits], ensure_ascii=False, indent=2))
        return 0
    for hit in hits:
        print(f"{hit.score:>6}  {hit.path}  # {hit.section}")
        print(f"        {hit.excerpt[:260]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
