"""Один проход мониторинга: группы -> матчинг -> телеграм; свои посты -> комментарии -> телеграм.
Запуск: .venv/bin/python worker.py [--dataset <id>] (--dataset: взять готовый датасет вместо запуска актора)"""
import sys
from pathlib import Path

for line in (Path(__file__).parent / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        import os
        os.environ.setdefault(k.strip(), v.strip())

import db
import matcher
import notifier
import apify_client


def check_groups(conn):
    groups = conn.execute("SELECT url FROM groups WHERE enabled=1").fetchall()
    phrases = [r["phrase"] for r in
               conn.execute("SELECT phrase FROM keywords WHERE enabled=1")]
    negatives = [r["word"] for r in
                 conn.execute("SELECT word FROM negative_keywords WHERE enabled=1")]
    if not groups or not phrases:
        print("нет групп или ключевых слов")
        return

    from datetime import datetime, timezone, timedelta as td
    run_started = datetime.now(timezone.utc)

    if "--dataset" in sys.argv:
        items = apify_client.get_dataset(sys.argv[sys.argv.index("--dataset") + 1])
    else:
        st = conn.execute("SELECT value FROM state WHERE key='last_scrape_at'").fetchone()
        # читаем с момента прошлого успешного скрапа (с получасовым нахлёстом), иначе за сутки
        newer = ((datetime.fromisoformat(st["value"]) - td(minutes=30))
                 .strftime("%Y-%m-%dT%H:%M:%S") if st else "1 day")
        items = apify_client.scrape_groups([g["url"] for g in groups], newer_than=newer)
        conn.execute("INSERT OR REPLACE INTO state(key,value) VALUES('last_scrape_at',?)",
                     (run_started.strftime("%Y-%m-%dT%H:%M:%S"),))
    print(f"получено постов: {len(items)}")

    new_matches = 0
    for it in items:
        url, text = it.get("url"), it.get("text") or ""
        if it.get("groupTitle") and it.get("facebookUrl"):
            conn.execute("UPDATE groups SET title=? WHERE url=? AND (title IS NULL OR title='')",
                         (it["groupTitle"], it["facebookUrl"]))
        if not url or not text:
            continue
        if conn.execute("SELECT 1 FROM seen_posts WHERE post_url=?", (url,)).fetchone():
            continue
        phrase = matcher.match(text, phrases, negatives)
        conn.execute(
            "INSERT INTO seen_posts(post_url, group_url, matched_phrase, text, posted_at, notified)"
            " VALUES(?,?,?,?,?,?)",
            (url, it.get("facebookUrl"), phrase, text[:1000], it.get("time"), 0))
        if phrase:
            author = (it.get("user") or {}).get("name", "")
            notifier.notify_post(it.get("groupTitle", ""), phrase, text, url, author)
            conn.execute("UPDATE seen_posts SET notified=1 WHERE post_url=?", (url,))
            new_matches += 1
    conn.execute("UPDATE groups SET last_checked_at=datetime('now')")
    conn.commit()
    print(f"новых совпадений: {new_matches}")


def check_my_posts(conn):
    posts = conn.execute("SELECT url FROM my_posts WHERE enabled=1").fetchall()
    if not posts:
        return
    items = apify_client.scrape_comments([p["url"] for p in posts])
    new = 0
    for it in items:
        cid = it.get("id") or it.get("commentUrl")
        if not cid:
            continue
        if conn.execute("SELECT 1 FROM seen_comments WHERE comment_id=?", (cid,)).fetchone():
            continue
        author = (it.get("author") or {}).get("name") or it.get("profileName", "")
        conn.execute(
            "INSERT INTO seen_comments(comment_id, post_url, author, text) VALUES(?,?,?,?)",
            (cid, it.get("facebookUrl") or it.get("postUrl"), author, (it.get("text") or "")[:1000]))
        notifier.notify_comment(it.get("facebookUrl") or it.get("postUrl"), author, it.get("text") or "")
        new += 1
    conn.execute("UPDATE my_posts SET last_checked_at=datetime('now')")
    conn.commit()
    print(f"новых комментариев: {new}")


if __name__ == "__main__":
    conn = db.connect()
    try:
        check_groups(conn)
        check_my_posts(conn)
    except Exception as e:
        try:
            notifier.send(f"⚠️ Мониторинг FB: ошибка — {e}")
        except Exception:
            pass
        raise
