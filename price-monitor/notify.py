"""Send a Telegram message. Usage: python3 notify.py "text"  (or pipe text on stdin)."""
import json
import os
import sys
import urllib.request

text = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
token = os.environ["TELEGRAM_BOT_TOKEN"]
chat_id = os.environ["TELEGRAM_CHAT_ID"]
req = urllib.request.Request(
    f"https://api.telegram.org/bot{token}/sendMessage",
    data=json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}).encode(),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=30) as resp:
    ok = json.load(resp).get("ok")
print("sent" if ok else "failed")
sys.exit(0 if ok else 1)
