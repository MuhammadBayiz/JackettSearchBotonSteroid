import requests
from pyrogram.types import Message


def is_ptp_available(timeout: int = 5) -> bool:
    try:
        response = requests.get("https://passthepopcorn.me", timeout=timeout)
        response.raise_for_status()
        return True
    except (requests.RequestException, requests.Timeout):
        return False


async def check_ptp(message: Message):
    if is_ptp_available(timeout=5):
        await message.reply_text("chal raha hai")
    else:
        await message.reply_text("gaya bhai")
