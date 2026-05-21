#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path


DEFAULT_WIKI = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")
DEFAULT_DB = DEFAULT_WIKI / "_meta" / "wiki-search.sqlite3"


@dataclass(frozen=True)
class Hit:
    score: float
    path: str
    title: str
    section: str
    page_type: str
    excerpt: str


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, flags=re.S)
    if not match:
        return "", text
    return match.group(1), text[match.end() :]


def field(frontmatter: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.*)$", frontmatter, flags=re.M)
    return match.group(1).strip().strip("'\"") if match else ""


def flatten_frontmatter(frontmatter: str) -> str:
    return re.sub(r"\s+", " ", frontmatter).strip()


def clean(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def sections(body: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"^(#{1,3})\s+(.+)$", body, flags=re.M))
    if not matches:
        return [("", body)]
    out = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        out.append((match.group(2).strip(), body[start:end].strip()))
    return out


def connect(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def rebuild(root: Path, db: Path, include_raw: bool = False) -> dict[str, int]:
    conn = connect(db)
    conn.executescript(
        """
        DROP TABLE IF EXISTS pages;
        DROP TABLE IF EXISTS page_fts;
        CREATE TABLE pages (
          id INTEGER PRIMARY KEY,
          path TEXT NOT NULL,
          title TEXT NOT NULL,
          section TEXT NOT NULL,
          page_type TEXT NOT NULL,
          frontmatter TEXT NOT NULL,
          body TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE page_fts USING fts5(
          title,
          section,
          page_type,
          frontmatter,
          body,
          content='pages',
          content_rowid='id',
          tokenize='unicode61'
        );
        """
    )
    inserted = 0
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if path.name.startswith("Icon") or "/.obsidian/" in rel:
            continue
        if not include_raw and rel.startswith("raw/"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        frontmatter, body = split_frontmatter(text)
        title = field(frontmatter, "title") or path.stem.replace("-", " ")
        page_type = field(frontmatter, "type") or (rel.split("/", 1)[0] if "/" in rel else "root")
        fm_flat = flatten_frontmatter(frontmatter)
        for section_title, section_body in sections(body):
            body_clean = clean(section_body)
            if len(body_clean) < 40:
                continue
            cur = conn.execute(
                "INSERT INTO pages(path,title,section,page_type,frontmatter,body) VALUES(?,?,?,?,?,?)",
                (rel, title, section_title or title, page_type, fm_flat, body_clean),
            )
            rowid = cur.lastrowid
            conn.execute(
                "INSERT INTO page_fts(rowid,title,section,page_type,frontmatter,body) VALUES(?,?,?,?,?,?)",
                (rowid, title, section_title or title, page_type, fm_flat, body_clean),
            )
            inserted += 1
    conn.commit()
    conn.close()
    return {"sections": inserted}


def to_fts_query(query: str) -> str:
    terms = re.findall(r"[A-Za-z][A-Za-z0-9+\-.]*|\d+(?:\.\d+)?|[\u4e00-\u9fff]{1,4}", query)
    cleaned = [term.replace('"', "") for term in terms if term.strip()]
    if not cleaned:
        return '""'
    return " OR ".join(f'"{term}"' for term in cleaned[:24])


def search(db: Path, query: str, limit: int) -> list[Hit]:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    fts_query = to_fts_query(query)
    fts_rows = conn.execute(
        """
        SELECT
          bm25(page_fts, 6.0, 4.0, 2.0, 3.0, 1.0) AS rank,
          pages.path,
          pages.title,
          pages.section,
          pages.page_type,
          snippet(page_fts, 4, '', '', ' ... ', 48) AS excerpt
        FROM page_fts
        JOIN pages ON pages.id = page_fts.rowid
        WHERE page_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (fts_query, max(limit * 3, limit + 12)),
    ).fetchall()
    fallback_rows = fallback_like_search(conn, query, max(limit * 3, limit + 12)) if should_merge_fallback(query) or not fts_rows else []
    rows = rerank_rows([*fts_rows, *fallback_rows], query, limit)
    conn.close()
    hits = []
    for row in rows:
        score = round(float(row["rank"]) * -1, 4)
        hits.append(Hit(score, row["path"], row["title"], row["section"], row["page_type"], row["excerpt"]))
    return hits


def should_merge_fallback(query: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", query)) or any(
        term in query.lower()
        for term in ("evidence grade", "recommendation grade", "strong recommendation", "lower certainty", "practice point")
    )


def evidence_grade_query(query: str) -> bool:
    lower = query.lower()
    return any(term in query for term in ("證據等級", "建議等級", "證據較低", "哪些證據", "哪些建議")) or any(
        term in lower
        for term in ("evidence grade", "recommendation grade", "strong recommendation", "lower certainty", "practice point", "grade c")
    )


def pregnancy_pharmacotherapy_query(query: str) -> bool:
    lower = query.lower()
    gdm_specific = any(term in query for term in ("妊娠糖尿病", "懷孕糖尿病", "孕期糖尿病")) or any(
        term in lower for term in ("gdm", "gestational diabetes")
    )
    diabetes_pregnancy = gdm_specific or any(term in lower for term in ("diabetes in pregnancy", "pregnancy diabetes"))
    drug_specific = any(term in query for term in ("胰島素",)) or any(
        term in lower for term in ("metformin", "glyburide", "insulin")
    )
    generic_gdm_medication = any(term in query for term in ("藥", "用藥", "口服藥")) or any(
        term in lower for term in ("pharmacotherapy", "medication", "oral agent")
    )
    return diabetes_pregnancy and (drug_specific or generic_gdm_medication)


def kidney_context_query(query: str) -> bool:
    lower = query.lower()
    return "腎" in query or any(term in lower for term in ("ckd", "egfr", "kidney", "renal", "uacr", "albuminuria"))


def rerank_rows(rows: list[sqlite3.Row | dict], query: str, limit: int) -> list[sqlite3.Row | dict]:
    best: dict[tuple[str, str], tuple[float, sqlite3.Row | dict]] = {}
    for row in rows:
        path = str(row["path"])
        section = str(row["section"])
        rank = float(row["rank"])
        score = -rank
        page_type = str(row["page_type"]).lower()
        haystack = " ".join(
            str(row.get(key, "") if isinstance(row, dict) else row[key] if key in row.keys() else "")
            for key in ("path", "title", "section", "page_type", "frontmatter", "excerpt")
        ).lower()
        if evidence_grade_query(query):
            if page_type == "claim" or path.startswith("claims/"):
                score *= 8.0
            if "ada-kdigo-2026-ckd-cardiorenal-claims" in path:
                score *= 20.0
            if any(term in haystack for term in ("claim_id", "lower-certainty", "grade c", "practice point", "1c")):
                score *= 3.0
        if pregnancy_pharmacotherapy_query(query):
            if "ada-2026-gdm-pharmacotherapy" in path:
                score *= 40.0
            if "diabetes-pregnancy-gdm-cgm" in path:
                score *= 15.0
            if any(term in haystack for term in ("15.17", "15.21", "not first-line", "cross placenta", "glyburide", "insulin preferred")):
                score *= 5.0
            if page_type == "claim" or path.startswith("claims/"):
                score *= 3.0
            if not kidney_context_query(query) and any(term in haystack for term in ("ckd", "egfr", "albuminuria", "kidney")):
                score *= 0.2
        key = (path, section)
        existing = best.get(key)
        if not existing or score > existing[0]:
            best[key] = (score, row)
    ordered = sorted(best.values(), key=lambda item: item[0], reverse=True)[:limit]
    out = []
    for score, row in ordered:
        if isinstance(row, dict):
            row["rank"] = -score
        out.append(row)
    return out


def query_terms(query: str) -> list[str]:
    terms = re.findall(r"[A-Za-z][A-Za-z0-9+\-.]*|\d+(?:\.\d+)?|[\u4e00-\u9fff]{1,4}", query.lower())
    return [term for term in terms if term.strip()]


def fallback_like_search(conn: sqlite3.Connection, query: str, limit: int) -> list[sqlite3.Row]:
    terms = query_terms(query)
    if not terms:
        return []
    rows = conn.execute(
        "SELECT 0.0 AS rank, path, title, section, page_type, frontmatter, body AS excerpt FROM pages"
    ).fetchall()
    scored: list[tuple[float, sqlite3.Row]] = []
    for row in rows:
        title = str(row["title"]).lower()
        section = str(row["section"]).lower()
        page_type = str(row["page_type"]).lower()
        frontmatter = str(row["frontmatter"]).lower()
        body = str(row["excerpt"]).lower()
        score = 0.0
        for term in terms:
            if term in title:
                score += 8.0
            if term in section:
                score += 5.0
            if term in page_type:
                score += 4.0
            if term in frontmatter:
                score += 3.0
            count = body.count(term)
            if count:
                score += min(count, 6) * 1.3
        if ("claim" in frontmatter or str(row["path"]).startswith("claims/")) and any(term in query for term in ("證據", "建議", "strong", "grade")):
            score *= 6.0
        if evidence_grade_query(query) and "ada-kdigo-2026-ckd-cardiorenal-claims" in str(row["path"]):
            score *= 20.0
        if pregnancy_pharmacotherapy_query(query):
            path = str(row["path"])
            row_text = " ".join(str(row[key]).lower() for key in ("title", "section", "frontmatter", "excerpt"))
            if "ada-2026-gdm-pharmacotherapy" in path:
                score *= 40.0
            if "diabetes-pregnancy-gdm-cgm" in path:
                score *= 15.0
            if any(term in row_text for term in ("15.17", "15.21", "not first-line", "cross placenta", "glyburide", "insulin preferred")):
                score *= 5.0
            if not kidney_context_query(query) and any(term in row_text for term in ("ckd", "egfr", "albuminuria", "kidney")):
                score *= 0.2
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    converted = []
    for score, row in scored[:limit]:
        excerpt = str(row["excerpt"])
        converted.append(
            {
                "rank": -score,
                "path": row["path"],
                "title": row["title"],
                "section": row["section"],
                "page_type": row["page_type"],
                "excerpt": excerpt[:500],
            }
        )
    return converted  # type: ignore[return-value]


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite FTS5 / QMD-like search for the LLM Wiki.")
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--include-raw", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.rebuild or not args.db.exists():
        stats = rebuild(args.wiki, args.db, include_raw=args.include_raw)
        if not args.query:
            print(json.dumps({"db": str(args.db), **stats}, ensure_ascii=False) if args.json else f"rebuilt {args.db} sections={stats['sections']}")
            return 0
    if not args.query:
        parser.error("query is required unless only rebuilding")
    hits = search(args.db, args.query, args.limit)
    if args.json:
        print(json.dumps([hit.__dict__ for hit in hits], ensure_ascii=False, indent=2))
        return 0
    for hit in hits:
        print(f"{hit.score:>9}  {hit.path}  # {hit.section} [{hit.page_type}]")
        print(f"           {hit.excerpt[:320]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
