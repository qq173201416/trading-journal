"""
tg_news.py
========================================
Telegram 新闻群 → 市场影响分析 routine 的数据层（只负责收发，不做分析）。

    python news/tg_news.py fetch            # 拉取新消息（不确认），写 news/pending.json 并打印
    python news/tg_news.py ack              # 分析完成后确认 offset，清空 pending
    python news/tg_news.py send report.md   # 把报告推送到个人 Telegram
    python news/tg_news.py channel [--hours N]  # 抓公开频道网页版 t.me/s/<name> 上次运行以来的帖子

环境变量:
    TG_GETNEWS_BOT_TOKEN / TG_GETNEWS_GROUP_ID   读消息的 bot + 群/频道 ID（多个用逗号分隔）
                                                 群里别的 bot 发的消息 bot 收不到；频道里 bot 当管理员就能全收
    TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID        推送报告的 bot + 个人 chat
    TG_PUBLIC_CHANNELS                           公开频道用户名，逗号分隔（默认 LianDaShiNews）

公开频道不需要 bot：直接读 t.me/s/<name> 网页（需网络放行 t.me）。不存 state，
按时间窗口取"上一个定时点（07:45 / 16:45 ET）以来"的帖子，手动多跑一次只会重复不会漏。

fetch 和 ack 分开：getUpdates 未确认的消息 Telegram 保留 24h，routine 中途失败
下次还能重新拿到，不会丢。所以 routine 间隔必须 < 24h。

"读到哪了"由 Telegram 服务端记录（ack 时用 offset 确认），本地不存 state，
所以 routine 不需要 git push 权限，每次全新 clone 也能正确续上。
"""

import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
PENDING_PATH = HERE / "pending.json"
TG_MAX_LEN = 4000  # Telegram 单条上限 4096，留余量
ET = ZoneInfo("America/New_York")
RUN_SLOTS = [(7, 45), (16, 45)]  # 与 routine 的 cron 保持一致
MAX_PAGES = 30  # 每页约 20 帖，防止窗口算错时无限翻页


def _api(token: str, method: str, params: dict) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(url, data=data, timeout=30) as resp:
        body = json.load(resp)
    if not body.get("ok"):
        raise RuntimeError(f"{method} failed: {body}")
    return body["result"]


def _save_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def _extract(update: dict, chat_ids: set):
    msg = update.get("message") or update.get("channel_post") or update.get("edited_message")
    if not msg or msg.get("chat", {}).get("id") not in chat_ids:
        return None
    text = msg.get("text") or msg.get("caption") or ""
    if not text.strip():
        return None
    sender = msg.get("from") or msg.get("sender_chat") or {}
    origin = msg.get("forward_origin") or {}
    return {
        "update_id": update["update_id"],
        "message_id": msg["message_id"],
        "date": datetime.fromtimestamp(msg["date"], timezone.utc).isoformat(),
        "chat": msg["chat"].get("title"),
        "sender": sender.get("username") or sender.get("title") or sender.get("first_name"),
        "forwarded_from": (origin.get("chat") or origin.get("sender_user") or {}).get("title")
        or origin.get("sender_user_name"),
        "edited": "edited_message" in update,
        "text": text,
    }


def fetch() -> None:
    token = os.environ["TG_GETNEWS_BOT_TOKEN"]
    chat_ids = {int(x) for x in os.environ["TG_GETNEWS_GROUP_ID"].split(",") if x.strip()}
    # 不传 offset 时 getUpdates 只返回服务端尚未确认的 update
    offset, updates, max_id = None, [], None
    while True:
        params = {"limit": 100, "timeout": 0,
                  "allowed_updates": json.dumps(["message", "channel_post", "edited_message"])}
        if offset is not None:
            params["offset"] = offset
        batch = _api(token, "getUpdates", params)
        if not batch:
            break
        updates.extend(batch)
        max_id = batch[-1]["update_id"]
        offset = max_id + 1
        if len(batch) < 100:
            break

    messages = [m for m in (_extract(u, chat_ids) for u in updates) if m]
    _save_json(PENDING_PATH, {"max_update_id": max_id, "messages": messages})
    print(json.dumps({"count": len(messages), "messages": messages}, ensure_ascii=False, indent=2))


def ack() -> None:
    if not PENDING_PATH.exists():
        print("nothing pending")
        return
    pending = json.loads(PENDING_PATH.read_text())
    max_id = pending["max_update_id"]
    if max_id is not None:
        # 用 offset=max+1 调一次 getUpdates，Telegram 端才真正丢弃这些 update
        _api(os.environ["TG_GETNEWS_BOT_TOKEN"], "getUpdates",
             {"offset": max_id + 1, "limit": 1, "timeout": 0})
    PENDING_PATH.unlink()
    print(f"acked through update_id={max_id}")


def send(report_path: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    text = Path(report_path).read_text()
    chunks, buf = [], ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > TG_MAX_LEN and buf:
            chunks.append(buf)
            buf = ""
        buf += line
    if buf:
        chunks.append(buf)
    for chunk in chunks:
        # 纯文本发送，避免 Markdown 特殊字符导致 400
        _api(token, "sendMessage",
             {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": "true"})
    print(f"sent {len(chunks)} message(s)")


def _previous_slot(now: datetime) -> datetime:
    """上一个定时点；留 30 分钟余量，避免定时运行把自己这一档当成起点。"""
    ref = now.astimezone(ET) - timedelta(minutes=30)
    for days_back in range(0, 3):
        day = (ref - timedelta(days=days_back)).date()
        for h, m in sorted(RUN_SLOTS, reverse=True):
            slot = datetime(day.year, day.month, day.day, h, m, tzinfo=ET)
            if slot <= ref:
                return slot
    return ref - timedelta(hours=24)


def _parse_channel_page(page: str) -> list[dict]:
    posts = []
    for chunk in page.split('class="tgme_widget_message_wrap')[1:]:
        post = re.search(r'data-post="([^"]+)"', chunk)
        when = re.search(r'<time[^>]+datetime="([^"]+)"', chunk)
        if not post or not when:
            continue
        body = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', chunk, re.S)
        text = ""
        if body:
            text = re.sub(r"<br\s*/?>", "\n", body.group(1))
            text = html.unescape(re.sub(r"<[^>]+>", "", text)).strip()
        posts.append({
            "post": post.group(1),
            "id": int(post.group(1).rsplit("/", 1)[1]),
            "date": datetime.fromisoformat(when.group(1)).astimezone(timezone.utc).isoformat(),
            "text": text,
        })
    return posts


def channel(hours) -> None:
    names = [x.strip() for x in os.environ.get("TG_PUBLIC_CHANNELS", "LianDaShiNews").split(",") if x.strip()]
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours) if hours else _previous_slot(now)
    result = []
    for name in names:
        url, collected = f"https://t.me/s/{name}", {}
        for _ in range(MAX_PAGES):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                posts = _parse_channel_page(resp.read().decode("utf-8", "replace"))
            if not posts:
                break
            for p in posts:
                collected[p["id"]] = p
            oldest = min(posts, key=lambda p: p["id"])
            if datetime.fromisoformat(oldest["date"]) < since:
                break
            url = f"https://t.me/s/{name}?before={oldest['id']}"
        fresh = [p for p in sorted(collected.values(), key=lambda p: p["id"])
                 if datetime.fromisoformat(p["date"]) >= since and p["text"]]
        result.append({"channel": name, "count": len(fresh), "posts": fresh})
    print(json.dumps({"since": since.isoformat(), "channels": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "fetch":
        fetch()
    elif cmd == "ack":
        ack()
    elif cmd == "channel":
        channel(float(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[2] == "--hours" else None)
    elif cmd == "send" and len(sys.argv) > 2:
        send(sys.argv[2])
    else:
        sys.exit(__doc__)
