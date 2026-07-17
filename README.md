# FB Group Monitor

Telegram-bot dashboard that watches Facebook groups for people looking for accommodation and turns them into leads — built for an apartment/hotel network in Montenegro.

## What it does

- **Scrapes Facebook groups daily** via the Apify `facebook-groups-scraper` actor (no cookies, public groups only) and stores every post in SQLite.
- **Matches posts against keyword phrases** with Russian morphology (pymorphy3 lemmatization): the phrase `ищу квартиру` matches "ищем квартиру", "ищете квартиру", etc. A post matches when it contains **all** words of a phrase.
- **Negative keywords** kill false positives (landlord ads, other countries, transfer/excursion spam) — applied reactively to already-stored posts, so editing dictionaries instantly changes results.
- **Instant Telegram alerts** for matched posts and for new comments under your own Facebook posts.
- **Telegram bot as the dashboard** — no web UI needed:
  - 📋 posts by day / week / matches-only, grouped by source group
  - ⭐ favorites
  - ✍️ AI-generated reply drafts (any OpenAI-compatible LLM endpoint) with copy-to-clipboard button
  - 🔑 keyword management, 🚫 negative keywords, 👥 groups (open/delete cards), 📝 own posts
  - 📤 CSV export (all posts, with match/filter annotations)
- **Access control**: date-derived daily/monthly passwords; password images sold via Telegram Stars.

## Architecture

```
Telegram bot (aiogram 3) ──► SQLite ◄── worker (daily systemd timer)
        │                                   │
        ▼                                   ▼
  LLM endpoint (replies)              Apify actors (FB scraping)
```

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install aiogram pymorphy3 requests pillow
cp .env.example .env   # fill in tokens
.venv/bin/python bot.py        # the bot
.venv/bin/python worker.py    # one scrape pass (run via cron/systemd timer)
```

### .env

| Variable | Purpose |
|---|---|
| `APIFY_TOKEN` | Apify API token |
| `TG_BOT_TOKEN` | Telegram bot token |
| `TG_CHAT_ID`, `TG_CHAT_ID_2` | Chats that receive alerts (always authorized) |
| `LLM_API_URL`, `LLM_API_KEY`, `LLM_MODEL` | OpenAI-compatible endpoint for reply generation |

## Files

| File | Role |
|---|---|
| `bot.py` | Telegram bot: menus, posts, favorites, replies, auth, Stars payments |
| `worker.py` | Daily pass: scrape groups → match → notify; comment watch for own posts |
| `matcher.py` | Lemma-based phrase matching with negative keywords |
| `apify_client.py` | Thin Apify REST client |
| `notifier.py` | Telegram alert sender |
| `imggen.py` | Password-image generator (Pillow) |
| `llm.py` | Reply drafting via LLM |
| `db.py` | SQLite schema |

## License

MIT
