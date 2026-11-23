#!/usr/bin/env python3
"""Read-only export of ONE Telegram chat to JSON + plain text.

Run it on your own computer. It never sends anything, never downloads media,
and never writes to Telegram. The login session stays on your machine.

Setup (once):
  1. Get api_id / api_hash at https://my.telegram.org -> "API development tools".
  2. pip install telethon
  3. export TG_API_ID=123456 TG_API_HASH=abcdef...   (Windows: set ...)

Usage:
  python telegram_export.py --list                      # show your chats
  python telegram_export.py --chat "Имя менеджера" --days 30
  python telegram_export.py --chat 123456789 --limit 500

Output: telegram_export/<chat>.json and telegram_export/<chat>.txt
Send only the .txt file (or paste its content) — NOT the *.session file.
"""
import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon import TelegramClient

SESSION_PATH = Path.home() / ".telegram_export_session"
OUT_DIR = Path("telegram_export")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list", action="store_true", help="list recent chats and exit")
    p.add_argument("--chat", help="chat title, @username or numeric id")
    p.add_argument("--days", type=int, help="only messages from the last N days")
    p.add_argument("--limit", type=int, default=1000, help="max messages (default 1000)")
    return p.parse_args()


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"Не задана переменная окружения {name}. См. инструкцию в начале файла.")
    return value


def safe_name(title: str) -> str:
    return re.sub(r"[^\w\-]+", "_", title, flags=re.UNICODE).strip("_") or "chat"


async def find_chat(client: TelegramClient, query: str):
    if query.lstrip("-").isdigit():
        return await client.get_entity(int(query))
    if query.startswith("@"):
        return await client.get_entity(query)
    async for dialog in client.iter_dialogs():
        if query.lower() in (dialog.name or "").lower():
            return dialog.entity
    sys.exit(f"Чат «{query}» не найден. Запустите с --list.")


async def main() -> None:
    args = parse_args()
    if not args.list and not args.chat:
        sys.exit("Укажите --list или --chat.")

    client = TelegramClient(str(SESSION_PATH), int(require_env("TG_API_ID")), require_env("TG_API_HASH"))
    async with client:  # asks for phone + login code interactively on first run
        if args.list:
            async for dialog in client.iter_dialogs(limit=50):
                print(f"{dialog.id}\t{dialog.name}")
            return

        entity = await find_chat(client, args.chat)
        title = getattr(entity, "title", None) or getattr(entity, "first_name", None) or str(args.chat)
        since = datetime.now(timezone.utc) - timedelta(days=args.days) if args.days else None

        messages = []
        async for msg in client.iter_messages(entity, limit=args.limit):
            if since and msg.date < since:
                break
            messages.append({
                "id": msg.id,
                "date": msg.date.astimezone().isoformat(timespec="seconds"),
                "from": getattr(msg.sender, "first_name", None) or getattr(msg.sender, "title", None) or "?",
                "text": msg.message or "",
                "has_media": bool(msg.media),
                "reply_to": msg.reply_to_msg_id,
            })
        messages.reverse()

    OUT_DIR.mkdir(exist_ok=True)
    stem = OUT_DIR / safe_name(title)
    stem.with_suffix(".json").write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = []
    for m in messages:
        media = " [вложение]" if m["has_media"] else ""
        lines.append(f"[{m['date']}] {m['from']}: {m['text']}{media}")
    stem.with_suffix(".txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"Готово: {len(messages)} сообщений -> {stem}.txt")


if __name__ == "__main__":
    asyncio.run(main())
