from __future__ import annotations

import asyncio
import base64
import concurrent.futures
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import html
import hashlib
import hmac
import json
import os
import re
import sqlite3
import sys
import tarfile
import threading
import inspect
from time import monotonic as time_monotonic
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

try:
    from section12_routing import has_kidney_context, has_liver_context, section12_topic_from_context
except ModuleNotFoundError:
    print("WARNING: section12_routing.py not found; Section 12 intent routing is disabled.", file=sys.stderr)
    def has_kidney_context(text: str) -> bool:
        lower = text.lower()
        return bool(
            re.search(r"腎|腎絲球|腎病變|腎衰竭|尿蛋白|白蛋白尿", text)
            or re.search(r"\b(?:ckd|kidney|renal|egfr|uacr|albuminuria|proteinuria|kdigo|finerenone)\b", lower)
        )

    def has_liver_context(text: str) -> bool:
        lower = text.lower()
        return bool(
            re.search(r"肝|脂肪肝|脂肪性肝炎|代謝性脂肪肝|肝硬化|肝纖維", text)
            or re.search(r"\b(?:masld|mash|nafld|nash|steatotic liver|steatohepatitis|fatty liver|cirrhosis|fib-4)\b", lower)
        )

    def section12_topic_from_context(user_text: str, recent_context: str = "") -> str:
        return ""

try:
    from knowledge import (
        KnowledgeHit,
        knowledge_candidates_prompt,
        knowledge_no_answer_text,
        knowledge_prompt_from_hits,
        knowledge_status,
        load_knowledge_base,
        reset_knowledge_cache,
        hit_facets,
        clinical_search_brain_plan,
        query_variant_specs,
        required_facets,
        search_knowledge_candidates,
        search_knowledge_candidates_with_trace,
        search_whole_section_context,
    )
except ModuleNotFoundError:
    KnowledgeHit = Any

    def knowledge_no_answer_text() -> str:
        return (
            "目前糖尿病指南知識庫尚未正確載入，"
            "為了避免提供不準確的資訊，我先不回答這個問題。"
        )

    def search_knowledge_candidates(query: str) -> list[Any]:
        return []

    def search_knowledge_candidates_with_trace(query: str) -> dict[str, Any]:
        return {
            "hits": [],
            "retrieval_mode": "fallback_raw",
            "elapsed_ms": 0.0,
            "fast_path_enabled": False,
            "fast_hit_count": 0,
            "fallback_reason": "knowledge_module_unavailable",
        }

    def search_whole_section_context(query: str, seed_hits: list[Any]) -> list[Any]:
        return []

    def query_variant_specs(query: str) -> list[Any]:
        return []

    def knowledge_candidates_prompt(hits: list[Any]) -> str:
        return "\n\n候選指南內容：目前部署環境沒有載入 knowledge.py。"

    def knowledge_prompt_from_hits(hits: list[Any]) -> str:
        return (
            "\n\n背景知識檢索：目前部署環境沒有載入 knowledge.py，"
            "請不要使用模型內建知識回答。"
        )

    def knowledge_status() -> dict[str, object]:
        return {
            "enabled": False,
            "available": False,
            "error": "knowledge.py not found in deployment",
        }

    def load_knowledge_base() -> Any:
        return None

    def reset_knowledge_cache() -> None:
        return None

    def required_facets(query: str) -> set[str]:
        return set()

    def hit_facets(hit: Any) -> set[str]:
        return set()

    def clinical_search_brain_plan(query: str) -> dict[str, list[str]]:
        return {}


GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com").rstrip("/")
APP_VERSION = os.getenv("APP_VERSION", "2026-05-21-wiki-self-heal-v46")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_REASONING_EFFORT = os.getenv("DEEPSEEK_REASONING_EFFORT", "high")
DEEPSEEK_THINKING_ENABLED = os.getenv("DEEPSEEK_THINKING_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "20"))
LINE_QUERY_PLANNING_ENABLED = os.getenv("LINE_QUERY_PLANNING_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
LINE_EVIDENCE_REVIEW_ENABLED = os.getenv("LINE_EVIDENCE_REVIEW_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
LINE_LLM_RERANK_ENABLED = os.getenv("LINE_LLM_RERANK_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
LINE_LLM_RERANK_TOP_K = int(os.getenv("LINE_LLM_RERANK_TOP_K", "5"))
LINE_RECURSIVE_COVERAGE_ENABLED = os.getenv("LINE_RECURSIVE_COVERAGE_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
LINE_RECURSIVE_COVERAGE_MAX_QUERIES = int(os.getenv("LINE_RECURSIVE_COVERAGE_MAX_QUERIES", "2"))
LINE_RECURSIVE_COVERAGE_MAX_HITS = int(os.getenv("LINE_RECURSIVE_COVERAGE_MAX_HITS", "2"))
LINE_LONG_CONTEXT_VERIFICATION_ENABLED = os.getenv("LINE_LONG_CONTEXT_VERIFICATION_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
LINE_PARALLEL_VERIFICATION_ENABLED = os.getenv("LINE_PARALLEL_VERIFICATION_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
LINE_WHOLE_SECTION_CONTEXT_ENABLED = os.getenv("LINE_WHOLE_SECTION_CONTEXT_ENABLED", "0").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
LINE_DEBUG_SEARCH_ENABLED = os.getenv("LINE_DEBUG_SEARCH_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
LINE_DEBUG_SEARCH_MAX_HITS = int(os.getenv("LINE_DEBUG_SEARCH_MAX_HITS", "12"))
LINE_RETRIEVAL_QUERY_MAX_CHARS = int(os.getenv("LINE_RETRIEVAL_QUERY_MAX_CHARS", "1400"))
LINE_KNOWLEDGE_PRELOAD_ENABLED = os.getenv("LINE_KNOWLEDGE_PRELOAD_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
LINE_HEALTH_FAST_ENABLED = os.getenv("LINE_HEALTH_FAST_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
LINE_HEALTH_STATUS_CACHE_SECONDS = int(os.getenv("LINE_HEALTH_STATUS_CACHE_SECONDS", "30"))
LINE_LLM_WIKI_SELF_HEAL_ENABLED = os.getenv("LINE_LLM_WIKI_SELF_HEAL_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
LINE_LLM_WIKI_SELF_HEAL_ARCHIVE = os.getenv("LINE_LLM_WIKI_SELF_HEAL_ARCHIVE", "deploy/zeabur-llm-wiki.tar")
LINE_LLM_WIKI_SELF_HEAL_MIN_FILES = int(os.getenv("LINE_LLM_WIKI_SELF_HEAL_MIN_FILES", "20"))
DEFAULT_LLM_WIKI_DIRS = "/app/data/wiki/ada-kdigo-diabetes-wiki,/app/data/llm-wiki,/app/wiki"
LLM_WIKI_SEED_EXCLUDED_ROOTS = {".git", ".obsidian", ".metadata_cache", "inbox", "reports"}


def is_metadata_file_name(name: str) -> bool:
    return name == ".DS_Store" or name.startswith("._") or name == "Icon" or (
        name.startswith("Icon") and len(name) <= 5
    )
LINE_TIMEOUT = int(os.getenv("LINE_TIMEOUT", "12"))
LINE_MEMORY_ENABLED = os.getenv("LINE_MEMORY_ENABLED", "1").strip() != "0"
LINE_MEMORY_DB = os.getenv("LINE_MEMORY_DB", "/tmp/line_lifebot_memory.sqlite3")
LINE_CONTEXT_ENABLED = os.getenv("LINE_CONTEXT_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
LINE_CONTEXT_MAX_MESSAGES = int(os.getenv("LINE_CONTEXT_MAX_MESSAGES", "8"))
LINE_CONTEXT_TTL_SECONDS = int(os.getenv("LINE_CONTEXT_TTL_SECONDS", "43200"))
LINE_SESSION_SCOPE = os.getenv("LINE_SESSION_SCOPE", "user").strip().lower()
LINE_QUERY_CANDIDATE_WRITEBACK_ENABLED = os.getenv("LINE_QUERY_CANDIDATE_WRITEBACK_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
LINE_QUERY_CANDIDATE_DIR = os.getenv(
    "LINE_QUERY_CANDIDATE_DIR",
    "/app/data/wiki/ada-kdigo-diabetes-wiki/inbox/query-candidates",
)
LINE_QUERY_CANDIDATE_MAX_ANSWER_CHARS = int(os.getenv("LINE_QUERY_CANDIDATE_MAX_ANSWER_CHARS", "1200"))
LINE_QUERY_CANDIDATE_TIMEZONE = timezone(timedelta(hours=8))
LINE_RETRIEVAL_FAILURE_WRITEBACK_ENABLED = os.getenv("LINE_RETRIEVAL_FAILURE_WRITEBACK_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
LINE_RETRIEVAL_FAILURE_DIR = os.getenv(
    "LINE_RETRIEVAL_FAILURE_DIR",
    "/app/data/wiki/ada-kdigo-diabetes-wiki/inbox/retrieval-failures",
)
LINE_RESEARCH_REQUEST_DIR = os.getenv(
    "LINE_RESEARCH_REQUEST_DIR",
    "/app/data/wiki/ada-kdigo-diabetes-wiki/inbox/research-requests",
)
LINE_RESEARCH_REQUEST_WRITEBACK_ENABLED = os.getenv(
    "LINE_RESEARCH_REQUEST_WRITEBACK_ENABLED",
    "1",
).strip().lower() not in {"0", "false", "no", "off"}
LINE_ANSWER_IMPROVEMENT_ENABLED = os.getenv("LINE_ANSWER_IMPROVEMENT_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
LINE_ANSWER_IMPROVEMENT_DIR = os.getenv(
    "LINE_ANSWER_IMPROVEMENT_DIR",
    "/app/data/wiki/ada-kdigo-diabetes-wiki/inbox/answer-improvements",
)
LINE_ANSWER_IMPROVEMENT_PROVIDER = os.getenv("LINE_ANSWER_IMPROVEMENT_PROVIDER", "gemini").strip().lower()
LINE_ANSWER_IMPROVEMENT_MODEL = os.getenv(
    "LINE_ANSWER_IMPROVEMENT_MODEL",
    GEMINI_MODEL if LINE_ANSWER_IMPROVEMENT_PROVIDER == "gemini" else "gpt-5.4-mini",
)
LINE_ANSWER_IMPROVEMENT_TIMEOUT = int(os.getenv("LINE_ANSWER_IMPROVEMENT_TIMEOUT", "18"))
LINE_ANSWER_IMPROVEMENT_MAX_EXCERPT_CHARS = int(os.getenv("LINE_ANSWER_IMPROVEMENT_MAX_EXCERPT_CHARS", "700"))

app = FastAPI(title="LifeBot Fast LINE QA")

_memory_ready = False
_memory_lock = threading.Lock()
_session_locks: dict[str, threading.Lock] = {}
_session_locks_guard = threading.Lock()
_knowledge_preload_started = False
_knowledge_preload_done = False
_knowledge_preload_error = ""
_knowledge_preload_seconds = 0.0
_knowledge_status_cache: dict[str, object] | None = None
_knowledge_status_cache_at = 0.0
_knowledge_status_lock = threading.Lock()
_wiki_self_heal_status: dict[str, object] = {"attempted": False, "restored": False}
_wiki_self_heal_lock = threading.RLock()


@app.on_event("startup")
def preload_knowledge_on_startup() -> None:
    self_heal_llm_wiki_if_needed()
    start_knowledge_preload()


SYSTEM_PROMPT = """你是 LifeBot 糖尿病衛教 LINE 機器人，請用繁體中文回答病友問題。

回答規則：
- 口吻溫和、清楚、像衛教師在 LINE 上簡短回覆。
- 不要使用 Markdown 格式，不要使用井字號、星號或程式碼區塊。
- 不要提供個人化診斷、處方、劑量調整、停藥建議，或替代醫師判斷。
- 回答以 2 到 4 個短段落為主，適合手機閱讀。
- 只能根據「背景知識檢索」提供的已載入臨床指南、LLM Wiki 知識頁與結構化證據卡回答。
- 背景知識可能包含 LLM Wiki compiled pages，這是已整理的長期醫學知識層；也可能包含 compiled guideline artifacts，這些是從已上傳 Markdown 指南預先編譯出的 recommendation/table/section/concept/cross-guideline 證據卡。
- LLM Wiki pages 是已修訂的回答層；若本輪檢索到相關 LLM Wiki 內容，請優先用它組織繁體中文回答。原始 Markdown 指南只作為精確門檻、適應症、禁忌或分級建議的查核依據，不要用原始 Markdown 取代已修訂的 LLM Wiki 回答架構。
- 不要使用模型內建知識、一般醫學常識、未載入指南、新聞或推測補完。
- 若問題屬於糖尿病、CKD、高血壓、血脂、心血管風險、肥胖、脂肪肝、骨骼健康或慢性病照護範圍，而且已載入內容有相關依據，請回答已載入內容能支持的部分；若證據不完整，請說明限制，不要直接拒答。
- 只有在問題明顯離開上述慢性病照護範圍，或本輪完全沒有相關指南或知識庫內容時，才說目前指南知識庫資料不足。
- 回答中請自然標示依據來源，例如 ADA 2026、KDIGO 或知識庫中出現的指南名稱；不要編造未出現在已載入內容中的來源。
- 不要在給 LINE 使用者的回答中使用內部檢索用語；請改說「根據 ADA 2026」、「根據目前已載入的指南內容」或「知識庫整理」。
- 若骨骼健康問題的已載入內容包含 T-score、FRAX、DXA/BMD、TZD、sulfonylurea、低血糖或跌倒風險，就不可回答「缺乏 FRAX/T-score/DXA 或治療策略資訊」。
- 若問題涉及低血糖、高血糖急症、胸痛、意識不清、酮酸中毒疑慮、懷孕、兒童、腎功能、嚴重感染或傷口惡化，請提醒盡快聯絡醫療團隊或就醫。
- 回覆結尾不要提出追問；即使資訊不足，也請用一般提醒收束，不要問「請問您目前...？」。
- 不要編造最新研究、新聞或來源；若病友要求最新醫學期刊或新聞，請說明需要啟用搜尋流程，並先給一般衛教原則。
- 若有提供「最近對話脈絡」，請用它理解代名詞、接續問題與前後文；但不要把短期對話內容當作永久病歷或已驗證診斷。
"""


def memory_database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip() or os.getenv("POSTGRES_URL", "").strip()


def memory_backend() -> str:
    url = memory_database_url()
    if urlparse(url).scheme in {"postgres", "postgresql"}:
        return "postgres"
    return "sqlite"


def llm_wiki_dir_candidates() -> list[Path]:
    raw = os.getenv("LINE_LLM_WIKI_DIRS", DEFAULT_LLM_WIKI_DIRS)
    paths: list[Path] = []
    for part in re.split(r"[,;\n]+", raw):
        value = part.strip()
        if value and value.lower() not in {"0", "false", "no", "off"}:
            paths.append(Path(value).expanduser())
    return paths


def first_llm_wiki_dir() -> Path | None:
    candidates = llm_wiki_dir_candidates()
    return candidates[0] if candidates else None


def llm_wiki_self_heal_target(archive_path: Path) -> tuple[Path | None, set[str]]:
    candidates = llm_wiki_dir_candidates()
    if not candidates:
        return None, set()
    if not archive_path.exists():
        return candidates[0], set()
    archive_tops = tar_top_level_dirs(archive_path)
    if len(archive_tops) == 1:
        archive_top = next(iter(archive_tops))
        for candidate in candidates:
            if candidate.name == archive_top:
                return candidate, archive_tops
    return candidates[0], archive_tops


def bundled_wiki_archive_path() -> Path:
    archive = Path(LINE_LLM_WIKI_SELF_HEAL_ARCHIVE).expanduser()
    if archive.is_absolute():
        return archive
    return Path(__file__).resolve().parent / archive


def canonical_wiki_file_count(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    count = 0
    for child in path.rglob("*.md"):
        if not child.is_file() or is_metadata_file_name(child.name):
            continue
        try:
            relative = child.relative_to(path)
        except ValueError:
            continue
        if relative.parts and relative.parts[0] in LLM_WIKI_SEED_EXCLUDED_ROOTS:
            continue
        count += 1
    return count


def tar_top_level_dirs(archive_path: Path) -> set[str]:
    roots: set[str] = set()
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive.getmembers():
            parts = Path(member.name).parts
            if parts:
                roots.add(parts[0])
    return roots


def seed_archive_markdown_count(archive_path: Path, expected_top_level: str) -> int:
    count = 0
    destination = Path("/")
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive.getmembers():
            member_path = validate_seed_tar_member(
                member,
                destination,
                expected_top_level,
                check_destination_symlinks=False,
            )
            if member_path is not None and member.isfile() and member.name.endswith(".md"):
                count += 1
    return count


def validate_seed_tar_member(
    member: tarfile.TarInfo,
    destination: Path,
    expected_top_level: str,
    check_destination_symlinks: bool = True,
) -> Path | None:
    if os.path.isabs(member.name) or ".." in Path(member.name).parts:
        raise RuntimeError(f"unsafe archive path: {member.name}")
    parts = Path(member.name).parts
    if not parts or parts[0] != expected_top_level:
        raise RuntimeError(f"archive top-level mismatch: {member.name}")
    if is_metadata_file_name(Path(member.name).name):
        raise RuntimeError(f"archive metadata files are not allowed: {member.name}")
    if len(parts) > 1 and parts[1] in LLM_WIKI_SEED_EXCLUDED_ROOTS:
        return None
    member_path = Path(os.path.abspath(destination / member.name))
    if destination != member_path and destination not in member_path.parents:
        raise RuntimeError(f"unsafe archive path: {member.name}")
    relative_member_path = member_path.relative_to(destination)
    if check_destination_symlinks:
        current = destination
        for part in relative_member_path.parts[:-1]:
            current = current / part
            if current.exists() and current.is_symlink():
                raise RuntimeError(f"destination symlink parent is not allowed: {current.name}")
    if member.islnk() or member.issym():
        raise RuntimeError(f"archive links are not allowed: {member.name}")
    if member.isdev() or member.isfifo():
        raise RuntimeError(f"archive special files are not allowed: {member.name}")
    return member_path


def safe_extract_tar(archive_path: Path, destination: Path, expected_top_level: str) -> None:
    destination = destination.resolve()
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive.getmembers():
            validate_seed_tar_member(member, destination, expected_top_level)

        kwargs: dict[str, object] = {}
        if "filter" in inspect.signature(archive.extract).parameters:
            kwargs["filter"] = "data"
        for member in archive.getmembers():
            member_path = validate_seed_tar_member(member, destination, expected_top_level)
            if member_path is None:
                continue
            member.uid = 0
            member.gid = 0
            member.uname = ""
            member.gname = ""
            member.mode = 0o755 if member.isdir() else 0o644
            if member.isdir():
                member_path.mkdir(parents=True, exist_ok=True)
                continue
            if member_path.exists():
                continue
            member_path.parent.mkdir(parents=True, exist_ok=True)
            archive.extract(member, destination, **kwargs)


def set_wiki_self_heal_status(status: dict[str, object]) -> None:
    global _wiki_self_heal_status
    with _wiki_self_heal_lock:
        _wiki_self_heal_status = dict(status)


def public_wiki_self_heal_status() -> dict[str, object]:
    with _wiki_self_heal_lock:
        status = dict(_wiki_self_heal_status)
    error_text = str(status.get("error") or "")
    if "archive not found" in error_text:
        error_summary = "archive_not_found"
    elif "top-levels" in error_text or "top-level mismatch" in error_text:
        error_summary = "archive_top_level_mismatch"
    elif error_text:
        error_summary = "self_heal_error"
    else:
        error_summary = ""
    return {
        "enabled": bool(status.get("enabled", LINE_LLM_WIKI_SELF_HEAL_ENABLED)),
        "attempted": bool(status.get("attempted", False)),
        "restored": bool(status.get("restored", False)),
        "before_files": status.get("before_files", 0),
        "after_files": status.get("after_files", 0),
        "had_error": bool(status.get("error")),
        "error": error_summary,
    }


def self_heal_llm_wiki_if_needed() -> dict[str, object]:
    with _wiki_self_heal_lock:
        archive_path = bundled_wiki_archive_path()
        target, archive_tops = llm_wiki_self_heal_target(archive_path)
        status: dict[str, object] = {
            "enabled": LINE_LLM_WIKI_SELF_HEAL_ENABLED,
            "attempted": False,
            "restored": False,
            "target": str(target) if target else "",
            "archive": str(archive_path),
            "before_files": 0,
            "after_files": 0,
            "error": "",
        }
        if not LINE_LLM_WIKI_SELF_HEAL_ENABLED or not target:
            set_wiki_self_heal_status(status)
            return status

        before_files = canonical_wiki_file_count(target)
        status["before_files"] = before_files
        status["after_files"] = before_files

        if before_files >= LINE_LLM_WIKI_SELF_HEAL_MIN_FILES and not archive_path.exists():
            set_wiki_self_heal_status(status)
            return status

        status["attempted"] = True
        if not archive_path.exists():
            status["error"] = f"archive not found: {archive_path}"
            set_wiki_self_heal_status(status)
            print(f"LLM Wiki self-heal skipped: {status['error']}")
            return status

        try:
            if archive_tops != {target.name}:
                raise RuntimeError(f"archive top-levels {sorted(archive_tops)!r} do not match target {target.name!r}")
            archive_markdown_files = seed_archive_markdown_count(archive_path, target.name)
            if before_files >= max(LINE_LLM_WIKI_SELF_HEAL_MIN_FILES, archive_markdown_files):
                status["attempted"] = False
                set_wiki_self_heal_status(status)
                return status
            target.parent.mkdir(parents=True, exist_ok=True)
            safe_extract_tar(archive_path, target.parent, target.name)
            after_files = canonical_wiki_file_count(target)
            status["after_files"] = after_files
            status["restored"] = after_files > before_files and after_files >= LINE_LLM_WIKI_SELF_HEAL_MIN_FILES
            print(
                "LLM Wiki self-heal "
                f"target={target} before_files={before_files} after_files={after_files} restored={status['restored']}"
            )
        except Exception as exc:
            status["error"] = f"{type(exc).__name__}: {exc}"
            status["after_files"] = canonical_wiki_file_count(target)
            print(f"LLM Wiki self-heal failed: {status['error']}")

        set_wiki_self_heal_status(status)
        return status


def refresh_cached_knowledge_status() -> dict[str, object]:
    global _knowledge_status_cache, _knowledge_status_cache_at
    status = knowledge_status()
    with _knowledge_status_lock:
        _knowledge_status_cache = status
        _knowledge_status_cache_at = time_monotonic()
    return status


def minimal_knowledge_status() -> dict[str, object]:
    return {
        "enabled": True,
        "available": _knowledge_preload_done and not _knowledge_preload_error,
        "warming_up": _knowledge_preload_started and not _knowledge_preload_done,
        "preload_started": _knowledge_preload_started,
        "preload_done": _knowledge_preload_done,
        "preload_error": _knowledge_preload_error,
        "preload_seconds": round(_knowledge_preload_seconds, 3),
        "status": "warming_up" if _knowledge_preload_started and not _knowledge_preload_done else "not_loaded",
    }


def cached_knowledge_status(force: bool = False) -> dict[str, object]:
    if not LINE_HEALTH_FAST_ENABLED or force:
        return refresh_cached_knowledge_status()
    now = time_monotonic()
    with _knowledge_status_lock:
        cached = _knowledge_status_cache
        cached_at = _knowledge_status_cache_at
    if cached and now - cached_at <= LINE_HEALTH_STATUS_CACHE_SECONDS:
        return cached
    if _knowledge_preload_started and not _knowledge_preload_done:
        return cached or minimal_knowledge_status()
    return refresh_cached_knowledge_status()


def knowledge_preload_worker() -> None:
    global _knowledge_preload_done, _knowledge_preload_error, _knowledge_preload_seconds
    started = time_monotonic()
    try:
        self_heal_llm_wiki_if_needed()
        load_knowledge_base()
        refresh_cached_knowledge_status()
        _knowledge_preload_error = ""
    except Exception as exc:
        _knowledge_preload_error = f"{type(exc).__name__}: {exc}"
        print(f"Knowledge preload failed: {_knowledge_preload_error}")
    finally:
        _knowledge_preload_seconds = time_monotonic() - started
        _knowledge_preload_done = True
        print(f"Knowledge preload finished in {_knowledge_preload_seconds:.2f}s")


def start_knowledge_preload() -> None:
    global _knowledge_preload_started
    if not LINE_KNOWLEDGE_PRELOAD_ENABLED or _knowledge_preload_started:
        return
    _knowledge_preload_started = True
    thread = threading.Thread(target=knowledge_preload_worker, name="knowledge-preload", daemon=True)
    thread.start()


@contextmanager
def memory_connection():
    if memory_backend() == "postgres":
        import psycopg

        with psycopg.connect(memory_database_url()) as conn:
            yield conn
        return

    path = Path(LINE_MEMORY_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_memory_db() -> None:
    global _memory_ready
    if not (LINE_MEMORY_ENABLED or LINE_CONTEXT_ENABLED) or _memory_ready:
        return
    with _memory_lock:
        if _memory_ready:
            return
        with memory_connection() as conn:
            if memory_backend() == "postgres":
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS line_user_memory (
                        line_user_id TEXT PRIMARY KEY,
                        display_name TEXT,
                        profile_summary TEXT,
                        consent_memory BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS line_conversation_context (
                        line_user_id TEXT PRIMARY KEY,
                        turns_json TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            else:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS line_user_memory (
                        line_user_id TEXT PRIMARY KEY,
                        display_name TEXT,
                        profile_summary TEXT,
                        consent_memory INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS line_conversation_context (
                        line_user_id TEXT PRIMARY KEY,
                        turns_json TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
        _memory_ready = True


def fetch_user_memory(line_user_id: str) -> dict[str, Any] | None:
    if not LINE_MEMORY_ENABLED or not line_user_id:
        return None
    ensure_memory_db()
    with memory_connection() as conn:
        row = conn.execute(
            "SELECT line_user_id, display_name, profile_summary, consent_memory, updated_at "
            "FROM line_user_memory WHERE line_user_id = %s"
            if memory_backend() == "postgres"
            else "SELECT line_user_id, display_name, profile_summary, consent_memory, updated_at "
            "FROM line_user_memory WHERE line_user_id = ?",
            (line_user_id,),
        ).fetchone()
    if not row:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    keys = ["line_user_id", "display_name", "profile_summary", "consent_memory", "updated_at"]
    return dict(zip(keys, row))


def delete_user_memory(line_user_id: str) -> None:
    if not LINE_MEMORY_ENABLED or not line_user_id:
        return
    ensure_memory_db()
    with memory_connection() as conn:
        conn.execute(
            "DELETE FROM line_user_memory WHERE line_user_id = %s"
            if memory_backend() == "postgres"
            else "DELETE FROM line_user_memory WHERE line_user_id = ?",
            (line_user_id,),
        )


def fetch_conversation_turns(line_user_id: str) -> list[dict[str, Any]]:
    if not LINE_CONTEXT_ENABLED or not line_user_id:
        return []
    ensure_memory_db()
    with memory_connection() as conn:
        row = conn.execute(
            "SELECT turns_json FROM line_conversation_context WHERE line_user_id = %s"
            if memory_backend() == "postgres"
            else "SELECT turns_json FROM line_conversation_context WHERE line_user_id = ?",
            (line_user_id,),
        ).fetchone()
    if not row:
        return []
    raw_json = row[0] if not hasattr(row, "keys") else row["turns_json"]
    try:
        turns = json.loads(raw_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(turns, list):
        return []

    cutoff = current_epoch_seconds() - LINE_CONTEXT_TTL_SECONDS
    fresh_turns = [
        turn
        for turn in turns
        if isinstance(turn, dict) and int(turn.get("ts") or 0) >= cutoff and turn.get("role") in {"user", "assistant"}
    ]
    return fresh_turns[-LINE_CONTEXT_MAX_MESSAGES:]


def save_conversation_turn(line_user_id: str, user_text: str, assistant_text: str) -> None:
    if not LINE_CONTEXT_ENABLED or not line_user_id:
        return
    ensure_memory_db()
    now = current_epoch_seconds()
    turns = fetch_conversation_turns(line_user_id)
    turns.extend(
        [
            {"role": "user", "text": clean_context_text(user_text), "ts": now},
            {"role": "assistant", "text": clean_context_text(assistant_text), "ts": now},
        ]
    )
    turns = [turn for turn in turns if turn.get("text")][-LINE_CONTEXT_MAX_MESSAGES:]
    turns_json = json.dumps(turns, ensure_ascii=False)
    with memory_connection() as conn:
        if memory_backend() == "postgres":
            conn.execute(
                """
                INSERT INTO line_conversation_context (line_user_id, turns_json, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (line_user_id) DO UPDATE SET
                    turns_json = EXCLUDED.turns_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (line_user_id, turns_json),
            )
        else:
            conn.execute(
                """
                INSERT INTO line_conversation_context (line_user_id, turns_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(line_user_id) DO UPDATE SET
                    turns_json = excluded.turns_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (line_user_id, turns_json),
            )


def delete_conversation_context(line_user_id: str) -> None:
    if not LINE_CONTEXT_ENABLED or not line_user_id:
        return
    ensure_memory_db()
    with memory_connection() as conn:
        conn.execute(
            "DELETE FROM line_conversation_context WHERE line_user_id = %s"
            if memory_backend() == "postgres"
            else "DELETE FROM line_conversation_context WHERE line_user_id = ?",
            (line_user_id,),
        )


def conversation_prompt(line_user_id: str) -> str:
    turns = fetch_conversation_turns(line_user_id)
    if not turns:
        return ""
    labels = {"user": "使用者", "assistant": "LifeBot"}
    lines = [
        "\n\n最近對話脈絡：",
        "以下是同一個 LINE 對話中尚未過期的最近訊息，只用來理解前後文、代名詞與接續問題。",
        "若最近脈絡和本次問題衝突，請以本次問題為主；不要主動揭露這段脈絡存在。",
    ]
    for turn in turns:
        text = clean_context_text(str(turn.get("text") or ""))
        if text:
            lines.append(f"- {labels.get(str(turn.get('role')), '訊息')}：{text}")
    return "\n".join(lines)


def current_epoch_seconds() -> int:
    import time

    return int(time.time())


def clean_context_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value[:700]


def clean_memory_text(value: str) -> str:
    value = re.split(r"\b(?:and|with|but|because|who|that|having|taking|using|on)\b", value, maxsplit=1, flags=re.I)[0]
    value = re.split(r"(?:，|。|、|；|;|,|！|!|？|\?|目前|正在|有|患有|罹患|得了|想問|請問)", value, maxsplit=1)[0]
    value = re.sub(r"\s+", " ", value).strip(" ，。,.！!？?")
    return value[:20]


def save_user_name(line_user_id: str, display_name: str) -> None:
    if not LINE_MEMORY_ENABLED or not line_user_id:
        return
    ensure_memory_db()
    display_name = clean_memory_text(display_name)
    if not display_name:
        return
    with memory_connection() as conn:
        if memory_backend() == "postgres":
            conn.execute(
                """
                INSERT INTO line_user_memory (line_user_id, display_name, profile_summary, consent_memory, updated_at)
                VALUES (%s, %s, %s, TRUE, CURRENT_TIMESTAMP)
                ON CONFLICT (line_user_id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    profile_summary = NULL,
                    consent_memory = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (line_user_id, display_name, None),
            )
        else:
            conn.execute(
                """
                INSERT INTO line_user_memory (line_user_id, display_name, profile_summary, consent_memory, updated_at)
                VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(line_user_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    profile_summary = NULL,
                    consent_memory = 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (line_user_id, display_name, None),
            )


def memory_prompt(line_user_id: str) -> str:
    memory = fetch_user_memory(line_user_id)
    if not memory or not memory.get("consent_memory"):
        return ""
    parts = []
    if memory.get("display_name"):
        parts.append(f"稱呼：{memory['display_name']}")
    if not parts:
        return ""
    return "\n\n使用者已明確同意保存的稱呼：\n" + "\n".join(f"- {part}" for part in parts) + (
        "\n回答時可以自然用這個稱呼；不要主動揭露 LINE userId，也不要假裝知道未保存的個資。"
    )


def extract_display_name(text: str) -> str | None:
    patterns = [
        r"(?:請|幫我)?記住(?:我)?(?:叫|名字是|姓名是)\s*([^\s，。,.！!？?]{1,20})",
        r"(?:我叫|我的名字是|我的姓名是)\s*([^\s，。,.！!？?]{1,20})",
        r"我是\s*([^\s，。,.！!？?]{1,20})",
        r"(?:以後|下次)(?:請)?(?:叫我|稱呼我)\s*([^\s，。,.！!？?]{1,20})",
        r"你可以叫我\s*([^\s，。,.！!？?]{1,20})",
        r"(?i)\bmy name is\s+([A-Za-z][A-Za-z .'-]{0,38})",
        r"(?i)\bcall me\s+([A-Za-z][A-Za-z .'-]{0,38})",
        r"(?i)\byou can call me\s+([A-Za-z][A-Za-z .'-]{0,38})",
        r"(?i)\bi am\s+([A-Za-z][A-Za-z .'-]{0,38})",
        r"(?i)\bi'm\s+([A-Za-z][A-Za-z .'-]{0,38})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            name = clean_memory_text(match.group(1))
            if is_plausible_display_name(name):
                return name
    return None


def is_plausible_display_name(value: str) -> bool:
    if not value:
        return False
    lower = value.lower().strip()
    rejected = {
        "diabetic",
        "a diabetic",
        "pregnant",
        "sick",
        "hungry",
        "low",
        "high",
        "type 1",
        "type 2",
        "type one",
        "type two",
        "糖尿病",
        "糖尿病患者",
        "病人",
        "患者",
        "孕婦",
        "懷孕",
        "低血糖",
        "高血糖",
        "第一型糖尿病",
        "第二型糖尿病",
    }
    if lower in rejected or lower.startswith(("having ", "taking ", "using ", "on ")):
        return False
    if any(term in value for term in ("糖尿病", "血糖", "懷孕", "症狀", "用藥", "藥物", "胰島素")):
        return False
    return True


def memory_command_response(line_user_id: str, user_text: str) -> str | None:
    if is_context_reset_command(user_text):
        delete_conversation_context(line_user_id)
        return "好的，這段對話脈絡已清除。接下來我會把下一則訊息當作新的問題開始。"

    display_name = extract_display_name(user_text)
    if not LINE_MEMORY_ENABLED:
        if display_name:
            return "目前名字記憶功能尚未啟用，所以我暫時無法保存你的稱呼。"
        return None

    if re.search(r"(忘記|刪除|清除).*(我的)?(名字|稱呼|資料|記憶)|不要再記住我", user_text):
        delete_user_memory(line_user_id)
        delete_conversation_context(line_user_id)
        return "我已經刪除目前為你保存的稱呼。之後如果你希望我再記住名字，可以再告訴我。"

    if re.search(r"(你記得我什麼|我有哪些資料被記住|查詢.*(名字|稱呼|資料|記憶)|看.*我的記憶|你記得我的名字嗎)", user_text):
        memory = fetch_user_memory(line_user_id)
        if not memory or not memory.get("consent_memory") or not memory.get("display_name"):
            return "目前我還沒有記住你的名字。你可以說：我叫小明。"
        return f"我目前記得你的稱呼是：{memory['display_name']}。"

    if not display_name:
        return None

    save_user_name(line_user_id, display_name)
    return f"好的，我記住了。之後我會用「{display_name}」來稱呼你。你也可以隨時說「忘記我的名字」來刪除。"


def is_context_reset_command(user_text: str) -> bool:
    return bool(re.search(r"(忘記|刪除|清除).*(這段|剛剛|對話|上下文|脈絡|context)|重新開始|從頭開始", user_text, re.I))


def verify_line_signature(body: bytes, signature: str) -> None:
    secret = os.getenv("LINE_CHANNEL_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=500, detail="LINE_CHANNEL_SECRET is not configured")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    if not hmac.compare_digest(expected, signature or ""):
        raise HTTPException(status_code=401, detail="invalid LINE signature")


def line_send(endpoint: str, payload: dict[str, Any]) -> tuple[bool, str]:
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    if not token:
        return False, "LINE_CHANNEL_ACCESS_TOKEN is not configured"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=LINE_TIMEOUT) as response:
            return response.status < 300, f"LINE HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return False, f"LINE HTTP {exc.code}: {body[:300]}"
    except urllib.error.URLError as exc:
        return False, f"LINE request failed: {exc}"


def line_reply_text(reply_token: str, text: str) -> tuple[bool, str]:
    return line_send(
        "https://api.line.me/v2/bot/message/reply",
        {"replyToken": reply_token, "messages": [{"type": "text", "text": text[:4900]}]},
    )


def line_push_text(to: str, text: str) -> tuple[bool, str]:
    return line_send(
        "https://api.line.me/v2/bot/message/push",
        {"to": to, "messages": [{"type": "text", "text": text[:4900]}]},
    )


def source_target(event: dict[str, Any]) -> str:
    source = event.get("source", {})
    return source.get("groupId") or source.get("roomId") or source.get("userId") or ""


def source_session_key(event: dict[str, Any]) -> str:
    source = event.get("source", {})
    user_id = source.get("userId") or ""
    group_id = source.get("groupId") or ""
    room_id = source.get("roomId") or ""
    chat_id = group_id or room_id or user_id

    if LINE_SESSION_SCOPE == "chat":
        return f"chat:{chat_id}" if chat_id else ""
    if LINE_SESSION_SCOPE == "chat_user":
        if chat_id and user_id and chat_id != user_id:
            return f"chat_user:{chat_id}:{user_id}"
        return user_id or chat_id

    return user_id or chat_id


def session_lock(session_key: str) -> threading.Lock:
    with _session_locks_guard:
        lock = _session_locks.get(session_key)
        if lock is None:
            lock = threading.Lock()
            _session_locks[session_key] = lock
        return lock


def answer_for_session(session_key: str, user_text: str) -> str:
    with session_lock(session_key):
        memory_answer = memory_command_response(session_key, user_text)
        answer = memory_answer or llm_answer(user_text, session_key)
        if not is_context_reset_command(user_text):
            save_conversation_turn(session_key, user_text, answer)
        return answer


def query_candidate_slug(text: str) -> str:
    ascii_words = re.findall(r"[A-Za-z0-9]+", text.lower())
    if ascii_words:
        slug = "-".join(ascii_words[:8])
    else:
        zh_terms = re.findall(r"[\u4e00-\u9fff]{1,8}", text)
        slug = "-".join(zh_terms[:6])
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff-]+", "-", slug).strip("-")
    return slug[:72] or "line-guideline-query"


def redacted_query_candidate_text(text: str) -> str:
    text = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[email-redacted]", text, flags=re.I)
    text = re.sub(r"\b09\d{2}[- ]?\d{3}[- ]?\d{3}\b", "[phone-redacted]", text)
    text = re.sub(r"\b[A-Z][12]\d{8}\b", "[id-redacted]", text, flags=re.I)
    return text.strip()


def query_candidate_allowed(user_text: str, answer: str, clinical_intent: dict[str, Any] | None) -> bool:
    if not LINE_QUERY_CANDIDATE_WRITEBACK_ENABLED:
        return False
    if not user_text.strip() or not answer.strip():
        return False
    if knowledge_no_answer_text()[:20] in answer:
        return False
    if re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|09\d{2}[- ]?\d{3}[- ]?\d{3}|[A-Z][12]\d{8}", user_text, flags=re.I):
        return False
    concepts = " ".join(str(item) for item in (clinical_intent or {}).get("concepts", []))
    haystack = f"{user_text} {concepts}".lower()
    return bool(
        re.search(
            r"ada|kdigo|ckd|egfr|uacr|albuminuria|dialysis|sglt2|glp|cgm|aid|a1c|hypogly|finerenone|metformin|"
            r"糖尿病|腎|洗腎|透析|尿蛋白|白蛋白尿|排糖藥|連續血糖|血糖機|低血糖|指引",
            haystack,
        )
    )


def write_query_candidate(
    user_text: str,
    answer: str,
    clinical_intent: dict[str, Any] | None,
    selected_hits: list[KnowledgeHit],
    retrieval_trace: dict[str, Any],
) -> None:
    if not query_candidate_allowed(user_text, answer, clinical_intent):
        return
    try:
        candidate_dir = Path(LINE_QUERY_CANDIDATE_DIR)
        candidate_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(LINE_QUERY_CANDIDATE_TIMEZONE)
        question = redacted_query_candidate_text(user_text)
        digest = hashlib.sha1(question.encode("utf-8", errors="ignore")).hexdigest()[:10]
        filename = f"{now.date().isoformat()}-{query_candidate_slug(question)}-{digest}.md"
        path = candidate_dir / filename
        if path.exists():
            return
        hit_lines = []
        for hit in selected_hits[:6]:
            hit_lines.append(
                f"- {getattr(hit, 'chunk_type', '')}: {getattr(hit, 'source_label', '')} / {getattr(hit, 'section', '')}"
            )
        intent = clinical_intent or {}
        content = "\n".join(
            [
                "---",
                f"title: LINE Query Candidate - {digest}",
                f"created: {now.isoformat()}",
                f"updated: {now.isoformat()}",
                "type: query-candidate",
                "tags: [line, query-candidate, guideline-qa]",
                "sources:",
                *[f"  - {line[2:]}" for line in hit_lines[:3]],
                "evidence_level: local-practice",
                "clinical_use: workflow",
                "confidence: uncertain",
                f"last_verified: {now.date().isoformat()}",
                "status: open",
                "obsidian_type: registry",
                "owner_agent: line-lifebot-qa",
                "write_policy: review-before-canonical",
                "---",
                "",
                "# LINE Query Candidate",
                "",
                "## Question",
                "",
                question,
                "",
                "## Retrieval",
                "",
                f"- retrieval_mode: {retrieval_trace.get('retrieval_mode', '')}",
                f"- retrieval_elapsed_ms: {retrieval_trace.get('elapsed_ms', '')}",
                f"- fast_hit_count: {retrieval_trace.get('fast_hit_count', '')}",
                f"- fallback_reason: {retrieval_trace.get('fallback_reason', '')}",
                "",
                "## Clinical Intent",
                "",
                f"- clinical_intent: {intent.get('clinical_intent', '')}",
                f"- question_type: {intent.get('question_type', '')}",
                f"- required_facets: {', '.join(str(x) for x in intent.get('required_facets', []))}",
                "",
                "## Selected Evidence",
                "",
                *(hit_lines or ["- No selected hits recorded."]),
                "",
                "## Answer Excerpt",
                "",
                redacted_query_candidate_text(answer)[:LINE_QUERY_CANDIDATE_MAX_ANSWER_CHARS],
                "",
                "## Review Decision",
                "",
                "- [ ] Promote to `queries/`",
                "- [ ] Update existing concept/drug/comparison page",
                "- [ ] Discard as one-off",
            ]
        )
        path.write_text(content + "\n", encoding="utf-8")
        print(f"query candidate saved: {path}")
    except Exception as exc:
        print(f"query candidate writeback failed: {type(exc).__name__}: {exc}")


def retrieval_failure_term_routes(user_text: str) -> list[tuple[str, str]]:
    lower = user_text.lower()
    routes: list[tuple[str, str]] = []
    route_specs = [
        (r"排糖藥|sglt2|sglt-2|egfr.*20|腎功能.*20", "drugs/sglt2i-egfr-under-20-not-on-dialysis"),
        (r"glp.?1|glp-1ra|洗腎.*glp|透析.*glp|dialysis.*glp", "drugs/glp1-based-therapy-on-dialysis"),
        (r"cgm|連續血糖|糖尿病新科技|血糖機|time in range|tir", "concepts/diabetes-technology-cgm-aid"),
        (r"骨質疏鬆|骨鬆|骨折|骨密度|骨骼|osteoporosis|bone health|fracture|bmd|dxa|frax|t-score", "concepts/diabetes-bone-health-osteoporosis"),
        (r"uacr|albuminuria|白蛋白尿|尿蛋白|dkd|糖尿病腎", "concepts/diabetes-ckd-risk-stratification"),
        (r"(metformin|glyburide|insulin|胰島素|藥物|用藥|口服藥).{0,120}(gdm|gestational diabetes|diabetes in pregnancy|pregnancy diabetes|妊娠糖尿病|懷孕糖尿病|孕期糖尿病)|(gdm|gestational diabetes|妊娠糖尿病|懷孕糖尿病|孕期糖尿病).{0,120}(metformin|glyburide|insulin|藥物|用藥|口服藥|胰島素)", "claims/ada-2026-gdm-pharmacotherapy-claims"),
        (r"metformin|finerenone|nsmra|a1c.*ckd|洗腎.*a1c|低血糖.*腎", "comparisons/ada-2026-vs-kdigo-2026-diabetes-ckd"),
        (r"older adults|長者|老人|pregnancy|懷孕|妊娠|steroid|glucocorticoid|住院", "guidelines/ada-standards-of-care-2026"),
    ]
    for pattern, route in route_specs:
        if re.search(pattern, lower):
            routes.append((pattern, route))
    return routes


def retrieval_failure_analysis(
    user_text: str,
    clinical_intent: dict[str, Any] | None,
    candidates: list[KnowledgeHit],
    selected_hits: list[KnowledgeHit],
    retrieval_trace: dict[str, Any],
    stage: str,
    gap_text: str = "",
) -> dict[str, Any]:
    required = set(required_facets(user_text))
    required.update(json_list((clinical_intent or {}).get("required_facets")))
    covered: set[str] = set()
    for hit in selected_hits or candidates[:5]:
        covered.update(hit_facets(hit))
    missing = sorted(required - covered)
    routes = retrieval_failure_term_routes(user_text)

    failure_types: list[str] = []
    if not candidates:
        failure_types.append("no_candidates")
    if retrieval_trace.get("retrieval_mode") == "fallback_raw":
        failure_types.append("wiki_fast_path_insufficient")
    if routes and not candidates:
        failure_types.append("missing_alias_or_topic_route")
    elif routes and missing:
        failure_types.append("weak_alias_or_topic_route")
    if missing:
        failure_types.append("missing_required_facets")
    if candidates and not selected_hits:
        failure_types.append("retrieval_noise_or_rerank_gap")
    if stage in {"evidence_review_unanswerable", "verification_unverified"}:
        failure_types.append("verification_gap")
    if not failure_types:
        failure_types.append("answerability_gap")

    suggested_fixes: list[str] = []
    for _, route in routes:
        suggested_fixes.append(f"Check or add alias/topic route to `{route}`.")
    if missing:
        suggested_fixes.append(f"Add page metadata or source coverage for missing facets: {', '.join(missing)}.")
    if not candidates:
        suggested_fixes.append("Create a research request if raw sources also lack coverage.")
    if candidates and not selected_hits:
        suggested_fixes.append("Inspect top candidates for retrieval noise; consider a smoke-test case or reranker rule.")
    if stage in {"evidence_review_unanswerable", "verification_unverified"}:
        suggested_fixes.append("Verify exact claims against raw ADA/KDIGO Markdown before promoting to a query page.")

    return {
        "stage": stage,
        "failure_types": sorted(set(failure_types)),
        "missing_facets": missing,
        "candidate_count": len(candidates),
        "selected_count": len(selected_hits),
        "retrieval_mode": retrieval_trace.get("retrieval_mode", ""),
        "retrieval_elapsed_ms": retrieval_trace.get("elapsed_ms", ""),
        "fallback_reason": retrieval_trace.get("fallback_reason", ""),
        "matched_routes": sorted(set(route for _, route in routes)),
        "suggested_fixes": suggested_fixes,
        "gap_text": gap_text,
    }


def write_research_request(
    user_text: str,
    clinical_intent: dict[str, Any] | None,
    analysis: dict[str, Any],
    selected_hits: list[KnowledgeHit],
) -> None:
    if not LINE_RESEARCH_REQUEST_WRITEBACK_ENABLED:
        return
    if re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|09\d{2}[- ]?\d{3}[- ]?\d{3}|[A-Z][12]\d{8}", user_text, flags=re.I):
        return
    try:
        request_dir = Path(LINE_RESEARCH_REQUEST_DIR)
        request_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(LINE_QUERY_CANDIDATE_TIMEZONE)
        question = redacted_query_candidate_text(user_text)
        digest = hashlib.sha1(f"research-request:{analysis.get('stage')}:{question}".encode("utf-8", errors="ignore")).hexdigest()[:10]
        filename = f"{now.date().isoformat()}-line-gap-{query_candidate_slug(question)}-{digest}.md"
        path = request_dir / filename
        if path.exists():
            return
        intent = clinical_intent or {}
        hit_lines = []
        source_lines = []
        for hit in selected_hits[:8]:
            parts = [str(getattr(hit, "chunk_type", "") or "").strip(), str(getattr(hit, "source_label", "") or "").strip()]
            section = str(getattr(hit, "section", "") or "").strip()
            label = " / ".join(part for part in parts if part)
            display_line = f"- {label} / {section}" if section else f"- {label or 'selected evidence'}"
            hit_lines.append(display_line)
            if len(source_lines) < 3:
                source_lines.append(f"  - {json.dumps(display_line[2:], ensure_ascii=False)}")
        source_lines = source_lines or ["sources: []"]
        content = "\n".join(
            [
                "---",
                f"title: LINE Research Request - {digest}",
                f"created: {now.isoformat()}",
                f"updated: {now.isoformat()}",
                "type: research-request",
                "tags: [research-request, line, guideline-qa, llm-wiki-gap]",
                *(["sources:"] + source_lines if hit_lines else source_lines),
                "evidence_level: local-practice",
                "clinical_use: workflow",
                "confidence: uncertain",
                f"last_verified: {now.date().isoformat()}",
                "status: open",
                "obsidian_type: registry",
                "owner_agent: line-lifebot-qa",
                "write_policy: hermes-source-aware-review",
                "---",
                "",
                "# LINE Research Request",
                "",
                "## User Question",
                "",
                question,
                "",
                "## Why This Needs Work",
                "",
                f"- stage: {analysis.get('stage', '')}",
                f"- failure_types: {', '.join(str(x) for x in analysis.get('failure_types', []))}",
                f"- missing_facets: {', '.join(str(x) for x in analysis.get('missing_facets', []))}",
                f"- retrieval_mode: {analysis.get('retrieval_mode', '')}",
                f"- fallback_reason: {analysis.get('fallback_reason', '')}",
                "",
                "## Query Planner Output",
                "",
                "```json",
                json.dumps(
                    {
                        "clinical_intent": intent.get("clinical_intent"),
                        "question_type": intent.get("question_type"),
                        "concepts": json_list(intent.get("concepts")),
                        "target_chapters": json_list(intent.get("target_chapters")),
                        "evidence_targets": json_list(intent.get("evidence_targets")),
                        "required_facets": json_list(intent.get("required_facets")),
                        "avoid_routes": json_list(intent.get("avoid_routes")),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
                "## Suggested Outputs",
                "",
                "- [ ] missing aliases",
                "- [ ] claim card",
                "- [ ] evidence card",
                "- [ ] regression test",
                "- [ ] canonical query page or MOC route if source-supported",
                "",
                "## Candidate Evidence Seen",
                "",
                *(hit_lines or ["- No selected evidence recorded."]),
                "",
                "## Notes",
                "",
                str(analysis.get("gap_text") or "No explicit gap text recorded."),
            ]
        )
        path.write_text(content + "\n", encoding="utf-8")
        print(f"research request saved: {path}")
    except Exception as exc:
        print(f"research request writeback failed: {type(exc).__name__}: {exc}")


def schedule_research_request(
    user_text: str,
    clinical_intent: dict[str, Any] | None,
    analysis: dict[str, Any],
    selected_hits: list[KnowledgeHit],
) -> None:
    analysis_snapshot = dict(analysis)
    selected_hits_snapshot = list(selected_hits)
    thread = threading.Thread(
        target=write_research_request,
        args=(user_text, clinical_intent, analysis_snapshot, selected_hits_snapshot),
        daemon=True,
    )
    thread.start()


def write_retrieval_failure(
    user_text: str,
    clinical_intent: dict[str, Any] | None,
    candidates: list[KnowledgeHit],
    selected_hits: list[KnowledgeHit],
    retrieval_trace: dict[str, Any],
    stage: str,
    gap_text: str = "",
) -> None:
    if re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|09\d{2}[- ]?\d{3}[- ]?\d{3}|[A-Z][12]\d{8}", user_text, flags=re.I):
        return
    analysis = retrieval_failure_analysis(user_text, clinical_intent, candidates, selected_hits, retrieval_trace, stage, gap_text)
    if stage in {"no_candidates", "insufficient_selected_evidence", "evidence_review_unanswerable", "verification_unverified"}:
        schedule_research_request(user_text, clinical_intent, analysis, selected_hits or candidates[:8])
    if not LINE_RETRIEVAL_FAILURE_WRITEBACK_ENABLED:
        return
    try:
        failure_dir = Path(LINE_RETRIEVAL_FAILURE_DIR)
        failure_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(LINE_QUERY_CANDIDATE_TIMEZONE)
        question = redacted_query_candidate_text(user_text)
        digest = hashlib.sha1(f"{stage}:{question}".encode("utf-8", errors="ignore")).hexdigest()[:10]
        filename = f"{now.date().isoformat()}-{query_candidate_slug(question)}-{stage}-{digest}.md"
        path = failure_dir / filename
        if path.exists():
            return
        hit_lines = []
        for hit in (selected_hits or candidates)[:8]:
            hit_lines.append(
                f"- {getattr(hit, 'chunk_type', '')}: {getattr(hit, 'source_label', '')} / {getattr(hit, 'section', '')}"
            )
        source_lines = [f"  - {json.dumps(line[2:], ensure_ascii=False)}" for line in hit_lines[:3]]
        intent = clinical_intent or {}
        content = "\n".join(
            [
                "---",
                f"title: Retrieval Failure - {digest}",
                f"created: {now.isoformat()}",
                f"updated: {now.isoformat()}",
                "type: retrieval-failure",
                "tags: [retrieval-failure, line, guideline-qa, learning-loop]",
                *(["sources:"] + source_lines if source_lines else ["sources: []"]),
                "evidence_level: local-practice",
                "clinical_use: workflow",
                "confidence: uncertain",
                f"last_verified: {now.date().isoformat()}",
                "status: open",
                "obsidian_type: registry",
                "owner_agent: line-lifebot-qa",
                "write_policy: review-before-canonical",
                "---",
                "",
                "# Retrieval Failure",
                "",
                "## Question",
                "",
                question,
                "",
                "## Failure Analysis",
                "",
                f"- stage: {analysis['stage']}",
                f"- failure_types: {', '.join(analysis['failure_types'])}",
                f"- missing_facets: {', '.join(analysis['missing_facets'])}",
                f"- retrieval_mode: {analysis['retrieval_mode']}",
                f"- retrieval_elapsed_ms: {analysis['retrieval_elapsed_ms']}",
                f"- fallback_reason: {analysis['fallback_reason']}",
                f"- candidate_count: {analysis['candidate_count']}",
                f"- selected_count: {analysis['selected_count']}",
                "",
                "## Clinical Intent",
                "",
                f"- clinical_intent: {intent.get('clinical_intent', '')}",
                f"- question_type: {intent.get('question_type', '')}",
                f"- required_facets: {', '.join(str(x) for x in intent.get('required_facets', []))}",
                "",
                "## Matched Route Candidates",
                "",
                *(f"- `{route}`" for route in analysis["matched_routes"]),
                "",
                "## Suggested Low-Risk Fixes",
                "",
                *(f"- {fix}" for fix in analysis["suggested_fixes"]),
                "",
                "## Evidence Seen",
                "",
                *(hit_lines or ["- No candidates recorded."]),
                "",
                "## Gap Text",
                "",
                gap_text or "No explicit gap text recorded.",
                "",
                "## Review Decision",
                "",
                "- [ ] Add alias/entity",
                "- [ ] Update topic-map/MOC",
                "- [ ] Create research-request",
                "- [ ] Create query page after verification",
                "- [ ] Discard as out-of-scope or one-off",
            ]
        )
        path.write_text(content + "\n", encoding="utf-8")
        print(f"retrieval failure saved: {path}")
    except Exception as exc:
        print(f"retrieval failure writeback failed: {type(exc).__name__}: {exc}")


def answer_improvement_allowed(user_text: str, answer: str) -> bool:
    if not LINE_ANSWER_IMPROVEMENT_ENABLED:
        return False
    if not answer_improvement_api_key():
        return False
    if not user_text.strip() or not answer.strip():
        return False
    if re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|09\d{2}[- ]?\d{3}[- ]?\d{3}|[A-Z][12]\d{8}", user_text, flags=re.I):
        return False
    return bool(
        re.search(
            r"ada|kdigo|ckd|egfr|uacr|dialysis|sglt2|glp|cgm|aid|a1c|骨|骨鬆|骨質疏鬆|"
            r"diabetes|type 1|type 2|screening|hypertension|blood pressure|lipid|obesity|pregnancy|gestational|gdm|"
            r"retinopathy|neuropathy|foot|pad|masld|mash|糖尿病|第一型|第二型|篩檢|普篩|高血壓|血壓|血脂|肥胖|"
            r"懷孕|妊娠|妊娠糖尿病|視網膜|神經病變|足部|周邊動脈|脂肪肝|腎|洗腎|透析|尿蛋白|白蛋白尿|排糖藥|連續血糖|指引|治療|診斷",
            f"{user_text} {answer}".lower(),
        )
    )


def answer_improvement_api_key() -> str:
    if LINE_ANSWER_IMPROVEMENT_PROVIDER == "openai":
        return os.getenv("OPENAI_API_KEY", "").strip()
    if LINE_ANSWER_IMPROVEMENT_PROVIDER == "gemini":
        return os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
    return ""


def answer_improvement_hit_lines(selected_hits: list[KnowledgeHit]) -> list[str]:
    lines: list[str] = []
    for hit in selected_hits[:8]:
        excerpt = str(getattr(hit, "text", "") or getattr(hit, "excerpt", "") or "")
        excerpt = re.sub(r"\s+", " ", excerpt).strip()[:LINE_ANSWER_IMPROVEMENT_MAX_EXCERPT_CHARS]
        lines.append(
            "\n".join(
                [
                    f"- source: {getattr(hit, 'source_label', '')}",
                    f"  section: {getattr(hit, 'section', '')}",
                    f"  type: {getattr(hit, 'chunk_type', '')}",
                    f"  excerpt: {excerpt}",
                ]
            )
        )
    return lines


def answer_improvement_system_prompt() -> str:
    return (
        "You are a medical guideline QA improvement auditor for a LINE chatbot. "
        "Review the answer only against the provided retrieval trace and evidence excerpts. "
        "Do not add new clinical facts. Identify how the answer, retrieval routing, and LLM Wiki can improve. "
        "Allowed safe auto-actions: add aliases/entities, add topic-map or MOC links, create query-candidate drafts, "
        "add smoke-test questions, or create research requests. "
        "Not allowed without human/source review: changing clinical thresholds, recommendation grades, drug indications, "
        "contraindications, or promoting draft clinical claims into canonical wiki pages. "
        "Return strict JSON with keys: quality_score, answer_complete, public_wording_issues, missing_evidence_facets, "
        "retrieval_route_issues, missing_aliases, missing_claim_cards, missing_evidence_cards, proposed_regression_tests, "
        "research_requests, safe_auto_actions, requires_human_or_clinical_review, proposed_query_page_title, proposed_smoke_test, "
        "summary. Use empty arrays when no item is needed."
    )


def build_answer_improvement_review(
    user_text: str,
    answer: str,
    clinical_intent: dict[str, Any] | None,
    selected_hits: list[KnowledgeHit],
    retrieval_trace: dict[str, Any],
) -> str:
    intent = clinical_intent or {}
    user_payload = "\n".join(
        [
            "Question:",
            redacted_query_candidate_text(user_text),
            "",
            "Answer:",
            redacted_query_candidate_text(answer)[:2200],
            "",
            "Retrieval trace:",
            json.dumps(
                {
                    "retrieval_mode": retrieval_trace.get("retrieval_mode"),
                    "elapsed_ms": retrieval_trace.get("elapsed_ms"),
                    "fast_hit_count": retrieval_trace.get("fast_hit_count"),
                    "fallback_reason": retrieval_trace.get("fallback_reason"),
                    "clinical_intent": intent.get("clinical_intent"),
                    "question_type": intent.get("question_type"),
                    "required_facets": json_list(intent.get("required_facets")),
                    "concepts": json_list(intent.get("concepts")),
                },
                ensure_ascii=False,
            ),
            "",
            "Evidence excerpts:",
            "\n".join(answer_improvement_hit_lines(selected_hits)) or "- No evidence excerpts recorded.",
        ]
    )
    return call_answer_improvement_model(answer_improvement_system_prompt(), user_payload)


def normalize_answer_improvement_review(review_json: dict[str, Any] | None) -> dict[str, Any] | None:
    if not review_json:
        return None
    array_keys = (
        "public_wording_issues",
        "missing_evidence_facets",
        "retrieval_route_issues",
        "missing_aliases",
        "missing_claim_cards",
        "missing_evidence_cards",
        "proposed_regression_tests",
        "research_requests",
        "safe_auto_actions",
        "proposed_smoke_test",
    )
    normalized = dict(review_json)
    for key in array_keys:
        normalized[key] = json_list(normalized.get(key))
    normalized.setdefault("quality_score", "")
    normalized.setdefault("answer_complete", False)
    normalized.setdefault("requires_human_or_clinical_review", True)
    normalized.setdefault("proposed_query_page_title", "")
    normalized.setdefault("summary", "")
    return normalized


def review_target_lines(review_json: dict[str, Any] | None, key: str) -> list[str]:
    if not review_json:
        return ["- (none)"]
    values = json_list(review_json.get(key))
    return [f"- {item}" for item in values] or ["- (none)"]


def write_answer_improvement(
    user_text: str,
    answer: str,
    clinical_intent: dict[str, Any] | None,
    selected_hits: list[KnowledgeHit],
    retrieval_trace: dict[str, Any],
) -> None:
    if not answer_improvement_allowed(user_text, answer):
        return
    try:
        review_text = build_answer_improvement_review(user_text, answer, clinical_intent, selected_hits, retrieval_trace)
        if not review_text:
            return
        review_json = normalize_answer_improvement_review(extract_json_object(review_text))
        improvement_dir = Path(LINE_ANSWER_IMPROVEMENT_DIR)
        improvement_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(LINE_QUERY_CANDIDATE_TIMEZONE)
        question = redacted_query_candidate_text(user_text)
        digest = hashlib.sha1(f"answer-improvement:{question}".encode("utf-8", errors="ignore")).hexdigest()[:10]
        filename = f"{now.date().isoformat()}-{query_candidate_slug(question)}-improve-{digest}.md"
        path = improvement_dir / filename
        if path.exists():
            return
        intent = clinical_intent or {}
        evidence_lines = answer_improvement_hit_lines(selected_hits)
        quality_score = review_json.get("quality_score", "") if review_json else ""
        requires_review = review_json.get("requires_human_or_clinical_review", True) if review_json else True
        source_lines = []
        for hit in selected_hits[:3]:
            source_label = getattr(hit, "source_label", "")
            section = getattr(hit, "section", "")
            source_lines.append(f"  - {json.dumps(f'{source_label} / {section}', ensure_ascii=False)}")
        content = "\n".join(
            [
                "---",
                f"title: Answer Improvement - {digest}",
                f"created: {now.isoformat()}",
                f"updated: {now.isoformat()}",
                "type: answer-improvement",
                f"tags: [answer-improvement, line, guideline-qa, self-improvement, {LINE_ANSWER_IMPROVEMENT_PROVIDER}-reviewer]",
                *(["sources:"] + source_lines if source_lines else ["sources: []"]),
                "evidence_level: local-practice",
                "clinical_use: workflow",
                "confidence: uncertain",
                f"last_verified: {now.date().isoformat()}",
                "status: open",
                "obsidian_type: registry",
                f"owner_agent: {LINE_ANSWER_IMPROVEMENT_PROVIDER}-answer-reviewer",
                "write_policy: safe-autofix-or-review-before-canonical",
                f"quality_score: {quality_score}",
                f"requires_human_or_clinical_review: {str(requires_review).lower()}",
                "---",
                "",
                "# Answer Improvement",
                "",
                "## Question",
                "",
                question,
                "",
                "## Retrieval Trace",
                "",
                f"- retrieval_mode: {retrieval_trace.get('retrieval_mode', '')}",
                f"- retrieval_elapsed_ms: {retrieval_trace.get('elapsed_ms', '')}",
                f"- fast_hit_count: {retrieval_trace.get('fast_hit_count', '')}",
                f"- fallback_reason: {retrieval_trace.get('fallback_reason', '')}",
                "",
                "## Clinical Intent",
                "",
                f"- clinical_intent: {intent.get('clinical_intent', '')}",
                f"- question_type: {intent.get('question_type', '')}",
                f"- required_facets: {', '.join(str(x) for x in intent.get('required_facets', []))}",
                f"- concepts: {', '.join(str(x) for x in intent.get('concepts', []))}",
                "",
                "## Answer",
                "",
                redacted_query_candidate_text(answer)[:1800],
                "",
                "## Evidence Seen",
                "",
                *(evidence_lines or ["- No selected hits recorded."]),
                "",
                "## Answer Improvement Review",
                "",
                f"- provider: {LINE_ANSWER_IMPROVEMENT_PROVIDER}",
                f"- model: {LINE_ANSWER_IMPROVEMENT_MODEL}",
                "",
                "## Structured Improvement Targets",
                "",
                "### Missing Aliases",
                *review_target_lines(review_json, "missing_aliases"),
                "",
                "### Missing Claim Cards",
                *review_target_lines(review_json, "missing_claim_cards"),
                "",
                "### Missing Evidence Cards",
                *review_target_lines(review_json, "missing_evidence_cards"),
                "",
                "### Proposed Regression Tests",
                *review_target_lines(review_json, "proposed_regression_tests"),
                "",
                "### Research Requests",
                *review_target_lines(review_json, "research_requests"),
                "",
                "```json",
                json.dumps(review_json, ensure_ascii=False, indent=2) if review_json else review_text,
                "```",
                "",
                "## Safe Action Checklist",
                "",
                "- [ ] Add aliases/entities only if they map to existing canonical pages",
                "- [ ] Add topic-map or MOC links",
                "- [ ] Add or update retrieval smoke-test case",
                "- [ ] Create research request for true source gap",
                "- [ ] Do not change clinical thresholds/recommendation grades without source review",
            ]
        )
        path.write_text(content + "\n", encoding="utf-8")
        print(f"answer improvement saved: {path}")
    except Exception as exc:
        print(f"answer improvement writeback failed: {type(exc).__name__}: {exc}")


def schedule_answer_improvement(
    user_text: str,
    answer: str,
    clinical_intent: dict[str, Any] | None,
    selected_hits: list[KnowledgeHit],
    retrieval_trace: dict[str, Any],
) -> None:
    if not answer_improvement_allowed(user_text, answer):
        return
    thread = threading.Thread(
        target=write_answer_improvement,
        args=(user_text, answer, clinical_intent, list(selected_hits), dict(retrieval_trace)),
        daemon=True,
    )
    thread.start()


def retrieval_ladder_summary(retrieval_trace: dict[str, Any], candidates: list[KnowledgeHit], stage: str = "") -> str:
    mode = str(retrieval_trace.get("retrieval_mode") or "")
    fallback_reason = str(retrieval_trace.get("fallback_reason") or "")
    if mode == "fast_path":
        return "已找到部分已整理知識與指南證據；以下只整理目前證據可支持的內容。"
    if candidates:
        reason = f"（原因：{fallback_reason}）" if fallback_reason else ""
        return f"知識庫專頁尚未完整整理，已改用已載入指南內容與結構化證據{reason}。"
    return "目前在已載入知識庫與指南內容中都沒有找到足夠直接的依據。"


def safe_learning_loop_message(stage: str, has_candidates: bool) -> str:
    if has_candidates:
        return (
            "這題我也會記錄為知識庫補強項，後續可補 aliases、claim card、evidence card、"
            "regression test 或 research request，讓下次更容易命中。"
        )
    return (
        "這題目前需要補強知識庫；我已建立改進紀錄，後續可補 missing aliases、"
        "claim card、evidence card、regression test 或 research request。"
    )


def red_flag_safety_text() -> str:
    return "若你有低血糖症狀、血糖持續很高、胸痛、意識不清、呼吸急促、嚴重脫水或明顯不舒服，請先聯絡醫療團隊或就醫。"


def static_evidence_gap_response(stage: str, has_candidates: bool, gap_text: str = "") -> str:
    if has_candidates:
        prefix = "已檢索到部分已載入指南內容，但本輪證據審查認為不足以安全整理成完整答案。"
    else:
        prefix = "這題目前在已載入知識庫與指南內容中都沒有找到足夠直接的依據。"
    gap_excerpt = "" if stage in {"evidence_review_unanswerable", "verification_unverified"} else public_gap_excerpt(gap_text)
    gap = f" 目前缺口：{gap_excerpt}" if gap_excerpt else ""
    return f"{prefix}{gap} {safe_learning_loop_message(stage, has_candidates)} {red_flag_safety_text()}"[:4900]


def public_gap_excerpt(gap_text: str) -> str:
    text = re.sub(r"\b(ANSWERABLE|VERIFIED)\s*:\s*(yes|no)\b", "", gap_text or "", flags=re.I)
    text = re.sub(r"\b(EVIDENCE|GAPS?|REASONS?|FINDINGS?)\s*:\s*", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -:;。\n\t")
    if re.search(
        r"片段|chunk|rerank|fast[_ -]?path|llm wiki|raw guideline|json|retrieval|candidate|facet|alias|topic-?map|moc|\{|\}",
        text,
        flags=re.I,
    ):
        return ""
    return text[:260]


def build_limited_guideline_fallback_answer(
    api_key: str,
    user_text: str,
    clinical_intent: dict[str, Any] | None,
    candidates: list[KnowledgeHit],
    selected_hits: list[KnowledgeHit],
    retrieval_trace: dict[str, Any],
    stage: str,
    gap_text: str = "",
    evidence_review: str = "",
    long_context_verification: str = "",
) -> str:
    evidence_hits = selected_hits
    if not evidence_hits:
        return static_evidence_gap_response(stage, False, gap_text)

    ladder = retrieval_ladder_summary(retrieval_trace, candidates, stage)
    learning_note = safe_learning_loop_message(stage, True)
    system_text = (
        SYSTEM_PROMPT
        + clinical_intent_prompt(clinical_intent)
        + knowledge_prompt_from_hits(evidence_hits)
        + evidence_review_prompt(evidence_review)
        + long_context_verification_prompt(long_context_verification)
        + (
            "\n\n檢索階梯狀態：\n"
            f"{ladder}\n"
            "只有本輪已選取且通過覆蓋檢查的 guideline evidence 可以用來回答。"
            "不能使用模型內建知識或外部網路內容補完缺口。"
        )
        + (
            "\n\nCoverage gap:\n"
            f"{gap_text}\n"
            "若有缺口，請在回答末段說明目前已載入內容不足以回答的部分。"
            if gap_text
            else ""
        )
    )
    try:
        answer = call_llm(
            api_key,
            system_text,
            (
                f"病友問題：{user_text}\n\n"
                "請用繁體中文回答。先直接回答已載入指南可支持的部分；"
                "如果只是知識庫專頁未完整整理但已選取指南證據有內容，請說「知識庫專頁尚未完整整理，但已載入指南內容顯示……」。"
                "不要使用「片段」這個詞，不要說目前快速問答暫時無法回覆。"
            ),
            max_output_tokens=760,
            temperature=0.25,
            timeout=GEMINI_TIMEOUT,
        )
        if answer.strip():
            return (remove_trailing_question(answer).strip() + "\n\n" + learning_note)[:4900]
    except Exception as exc:
        print(f"{LLM_PROVIDER} limited fallback answer failed: {type(exc).__name__}: {exc}")

    return (
        f"{ladder} 但目前證據覆蓋仍不足以安全整理成完整答案。"
        + " "
        + learning_note
        + " "
        + red_flag_safety_text()
    )


def extract_gemini_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for candidate in payload.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            if part.get("text"):
                parts.append(str(part["text"]))
    return "\n".join(parts).strip()


def active_model() -> str:
    if LLM_PROVIDER == "deepseek":
        return DEEPSEEK_MODEL
    return GEMINI_MODEL


def active_api_key() -> str:
    if LLM_PROVIDER == "deepseek":
        return os.getenv("DEEPSEEK_API_KEY", "").strip()
    return os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()


def llm_configured() -> bool:
    return bool(active_api_key())


def call_gemini(
    api_key: str,
    system_text: str,
    user_text: str,
    max_output_tokens: int = 650,
    temperature: float = 0.4,
    timeout: int | None = None,
) -> str:
    body = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "maxOutputTokens": max_output_tokens,
            "temperature": temperature,
        },
    }
    target_url = f"{GEMINI_API_BASE}/{GEMINI_MODEL}:generateContent"
    request = urllib.request.Request(
        target_url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout or GEMINI_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    return extract_gemini_text(payload)


def extract_deepseek_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for choice in payload.get("choices", []):
        message = choice.get("message") or {}
        content = message.get("content")
        if content:
            parts.append(str(content))
    return "\n".join(parts).strip()


def call_deepseek(
    api_key: str,
    system_text: str,
    user_text: str,
    max_output_tokens: int = 650,
    temperature: float = 0.4,
    timeout: int | None = None,
) -> str:
    body: dict[str, Any] = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": max_output_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if DEEPSEEK_THINKING_ENABLED:
        body["thinking"] = {"type": "enabled"}
        if DEEPSEEK_REASONING_EFFORT:
            body["reasoning_effort"] = DEEPSEEK_REASONING_EFFORT
    else:
        body["thinking"] = {"type": "disabled"}

    request = urllib.request.Request(
        f"{DEEPSEEK_API_BASE}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout or GEMINI_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    return extract_deepseek_text(payload)


def call_llm(
    api_key: str,
    system_text: str,
    user_text: str,
    max_output_tokens: int = 650,
    temperature: float = 0.4,
    timeout: int | None = None,
) -> str:
    if LLM_PROVIDER == "deepseek":
        return call_deepseek(api_key, system_text, user_text, max_output_tokens, temperature, timeout)
    return call_gemini(api_key, system_text, user_text, max_output_tokens, temperature, timeout)


def extract_json_object(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def extract_openai_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return str(payload["output_text"]).strip()
    parts: list[str] = []
    for choice in payload.get("choices", []):
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("text"):
                    parts.append(str(item["text"]))
    return "\n".join(parts).strip()


def call_gemini_review_model(system_text: str, user_text: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key:
        return ""
    body = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "maxOutputTokens": 900,
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    target_url = f"{GEMINI_API_BASE}/{LINE_ANSWER_IMPROVEMENT_MODEL}:generateContent"
    request = urllib.request.Request(
        target_url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=LINE_ANSWER_IMPROVEMENT_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    return extract_gemini_text(payload)


def call_openai_review_model(system_text: str, user_text: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return ""
    body: dict[str, Any] = {
        "model": LINE_ANSWER_IMPROVEMENT_MODEL,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.1,
        "max_tokens": 900,
    }
    request = urllib.request.Request(
        os.getenv("OPENAI_CHAT_COMPLETIONS_URL", "https://api.openai.com/v1/chat/completions"),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=LINE_ANSWER_IMPROVEMENT_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    return extract_openai_text(payload)


def call_answer_improvement_model(system_text: str, user_text: str) -> str:
    if LINE_ANSWER_IMPROVEMENT_PROVIDER == "openai":
        return call_openai_review_model(system_text, user_text)
    if LINE_ANSWER_IMPROVEMENT_PROVIDER == "gemini":
        return call_gemini_review_model(system_text, user_text)
    print(f"answer improvement skipped: unsupported provider {LINE_ANSWER_IMPROVEMENT_PROVIDER}")
    return ""


def json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def clinical_intent_text(clinical_intent: dict[str, Any] | None) -> str:
    if not clinical_intent:
        return ""
    parts = [
        str(clinical_intent.get("clinical_intent") or "").strip(),
        str(clinical_intent.get("question_type") or "").strip(),
        *json_list(clinical_intent.get("patient_context")),
        *json_list(clinical_intent.get("must_retrieve")),
        *json_list(clinical_intent.get("required_facets")),
        *json_list(clinical_intent.get("concepts")),
        *json_list(clinical_intent.get("target_chapters")),
        *json_list(clinical_intent.get("evidence_targets")),
    ]
    return " ".join(part for part in parts if part).strip()


def clinical_intent_prompt(clinical_intent: dict[str, Any] | None) -> str:
    if not clinical_intent:
        return ""
    return (
        "\n\n臨床問題理解：\n"
        "以下 JSON 是本輪回答前對使用者問題的臨床意圖拆解，用來定義要檢索與整理哪些證據；"
        "它不是醫療知識來源，最終回答仍只能根據已載入指南與知識庫內容。\n"
        f"{json.dumps(clinical_intent, ensure_ascii=False)}"
    )


def clinical_retrieval_intent_prompt(clinical_intent: dict[str, Any] | None) -> str:
    if not clinical_intent:
        return ""
    allowed_keys = (
        "clinical_intent",
        "question_type",
        "patient_context",
        "must_retrieve",
        "required_facets",
        "concepts",
        "target_chapters",
        "evidence_targets",
    )
    retrieval_intent = {key: clinical_intent.get(key) for key in allowed_keys if clinical_intent.get(key)}
    return (
        "\n\n臨床檢索目標：\n"
        "以下 JSON 只保留正向檢索欄位；負面路由與回答策略欄位不應進入 search_query。\n"
        f"{json.dumps(retrieval_intent, ensure_ascii=False)}"
    )


def contextual_guideline_followup(user_text: str, recent_context: str = "") -> bool:
    if not recent_context.strip():
        return False
    followup = user_text.strip().lower()
    if len(followup) > 80 and not re.search(r"上述|前面|剛剛|哪些|哪個|證據|等級|grade|strong|recommendation", followup):
        return False
    has_followup_cue = bool(
        re.search(
            r"上述|前面|剛剛|這些|哪些|哪個|哪一些|證據|等級|證據等級|建議等級|"
            r"較低|低證據|strong|conditional|recommendation|grade|evidence|recommend",
            followup,
            flags=re.I,
        )
    )
    context_scope = f"{recent_context}".lower()
    has_guideline_context = bool(
        re.search(
            r"ada|kdigo|diabetes|糖尿病|ckd|egfr|uacr|sglt|glp|metformin|insulin|finerenone|"
            r"冠狀動脈|心血管|腎|白蛋白尿|指南|recommendation|證據",
            context_scope,
            flags=re.I,
        )
    )
    return has_followup_cue and has_guideline_context


def context_search_excerpt(recent_context: str, max_chars: int = 900) -> str:
    if not recent_context.strip():
        return ""
    text = re.sub(r"\s+", " ", recent_context).strip()
    text = re.sub(r"最近對話脈絡：|以下是同一個 LINE 對話中尚未過期的最近訊息.*?存在。", " ", text)
    return text[-max_chars:]


def evidence_grade_followup(user_text: str, recent_context: str = "") -> bool:
    haystack = f"{user_text} {recent_context}".lower()
    return bool(
        re.search(
            r"證據等級|建議等級|哪些證據|證據.*較低|較低.*證據|低證據|"
            r"strong recommendation|conditional recommendation|recommendation grade|evidence grade|grade 1|grade 2|1a|1b|2a|2b|2c",
            haystack,
            flags=re.I,
        )
    )


def section12_evidence_grade_context(user_text: str, recent_context: str = "") -> str:
    return section12_topic_from_context(user_text, recent_context)


def fallback_clinical_intent(user_text: str, recent_context: str = "") -> dict[str, Any]:
    context_excerpt = context_search_excerpt(recent_context)
    planning_text = f"{user_text} {context_excerpt}" if contextual_guideline_followup(user_text, recent_context) else user_text
    brain_plan = clinical_search_brain_plan(planning_text)
    planning_lower = planning_text.lower()
    gdm_specific = any(term in planning_text for term in ("妊娠糖尿病", "懷孕糖尿病", "孕期糖尿病")) or any(
        term in planning_lower for term in ("gdm", "gestational diabetes")
    )
    diabetes_pregnancy_specific = gdm_specific or "diabetes in pregnancy" in planning_lower or "pregnancy diabetes" in planning_lower
    pregnancy_drug_specific = any(term in planning_text for term in ("胰島素",)) or any(
        term in planning_lower for term in ("metformin", "glyburide", "insulin")
    )
    generic_gdm_medication = any(term in planning_text for term in ("藥", "用藥", "口服藥")) or any(
        term in planning_lower for term in ("pharmacotherapy", "medication", "oral agent")
    )
    gdm_technology_context = any(term in planning_text for term in ("連續血糖", "幫浦", "自動胰島素")) or any(
        term in planning_lower for term in ("cgm", "pump", "automated insulin delivery", "aid")
    )
    gdm_pharmacotherapy = diabetes_pregnancy_specific and (pregnancy_drug_specific or generic_gdm_medication)
    if gdm_technology_context and not pregnancy_drug_specific and not generic_gdm_medication:
        gdm_pharmacotherapy = False
    if gdm_pharmacotherapy:
        question_type = (
            "pregnancy_pharmacotherapy_evidence_grade"
            if evidence_grade_followup(user_text, recent_context)
            else "pregnancy_pharmacotherapy_evidence"
        )
        intent = {
            "clinical_intent": "gdm_pharmacotherapy_guideline_question",
            "question_type": question_type,
            "patient_context": [user_text, context_excerpt],
            "must_retrieve": [
                "ADA 2026 Section 15 Management of Diabetes in Pregnancy",
                "Recommendation 15.15 lifestyle behavior change and insulin if needed",
                "Recommendation 15.17 insulin preferred agent for GDM",
                "Recommendation 15.21 metformin and glyburide not first-line because both cross placenta",
                "Recommendation 15.21 metformin and glyburide may not be sufficient to achieve glycemic goals",
                "other oral and noninsulin injectable glucose-lowering medications lack long-term safety data",
            ],
            "required_facets": ["pregnancy", "medication", "treatment"],
            "concepts": ["GDM pharmacotherapy", "metformin in GDM", "insulin preferred agent", "ADA 2026 Section 15"],
            "target_chapters": ["ADA S15 Management of Diabetes in Pregnancy"],
            "evidence_targets": ["ADA 15.15", "ADA 15.17", "ADA 15.21", "Grade A", "Grade B", "Grade E"],
            "avoid_routes": ["CKD metformin-only pages unless the user also asks about kidney disease"],
            "answer_strategy": (
                "Answer from ADA 2026 Section 15 pharmacotherapy evidence. State insulin is preferred for GDM; "
                "metformin/glyburide are not first-line because both cross the placenta and may not meet glycemic goals. "
                "Do not describe this as an absolute ban."
            ),
            "do_not_answer_with": [
                "no loaded guideline evidence",
                "CKD metformin renal-dose answer",
                "absolute prohibition of metformin without individualization",
            ],
        }
        return merge_clinical_brain(intent, brain_plan)
    section12_context = section12_evidence_grade_context(user_text, recent_context)
    if evidence_grade_followup(user_text, recent_context) and section12_context:
        kidney_grade_context = has_kidney_context(planning_text)
        if section12_context == "retinopathy":
            concepts = [
                "ADA 2026 Section 12 retinopathy treatment",
                "diabetic macular edema",
                "PDR",
                "NPDR",
                "anti-VEGF",
                "panretinal laser photocoagulation",
                "Evidence Grade Router MOC",
            ]
            must_retrieve = [
                "Evidence Grade Router MOC",
                "ADA 2026 Section 12 recommendation grades",
                "Recommendation 12.9 prompt ophthalmology referral",
                "Recommendation 12.10 panretinal laser photocoagulation",
                "Recommendation 12.11 anti-VEGF for PDR",
                "Recommendation 12.12 anti-VEGF first-line for center-involved DME impairing visual acuity",
                "Recommendation 12.13 focal/grid photocoagulation or corticosteroid for persistent DME or anti-VEGF non-candidates",
                "Recommendation 12.15 and 12.16 vision rehabilitation Grade E",
            ]
            evidence_targets = ["ADA 12.9", "ADA 12.10", "ADA 12.11", "ADA 12.12", "ADA 12.13", "Grade A", "Grade E"]
            section_required_facets = ["retinopathy_context", "treatment"]
            answer_strategy = (
                "Answer Section 12 retinopathy treatment evidence grades first. Do not default to CKD/cardiorenal grades. "
                "For severe diabetic eye disease, name 12.9 referral and the treatment rows 12.10-12.13 before caveats."
            )
        elif section12_context == "neuropathy":
            concepts = [
                "ADA 2026 Section 12 neuropathy treatment",
                "diabetic peripheral neuropathy",
                "neuropathic pain pharmacotherapy",
                "gabapentinoids",
                "SNRI",
                "TCA",
                "sodium channel blockers",
                "Evidence Grade Router MOC",
            ]
            must_retrieve = [
                "Evidence Grade Router MOC",
                "ADA 2026 Section 12 recommendation grades",
                "Recommendation 12.20 neuropathy prevention/progression grade split",
                "Recommendation 12.21 painful DPN and autonomic symptom treatment",
                "Recommendation 12.22 gabapentinoids SNRIs TCAs sodium channel blockers initial pharmacologic treatments",
                "Recommendation 12.22 opioid tramadol tapentadol avoidance except rare circumstances",
            ]
            evidence_targets = ["ADA 12.20", "ADA 12.21", "ADA 12.22", "Grade A", "Grade B", "Grade C", "Grade E"]
            section_required_facets = ["treatment", "medication"]
            answer_strategy = (
                "Answer Section 12 neuropathy treatment evidence grades first. For medication questions, lead with 12.22: "
                "initial drug classes are Grade A, combination therapy Grade A, opioids/tramadol/tapentadol should generally not be used except rare circumstances Grade B."
            )
        else:
            concepts = [
                "ADA 2026 Section 12 foot care PAD",
                "diabetic foot care",
                "PAD screening",
                "LOPS",
                "ABI with toe pressures",
                "Evidence Grade Router MOC",
            ]
            must_retrieve = [
                "Evidence Grade Router MOC",
                "ADA 2026 Section 12 recommendation grades",
                "Recommendation 12.23 annual comprehensive foot evaluation",
                "Recommendation 12.24 foot exam components",
                "Recommendation 12.25 every-visit foot inspection for high risk",
                "Recommendation 12.27 PAD screening and ABI with toe pressures",
                "Recommendation 12.29 foot specialist referral and smoking cessation grade split",
            ]
            evidence_targets = ["ADA 12.23", "ADA 12.24", "ADA 12.25", "ADA 12.27", "ADA 12.29", "Grade A", "Grade B"]
            section_required_facets = ["foot_care", "pad_context", "treatment"]
            answer_strategy = (
                "Answer Section 12 foot/PAD evidence grades first. Keep PAD screening/foot-care grades separate from CKD/cardiorenal drug grades."
            )
        intent = {
            "clinical_intent": (
                f"mixed_ckd_ada_section12_{section12_context}_evidence_grade_followup"
                if kidney_grade_context
                else f"ada_section12_{section12_context}_evidence_grade_followup"
            ),
            "question_type": "evidence_grade_comparison",
            "patient_context": [user_text, context_excerpt],
            "must_retrieve": must_retrieve
            + (
                [
                    "ADA/KDIGO CKD cardiorenal claim registry",
                    "ADA 2026 Section 11 CKD recommendations",
                    "KDIGO 2026 diabetes management in CKD recommendations",
                    "SGLT2i eGFR and albuminuria recommendation grades",
                ]
                if kidney_grade_context
                else []
            ),
            "required_facets": section_required_facets + (["kidney_context"] if kidney_grade_context else []),
            "concepts": concepts + (["CKD", "KDIGO 2026", "cardiorenal evidence grades"] if kidney_grade_context else []),
            "target_chapters": ["ADA S12 Retinopathy, Neuropathy, and Foot Care"]
            + (["ADA S11 Chronic Kidney Disease", "KDIGO diabetes management in CKD"] if kidney_grade_context else []),
            "evidence_targets": evidence_targets
            + (["ADA 11.7a", "ADA 11.11a", "KDIGO 4.3.1", "KDIGO GRADE"] if kidney_grade_context else []),
            "avoid_routes": (
                ["Do not answer as CKD-only or Section-12-only; keep CKD/KDIGO and ADA Section 12 evidence grades in separate buckets."]
                if kidney_grade_context
                else ["CKD/cardiorenal evidence cards unless the user also asks kidney disease, eGFR, UACR, SGLT2i, GLP-1RA, finerenone, ACEi/ARB, or KDIGO"]
            ),
            "answer_strategy": (
                answer_strategy
                + " Because CKD/KDIGO context is also present, retrieve and answer CKD/cardiorenal evidence grades as a separate bucket."
                if kidney_grade_context
                else answer_strategy
            ),
            "do_not_answer_with": [
                "no loaded guideline evidence",
                "CKD/cardiorenal-only evidence grade answer",
                "invented recommendation grades",
            ],
        }
        return merge_clinical_brain(intent, brain_plan)
    if evidence_grade_followup(user_text, recent_context) and has_liver_context(planning_text):
        kidney_grade_context = has_kidney_context(planning_text)
        intent = {
            "clinical_intent": (
                "mixed_ckd_ada_section4_masld_mash_evidence_grade_followup"
                if kidney_grade_context
                else "ada_section4_masld_mash_evidence_grade_followup"
            ),
            "question_type": "evidence_grade_comparison",
            "patient_context": [user_text, context_excerpt],
            "must_retrieve": [
                "Evidence Grade Router MOC",
                "ADA 2026 Section 4 MASLD MASH claim cards",
                "ADA 4.22a FIB-4 screening recommendation grade",
                "ADA 4.25 liver stiffness measurement recommendation grade",
                "ADA 4.26 multidisciplinary care recommendation grade",
                "ADA 4.27a weight loss and GLP-1 RA pioglitazone tirzepatide recommendation grades",
                "ADA 4.28 resmetirom recommendation grade",
                "ADA 4.31a/4.31b cirrhosis care and ADA 4.32a/4.32b metabolic surgery recommendation grades",
            ]
            + (
                [
                    "ADA/KDIGO CKD cardiorenal claim registry",
                    "ADA 2026 Section 11 CKD recommendations",
                    "KDIGO diabetes management in CKD recommendations",
                ]
                if kidney_grade_context
                else []
            ),
            "required_facets": ["liver_context", "evidence_grade"] + (["kidney_context"] if kidney_grade_context else []),
            "concepts": [
                "MASLD",
                "MASH",
                "FIB-4",
                "liver fibrosis",
                "GLP-1 RA",
                "pioglitazone",
                "tirzepatide",
                "resmetirom",
                "ADA 2026 Section 4",
                "Evidence Grade Router MOC",
            ]
            + (["CKD", "KDIGO 2026", "cardiorenal evidence grades"] if kidney_grade_context else []),
            "target_chapters": ["ADA S4 Comprehensive Medical Evaluation and Assessment of Comorbidities"]
            + (["ADA S11 Chronic Kidney Disease", "KDIGO diabetes management in CKD"] if kidney_grade_context else []),
            "evidence_targets": [
                "ADA 4.22a",
                "ADA 4.25",
                "ADA 4.26",
                "ADA 4.27a",
                "ADA 4.28",
                "ADA 4.31a",
                "ADA 4.32a",
                "ADA 4.32b",
                "Grade A",
                "Grade B",
                "Grade C",
            ]
            + (["ADA 11.7a", "ADA 11.11a", "KDIGO GRADE"] if kidney_grade_context else []),
            "avoid_routes": (
                ["Do not answer as CKD-only or MASLD-only; keep CKD/KDIGO and ADA Section 4 evidence grades in separate buckets."]
                if kidney_grade_context
                else ["CKD/cardiorenal evidence cards unless the user also asks kidney disease, eGFR, UACR, SGLT2i, GLP-1RA, finerenone, ACEi/ARB, or KDIGO"]
            ),
            "answer_strategy": (
                "Answer ADA 2026 Section 4 MASLD/MASH evidence grades first. Mention FIB-4, liver stiffness or ELF testing, "
                "weight loss/lifestyle, GLP-1 RA/pioglitazone/tirzepatide, resmetirom, and cirrhosis care only when supported by retrieved claim cards. "
                "Do not default to CKD/cardiorenal grades merely because the user asks 建議等級."
            ),
            "do_not_answer_with": [
                "no loaded guideline evidence",
                "CKD/cardiorenal-only evidence grade answer",
                "invented recommendation grades",
            ],
        }
        return merge_clinical_brain(intent, brain_plan)
    if evidence_grade_followup(user_text, recent_context):
        intent = {
            "clinical_intent": "guideline_evidence_grade_followup",
            "question_type": "evidence_grade_comparison",
            "patient_context": [user_text, context_excerpt],
            "must_retrieve": [
                "ADA 2026 recommendation grade evidence level",
                "KDIGO 2026 recommendation strength grade 1 grade 2 evidence quality A B C D",
                "SGLT2 inhibitor CKD strong recommendation evidence",
                "GLP-1 RA ASCVD CKD evidence grade",
                "metformin CKD eGFR evidence grade",
                "finerenone albuminuria CKD recommendation evidence",
                "glycemic target individualized A1C evidence grade",
            ],
            "required_facets": ["kidney_context", "medication", "ascvd_context", "treatment"],
            "concepts": [
                "recommendation strength",
                "evidence grade",
                "SGLT2 inhibitor",
                "GLP-1 RA",
                "CKD",
                "ASCVD",
                "albuminuria",
                "ADA 2026",
                "KDIGO 2026",
            ],
            "target_chapters": [
                "ADA S9 pharmacologic approaches",
                "ADA S10 cardiovascular disease and risk management",
                "ADA S11 chronic kidney disease",
                "KDIGO diabetes management in CKD",
            ],
            "evidence_targets": [
                "strong recommendation",
                "conditional recommendation",
                "grade 1",
                "grade 2",
                "evidence quality A B C D",
                "expert consensus",
                "lower certainty evidence",
            ],
            "answer_strategy": (
                "Use the previous clinical scenario from recent context. Separate strong/high-certainty recommendations "
                "from lower-certainty, conditional, consensus, or individualized recommendations. If exact KDIGO/ADA "
                "grade is not present in retrieved evidence, state that limitation rather than inventing a grade."
            ),
            "do_not_answer_with": [
                "out-of-scope refusal for short follow-up",
                "model general medical knowledge",
                "invented recommendation grades",
            ],
        }
        return merge_clinical_brain(intent, brain_plan)
    if comparative_threshold_question(user_text):
        intent = {
            "clinical_intent": "advanced_ckd_medication_selection",
            "question_type": "medication_threshold_comparison",
            "patient_context": ["diabetes", "advanced CKD", "low eGFR", user_text],
            "must_retrieve": [
                "CKD glucose-lowering therapy",
                "SGLT2 inhibitor eGFR initiation threshold",
                "metformin eGFR contraindication or dose limitation",
                "GLP-1 receptor agonist use in CKD",
                "finerenone or nonsteroidal MRA eGFR threshold",
                "hypoglycemia risk in advanced CKD",
                "insulin safety or dose adjustment in kidney impairment",
            ],
            "required_facets": ["kidney_context", "medication", "threshold"],
            "answer_strategy": (
                "compare retrieved eGFR thresholds with the user's eGFR value; state what is not suitable "
                "to initiate, what may be considered from the retrieved guideline evidence, and what requires clinician individualization"
            ),
            "do_not_answer_with": [
                "requiring an exact sentence for the exact eGFR number",
                "personalized dose recommendation",
                "model general medical knowledge",
            ],
        }
        return merge_clinical_brain(intent, brain_plan)
    facets = sorted(required_facets(user_text))
    intent = {
        "clinical_intent": "diabetes_guideline_question",
        "question_type": "guideline_grounded_answer",
        "patient_context": [user_text],
        "must_retrieve": [],
        "required_facets": facets,
        "answer_strategy": "answer only if retrieved guideline evidence covers the user's core question",
        "do_not_answer_with": ["model general medical knowledge", "unsupported inference"],
    }
    return merge_clinical_brain(intent, brain_plan)


def merge_clinical_brain(intent: dict[str, Any], brain_plan: dict[str, list[str]]) -> dict[str, Any]:
    if not brain_plan:
        return intent
    merged = dict(intent)
    for target_key, brain_key in (
        ("concepts", "concepts"),
        ("target_chapters", "target_chapters"),
        ("evidence_targets", "evidence_targets"),
        ("avoid_routes", "avoid_routes"),
        ("required_facets", "required_facets"),
        ("must_retrieve", "evidence_targets"),
    ):
        values = [*json_list(merged.get(target_key)), *json_list(brain_plan.get(brain_key))]
        merged[target_key] = dedupe_preserve(values)
    merged["clinical_search_brain"] = brain_plan
    if brain_plan.get("avoid_routes"):
        merged["do_not_answer_with"] = dedupe_preserve(
            [*json_list(merged.get("do_not_answer_with")), *brain_plan["avoid_routes"]]
        )
    return merged


def dedupe_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        compact = re.sub(r"\s+", " ", str(value)).strip()
        key = compact.lower()
        if compact and key not in seen:
            seen.add(key)
            result.append(compact)
    return result


def build_clinical_intent(api_key: str, user_text: str, recent_context: str) -> dict[str, Any]:
    fallback = fallback_clinical_intent(user_text, recent_context)
    if not LINE_QUERY_PLANNING_ENABLED or not api_key:
        return fallback

    system_text = (
        "你是糖尿病指南問答的 clinical intent parser，不是回答者。"
        "你的任務是先理解使用者真正要問的臨床問題，定義需要檢索哪些指南證據。"
        "不要提供醫療建議，不要回答問題，不要使用模型內建醫學知識下結論。"
        "請輸出 JSON，欄位固定為："
        "clinical_intent, question_type, patient_context, concepts, target_chapters, evidence_targets, must_retrieve, required_facets, avoid_routes, answer_strategy, do_not_answer_with。"
        "required_facets 只能使用這些值：blood_pressure_target, kidney_context, medication, threshold, glycemic_target, a1c_reliability, monitoring, technology_indication, diagnosis, retinopathy_context, staging, pad_context, ascvd_context, pregnancy, hypoglycemia, treatment, foot_care, frequency, liver_context, hospital_context, steroid_context, bone_health, fracture_risk。"
        "若使用者問血糖控制目標、A1C 目標、CGM/TIR 目標，請理解為 glycemic targets；target_chapters 應包含 ADA S6，required_facets 應包含 glycemic_target。"
        "若使用者問血壓控制目標、高血壓目標、BP target，請理解為 blood pressure target / hypertension treatment goal，不要歸類為 glycemic target；target_chapters 應包含 ADA S10；evidence_targets 應包含 Recommendation 10.3、Recommendation 10.4、<130/80 mmHg、high cardiovascular or kidney risk 時可鼓勵 systolic <120 mmHg、individualized/shared decision-making/adverse effects；required_facets 應包含 blood_pressure_target, ascvd_context, treatment。"
        "若使用者問血脂、膽固醇、LDL、三酸甘油脂的治療目標，請歸類為 cardiovascular/lipid risk management，不要歸類為 glycemic target；target_chapters 應包含 ADA S10；required_facets 請使用 ascvd_context, treatment, threshold。"
        "若使用者用白話描述下肢動脈阻塞、腳血管塞住、跛行、下肢缺血，請理解為 PAD / lower-extremity arterial disease / ASCVD；target_chapters 應包含 ADA S10 與 ADA S12，evidence_targets 應包含 antiplatelet、aspirin/clopidogrel、rivaroxaban plus aspirin、statin/lipid、blood pressure、smoking cessation、vascular assessment/revascularization、GLP-1 RA/semaglutide limb outcome evidence；avoid_routes 要說不要只用一般降血糖藥物表回答。"
        "若使用者提到 HHNK、HHS、高滲透壓、高血糖高滲透壓、酮酸中毒、酮酸、DKA 或高血糖急症，請理解為 hyperglycemic crises；target_chapters 應包含 ADA S16 Diabetes Care in the Hospital 和 ADA S6；evidence_targets 應包含 DKA/HHS diagnostic criteria、Table 16.1、intravenous fluids、insulin、electrolytes、potassium/osmolality/ketones/pH/bicarbonate、transition to subcutaneous insulin、precipitating cause；avoid_routes 要說不要從 GDM 或一般 outpatient diagnosis criteria 回答。"
        "若使用者提到住院/病房/inpatient/hospitalized 加上類固醇/glucocorticoid/steroid/corticosteroid/prednisone/prednisolone/dexamethasone 與高血糖，請理解為 glucocorticoid-associated inpatient hyperglycemia；target_chapters 應包含 ADA S16 和 ADA S9；evidence_targets 應包含 NPH insulin with prednisone/prednisolone、basal insulin for dexamethasone or continuous glucocorticoids、prandial/correction insulin increases、daily adjustment、POC blood glucose monitoring；required_facets 應包含 hospital_context, steroid_context, treatment。"
        "若使用者提到 GDM、gestational diabetes、妊娠糖尿病、懷孕糖尿病，加上 metformin、glyburide、insulin、藥物、口服藥或 pharmacotherapy，請理解為 ADA S15 pregnancy pharmacotherapy；target_chapters 應包含 ADA S15；evidence_targets 應包含 Recommendation 15.15、15.17、15.21、insulin preferred agent for GDM、metformin/glyburide not first-line、cross placenta、may not be sufficient for glycemic goals、other oral/noninsulin agents lack long-term safety data；required_facets 應包含 pregnancy, medication, treatment；avoid_routes 要說不要只走 CKD metformin。"
        "若使用者提到骨質疏鬆、骨鬆、骨折、骨密度、骨骼健康、osteoporosis、bone health、fracture、BMD、DXA、T-score 或 FRAX，請理解為 diabetes bone health / osteoporosis；target_chapters 應包含 ADA S4 Comprehensive Medical Evaluation；evidence_targets 應包含 recommendations 4.8-4.13b、fracture risk assessment、DXA/BMD monitoring、T-score <= -2.5、T-score -2.0 to -2.5 with additional risk factors、fragility fracture、FRAX、TZD/sulfonylurea fracture risk、hypoglycemia/falls、calcium/vitamin D；required_facets 應包含 bone_health, fracture_risk, treatment；avoid_routes 要說不要只用視網膜、足部、PAD 或 CKD 內容回答，也不要在已檢索到 FRAX/T-score/DXA 時說缺乏這些資訊。"
        "若短 follow-up 問「證據等級/建議等級」且最近脈絡是視網膜病變、嚴重眼病變、DME、PDR、NPDR、anti-VEGF、雷射、眼科，請理解為 ADA S12 retinopathy treatment evidence grade；target_chapters 應包含 ADA S12；evidence_targets 應包含 12.9-12.16、Grade A、Grade E；avoid_routes 要說不要預設走 CKD/cardiorenal evidence cards。"
        "若短 follow-up 問「藥物的證據等級/治療等級」且最近脈絡是神經病變、DPN、神經痛、gabapentinoids、SNRI、TCA、sodium channel blocker、opioid、tramadol，請理解為 ADA S12 neuropathy treatment evidence grade；evidence_targets 應包含 12.20、12.21、12.22、Grade A/B/C/E；required_facets 應包含 medication, treatment。"
        "若短 follow-up 問證據等級且最近脈絡是糖尿病足、PAD、周邊動脈、LOPS、monofilament、ABI、toe pressure，請理解為 ADA S12 foot/PAD recommendation grade；evidence_targets 應包含 12.23-12.29、Grade A/B；required_facets 應包含 foot_care, pad_context。"
        "若本次問題很短，像「哪些證據等級較低」、「哪些是 strong recommendation」、「那證據等級呢」，請使用最近對話脈絡還原上一題的疾病、藥物與指南範圍；question_type 應是 evidence_grade_comparison，required_facets 至少包含 medication, treatment，evidence_targets 應包含 recommendation strength、evidence grade、strong/conditional、grade 1/2、A/B/C/D、expert consensus。不要把這種短 follow-up 判成 out-of-scope。"
        "若問題是特定 eGFR 數值下的用藥/合併用藥，question_type 必須是 medication_threshold_comparison，"
        "must_retrieve 要包含 SGLT2 eGFR threshold、metformin eGFR limitation、GLP-1 RA in CKD、finerenone/nsMRA eGFR threshold、advanced CKD hypoglycemia/insulin safety。"
        "answer_strategy 要明確說明：用檢索到的 eGFR 門檻與使用者 eGFR 數值比較，不需要文件逐字出現 exact eGFR 數字。"
    )
    prompt = (
        f"本次問題：{user_text}\n\n"
        f"{recent_context or '最近對話脈絡：無'}\n\n"
        "請先輸出臨床意圖 JSON。"
    )
    try:
        raw = call_llm(
            api_key,
            system_text,
            prompt,
            max_output_tokens=520,
            temperature=0.05,
            timeout=min(GEMINI_TIMEOUT, 10),
        )
    except Exception as exc:
        print(f"{LLM_PROVIDER} clinical intent failed: {type(exc).__name__}: {exc}")
        return fallback

    data = extract_json_object(raw)
    if not data:
        return fallback
    merged = {**fallback, **data}
    for key in (
        "patient_context",
        "concepts",
        "target_chapters",
        "evidence_targets",
        "must_retrieve",
        "required_facets",
        "avoid_routes",
        "do_not_answer_with",
    ):
        merged[key] = dedupe_preserve([*json_list(fallback.get(key)), *json_list(data.get(key))])
    planning_text = (
        f"{user_text} {context_search_excerpt(recent_context)}"
        if contextual_guideline_followup(user_text, recent_context)
        else user_text
    )
    return merge_clinical_brain(merged, clinical_search_brain_plan(planning_text))


def build_retrieval_query(
    api_key: str,
    user_text: str,
    recent_context: str,
    clinical_intent: dict[str, Any] | None = None,
) -> str:
    if not LINE_QUERY_PLANNING_ENABLED or not api_key:
        return " ".join(part for part in [user_text, clinical_intent_text(clinical_intent)] if part).strip() or user_text

    system_text = (
        "你不是回答者，也不要提供醫療建議。"
        "你的唯一任務是把 LINE 病友問題轉成已載入臨床指南文件檢索查詢。"
        "請根據本次問題與最近對話脈絡，補上可能出現在這些指南文件中的英文術語、縮寫、同義詞與章節詞。"
        "你會收到 clinical intent JSON；請優先根據 concepts、target_chapters、evidence_targets、must_retrieve、required_facets 產生多面向檢索詞。"
        "avoid_routes 與 do_not_answer_with 是負面路由規則，只能用來排除方向，不可把其中的否定詞、禁搜詞或不該走的章節詞加入 search_query。"
        "若問題是血糖控制目標、A1C 目標、CGM/TIR 目標，請加入 ADA section 6、glycemic goals、A1C goal、individualized targets、CGM metrics、time in range。"
        "若問題是血壓控制目標、高血壓目標、BP target，請加入 ADA section 10、dc26s010、Treatment Goals、blood pressure goals、hypertension、Recommendation 10.3、Recommendation 10.4、on-treatment blood pressure goal、<130/80 mmHg、systolic blood pressure goal <120 mmHg、high cardiovascular or kidney risk、individualized/shared decision-making；不要加入 glycemic goals 或 A1C target，除非使用者同時問血糖。"
        "若問題是血脂、膽固醇、LDL 或三酸甘油脂治療目標，請加入 ADA section 10、dc26s010、lipid management、LDL cholesterol、statin therapy、primary prevention、secondary prevention、ASCVD、triglyceride；不要加入 glycemic goals 或 A1C target，除非使用者同時問血糖。"
        "若問題提到洗腎/透析/腎衰竭與血糖控制目標，請加入 dialysis、kidney failure、glycemic goals、A1C goal、A1C reliability、CGM、BGM、glycated albumin、fructosamine。"
        "若 question_type 是 medication_threshold_comparison，請加入 CKD glucose-lowering therapy、SGLT2 inhibitor eGFR threshold、metformin eGFR、GLP-1 RA CKD、finerenone nonsteroidal MRA eGFR、hypoglycemia risk advanced CKD、insulin kidney impairment。"
        "若問題提到脂肪肝、脂肪性肝炎、MASLD、MASH、NAFLD、NASH、肝硬化或肝纖維化，請加入 MASLD、MASH、NAFLD、NASH、steatotic liver disease、steatohepatitis、fibrosis、cirrhosis、GLP-1 receptor agonist、pioglitazone、tirzepatide、weight loss。"
        "若 concepts 或問題指向 PAD、peripheral artery disease、下肢動脈阻塞、下肢缺血或跛行，請加入 ADA section 10、ADA section 12、PAD、lower-extremity arterial disease、ASCVD、antiplatelet、aspirin、clopidogrel、rivaroxaban、statin、lipid-lowering、blood pressure、smoking cessation、ABI、toe pressure、revascularization、semaglutide、STRIDE、limb outcomes；並避免只搜尋 glucose-lowering medication table。"
        "若問題提到 HHNK、HHS、高滲透壓、高血糖高滲透壓、酮酸中毒、酮酸、DKA 或高血糖急症，請加入 ADA section 16、dc26s016、hyperglycemic crises、DKA、diabetic ketoacidosis、HHS、hyperosmolar hyperglycemic state、diagnostic criteria、Table 16.1、intravenous fluids、insulin、electrolytes、potassium、osmolality、ketones、pH、bicarbonate、transition to subcutaneous insulin、precipitating cause；並避免搜尋 GDM/outpatient diagnosis criteria。"
        "若問題提到住院/病房/inpatient/hospitalized 加上類固醇/glucocorticoid/steroid/corticosteroid/prednisone/prednisolone/dexamethasone 與高血糖，請加入 ADA section 16、dc26s016、glucocorticoid therapy、steroid-induced hyperglycemia、NPH insulin、prednisone、prednisolone、dexamethasone、basal insulin、prandial insulin、correction insulin、point-of-care blood glucose monitoring、ADA section 9、recommendation 9.36、frequent reassessment。"
        "若問題提到 GDM、gestational diabetes、妊娠糖尿病、懷孕糖尿病，加上 metformin、glyburide、insulin、藥物、口服藥或 pharmacotherapy，請加入 ADA section 15、dc26s015、Recommendation 15.15、15.17、15.21、insulin preferred agent、metformin glyburide not first-line、cross placenta、may not be sufficient to achieve glycemic goals、long-term safety data。"
        "若本次問題是短 follow-up，詢問證據等級、strong recommendation、conditional recommendation、grade 1/2、A/B/C/D 或哪些證據較低，且最近脈絡含視網膜病變、眼病變、DME、NPDR、PDR、anti-VEGF、雷射或眼科，請加入 Evidence Grade Router MOC、ADA section 12、dc26s012、Retinopathy Neuropathy and Foot Care、Recommendation 12.9、12.10、12.11、12.12、12.13、12.15、12.16、retinopathy treatment evidence grade、DME、PDR、anti-VEGF、panretinal laser photocoagulation、vision rehabilitation。"
        "若本次問題是短 follow-up，詢問藥物或治療的證據等級，且最近脈絡含神經病變、DPN、神經痛、gabapentinoids、SNRI、TCA、sodium channel blocker、opioid、tramadol 或 tapentadol，請加入 Evidence Grade Router MOC、ADA section 12、dc26s012、Recommendation 12.20、12.21、12.22、diabetic neuropathy treatment grade、neuropathic pain medication grade diabetes。"
        "若本次問題是短 follow-up，詢問證據等級且最近脈絡含糖尿病足、foot、PAD、周邊動脈、LOPS、monofilament、ABI 或 toe pressure，請加入 Evidence Grade Router MOC、ADA section 12、dc26s012、Recommendation 12.23、12.24、12.25、12.27、12.29、foot PAD recommendation grade。"
        "若本次問題是短 follow-up，詢問證據等級、strong recommendation、conditional recommendation、grade 1/2、A/B/C/D 或哪些證據較低，請從最近對話脈絡帶入上一題的疾病、用藥與指南範圍，並加入 ADA 2026、KDIGO 2026、recommendation strength、evidence grade、strong recommendation、conditional recommendation、expert consensus、SGLT2 inhibitor、GLP-1 RA、metformin、insulin、finerenone、CKD、ASCVD、albuminuria。"
        "不要新增使用者沒有問到的病情、診斷、用藥劑量或結論。"
        "只輸出 JSON，格式為：{\"search_query\":\"...\",\"keywords\":[\"...\"]}。"
    )
    prompt = (
        f"本次問題：{user_text}\n\n"
        f"{recent_context or '最近對話脈絡：無'}\n\n"
        f"{clinical_retrieval_intent_prompt(clinical_intent) or '臨床問題理解：無'}\n\n"
        "請產生適合全文檢索糖尿病指南 Markdown 的查詢。"
    )
    try:
        raw = call_llm(
            api_key,
            system_text,
            prompt,
            max_output_tokens=260,
            temperature=0.1,
            timeout=min(GEMINI_TIMEOUT, 10),
        )
    except Exception as exc:
        print(f"{LLM_PROVIDER} query planning failed: {type(exc).__name__}: {exc}")
        return user_text

    data = extract_json_object(raw)
    search_query = str(data.get("search_query") or "").strip()
    keywords = data.get("keywords") if isinstance(data.get("keywords"), list) else []
    keyword_text = " ".join(str(keyword).strip() for keyword in keywords if str(keyword).strip())
    context_excerpt = context_search_excerpt(recent_context) if contextual_guideline_followup(user_text, recent_context) else ""
    combined = " ".join(
        part for part in [user_text, context_excerpt, clinical_intent_text(clinical_intent), search_query, keyword_text] if part
    ).strip()
    return combined[:LINE_RETRIEVAL_QUERY_MAX_CHARS] or user_text


def local_evidence_coverage(
    user_text: str,
    hits: list[KnowledgeHit],
    clinical_intent: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    required = set(required_facets(user_text))
    required.update(
        facet
        for facet in json_list((clinical_intent or {}).get("required_facets"))
        if facet
        in {
            "blood_pressure_target",
            "kidney_context",
            "medication",
            "threshold",
            "glycemic_target",
            "a1c_reliability",
            "monitoring",
            "technology_indication",
            "diagnosis",
            "retinopathy_context",
            "staging",
            "pad_context",
            "ascvd_context",
            "pregnancy",
            "hypoglycemia",
            "treatment",
            "foot_care",
            "frequency",
            "liver_context",
            "hospital_context",
            "steroid_context",
        }
    )
    if not required:
        return bool(hits), ""

    covered: set[str] = set()
    for hit in hits:
        covered.update(hit_facets(hit))

    missing = required - covered
    if not missing:
        return True, ""

    return False, "本地檢索仍缺少必要面向：" + ", ".join(sorted(missing))


def hit_identity(hit: KnowledgeHit) -> tuple[str, str, str, str]:
    return (
        str(getattr(hit, "source", "")),
        str(getattr(hit, "section", "")),
        str(getattr(hit, "chunk_type", "")),
        hashlib.sha1(str(getattr(hit, "excerpt", "")).encode("utf-8", errors="ignore")).hexdigest()[:12],
    )


def recursive_coverage_queries(
    user_text: str,
    hits: list[KnowledgeHit],
    clinical_intent: dict[str, Any] | None = None,
) -> list[str]:
    if not LINE_RECURSIVE_COVERAGE_ENABLED:
        return []

    required = set(required_facets(user_text))
    required.update(json_list((clinical_intent or {}).get("required_facets")))

    covered: set[str] = set()
    for hit in hits:
        covered.update(hit_facets(hit))
    missing = required - covered

    lower = f"{user_text} {clinical_intent_text(clinical_intent)}".lower()
    queries: list[str] = []
    kidney = any(term in user_text for term in ("腎", "腎絲球", "尿蛋白", "白蛋白尿")) or any(
        term in lower for term in ("ckd", "kidney", "renal", "egfr", "uacr", "albuminuria")
    )
    medication = any(term in user_text for term in ("藥", "用藥", "降血糖", "合併")) or any(
        term in lower for term in ("medication", "pharmacologic", "sglt", "glp", "metformin", "insulin", "finerenone")
    )
    liver = any(term in user_text for term in ("脂肪肝", "脂肪性肝炎", "代謝性脂肪肝", "肝硬化", "肝纖維")) or any(
        term in lower for term in ("masld", "mash", "nafld", "nash", "steatotic liver", "steatohepatitis", "cirrhosis")
    )

    facet_queries = {
        "kidney_context": f"{user_text} CKD chronic kidney disease eGFR albuminuria UACR KDIGO ADA",
        "medication": f"{user_text} pharmacologic therapy medication selection SGLT2 GLP-1 metformin insulin finerenone",
        "threshold": f"{user_text} eGFR threshold cutoff contraindication initiate discontinue dose adjustment",
        "blood_pressure_target": f"{user_text} ADA section 10 dc26s010 Treatment Goals blood pressure goals hypertension Recommendation 10.3 Recommendation 10.4 on-treatment blood pressure goal <130/80 mmHg systolic blood pressure goal <120 mmHg high cardiovascular kidney risk individualized shared decision-making",
        "glycemic_target": f"{user_text} ADA section 6 dc26s006 glycemic goals A1C goals individualized A1C and CGM goals time in range TIR Table 6.2 Figure 6.1 hypoglycemia risk",
        "a1c_reliability": f"{user_text} A1C less reliable advanced CKD dialysis glycated albumin fructosamine CGM BGM",
        "monitoring": f"{user_text} monitoring CGM BGM SMBG time in range follow-up",
        "technology_indication": f"{user_text} ADA section 7 diabetes technology use of CGM recommended diabetes onset children adolescents adults insulin therapy noninsulin therapies hypoglycemia any diabetes treatment where CGM helps management",
        "diagnosis": f"{user_text} diagnosis screening diagnostic criteria A1C fasting plasma glucose OGTT",
        "retinopathy_context": f"{user_text} ADA section 12 diabetic retinopathy retinal disease ophthalmologist macular edema DME NPDR PDR",
        "staging": f"{user_text} staging severity classification mild moderate severe nonproliferative proliferative NPDR PDR diabetic macular edema DME",
        "pad_context": f"{user_text} ADA section 10 section 12 peripheral artery disease PAD lower-extremity arterial disease claudication limb ischemia ABI toe pressure revascularization amputation semaglutide STRIDE limb outcomes",
        "ascvd_context": f"{user_text} ASCVD cardiovascular disease risk management antiplatelet aspirin clopidogrel rivaroxaban statin lipid blood pressure smoking cessation GLP-1 RA SGLT2 inhibitor",
        "pregnancy": f"{user_text} pregnancy gestational diabetes preconception postpartum insulin glycemic goals",
        "hypoglycemia": f"{user_text} hypoglycemia level 1 level 2 level 3 treatment glucagon severe hypoglycemia",
        "treatment": f"{user_text} treatment management recommendation therapy intervention",
        "foot_care": f"{user_text} foot care neuropathy monofilament ulcer peripheral artery disease screening",
        "frequency": f"{user_text} screening frequency annually every year follow-up interval",
        "liver_context": f"{user_text} MASLD MASH NAFLD NASH steatotic liver disease diabetes obesity fibrosis cirrhosis",
        "hospital_context": f"{user_text} ADA section 16 dc26s016 Diabetes Care in the Hospital inpatient hospitalized hyperglycemia insulin point-of-care blood glucose monitoring",
        "steroid_context": f"{user_text} glucocorticoid therapy steroid-induced hyperglycemia corticosteroid prednisone prednisolone dexamethasone NPH insulin basal insulin prandial correction insulin ADA section 16 ADA recommendation 9.36",
    }
    for facet in sorted(missing):
        query = facet_queries.get(facet)
        if query:
            queries.append(query)

    if kidney and medication:
        queries.extend(
            [
                f"{user_text} SGLT2 inhibitor eGFR initiation threshold continuation DKA acute illness perioperative hold KDIGO",
                f"{user_text} metformin eGFR renal function contraindication contrast acute illness perioperative older adults",
                f"{user_text} GLP-1 receptor agonist CKD ASCVD weight hypoglycemia kidney cardiovascular benefit",
                f"{user_text} finerenone nonsteroidal MRA UACR albuminuria eGFR potassium hyperkalemia",
            ]
        )
    if liver:
        queries.extend(
            [
                f"{user_text} MASLD NAFLD metabolic dysfunction-associated steatotic liver disease diabetes obesity weight loss",
                f"{user_text} MASH NASH steatohepatitis GLP-1 receptor agonist pioglitazone tirzepatide cirrhosis fibrosis",
            ]
        )
    if "hospital_steroid_hyperglycemia" in " ".join(json_list((clinical_intent or {}).get("concepts"))).lower() or (
        ("類固醇" in user_text or "steroid" in lower or "glucocorticoid" in lower)
        and ("住院" in user_text or "hospital" in lower or "inpatient" in lower)
    ):
        queries.extend(
            [
                f"{user_text} ADA section 16 dc26s016 glucocorticoid therapy hospitalized hyperglycemia NPH insulin prednisone prednisolone dexamethasone basal insulin prandial correction insulin point-of-care blood glucose monitoring",
                f"{user_text} ADA section 9 recommendation 9.36 glucocorticoid treatment plan steroid-induced hyperglycemia insulin frequent reassessment",
            ]
        )

    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        compact = re.sub(r"\s+", " ", query).strip()
        key = compact.lower()
        if compact and key not in seen:
            seen.add(key)
            deduped.append(compact)
        if len(deduped) >= LINE_RECURSIVE_COVERAGE_MAX_QUERIES:
            break
    return deduped


def append_recursive_coverage_hits(
    user_text: str,
    selected_hits: list[KnowledgeHit],
    clinical_intent: dict[str, Any] | None = None,
) -> tuple[list[KnowledgeHit], str]:
    queries = recursive_coverage_queries(user_text, selected_hits, clinical_intent)
    if not queries:
        return selected_hits, ""

    merged = list(selected_hits)
    seen = {hit_identity(hit) for hit in merged}
    added = 0
    for query in queries:
        for hit in search_knowledge_candidates(query):
            key = hit_identity(hit)
            if key in seen:
                continue
            seen.add(key)
            merged.append(hit)
            added += 1
            if added >= LINE_RECURSIVE_COVERAGE_MAX_HITS:
                note = f"recursive coverage retrieval 補入 {added} 個候選內容。"
                return merged, note
    if added:
        return merged, f"recursive coverage retrieval 補入 {added} 個候選內容。"
    return selected_hits, "recursive coverage retrieval 已執行，但沒有找到新的非重複內容。"


def broad_section_context_needed(
    user_text: str,
    hits: list[KnowledgeHit],
    clinical_intent: dict[str, Any] | None = None,
) -> bool:
    if not LINE_WHOLE_SECTION_CONTEXT_ENABLED:
        return False
    lower = f"{user_text} {clinical_intent_text(clinical_intent)}".lower()
    facets = set(required_facets(user_text))
    facets.update(json_list((clinical_intent or {}).get("required_facets")))
    if "technology_indication" in facets:
        return True
    broad_terms = ("哪些", "哪種", "誰可以", "適用", "適合", "使用對象", "建議", "怎麼選", "治療建議")
    if any(term in user_text for term in broad_terms):
        return True
    if any(term in lower for term in ("who should", "indication", "recommended population", "management recommendation")):
        return True
    return any("whole_section_context" in getattr(hit, "metadata", ()) for hit in hits)


def append_whole_section_context_hits(
    user_text: str,
    selected_hits: list[KnowledgeHit],
    clinical_intent: dict[str, Any] | None = None,
) -> tuple[list[KnowledgeHit], str]:
    if not selected_hits or not broad_section_context_needed(user_text, selected_hits, clinical_intent):
        return selected_hits, ""
    whole_hits = search_whole_section_context(user_text, selected_hits)
    if not whole_hits:
        return selected_hits, "whole-section context 已觸發，但沒有找到可加入的完整 section。"
    seen = {hit_identity(hit) for hit in selected_hits}
    merged = list(selected_hits)
    added = 0
    for hit in whole_hits:
        key = hit_identity(hit)
        if key in seen:
            continue
        seen.add(key)
        merged.append(hit)
        added += 1
    if not added:
        return selected_hits, ""
    return merged, f"whole-section context 補入 {added} 個完整相關章節。"


def comparative_threshold_question(user_text: str) -> bool:
    lower = user_text.lower()
    has_numeric_threshold = bool(re.search(r"\b\d+(?:\.\d+)?\b", user_text))
    has_kidney = any(term in user_text for term in ("腎", "腎功能", "腎絲球")) or any(
        term in lower for term in ("egfr", "ckd", "kidney", "renal")
    )
    has_medication = any(term in user_text for term in ("藥", "用藥", "合併")) or any(
        term in lower for term in ("medication", "pharmacologic", "sglt", "glp", "metformin", "finerenone", "mra")
    )
    return has_numeric_threshold and has_kidney and has_medication


def guideline_scope_question(user_text: str, clinical_intent: dict[str, Any] | None = None) -> bool:
    intent_terms: list[str] = []
    if clinical_intent:
        for key in ("concepts", "target_chapters", "evidence_targets", "must_retrieve", "required_facets"):
            intent_terms.extend(json_list(clinical_intent.get(key)))
    lower = f"{user_text} {' '.join(intent_terms)}".lower()
    if re.search(
        r"\b(diabetes|diabetic|t1d|t2d|ckd|kidney|renal|egfr|uacr|albuminuria|hypertension|blood pressure|bp|lipid|ldl|statin|ascvd|cardiovascular|heart failure|hfpef|hfref|cgm|tir|a1c|hba1c|insulin|metformin|glyburide|sglt|glp|finerenone|obesity|masld|mash|nafld|nash|retinopathy|neuropathy|pad|foot|hospital|inpatient|pregnancy|gestational|gdm)\b",
        lower,
    ):
        return True
    return any(
        term in user_text
        for term in (
            "糖尿病",
            "血糖",
            "低血糖",
            "高血糖",
            "酮酸",
            "高滲透壓",
            "腎",
            "尿蛋白",
            "白蛋白尿",
            "洗腎",
            "透析",
            "血壓",
            "高血壓",
            "血脂",
            "膽固醇",
            "心血管",
            "心衰竭",
            "肥胖",
            "體重",
            "脂肪肝",
            "視網膜",
            "神經",
            "足部",
            "下肢",
            "住院",
            "懷孕",
            "慢性病",
            "照護",
            "指南",
            "證據",
            "證據等級",
            "建議等級",
            "建議",
        )
    )


def guideline_scope_no_answer_text() -> str:
    return (
        "這個問題不屬於目前已載入的糖尿病、CKD、高血壓、血脂、心血管風險、肥胖、脂肪肝或慢性病照護指南範圍；"
        "我先不延伸回答。"
    )


def selected_guideline_evidence_present(hits: list[KnowledgeHit]) -> bool:
    for hit in hits:
        haystack = (
            f"{getattr(hit, 'source', '')} {getattr(hit, 'source_label', '')} "
            f"{getattr(hit, 'title', '')} {getattr(hit, 'section', '')} "
            f"{getattr(hit, 'chunk_type', '')} {' '.join(getattr(hit, 'metadata', ()))} "
            f"{getattr(hit, 'excerpt', '')} {getattr(hit, 'parent_excerpt', '')[:600]}"
        ).lower()
        if re.search(r"\b(reference|references|acknowledg)\b", haystack) and not re.search(
            r"\b(recommendation|treatment|goal|target|diagnosis|screening|table|risk|therapy|management)\b",
            haystack,
        ):
            continue
        if re.search(r"\b(ada standards|kdigo|dc26s\d+|recommendation|practice point|table|section map|treatment|goal|target|diagnosis|screening|management)\b", haystack):
            return True
    return False


def answerable_with_available_guideline_evidence(
    user_text: str,
    hits: list[KnowledgeHit],
    clinical_intent: dict[str, Any] | None = None,
) -> bool:
    return guideline_scope_question(user_text, clinical_intent) and selected_guideline_evidence_present(hits)


def select_guideline_hits(
    api_key: str,
    user_text: str,
    candidates: list[KnowledgeHit],
    clinical_intent: dict[str, Any] | None = None,
) -> tuple[list[KnowledgeHit], bool, str]:
    if not candidates:
        return [], False, "沒有候選內容。"
    if not LINE_LLM_RERANK_ENABLED or not api_key:
        return candidates[:LINE_LLM_RERANK_TOP_K], True, "LLM reranker disabled; using local ranking."

    system_text = (
        "你是醫療指南檢索 reranker，不是回答者。"
        "你只能根據候選指南內容判斷哪些內容最能回答使用者問題。"
        "不要提供醫療建議，不要使用模型內建知識，不要補充候選內容以外的內容。"
        "你會收到 clinical intent JSON；請根據 required_facets 與 answer_strategy 判斷內容是否足夠，而不是只看候選內容是否逐字命中使用者原句。"
        "請特別檢查問題中的所有核心概念是否都有內容支持，例如藥物類別、疾病階段、eGFR 門檻、禁忌或安全限制。"
        "優先選擇 recommendation、treatment、selection、screening、diagnosis、table_row、含 eGFR/threshold/contraindication/avoid/dose 的內容。"
        "若 CKD/eGFR/albuminuria/UACR/finerenone/腎臟問題有 KDIGO 候選，請優先檢查並保留 KDIGO，因為腎臟病分期、eGFR、albuminuria 與腎臟保護治療通常以 KDIGO 較完整；再搭配 ADA 的糖尿病用藥與整體照護內容。若內容不足以完整回答，answerable 必須是 false。"
        "若使用者問洗腎/透析時血糖控制目標，但候選內容顯示沒有單一固定數字、需個別化、A1C 在 advanced CKD 較不可靠，並提供 CGM/BGM 或替代指標內容，這種情況可判定 answerable=true，用來回答「指南沒有固定單一目標，應個別化」。"
        "若使用者問特定 eGFR 數值下的用藥或合併用藥，而候選內容提供 eGFR 起始/使用門檻（例如 ≥20、≥25、≥30）或 CKD glucose-lowering therapy 建議，這可以回答「哪些藥物在此數值下不符合起始條件、哪些需依指南條件評估」，answerable 可為 true；不要因為內容沒有逐字寫出該 exact eGFR 數字就判 false。"
        "只輸出 JSON，格式：{\"selected_ids\":[1,2,3],\"answerable\":true,\"coverage_gaps\":[\"...\"]}。"
    )
    prompt = (
        f"使用者問題：{user_text}\n\n"
        f"{clinical_intent_prompt(clinical_intent) or '臨床問題理解：無'}\n\n"
        f"{knowledge_candidates_prompt(candidates)}\n\n"
        f"請選出最多 {LINE_LLM_RERANK_TOP_K} 個最能回答問題的候選 id，並判斷 evidence coverage 是否足夠。"
    )
    try:
        raw = call_llm(
            api_key,
            system_text,
            prompt,
            max_output_tokens=420,
            temperature=0.05,
            timeout=min(GEMINI_TIMEOUT, 12),
        )
    except Exception as exc:
        print(f"{LLM_PROVIDER} rerank failed: {type(exc).__name__}: {exc}")
        return candidates[:LINE_LLM_RERANK_TOP_K], True, "Reranker failed; using local ranking."

    data = extract_json_object(raw)
    selected_ids = data.get("selected_ids")
    if not isinstance(selected_ids, list):
        selected_ids = []

    selected: list[KnowledgeHit] = []
    seen: set[int] = set()
    for raw_id in selected_ids:
        try:
            candidate_index = int(raw_id) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= candidate_index < len(candidates) and candidate_index not in seen:
            seen.add(candidate_index)
            selected.append(candidates[candidate_index])
        if len(selected) >= LINE_LLM_RERANK_TOP_K:
            break

    if not selected:
        selected = candidates[:LINE_LLM_RERANK_TOP_K]

    answerable_value = data.get("answerable")
    if isinstance(answerable_value, bool):
        answerable = answerable_value
    elif answerable_value is None:
        answerable = True
    else:
        answerable = str(answerable_value).strip().lower() not in {"false", "no", "0"}
    gaps = data.get("coverage_gaps")
    if isinstance(gaps, list):
        coverage_gaps = "；".join(str(gap) for gap in gaps if str(gap).strip())
    else:
        coverage_gaps = str(gaps or "").strip()
    local_answerable, local_gap = local_evidence_coverage(user_text, selected, clinical_intent)
    if not local_answerable:
        all_candidates_answerable, all_candidates_gap = local_evidence_coverage(user_text, candidates, clinical_intent)
        if all_candidates_answerable:
            selected = candidates[:LINE_LLM_RERANK_TOP_K]
            local_answerable = True
            coverage_gaps = (coverage_gaps + "；" if coverage_gaps else "") + "LLM reranker 選片漏掉部分必要面向，已改用本地 coverage-aware 候選。"
        else:
            coverage_gaps = (coverage_gaps + "；" if coverage_gaps else "") + (local_gap or all_candidates_gap)
    if comparative_threshold_question(user_text) and local_answerable and not answerable:
        answerable = True
        coverage_gaps = (
            coverage_gaps + "；" if coverage_gaps else ""
        ) + "候選內容提供 eGFR 門檻，可用來回答此數值下的用藥限制與可評估方向。"
    if not local_answerable and answerable_with_available_guideline_evidence(user_text, selected, clinical_intent):
        local_answerable = True
        answerable = True
        coverage_gaps = (
            coverage_gaps + "；" if coverage_gaps else ""
        ) + "本題屬於已載入指南涵蓋的慢性病照護範圍；雖然部分 facet 未完全命中，仍可根據已選指南內容回答可支持的部分並標示限制。"
    if not local_answerable:
        answerable = False
    return selected, answerable, coverage_gaps


def build_evidence_review(
    api_key: str,
    user_text: str,
    knowledge_text: str,
    clinical_intent: dict[str, Any] | None = None,
) -> str:
    if not LINE_EVIDENCE_REVIEW_ENABLED or not api_key:
        return ""

    system_text = (
        "你是糖尿病指南證據整理助手，不是最終回答者。"
        "只能根據提供的已載入指南內容、LLM Wiki 知識頁與結構化證據卡整理，不可使用模型內建知識、未載入指南、新聞或推測補完。"
        "你會收到 clinical intent JSON；請用 answer_strategy 組織證據，但不可把 clinical intent 當成醫療證據。"
        "LLM Wiki page、compiled_concept、compiled_cross_guideline 都是可用的已載入知識內容；若其中已列出門檻、風險工具或治療原則，不可說沒有相關資訊。"
        "若骨骼健康問題的內容包含 T-score、FRAX、DXA/BMD、TZD、sulfonylurea、低血糖或跌倒風險，必須整理為可回答重點。"
        "請用繁體中文輸出精簡整理："
        "1. 可直接回答使用者問題的指南重點；"
        "2. 已載入內容中明確的門檻、限制、藥物例外或安全提醒；"
        "3. 使用者問題中的每個核心概念是否都有已載入內容支持；"
        "4. 若指南沒有給單一固定數字，但有說明應個別化或 A1C 不可靠，也要明確整理成可回答重點；"
        "5. 若使用者問特定 eGFR 數值下的用藥，而已載入內容提供藥物的 eGFR 起始/使用門檻，請用比較方式整理哪些不符合門檻、哪些可依指南條件評估；"
        "6. 已載入內容不足或不能回答的地方。"
        "最後一行必須寫 ANSWERABLE: yes 或 ANSWERABLE: no。"
    )
    prompt = (
        f"使用者問題：{user_text}\n\n"
        f"{clinical_intent_prompt(clinical_intent) or '臨床問題理解：無'}\n\n"
        f"{knowledge_text}\n\n"
        "請先整理證據，不要寫給病友看的最終答案。"
    )
    try:
        return call_llm(
            api_key,
            system_text,
            prompt,
            max_output_tokens=520,
            temperature=0.1,
            timeout=min(GEMINI_TIMEOUT, 12),
        ).strip()
    except Exception as exc:
        print(f"{LLM_PROVIDER} evidence review failed: {type(exc).__name__}: {exc}")
        return ""


def build_long_context_verification(
    api_key: str,
    user_text: str,
    hits: list[KnowledgeHit],
    clinical_intent: dict[str, Any] | None = None,
    evidence_review: str = "",
) -> str:
    if not LINE_LONG_CONTEXT_VERIFICATION_ENABLED or not api_key or not hits:
        return ""

    system_text = (
        "你是臨床指南長上下文驗證器，不是最終回答者。"
        "你只能根據提供的指南內容、父層章節上下文與結構化標籤檢查 evidence coverage。"
        "不要使用模型內建知識、不要補充未提供的指南內容。"
        "請檢查：1. 是否有回答使用者核心問題的直接依據；"
        "2. 是否需要補足其他章節、表格、footnote 或特殊族群；"
        "3. recommendation、rationale、table 或 safety warning 是否互相矛盾。"
        "輸出繁體中文，最多 6 行。最後一行必須是 VERIFIED: yes 或 VERIFIED: no。"
    )
    prompt = (
        f"使用者問題：{user_text}\n\n"
        f"{clinical_intent_prompt(clinical_intent) or '臨床問題理解：無'}\n\n"
        f"{knowledge_prompt_from_hits(hits)}\n\n"
        f"初步證據整理：\n{evidence_review or '無'}\n\n"
        "請做長上下文二次確認。"
    )
    try:
        return call_llm(
            api_key,
            system_text,
            prompt,
            max_output_tokens=420,
            temperature=0.05,
            timeout=min(GEMINI_TIMEOUT, 12),
        ).strip()
    except Exception as exc:
        print(f"{LLM_PROVIDER} long-context verification failed: {type(exc).__name__}: {exc}")
        return ""


def long_context_verification_prompt(verification: str) -> str:
    if not verification:
        return ""
    return (
        "\n\n長上下文二次確認：\n"
        "以下驗證只根據本輪內容與父層章節上下文；若它指出缺口，最終回答不可補完缺口。\n"
        f"{verification}"
    )


def long_context_says_unverified(verification: str) -> bool:
    return bool(re.search(r"VERIFIED\s*:\s*no\b", verification, flags=re.I))


def build_parallel_evidence_checks(
    api_key: str,
    user_text: str,
    selected_hits: list[KnowledgeHit],
    clinical_intent: dict[str, Any] | None,
    knowledge_text: str,
) -> tuple[str, str]:
    if (
        not LINE_PARALLEL_VERIFICATION_ENABLED
        or not LINE_EVIDENCE_REVIEW_ENABLED
        or not LINE_LONG_CONTEXT_VERIFICATION_ENABLED
        or not api_key
        or not selected_hits
    ):
        evidence_review = build_evidence_review(api_key, user_text, knowledge_text, clinical_intent)
        long_context_verification = build_long_context_verification(
            api_key,
            user_text,
            selected_hits,
            clinical_intent,
            evidence_review,
        )
        return evidence_review, long_context_verification

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        evidence_future = executor.submit(
            build_evidence_review,
            api_key,
            user_text,
            knowledge_text,
            clinical_intent,
        )
        verification_future = executor.submit(
            build_long_context_verification,
            api_key,
            user_text,
            selected_hits,
            clinical_intent,
            "",
        )
        evidence_review = evidence_future.result()
        long_context_verification = verification_future.result()
    return evidence_review, long_context_verification


def evidence_review_prompt(review: str) -> str:
    if not review:
        return ""
    return (
        "\n\n檢索後證據整理：\n"
        "以下整理只來自本輪已載入指南內容、LLM Wiki 知識頁與結構化證據卡，用來幫助最終回答完整且不漏重點；"
        "若它和原始指南內容衝突，必須以原始指南內容為準。不要在給使用者的回答中使用內部檢索用語。\n"
        f"{review}"
    )


def rerank_coverage_prompt(coverage_gaps: str) -> str:
    if not coverage_gaps:
        return ""
    return (
        "\n\nReranker coverage check：\n"
        "以下是檢索 reranker 對候選內容覆蓋度的判斷。若提到缺口，最終回答不可補完缺口，只能說明目前已載入指南內容不足。\n"
        f"{coverage_gaps}"
    )


def evidence_review_says_unanswerable(review: str) -> bool:
    return bool(re.search(r"ANSWERABLE\s*:\s*no\b", review, flags=re.I))


def remove_trailing_question(text: str) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text.strip()) if part.strip()]
    if not paragraphs:
        return text.strip()

    last = paragraphs[-1]
    if not re.search(r"[？?]\s*$", last):
        return text.strip()

    question_starters = (
        "請問",
        "想請問",
        "可否",
        "是否",
        "方便",
        "能否",
        "您目前",
        "你目前",
        "如果方便",
        "若方便",
        "May I",
        "Could you",
        "Can you",
        "Would you",
        "Do you",
        "Are you",
        "What",
        "When",
        "Where",
        "Which",
        "How",
    )

    sentence_parts = re.split(r"(?<=[。.!！])\s*", last)
    trailing_sentence = sentence_parts[-1].strip() if sentence_parts else last
    if trailing_sentence.startswith(question_starters) or len(trailing_sentence) <= 120:
        if len(sentence_parts) > 1:
            sentence_parts.pop()
            paragraphs[-1] = "".join(sentence_parts).strip()
            return "\n\n".join(part for part in paragraphs if part).strip()
        paragraphs.pop()
        return "\n\n".join(paragraphs).strip()
    return text.strip()


def serialize_debug_hit(hit: KnowledgeHit, index: int) -> dict[str, Any]:
    facets = sorted(hit_facets(hit))
    return {
        "id": index,
        "source": getattr(hit, "source", ""),
        "source_label": getattr(hit, "source_label", ""),
        "title": getattr(hit, "title", ""),
        "section": getattr(hit, "section", ""),
        "chunk_type": getattr(hit, "chunk_type", ""),
        "score": round(float(getattr(hit, "score", 0.0)), 3),
        "metadata": list(getattr(hit, "metadata", ())[:24]),
        "facets": facets,
        "has_parent_excerpt": bool(getattr(hit, "parent_excerpt", "")),
        "excerpt": re.sub(r"\s+", " ", str(getattr(hit, "excerpt", ""))).strip()[:420],
        "parent_excerpt": re.sub(r"\s+", " ", str(getattr(hit, "parent_excerpt", ""))).strip()[:420],
    }


def debug_search_trace(user_text: str, use_llm: bool = False) -> dict[str, Any]:
    trace_started_at = time_monotonic()
    api_key = active_api_key() if use_llm else ""
    recent_context = ""
    clinical_intent = build_clinical_intent(api_key, user_text, recent_context) if use_llm else fallback_clinical_intent(user_text)
    retrieval_query = build_retrieval_query(api_key, user_text, recent_context, clinical_intent) if use_llm else " ".join(
        part for part in [user_text, clinical_intent_text(clinical_intent)] if part
    ).strip()
    variants = query_variant_specs(retrieval_query)
    retrieval_trace = search_knowledge_candidates_with_trace(retrieval_query)
    candidates = list(retrieval_trace.get("hits", []))
    selected_hits, answerable, coverage_gaps = select_guideline_hits(api_key, user_text, candidates, clinical_intent)
    selected_hits, recursive_note = append_recursive_coverage_hits(user_text, selected_hits, clinical_intent)
    selected_hits, whole_section_note = append_whole_section_context_hits(user_text, selected_hits, clinical_intent)
    local_answerable, local_gap = local_evidence_coverage(user_text, selected_hits, clinical_intent)
    covered_facets: set[str] = set()
    for hit in selected_hits:
        covered_facets.update(hit_facets(hit))
    required = set(required_facets(user_text))
    required.update(json_list((clinical_intent or {}).get("required_facets")))
    guideline_scope = guideline_scope_question(user_text, clinical_intent)
    return {
        "query": user_text,
        "use_llm": use_llm,
        "guideline_scope": guideline_scope,
        "retrieval_mode": retrieval_trace.get("retrieval_mode", "fallback_raw"),
        "elapsed_ms": round((time_monotonic() - trace_started_at) * 1000, 2),
        "retrieval_elapsed_ms": retrieval_trace.get("elapsed_ms", 0.0),
        "fast_path_enabled": retrieval_trace.get("fast_path_enabled", False),
        "fast_hit_count": retrieval_trace.get("fast_hit_count", 0),
        "fallback_reason": retrieval_trace.get("fallback_reason", ""),
        "retrieval_query": retrieval_query,
        "clinical_intent": clinical_intent,
        "query_variants": [
            {
                "label": getattr(variant, "label", ""),
                "weight": getattr(variant, "weight", 0.0),
                "text": getattr(variant, "text", ""),
            }
            for variant in variants
        ],
        "required_facets": sorted(required),
        "covered_facets": sorted(covered_facets),
        "missing_facets": sorted(required - covered_facets),
        "candidate_count": len(candidates),
        "candidates": [
            serialize_debug_hit(hit, index)
            for index, hit in enumerate(candidates[:LINE_DEBUG_SEARCH_MAX_HITS], start=1)
        ],
        "selected_count": len(selected_hits),
        "selected_hits": [
            serialize_debug_hit(hit, index)
            for index, hit in enumerate(selected_hits[: max(LINE_DEBUG_SEARCH_MAX_HITS, LINE_LLM_RERANK_TOP_K)], start=1)
        ],
        "rerank_answerable": answerable,
        "local_answerable": local_answerable,
        "coverage_gaps": coverage_gaps,
        "local_gap": local_gap,
        "recursive_note": recursive_note,
        "whole_section_note": whole_section_note,
        "knowledge": cached_knowledge_status(),
    }


def llm_answer(user_text: str, line_user_id: str = "") -> str:
    api_key = active_api_key()
    if not api_key:
        return f"目前快速問答服務尚未設定 {LLM_PROVIDER} API key。若你有血糖不舒服、低血糖症狀或血糖持續很高，請先聯絡醫療團隊。"

    recent_context = conversation_prompt(line_user_id)
    clinical_intent = build_clinical_intent(api_key, user_text, recent_context)
    candidates: list[KnowledgeHit] = []
    selected_hits: list[KnowledgeHit] = []
    scope_text = (
        f"{user_text}\n{recent_context}"
        if contextual_guideline_followup(user_text, recent_context)
        else user_text
    )
    if not guideline_scope_question(scope_text, clinical_intent):
        return guideline_scope_no_answer_text()
    retrieval_query = build_retrieval_query(api_key, user_text, recent_context, clinical_intent)
    retrieval_trace = search_knowledge_candidates_with_trace(retrieval_query)
    candidates = list(retrieval_trace.get("hits", []))
    if not candidates:
        write_retrieval_failure(
            user_text,
            clinical_intent,
            candidates,
            [],
            retrieval_trace,
            "no_candidates",
            "No candidates returned after wiki fast path and fallback retrieval.",
        )
        final_answer = static_evidence_gap_response(
            "no_candidates",
            False,
            "No candidates returned after wiki fast path and fallback retrieval.",
        )
        schedule_answer_improvement(user_text, final_answer, clinical_intent, [], retrieval_trace)
        return final_answer

    selected_hits, rerank_answerable, coverage_gaps = select_guideline_hits(api_key, user_text, candidates, clinical_intent)
    selected_hits, recursive_note = append_recursive_coverage_hits(user_text, selected_hits, clinical_intent)
    if recursive_note:
        coverage_gaps = (coverage_gaps + "；" if coverage_gaps else "") + recursive_note
    if selected_hits:
        recursive_answerable, recursive_gap = local_evidence_coverage(user_text, selected_hits, clinical_intent)
        if recursive_answerable:
            rerank_answerable = True
        elif answerable_with_available_guideline_evidence(user_text, selected_hits, clinical_intent):
            rerank_answerable = True
            coverage_gaps = (
                coverage_gaps + "；" if coverage_gaps else ""
            ) + "本題屬於已載入指南涵蓋的慢性病照護範圍；以下回答會限制在目前檢索到的指南內容。"
        elif recursive_gap:
            coverage_gaps = (coverage_gaps + "；" if coverage_gaps else "") + recursive_gap
        selected_hits, whole_section_note = append_whole_section_context_hits(user_text, selected_hits, clinical_intent)
        if whole_section_note:
            coverage_gaps = (coverage_gaps + "；" if coverage_gaps else "") + whole_section_note
        whole_answerable, whole_gap = local_evidence_coverage(user_text, selected_hits, clinical_intent)
        if whole_answerable:
            rerank_answerable = True
        elif answerable_with_available_guideline_evidence(user_text, selected_hits, clinical_intent):
            rerank_answerable = True
        elif whole_gap:
            coverage_gaps = (coverage_gaps + "；" if coverage_gaps else "") + whole_gap
    if not selected_hits or not rerank_answerable:
        write_retrieval_failure(
            user_text,
            clinical_intent,
            candidates,
            selected_hits,
            retrieval_trace,
            "insufficient_selected_evidence",
            coverage_gaps,
        )
        final_answer = static_evidence_gap_response("insufficient_selected_evidence", bool(selected_hits or candidates), coverage_gaps)
        schedule_answer_improvement(user_text, final_answer, clinical_intent, selected_hits or candidates[:5], retrieval_trace)
        return final_answer

    knowledge_text = knowledge_prompt_from_hits(selected_hits)
    evidence_review, long_context_verification = build_parallel_evidence_checks(
        api_key,
        user_text,
        selected_hits,
        clinical_intent,
        knowledge_text,
    )
    if evidence_review_says_unanswerable(evidence_review):
        locally_answerable, _local_gap = local_evidence_coverage(user_text, selected_hits, clinical_intent)
        if not (
            (comparative_threshold_question(user_text) and locally_answerable)
            or answerable_with_available_guideline_evidence(user_text, selected_hits, clinical_intent)
        ):
            write_retrieval_failure(
                user_text,
                clinical_intent,
                candidates,
                selected_hits,
                retrieval_trace,
                "evidence_review_unanswerable",
                evidence_review,
            )
            final_answer = static_evidence_gap_response("evidence_review_unanswerable", bool(selected_hits or candidates), evidence_review)
            schedule_answer_improvement(user_text, final_answer, clinical_intent, selected_hits, retrieval_trace)
            return final_answer
        evidence_review = (
            evidence_review
            + "\n\n本地 coverage override：此題屬於已載入指南涵蓋的慢性病照護範圍；"
            "請只回答已載入指南內容能支持的部分，缺口要明確說明，不要補充已載入內容以外的資訊，也不要給個人化劑量。"
        )
    if long_context_says_unverified(long_context_verification):
        locally_answerable, _local_gap = local_evidence_coverage(user_text, selected_hits, clinical_intent)
        if not (
            (comparative_threshold_question(user_text) and locally_answerable)
            or answerable_with_available_guideline_evidence(user_text, selected_hits, clinical_intent)
        ):
            write_retrieval_failure(
                user_text,
                clinical_intent,
                candidates,
                selected_hits,
                retrieval_trace,
                "verification_unverified",
                long_context_verification,
            )
            final_answer = static_evidence_gap_response("verification_unverified", bool(selected_hits or candidates), long_context_verification)
            schedule_answer_improvement(user_text, final_answer, clinical_intent, selected_hits, retrieval_trace)
            return final_answer
    system_text = (
        SYSTEM_PROMPT
        + memory_prompt(line_user_id)
        + recent_context
        + clinical_intent_prompt(clinical_intent)
        + knowledge_text
        + rerank_coverage_prompt(coverage_gaps)
        + evidence_review_prompt(evidence_review)
        + long_context_verification_prompt(long_context_verification)
    )
    try:
        answer = call_llm(
            api_key,
            system_text,
            f"病友問題：{user_text}\n\n請先完整檢視本輪已載入指南內容、知識庫內容與證據整理，再用繁體中文回答。不要提出追問，也不要使用內部檢索術語。",
            max_output_tokens=820,
            temperature=0.35,
            timeout=GEMINI_TIMEOUT,
        )
        if answer:
            final_answer = remove_trailing_question(answer)[:4900]
            write_query_candidate(user_text, final_answer, clinical_intent, selected_hits, retrieval_trace)
            schedule_answer_improvement(user_text, final_answer, clinical_intent, selected_hits, retrieval_trace)
            return final_answer
        final_answer = build_limited_guideline_fallback_answer(
            api_key,
            user_text,
            clinical_intent,
            candidates,
            selected_hits,
            retrieval_trace,
            "answer_generation_empty",
            "Answer generator returned an empty response.",
            evidence_review,
            long_context_verification,
        )
        schedule_answer_improvement(user_text, final_answer, clinical_intent, selected_hits, retrieval_trace)
        return final_answer
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        print(f"{LLM_PROVIDER} HTTP {exc.code}: {detail}")
    except Exception as exc:
        print(f"{LLM_PROVIDER} request failed: {type(exc).__name__}: {exc}")
    final_answer = static_evidence_gap_response(
        "answer_generation_error",
        bool(selected_hits or candidates),
        "Final answer generation failed after retrieval.",
    )
    schedule_answer_improvement(user_text, final_answer, clinical_intent, selected_hits, retrieval_trace)
    return final_answer


async def handle_text_event(event: dict[str, Any]) -> None:
    message = event.get("message", {})
    user_text = (message.get("text") or "").strip()
    target = source_target(event)
    session_key = source_session_key(event)
    reply_token = (event.get("replyToken") or "").strip()
    if not user_text or not target or not session_key:
        return

    loop = asyncio.get_running_loop()
    answer = await loop.run_in_executor(None, answer_for_session, session_key, user_text)
    if reply_token:
        ok, status = line_reply_text(reply_token, answer)
        print(f"LINE fast QA reply status: {status}")
        if ok:
            return
    ok, status = line_push_text(target, answer)
    print(f"LINE fast QA fallback push status: {status}")
    if not ok:
        print(f"Failed to push LINE fast QA answer for target={target[:8]}...")


@app.get("/")
def health() -> dict[str, Any]:
    current_knowledge_status = cached_knowledge_status()
    return {
        "ok": True,
        "service": "line-lifebot-qa",
        "app_version": APP_VERSION,
        "llm_provider": LLM_PROVIDER,
        "model": active_model(),
        "llm_configured": llm_configured(),
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()),
        "deepseek_configured": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
        "deepseek_thinking_enabled": DEEPSEEK_THINKING_ENABLED if LLM_PROVIDER == "deepseek" else False,
        "line_configured": bool(os.getenv("LINE_CHANNEL_SECRET", "").strip() and os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()),
        "memory_enabled": LINE_MEMORY_ENABLED,
        "memory_backend": memory_backend(),
        "features": {
            "english_name_memory": True,
            "chinese_name_memory": True,
            "trailing_question_removal": True,
            "short_term_context": LINE_CONTEXT_ENABLED,
            "session_scoped_context": True,
            "guideline_strict_grounding": True,
            "guideline_query_planning": LINE_QUERY_PLANNING_ENABLED,
            "clinical_intent_planning": LINE_QUERY_PLANNING_ENABLED,
            "guideline_evidence_review": LINE_EVIDENCE_REVIEW_ENABLED,
            "all_mounted_guideline_sources": True,
            "ada_only_sources": False,
            "multi_guideline_sources": True,
            "source_aware_reranking": True,
            "source_balanced_retrieval": True,
            "section_aware_retrieval": True,
            "chapter_section_index": True,
            "recommendation_aware_retrieval": True,
            "table_aware_retrieval": True,
            "multi_query_retrieval": True,
            "intent_query_variants": True,
            "clinical_concept_routing": True,
            "hermes_clinical_search_brain": True,
            "metadata_indexing": True,
            "automatic_ontology_extraction": True,
            "dense_embedding_index": True,
            "coverage_aware_retrieval": True,
            "mmr_style_diversity": True,
            "local_coverage_answerability": True,
            "comparative_threshold_answering": True,
            "threshold_review_override": True,
            "deepseek_provider": True,
            "llm_reranker": LINE_LLM_RERANK_ENABLED,
            "coverage_answerability_check": True,
            "parent_child_table_context": True,
            "parent_child_section_retrieval": True,
            "structured_metadata_extraction": True,
            "recursive_coverage_retrieval": LINE_RECURSIVE_COVERAGE_ENABLED,
            "whole_section_context": LINE_WHOLE_SECTION_CONTEXT_ENABLED,
            "local_hashed_vector_index": True,
            "inverted_index_retrieval": True,
            "compiled_guideline_artifacts": bool(current_knowledge_status.get("compiled_knowledge_enabled")),
            "claim_registry_retrieval": True,
            "synthetic_qa_self_improvement": True,
            "source_freshness_watch": True,
            "debug_wiki_search_ui": True,
            "llm_wiki_first": bool(current_knowledge_status.get("llm_wiki_enabled"))
            and bool(current_knowledge_status.get("llm_wiki_first_enabled")),
            "llm_wiki_fast_path": os.getenv("LINE_LLM_WIKI_FAST_PATH_ENABLED", "1").strip().lower()
            not in {"0", "false", "no", "off"},
            "llm_wiki_files": current_knowledge_status.get("llm_wiki_files", 0),
            "llm_wiki_self_heal": LINE_LLM_WIKI_SELF_HEAL_ENABLED,
            "llm_wiki_self_heal_status": public_wiki_self_heal_status(),
            "knowledge_preload": LINE_KNOWLEDGE_PRELOAD_ENABLED,
            "fast_health_status": LINE_HEALTH_FAST_ENABLED,
            "long_context_verification": LINE_LONG_CONTEXT_VERIFICATION_ENABLED,
            "parallel_evidence_verification": LINE_PARALLEL_VERIFICATION_ENABLED,
            "debug_search_endpoint": LINE_DEBUG_SEARCH_ENABLED,
            "answer_improvement_writeback": LINE_ANSWER_IMPROVEMENT_ENABLED,
            "answer_improvement_provider": LINE_ANSWER_IMPROVEMENT_PROVIDER,
            "answer_improvement_configured": bool(answer_improvement_api_key()),
            "guideline_strict_grounding_current": True,
            "guideline_query_planning_current": LINE_QUERY_PLANNING_ENABLED,
            "guideline_evidence_review_current": LINE_EVIDENCE_REVIEW_ENABLED,
        },
        "context_enabled": LINE_CONTEXT_ENABLED,
        "context_max_messages": LINE_CONTEXT_MAX_MESSAGES,
        "context_ttl_seconds": LINE_CONTEXT_TTL_SECONDS,
        "session_scope": LINE_SESSION_SCOPE,
        "knowledge": current_knowledge_status,
    }


@app.get("/debug/search")
def debug_search(q: str = "", llm: bool = False, x_debug_token: str = Header(default="")) -> dict[str, Any]:
    if not LINE_DEBUG_SEARCH_ENABLED:
        raise HTTPException(status_code=404, detail="debug search disabled")
    expected_token = os.getenv("LINE_DEBUG_TOKEN", "").strip()
    if expected_token and not hmac.compare_digest(x_debug_token, expected_token):
        raise HTTPException(status_code=403, detail="invalid debug token")
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="missing q")
    trace = debug_search_trace(query, use_llm=llm)
    print(
        "debug search "
        f"mode={trace.get('retrieval_mode')} "
        f"elapsed_ms={trace.get('elapsed_ms')} "
        f"retrieval_elapsed_ms={trace.get('retrieval_elapsed_ms')} "
        f"candidates={trace.get('candidate_count')} "
        f"query={query[:120]!r}"
    )
    return trace


@app.get("/debug/wiki/search")
def debug_wiki_search(q: str = "", x_debug_token: str = Header(default="")) -> dict[str, Any]:
    if not LINE_DEBUG_SEARCH_ENABLED:
        raise HTTPException(status_code=404, detail="debug search disabled")
    expected_token = os.getenv("LINE_DEBUG_TOKEN", "").strip()
    if expected_token and not hmac.compare_digest(x_debug_token, expected_token):
        raise HTTPException(status_code=403, detail="invalid debug token")
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="missing q")
    trace = debug_search_trace(query, use_llm=False)
    return {
        "ok": True,
        "app_version": APP_VERSION,
        "query": query,
        "retrieval_mode": trace.get("retrieval_mode"),
        "elapsed_ms": trace.get("elapsed_ms"),
        "candidate_count": trace.get("candidate_count"),
        "candidates": trace.get("candidates", [])[:LINE_DEBUG_SEARCH_MAX_HITS],
    }


@app.get("/debug/wiki", response_class=HTMLResponse)
def debug_wiki_page(q: str = "", x_debug_token: str = Header(default="")) -> str:
    if not LINE_DEBUG_SEARCH_ENABLED:
        raise HTTPException(status_code=404, detail="debug search disabled")
    expected_token = os.getenv("LINE_DEBUG_TOKEN", "").strip()
    if expected_token and not hmac.compare_digest(x_debug_token, expected_token):
        raise HTTPException(status_code=403, detail="invalid debug token")
    query = q.strip()
    rows = ""
    meta = ""
    if query:
        trace = debug_search_trace(query, use_llm=False)
        meta = (
            f"<p><strong>mode</strong>: {html.escape(str(trace.get('retrieval_mode')))} "
            f"<strong>elapsed_ms</strong>: {html.escape(str(trace.get('elapsed_ms')))} "
            f"<strong>candidates</strong>: {html.escape(str(trace.get('candidate_count')))}</p>"
        )
        for hit in trace.get("candidates", [])[:LINE_DEBUG_SEARCH_MAX_HITS]:
            rows += (
                "<tr>"
                f"<td>{html.escape(str(hit.get('source', '')))}</td>"
                f"<td>{html.escape(str(hit.get('title', '')))}</td>"
                f"<td>{html.escape(str(hit.get('section', '')))}</td>"
                f"<td>{html.escape(str(hit.get('chunk_type', '')))}</td>"
                f"<td>{html.escape(str(hit.get('excerpt', ''))[:900])}</td>"
                "</tr>"
            )
    value = html.escape(query)
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LifeBot Wiki Search</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; line-height: 1.5; }}
    form {{ display: flex; gap: 8px; margin-bottom: 16px; }}
    input {{ flex: 1; padding: 10px; font-size: 16px; }}
    button {{ padding: 10px 14px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
    th {{ background: #f4f4f4; text-align: left; }}
    td:nth-child(5) {{ min-width: 360px; }}
  </style>
</head>
<body>
  <h1>LifeBot Wiki Search</h1>
  <form method="get" action="/debug/wiki">
    <input name="q" value="{value}" placeholder="例如：哪些證據等級較低？">
    <button type="submit">Search</button>
  </form>
  {meta}
  <table>
    <thead><tr><th>Source</th><th>Title</th><th>Section</th><th>Type</th><th>Excerpt</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>"""


@app.post("/debug/knowledge/reload")
def debug_reload_knowledge(x_debug_token: str = Header(default="")) -> dict[str, Any]:
    if not LINE_DEBUG_SEARCH_ENABLED:
        raise HTTPException(status_code=404, detail="debug search disabled")
    expected_token = os.getenv("LINE_DEBUG_TOKEN", "").strip()
    if expected_token and not hmac.compare_digest(x_debug_token, expected_token):
        raise HTTPException(status_code=403, detail="invalid debug token")
    self_heal_llm_wiki_if_needed()
    reset_knowledge_cache()
    status = cached_knowledge_status(force=True)
    return {
        "ok": True,
        "knowledge": status,
    }


@app.post("/line/webhook")
async def line_webhook(request: Request, x_line_signature: str = Header(default="")) -> dict[str, bool]:
    body = await request.body()
    verify_line_signature(body, x_line_signature)
    payload = json.loads(body.decode("utf-8"))
    for event in payload.get("events", []):
        if event.get("type") == "message" and event.get("message", {}).get("type") == "text":
            asyncio.create_task(handle_text_event(event))
    return {"ok": True}
