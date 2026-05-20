#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import tarfile
from pathlib import Path


DEFAULT_WIKI = os.getenv(
    "HERMES_LLM_WIKI_DIR",
    "/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki",
)
DEFAULT_OUTPUT = "deploy/zeabur-llm-wiki.tar"
EXCLUDED_ROOTS = {".git", ".obsidian", ".metadata_cache", "inbox", "reports"}


def is_metadata_file_name(name: str) -> bool:
    return name == ".DS_Store" or name.startswith("._") or name == "Icon" or (
        name.startswith("Icon") and len(name) <= 5
    )


def should_include(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    parts = relative.parts
    if not parts:
        return False
    if parts[0] in EXCLUDED_ROOTS:
        return False
    if is_metadata_file_name(path.name):
        return False
    if path.name.startswith("wiki-search.sqlite"):
        return False
    return True


def normalized_tarinfo(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo:
    tarinfo.uid = 0
    tarinfo.gid = 0
    tarinfo.uname = ""
    tarinfo.gname = ""
    tarinfo.mtime = 0
    if tarinfo.isdir():
        tarinfo.mode = 0o755
    elif tarinfo.isfile():
        tarinfo.mode = 0o644
    return tarinfo


def build_archive(wiki: Path, output: Path) -> int:
    if not wiki.is_dir():
        raise SystemExit(f"wiki directory not found: {wiki}")
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown_count = 0
    with tarfile.open(output, "w") as archive:
        for path in sorted([wiki, *wiki.rglob("*")], key=lambda item: str(item.relative_to(wiki.parent))):
            if not should_include(path, wiki):
                continue
            if path.is_symlink():
                continue
            arcname = path.relative_to(wiki.parent)
            archive.add(path, arcname=str(arcname), recursive=False, filter=normalized_tarinfo)
            if path.is_file() and path.suffix == ".md":
                markdown_count += 1
    return markdown_count


def verify_archive(output: Path, expected_top: str, min_markdown: int) -> int:
    markdown_count = 0
    top_levels: set[str] = set()
    with tarfile.open(output, "r:*") as archive:
        for member in archive.getmembers():
            parts = Path(member.name).parts
            if not parts:
                raise SystemExit(f"archive contains empty member name: {member.name!r}")
            top_levels.add(parts[0])
            if len(parts) > 1 and parts[1] in EXCLUDED_ROOTS:
                raise SystemExit(f"archive contains excluded root: {member.name}")
            if is_metadata_file_name(Path(member.name).name):
                raise SystemExit(f"archive contains AppleDouble file: {member.name}")
            if member.islnk() or member.issym() or member.isdev() or member.isfifo():
                raise SystemExit(f"archive contains unsafe member type: {member.name}")
            if member.isfile() and member.name.endswith(".md"):
                markdown_count += 1
    if top_levels != {expected_top}:
        raise SystemExit(f"archive top-levels {sorted(top_levels)!r} do not match {expected_top!r}")
    if markdown_count < min_markdown:
        raise SystemExit(f"archive markdown count {markdown_count} below minimum {min_markdown}")
    return markdown_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and verify the bundled Zeabur LLM Wiki seed archive.")
    parser.add_argument("--wiki", default=DEFAULT_WIKI)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--min-markdown", type=int, default=20)
    args = parser.parse_args()

    wiki = Path(args.wiki).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    built_count = build_archive(wiki, output)
    verified_count = verify_archive(output, wiki.name, args.min_markdown)
    print(f"archive={output}")
    print(f"wiki={wiki}")
    print(f"markdown_files={verified_count}")
    if built_count != verified_count:
        print(f"warning=built_count({built_count}) != verified_count({verified_count})")


if __name__ == "__main__":
    main()
