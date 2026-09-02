# telegram_bot.py
import os
import time
import requests

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram_message(message: str, max_retries: int = 3, base_delay_seconds: float = 5.0) -> dict:
    """
    发送消息到 Telegram,按错误类型区分重试策略(SOP v14 Step 4.5):
      - 403(bot token失效/被拉黑等不会自愈的问题): 不重试,直接判定为永久性失败。
      - 429(限流): 指数退避重试,优先遵守响应里的 Retry-After。
      - 5xx(服务端错误)/网络异常: 视为临时性,指数退避重试最多 max_retries 次。

    Token/Chat ID 从环境变量 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 读取,不写死在代码里。

    返回一个 dict,而不是单纯的 bool,方便调用方按错误类型分别记录 run_log:
      {
        "success": bool,          # True 才代表 Telegram 已确认收到(ok == True)
        "error_category": str|None,  # "permanent" | "rate_limited" | "server_error" | "network" | None
        "status_code": int|None,
        "detail": str,            # 供 run_log 直接记录的简短说明
      }
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return {
            "success": False,
            "error_category": "permanent",
            "status_code": None,
            "detail": "missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID env var",
        }

    url = TELEGRAM_API_URL.format(token=token)
    # 不传 parse_mode:2026-09-01 真实数据发现 parse_mode="Markdown" 会把消息里 enum 类
    # 字段值(HL_CONFIRMED / WAIT_NO_SIGNAL / market_state 等)中的下划线当成斜体分隔符,
    # 按整条消息里出现顺序两两配对消费掉,导致 HL_CONFIRMED 显示成 HLCONFIRMED 这类拼接
    # 错误。发送纯文本、不做任何 markdown 解析,从根上消除这类 field value 被解析器改写
    # 的风险,不需要对字段值做转义。
    payload = {
        "chat_id": chat_id,
        "text": message,
    }

    attempt = 0
    while attempt < max_retries:
        attempt += 1
        try:
            response = requests.post(url, json=payload, timeout=10)
        except requests.RequestException as e:
            if attempt >= max_retries:
                return {
                    "success": False,
                    "error_category": "network",
                    "status_code": None,
                    "detail": f"network exception after {attempt} attempts: {e}",
                }
            time.sleep(base_delay_seconds * (2 ** (attempt - 1)))
            continue

        if response.status_code == 200 and response.json().get("ok"):
            return {
                "success": True,
                "error_category": None,
                "status_code": 200,
                "detail": "sent",
            }

        if response.status_code == 403:
            return {
                "success": False,
                "error_category": "permanent",
                "status_code": 403,
                "detail": f"permanent failure, not retrying: {response.text}",
            }

        if response.status_code == 429:
            if attempt >= max_retries:
                return {
                    "success": False,
                    "error_category": "rate_limited",
                    "status_code": 429,
                    "detail": f"rate limited after {attempt} attempts: {response.text}",
                }
            retry_after = None
            try:
                retry_after = response.json().get("parameters", {}).get("retry_after")
            except Exception:
                pass
            delay = retry_after if retry_after else base_delay_seconds * (2 ** (attempt - 1))
            time.sleep(delay)
            continue

        if 500 <= response.status_code < 600:
            if attempt >= max_retries:
                return {
                    "success": False,
                    "error_category": "server_error",
                    "status_code": response.status_code,
                    "detail": f"server error after {attempt} attempts: {response.text}",
                }
            time.sleep(base_delay_seconds * (2 ** (attempt - 1)))
            continue

        # Any other non-200: treat as permanent (bad request, invalid chat_id, etc.), don't retry.
        return {
            "success": False,
            "error_category": "permanent",
            "status_code": response.status_code,
            "detail": f"unexpected response, not retrying: {response.text}",
        }

    return {
        "success": False,
        "error_category": "network",
        "status_code": None,
        "detail": "exhausted retries without a definitive response",
    }
