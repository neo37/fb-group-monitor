import os
import requests

TOKEN = os.environ["TG_BOT_TOKEN"]
CHAT_IDS = [c for c in (os.environ.get("TG_CHAT_ID"), os.environ.get("TG_CHAT_ID_2")) if c]


def send(text):
    errors = []
    for chat_id in CHAT_IDS:
        r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                          json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                "disable_web_page_preview": True}, timeout=30)
        if not r.json().get("ok"):
            errors.append(f"{chat_id}: {r.text[:150]}")
    if len(errors) == len(CHAT_IDS):
        raise RuntimeError(f"telegram: {'; '.join(errors)}")


def notify_post(group_title, phrase, text, url, author=""):
    send(f"🔎 <b>Совпадение: {phrase}</b>\n"
         f"Группа: {group_title}\n"
         f"Автор: {author}\n\n"
         f"{text[:500]}\n\n"
         f'<a href="{url}">Открыть пост</a>')


def notify_comment(post_url, author, text):
    send(f"💬 <b>Новый комментарий под вашим постом</b>\n"
         f"Автор: {author}\n\n"
         f"{text[:500]}\n\n"
         f'<a href="{post_url}">Открыть пост</a>')
