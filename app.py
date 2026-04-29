from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager
from pathlib import Path
import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException, Request


GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")
GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "20"))
LINE_TIMEOUT = int(os.getenv("LINE_TIMEOUT", "12"))
LINE_MEMORY_ENABLED = os.getenv("LINE_MEMORY_ENABLED", "1").strip() != "0"
LINE_MEMORY_DB = os.getenv("LINE_MEMORY_DB", "/tmp/line_lifebot_memory.sqlite3")
LINE_MEMORY_MAX_CHARS = int(os.getenv("LINE_MEMORY_MAX_CHARS", "1200"))

app = FastAPI(title="LifeBot Fast LINE QA")

_memory_ready = False
_memory_lock = threading.Lock()


SYSTEM_PROMPT = """你是 LifeBot 糖尿病衛教 LINE 機器人，請用繁體中文回答病友問題。

回答規則：
- 口吻溫和、清楚、像衛教師在 LINE 上簡短回覆。
- 不要使用 Markdown 格式，不要使用井字號、星號或程式碼區塊。
- 不要提供個人化診斷、處方、劑量調整、停藥建議，或替代醫師判斷。
- 回答以 2 到 4 個短段落為主，適合手機閱讀。
- 優先提供糖尿病自我照護、飲食、運動、用藥安全、血糖監測、併發症預防的衛教。
- 若問題涉及低血糖、高血糖急症、胸痛、意識不清、酮酸中毒疑慮、懷孕、兒童、腎功能、嚴重感染或傷口惡化，請提醒盡快聯絡醫療團隊或就醫。
- 若資訊不足，最後用一句話請病友補充，例如目前血糖、用藥、症狀、發生時間或飯前飯後。
- 不要編造最新研究、新聞或來源；若病友要求最新醫學期刊或新聞，請說明需要啟用搜尋流程，並先給一般衛教原則。
"""


def memory_database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip() or os.getenv("POSTGRES_URL", "").strip()


def memory_backend() -> str:
    url = memory_database_url()
    if urlparse(url).scheme in {"postgres", "postgresql"}:
        return "postgres"
    return "sqlite"


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
    if not LINE_MEMORY_ENABLED or _memory_ready:
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


def clean_memory_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" ，。,.！!？?")
    return value[:300]


def merge_profile_summary(existing: str | None, note: str | None) -> str | None:
    note = clean_memory_text(note or "")
    if not note:
        return existing
    existing = clean_memory_text(existing or "")
    if not existing:
        return note[:LINE_MEMORY_MAX_CHARS]
    if note in existing:
        return existing[:LINE_MEMORY_MAX_CHARS]
    return f"{existing}；{note}"[:LINE_MEMORY_MAX_CHARS]


def save_user_memory(line_user_id: str, display_name: str | None = None, profile_note: str | None = None) -> None:
    if not LINE_MEMORY_ENABLED or not line_user_id:
        return
    ensure_memory_db()
    current = fetch_user_memory(line_user_id) or {}
    display_name = clean_memory_text(display_name or current.get("display_name") or "") or None
    profile_summary = merge_profile_summary(current.get("profile_summary"), profile_note)
    with memory_connection() as conn:
        if memory_backend() == "postgres":
            conn.execute(
                """
                INSERT INTO line_user_memory (line_user_id, display_name, profile_summary, consent_memory, updated_at)
                VALUES (%s, %s, %s, TRUE, CURRENT_TIMESTAMP)
                ON CONFLICT (line_user_id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    profile_summary = EXCLUDED.profile_summary,
                    consent_memory = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (line_user_id, display_name, profile_summary),
            )
        else:
            conn.execute(
                """
                INSERT INTO line_user_memory (line_user_id, display_name, profile_summary, consent_memory, updated_at)
                VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(line_user_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    profile_summary = excluded.profile_summary,
                    consent_memory = 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (line_user_id, display_name, profile_summary),
            )


def memory_prompt(line_user_id: str) -> str:
    memory = fetch_user_memory(line_user_id)
    if not memory or not memory.get("consent_memory"):
        return ""
    parts = []
    if memory.get("display_name"):
        parts.append(f"稱呼：{memory['display_name']}")
    if memory.get("profile_summary"):
        parts.append(f"偏好或基本資料：{memory['profile_summary']}")
    if not parts:
        return ""
    return "\n\n使用者已明確同意保存的基本記憶：\n" + "\n".join(f"- {part}" for part in parts) + (
        "\n回答時可以自然運用這些資料，例如稱呼或調整衛教方向；不要主動揭露 LINE userId，也不要假裝知道未保存的個資。"
    )


def is_sensitive_memory(text: str) -> bool:
    sensitive_terms = [
        "身分證",
        "電話",
        "手機",
        "地址",
        "生日",
        "病歷",
        "診斷",
        "用藥",
        "藥名",
        "劑量",
        "胰島素",
        "血糖",
        "糖化血色素",
        "hba1c",
        "腎功能",
        "懷孕",
        "過敏",
    ]
    lowered = text.lower()
    return any(term in lowered for term in sensitive_terms)


def extract_display_name(text: str) -> str | None:
    patterns = [
        r"(?:請|幫我)?記住(?:我)?(?:叫|名字是|姓名是)\s*([^\s，。,.！!？?]{1,20})",
        r"(?:以後|下次)(?:請)?(?:叫我|稱呼我)\s*([^\s，。,.！!？?]{1,20})",
        r"你可以叫我\s*([^\s，。,.！!？?]{1,20})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return clean_memory_text(match.group(1))
    return None


def extract_profile_note(text: str) -> str | None:
    note = re.sub(r"^(請|幫我)?記住", "", text).strip()
    note = re.sub(r"^(一下|這件事|：|:)", "", note).strip()
    if not note or extract_display_name(text):
        return None
    return f"使用者希望我記住：{clean_memory_text(note)}"


def memory_command_response(line_user_id: str, user_text: str) -> str | None:
    if not LINE_MEMORY_ENABLED:
        return None

    if re.search(r"(忘記|刪除|清除).*(我的)?(資料|記憶)|不要再記住我", user_text):
        delete_user_memory(line_user_id)
        return "我已經刪除目前為你保存的記憶資料。之後如果你希望我再記住稱呼或偏好，可以再明確告訴我。"

    if re.search(r"(你記得我什麼|我有哪些資料被記住|查詢.*(資料|記憶)|看.*我的記憶)", user_text):
        memory = fetch_user_memory(line_user_id)
        if not memory or not memory.get("consent_memory"):
            return "目前我沒有為你保存任何長期記憶。若你希望我記住稱呼或衛教偏好，可以說：請記住我叫小明。"
        details = []
        if memory.get("display_name"):
            details.append(f"稱呼：{memory['display_name']}")
        if memory.get("profile_summary"):
            details.append(f"偏好或基本資料：{memory['profile_summary']}")
        return "目前我為你保存的資料是：\n" + "\n".join(details or ["沒有具體內容。"])

    if not re.search(r"(請|幫我)?記住|以後.*(叫我|稱呼我)|下次.*(叫我|稱呼我)|你可以叫我", user_text):
        return None

    if is_sensitive_memory(user_text):
        return "為了保護隱私，我暫時不保存血糖、用藥、病歷、電話、地址等敏感資料。可以幫你記住稱呼或一般衛教偏好，例如：請記住我想多看飲食控制的衛教。"

    display_name = extract_display_name(user_text)
    profile_note = extract_profile_note(user_text)
    if not display_name and not profile_note:
        return "可以，我能記住稱呼或一般衛教偏好。請用這樣的方式告訴我：請記住我叫小明。"

    save_user_memory(line_user_id, display_name=display_name, profile_note=profile_note)
    if display_name:
        return f"好的，我記住了。之後我會用「{display_name}」來稱呼你。你也可以隨時說「忘記我的資料」來刪除。"
    return "好的，我已記住這個一般偏好。你也可以隨時說「我有哪些資料被記住？」或「忘記我的資料」。"


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
    return source.get("userId") or source.get("groupId") or source.get("roomId") or ""


def extract_gemini_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for candidate in payload.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            if part.get("text"):
                parts.append(str(part["text"]))
    return "\n".join(parts).strip()


def gemini_answer(user_text: str, line_user_id: str = "") -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key:
        return "目前快速問答服務尚未設定 Gemini API key。若你有血糖不舒服、低血糖症狀或血糖持續很高，請先聯絡醫療團隊。"

    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT + memory_prompt(line_user_id)}]},
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"病友問題：{user_text}"}],
            }
        ],
        "generationConfig": {
            "maxOutputTokens": 650,
            "temperature": 0.4,
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
    try:
        with urllib.request.urlopen(request, timeout=GEMINI_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        answer = extract_gemini_text(payload)
        if answer:
            return answer[:4900]
        return "目前系統暫時沒有產生完整回覆。若你有明顯不舒服或血糖異常，請先聯絡醫療團隊。"
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        print(f"Gemini HTTP {exc.code}: {detail}")
    except Exception as exc:
        print(f"Gemini request failed: {type(exc).__name__}: {exc}")
    return "目前快速問答暫時無法回覆。若你有低血糖症狀、血糖持續很高、胸痛、意識不清或明顯不舒服，請先聯絡醫療團隊或就醫。"


async def handle_text_event(event: dict[str, Any]) -> None:
    message = event.get("message", {})
    user_text = (message.get("text") or "").strip()
    target = source_target(event)
    reply_token = (event.get("replyToken") or "").strip()
    if not user_text or not target:
        return

    loop = asyncio.get_running_loop()
    memory_answer = await loop.run_in_executor(None, memory_command_response, target, user_text)
    answer = memory_answer or await loop.run_in_executor(None, gemini_answer, user_text, target)
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
    return {
        "ok": True,
        "service": "line-lifebot-qa",
        "model": GEMINI_MODEL,
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()),
        "line_configured": bool(os.getenv("LINE_CHANNEL_SECRET", "").strip() and os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()),
        "memory_enabled": LINE_MEMORY_ENABLED,
        "memory_backend": memory_backend(),
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
