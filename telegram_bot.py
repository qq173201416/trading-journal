# telegram_bot.py
import os
import time
import requests

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram_message(message: str, max_retries: int = 3, retry_delay_seconds: float = 5.0) -> bool:
    """
    发送消息到 Telegram,失败自动重试。
    Token/Chat ID 从环境变量 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 读取,不写死在代码里。

    参数:
        message (str): 发送的文本消息
        max_retries (int): 最多尝试次数
        retry_delay_seconds (float): 每次失败后的等待秒数

    返回:
        bool: True 表示 Telegram 已确认收到(response.ok == True),
              调用方只应在 True 时才把这次提醒计入已发送状态。
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[Telegram] 缺少 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 环境变量")
        return False

    url = TELEGRAM_API_URL.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200 and response.json().get("ok"):
                print("[Telegram] 发送成功")
                return True
            print(f"[Telegram] 发送失败(第{attempt}次): {response.text}")
        except Exception as e:
            print(f"[Telegram] 请求异常(第{attempt}次): {e}")

        if attempt < max_retries:
            time.sleep(retry_delay_seconds)

    return False
