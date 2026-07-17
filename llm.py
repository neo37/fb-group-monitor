import os
import requests

URL = os.environ.get("LLM_API_URL", "https://videos.ai3d.art/v1")
KEY = os.environ["LLM_API_KEY"]
MODEL = os.environ.get("LLM_MODEL", "qwen2.5:3b-instruct")
SITE = "https://familyvacation.me/"

PROMPT = """Ты менеджер сети апартаментов FamilyVacation в Черногории (сайт {site}).
Человек опубликовал в Facebook-группе пост — он ищет жильё:
---
{post}
---
Напиши короткий дружелюбный ответ-комментарий (2–4 предложения) на языке поста:
- предложи наши апартаменты в Черногории и дай ссылку {site}
- зацепись за детали из поста (даты, число людей, город), если они есть
- живой тон, без канцелярита и давления, максимум 1–2 эмодзи
Верни только текст ответа, без кавычек и пояснений."""


def generate_reply(post_text):
    r = requests.post(
        f"{URL}/chat/completions",
        headers={"Authorization": f"Bearer {KEY}"},
        json={"model": MODEL, "temperature": 0.7,
              "messages": [{"role": "user",
                            "content": PROMPT.format(site=SITE, post=post_text[:1500])}]},
        timeout=90)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()
