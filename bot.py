"""Telegram-бот управления мониторингом FB-групп.
Меню: посты по дням недели, ключевые слова, минус-слова, группы, CSV-выгрузка, ручной запуск."""
import asyncio
import csv
import html
import os
import sys
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).parent
for line in (BASE / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup,
                           InlineKeyboardButton, ReplyKeyboardMarkup,
                           KeyboardButton, FSInputFile, CopyTextButton,
                           LabeledPrice, PreCheckoutQuery, BufferedInputFile)

import db
import imggen
import llm
import matcher

# всегда авторизована только личка владельца; группы — по паролю (день/месяц)
ALLOWED = {int(os.environ["TG_CHAT_ID"])}

_session = None
if os.environ.get("TG_PROXY"):
    from aiogram.client.session.aiohttp import AiohttpSession
    _session = AiohttpSession(proxy=os.environ["TG_PROXY"])
bot = Bot(os.environ["TG_BOT_TOKEN"], session=_session)
dp = Dispatcher()

MENU = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [KeyboardButton(text="📋 Посты"), KeyboardButton(text="👤 Профиль"), KeyboardButton(text="📤 CSV")],
    [KeyboardButton(text="🔑 Ключевые слова"), KeyboardButton(text="🚫 Минус-слова")],
    [KeyboardButton(text="👥 Группы"), KeyboardButton(text="📝 Мои посты")],
])

WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


class Add(StatesGroup):
    keyword = State()
    negative = State()
    group = State()
    my_post = State()


class Auth(StatesGroup):
    password = State()


def day_password():
    return str(sum(int(ch) for ch in date.today().strftime("%d%m%Y")) + 36)


def month_password():
    # |сумма цифр 01.ММ.ГГГГ - сумма цифр 30.ММ.ГГГГ| + 36
    t = date.today()
    d1 = sum(int(ch) for ch in t.strftime("01%m%Y"))
    d30 = sum(int(ch) for ch in t.strftime("30%m%Y"))
    return str(abs(d1 - d30) + 36)


def allowed(msg):
    if msg.chat.id in ALLOWED:
        return True
    c = conn()
    r = c.execute("SELECT 1 FROM authorized_chats WHERE chat_id=?"
                  " AND valid_until >= datetime('now','localtime')", (msg.chat.id,)).fetchone()
    c.close()
    return bool(r)


def auth_until(msg_chat_id):
    c = conn()
    r = c.execute("SELECT valid_until FROM authorized_chats WHERE chat_id=?",
                  (msg_chat_id,)).fetchone()
    c.close()
    return r["valid_until"] if r else None


def conn():
    return db.connect()


# ---------- посты ----------

def days_keyboard(prefix="posts"):
    rows, row = [], []
    for i in range(7):
        d = date.today() - timedelta(days=i)
        label = "сегодня" if i == 0 else ("вчера" if i == 1 else f"{WEEKDAYS[d.weekday()]} {d.strftime('%d.%m')}")
        row.append(InlineKeyboardButton(text=label, callback_data=f"{prefix}:{d.isoformat()}"))
        if len(row) == 3:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="📅 Вся неделя", callback_data=f"{prefix}:week"),
                 InlineKeyboardButton(text="🔎 Только совпадения", callback_data=f"{prefix}:matches")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def annotate(rows, c, keep_negatives=False):
    """Пересчитывает совпадения по ТЕКУЩИМ ключевым и минус-словам.
    keep_negatives=True (для CSV): посты с минус-словами не выкидываются,
    а помечаются, каким словом отсечены."""
    phrases = [r["phrase"] for r in c.execute("SELECT phrase FROM keywords WHERE enabled=1")]
    negs = {matcher.lemma(r["word"]): r["word"] for r in
            c.execute("SELECT word FROM negative_keywords WHERE enabled=1")}
    out = []
    for r in rows:
        toks = matcher.lemmas(r["text"] or "")
        hit = toks & set(negs)
        d = dict(r)
        if hit:
            d["matched_phrase"] = None
            d["negative_word"] = negs[next(iter(hit))]
            if keep_negatives:
                out.append(d)
            continue
        d["matched_phrase"] = matcher.match(r["text"] or "", phrases)
        d["negative_word"] = ""
        out.append(d)
    return out


def query_posts(sel):
    c = conn()
    if sel in ("week", "matches"):
        rows = c.execute("SELECT rowid AS rid, * FROM seen_posts WHERE posted_at >= datetime('now','-7 days') ORDER BY posted_at DESC").fetchall()
    else:
        rows = c.execute("SELECT rowid AS rid, * FROM seen_posts WHERE date(posted_at)=? ORDER BY posted_at DESC", (sel,)).fetchall()
    rows = annotate(rows, c)
    if sel == "matches":
        rows = [r for r in rows if r["matched_phrase"]]
    c.close()
    return rows


def fmt_post(r):
    d = (r["posted_at"] or "?")[:16].replace("T", " ")
    mark = f"🔎 <b>{html.escape(r['matched_phrase'])}</b>\n" if r["matched_phrase"] else ""
    t = html.escape((r["text"] or "").replace("\n", " ")[:150])
    return f'{mark}📅 <b>{d}</b>\n{t}…\n<a href="{r["post_url"]}">открыть пост</a>'


@dp.message(F.text == "📋 Посты")
async def posts_menu(msg: Message):
    if not allowed(msg):
        return
    await msg.answer("За какой день показать посты?", reply_markup=days_keyboard())


def post_kb(r):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⭐ В избранное", callback_data=f"fav:{r['rid']}"),
        InlineKeyboardButton(text="✍️ Ответ", callback_data=f"rep:{r['rid']}"),
        InlineKeyboardButton(text="📋 Текст",
                             copy_text=CopyTextButton(text=(r["text"] or "")[:256])),
    ]])


async def safe_answer(msg, *args, **kwargs):
    try:
        return await msg.answer(*args, **kwargs)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        return await msg.answer(*args, **kwargs)


@dp.callback_query(F.data.startswith("posts:"))
async def posts_show(cb: CallbackQuery):
    sel = cb.data.split(":", 1)[1]
    rows = query_posts(sel)
    await cb.answer()
    if not rows:
        await cb.message.answer("Постов за этот период нет.")
        return
    c = conn()
    titles = {r["url"]: r["title"] for r in c.execute("SELECT url,title FROM groups")}
    c.close()

    by_group = {}
    for r in rows:
        by_group.setdefault(r["group_url"] or "?", []).append(r)

    await cb.message.answer(f"Найдено постов: {len(rows)} в {len(by_group)} группах")
    for gurl, grp in by_group.items():
        await safe_answer(cb.message,
                          f"👥 <b>{html.escape(titles.get(gurl) or gurl)}</b> — постов: {len(grp)}",
                          parse_mode="HTML")
        for r in grp:
            await safe_answer(cb.message, fmt_post(r), parse_mode="HTML",
                              disable_web_page_preview=True, reply_markup=post_kb(r))
            await asyncio.sleep(0.4)


# ---------- избранное и ответы ----------

@dp.callback_query(F.data.startswith("fav:"))
async def fav_add(cb: CallbackQuery):
    rid = cb.data.split(":")[1]
    c = conn()
    r = c.execute("SELECT post_url FROM seen_posts WHERE rowid=?", (rid,)).fetchone()
    if r:
        c.execute("INSERT OR IGNORE INTO favorites(post_url) VALUES(?)", (r["post_url"],))
        c.commit()
    c.close()
    await cb.answer("⭐ Добавлено в избранное")


@dp.callback_query(F.data.startswith("unfav:"))
async def fav_del(cb: CallbackQuery):
    rid = cb.data.split(":")[1]
    c = conn()
    r = c.execute("SELECT post_url FROM seen_posts WHERE rowid=?", (rid,)).fetchone()
    if r:
        c.execute("DELETE FROM favorites WHERE post_url=?", (r["post_url"],))
        c.commit()
    c.close()
    await cb.answer("Убрано из избранного")
    await cb.message.delete()


@dp.message(F.text == "👤 Профиль")
async def profile(msg: Message):
    if not allowed(msg):
        await msg.answer("Доступ закрыт. Авторизуйтесь:", reply_markup=auth_kb())
        return
    c = conn()
    n_fav = c.execute("SELECT count(*) FROM favorites").fetchone()[0]
    c.close()
    if msg.chat.id in ALLOWED:
        status = "владелец (бессрочно)"
    else:
        u = auth_until(msg.chat.id)
        status = f"до {u[:10]}" if u else "нет"
    kb_rows = [
        [InlineKeyboardButton(text=f"⭐ Избранное ({n_fav})", callback_data="favlist")],
        [InlineKeyboardButton(text="💳 Пополнить баланс", callback_data="topup")],
    ]
    if msg.chat.id not in ALLOWED:
        kb_rows.append([InlineKeyboardButton(text="🚪 Выйти", callback_data="logout")])
    await msg.answer(f"👤 <b>Профиль</b>\n\nЧат: <code>{msg.chat.id}</code>\n"
                     f"Доступ: {status}", parse_mode="HTML",
                     reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


@dp.callback_query(F.data == "logout")
async def logout(cb: CallbackQuery):
    c = conn()
    c.execute("DELETE FROM authorized_chats WHERE chat_id=?", (cb.message.chat.id,))
    c.commit(); c.close()
    await cb.answer("Вы вышли")
    await cb.message.answer("🚪 Авторизация сброшена.", reply_markup=auth_kb())


@dp.callback_query(F.data == "topup")
async def topup(cb: CallbackQuery):
    await cb.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼 Пароль на день — 198 ⭐", callback_data="buy:pw_day")],
        [InlineKeyboardButton(text="🖼 Пароль на месяц — 5000 ⭐", callback_data="buy:pw_month")],
    ])
    await cb.message.answer("💳 Продление доступа за Telegram Stars:", reply_markup=kb)


@dp.callback_query(F.data == "favlist")
async def fav_list_cb(cb: CallbackQuery):
    await cb.answer()
    await send_favorites(cb.message)


@dp.message(F.text == "⭐ Избранное")
async def fav_list(msg: Message):
    if not allowed(msg):
        return
    await send_favorites(msg)


async def send_favorites(msg):
    c = conn()
    rows = c.execute(
        "SELECT p.rowid AS rid, p.* FROM favorites f JOIN seen_posts p ON p.post_url=f.post_url"
        " ORDER BY f.created_at DESC").fetchall()
    rows = annotate(rows, c, keep_negatives=True)
    c.close()
    if not rows:
        await msg.answer("В избранном пусто. Кнопка ⭐ под постом добавляет его сюда.")
        return
    await msg.answer(f"⭐ Избранное: {len(rows)}")
    for r in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✍️ Ответ", callback_data=f"rep:{r['rid']}"),
            InlineKeyboardButton(text="🗑 Убрать", callback_data=f"unfav:{r['rid']}"),
            InlineKeyboardButton(text="📋 Текст",
                                 copy_text=CopyTextButton(text=(r["text"] or "")[:256])),
        ]])
        await safe_answer(msg, fmt_post(r), parse_mode="HTML",
                          disable_web_page_preview=True, reply_markup=kb)
        await asyncio.sleep(0.4)


@dp.callback_query(F.data.startswith("rep:"))
async def reply_gen(cb: CallbackQuery):
    rid = cb.data.split(":")[1]
    c = conn()
    r = c.execute("SELECT * FROM seen_posts WHERE rowid=?", (rid,)).fetchone()
    c.close()
    if not r or not r["text"]:
        await cb.answer("Пост не найден", show_alert=True)
        return
    await cb.answer("Генерирую ответ…")
    wait = await cb.message.answer("⏳ Генерирую ответ…")
    try:
        reply = await asyncio.to_thread(llm.generate_reply, r["text"])
    except Exception as e:
        await wait.edit_text(f"⚠️ Не удалось сгенерировать: {str(e)[:150]}")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 В буфер", copy_text=CopyTextButton(text=reply[:256])),
         InlineKeyboardButton(text="↗ К посту", url=r["post_url"])],
        [InlineKeyboardButton(text="🔁 Ещё вариант", callback_data=f"rep:{rid}")],
    ])
    await wait.edit_text(
        f"✍️ <b>Вариант ответа:</b>\n\n<code>{html.escape(reply)}</code>\n\n"
        f"Текст копируется тапом по нему или кнопкой «В буфер».",
        parse_mode="HTML", reply_markup=kb)


# ---------- CSV ----------

@dp.message(F.text == "📤 CSV")
async def csv_menu(msg: Message):
    if not allowed(msg):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="За неделю", callback_data="csv:week"),
        InlineKeyboardButton(text="Полный список", callback_data="csv:all"),
    ]])
    await msg.answer("Что выгрузить?", reply_markup=kb)


@dp.callback_query(F.data.startswith("csv:"))
async def csv_export(cb: CallbackQuery):
    sel = cb.data.split(":", 1)[1]
    c = conn()
    if sel == "week":
        rows = c.execute("SELECT * FROM seen_posts WHERE posted_at >= datetime('now','-7 days') ORDER BY posted_at DESC").fetchall()
    else:
        rows = c.execute("SELECT * FROM seen_posts ORDER BY posted_at DESC").fetchall()
    rows = annotate(rows, c, keep_negatives=True)
    c.close()
    path = BASE / f"posts_{sel}_{date.today().isoformat()}.csv"
    def clean(v):
        # кавычки внутри значений убираем полностью, чтобы не ломать структуру
        return str(v or "").replace('"', "'").replace("\n", " ").replace("\r", " ")

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=",", quoting=csv.QUOTE_ALL)
        w.writerow(["Дата поста", "Группа", "Совпадение (фраза)", "Отсечён минус-словом", "Текст", "Ссылка"])
        for r in rows:
            w.writerow([clean((r["posted_at"] or "")[:16].replace("T", " ")),
                        clean(r["group_url"]), clean(r["matched_phrase"]),
                        clean(r["negative_word"]),
                        clean(r["text"]), clean(r["post_url"])])
    await cb.answer()
    await cb.message.answer_document(FSInputFile(path),
                                     caption=f"Постов в файле: {len(rows)}")
    path.unlink(missing_ok=True)


# ---------- списки (слова / минус-слова / группы) ----------

async def show_list(msg, table, col, title, prefix, add_label):
    c = conn()
    rows = c.execute(f"SELECT id,{col} FROM {table} WHERE enabled=1 ORDER BY id").fetchall()
    c.close()
    kb_rows = [[InlineKeyboardButton(text=f"❌ {r[col][:40]}", callback_data=f"{prefix}del:{r['id']}")]
               for r in rows]
    kb_rows.append([InlineKeyboardButton(text=add_label, callback_data=f"{prefix}add")])
    body = "\n".join(f"• {r[col]}" for r in rows) or "— пусто —"
    await msg.answer(f"<b>{title}</b>\n{body}\n\nНажмите ❌ чтобы удалить:",
                     parse_mode="HTML",
                     reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


@dp.message(F.text == "🔑 Ключевые слова")
async def kw_menu(msg: Message):
    if allowed(msg):
        await show_list(msg, "keywords", "phrase", "Ключевые фразы", "kw", "➕ Добавить фразу")


@dp.message(F.text == "🚫 Минус-слова")
async def ng_menu(msg: Message):
    if allowed(msg):
        await show_list(msg, "negative_keywords", "word", "Минус-слова (пост с ними игнорируется)", "ng", "➕ Добавить минус-слово")


def groups_view():
    c = conn()
    rows = c.execute("SELECT id,url,title FROM groups WHERE enabled=1 ORDER BY id").fetchall()
    c.close()
    kb = [[InlineKeyboardButton(
        text=f"{i}. {(r['title'] or r['url'].replace('https://www.facebook.com/', ''))[:48]}",
        callback_data=f"gritem:{r['id']}")] for i, r in enumerate(rows, 1)]
    kb.append([InlineKeyboardButton(text="➕ Добавить группу", callback_data="gradd")])
    return (f"<b>Группы Facebook ({len(rows)})</b>\nНажмите на группу — откроется карточка:",
            InlineKeyboardMarkup(inline_keyboard=kb))


@dp.message(F.text == "👥 Группы")
async def gr_menu(msg: Message):
    if not allowed(msg):
        return
    text, kb = groups_view()
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("gritem:"))
async def gr_item(cb: CallbackQuery):
    c = conn()
    r = c.execute("SELECT * FROM groups WHERE id=?", (cb.data.split(":")[1],)).fetchone()
    c.close()
    await cb.answer()
    if not r:
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↗ Перейти в группу", url=r["url"])],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"grdel:{r['id']}"),
         InlineKeyboardButton(text="↩️ К списку", callback_data="grlist")],
    ])
    await cb.message.edit_text(
        f"👥 <b>{html.escape(r['title'] or 'Группа')}</b>\n\n"
        f"Ссылка (нажмите, чтобы скопировать):\n<code>{html.escape(r['url'])}</code>",
        parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "grlist")
async def gr_list(cb: CallbackQuery):
    text, kb = groups_view()
    await cb.answer()
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("grdel:"))
async def gr_del(cb: CallbackQuery):
    c = conn()
    c.execute("DELETE FROM groups WHERE id=?", (cb.data.split(":")[1],))
    c.commit(); c.close()
    await cb.answer("Удалено")
    text, kb = groups_view()
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.message(F.text == "📝 Мои посты")
async def mp_menu(msg: Message):
    if allowed(msg):
        await show_list(msg, "my_posts", "url", "Мои посты FB (оповещения о любых комментариях)", "mp", "➕ Добавить пост")


@dp.callback_query(F.data.startswith(("kwdel:", "ngdel:", "mpdel:")))
async def item_del(cb: CallbackQuery):
    prefix, item_id = cb.data.split(":")
    table = {"kwdel": "keywords", "ngdel": "negative_keywords",
             "mpdel": "my_posts"}[prefix]
    c = conn()
    c.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))
    c.commit(); c.close()
    await cb.answer("Удалено")
    await cb.message.answer("✅ Удалено.")


@dp.callback_query(F.data.in_({"kwadd", "ngadd", "gradd", "mpadd"}))
async def item_add_start(cb: CallbackQuery, state: FSMContext):
    prompts = {
        "kwadd": (Add.keyword, "Пришлите ключевую фразу (например: Ищу квартиру Будва):"),
        "ngadd": (Add.negative, "Пришлите минус-слово (например: сдам):"),
        "gradd": (Add.group, "Пришлите ссылку на группу Facebook:"),
        "mpadd": (Add.my_post, "Пришлите ссылку на ваш пост Facebook:"),
    }
    st, text = prompts[cb.data]
    await state.set_state(st)
    await cb.answer()
    await cb.message.answer(text)


@dp.message(Add.keyword)
async def kw_add(msg: Message, state: FSMContext):
    c = conn()
    phrase = msg.text.strip().lower()
    c.execute("INSERT OR IGNORE INTO keywords(phrase) VALUES(?)", (phrase,))
    c.commit(); c.close()
    await state.clear()
    await msg.answer(f"✅ Фраза добавлена: {phrase}", reply_markup=MENU)


@dp.message(Add.negative)
async def ng_add(msg: Message, state: FSMContext):
    c = conn()
    c.execute("INSERT OR IGNORE INTO negative_keywords(word) VALUES(?)", (msg.text.strip().lower(),))
    c.commit(); c.close()
    await state.clear()
    await msg.answer(f"✅ Минус-слово добавлено: {msg.text.strip().lower()}", reply_markup=MENU)


@dp.message(Add.group)
async def gr_add(msg: Message, state: FSMContext):
    url = msg.text.strip()
    if "facebook.com" not in url:
        await msg.answer("Это не похоже на ссылку Facebook, попробуйте ещё раз.")
        return
    c = conn()
    c.execute("INSERT OR IGNORE INTO groups(url) VALUES(?)", (url,))
    c.commit(); c.close()
    await state.clear()
    await msg.answer(f"✅ Группа добавлена: {url}", reply_markup=MENU)


@dp.message(Add.my_post)
async def mp_add(msg: Message, state: FSMContext):
    url = msg.text.strip()
    if "facebook.com" not in url:
        await msg.answer("Это не похоже на ссылку Facebook, попробуйте ещё раз.")
        return
    c = conn()
    c.execute("INSERT OR IGNORE INTO my_posts(url) VALUES(?)", (url,))
    c.commit(); c.close()
    await state.clear()
    await msg.answer(f"✅ Пост добавлен, о новых комментариях сообщу: {url}", reply_markup=MENU)


@dp.callback_query(F.data == "auth")
async def auth_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Auth.password)
    await cb.answer()
    await cb.message.answer("🔐 Введите пароль на сегодня:")


@dp.message(Auth.password)
async def auth_check(msg: Message, state: FSMContext):
    await state.clear()
    pw = (msg.text or "").strip()
    t = date.today()
    if pw == day_password():
        until = t.strftime("%Y-%m-%d 23:59:59")
        label = "до конца дня"
    elif pw == month_password():
        nxt = (t.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        until = nxt.strftime("%Y-%m-%d 23:59:59")
        label = "до конца месяца"
    else:
        await msg.answer("❌ Неверный пароль.", reply_markup=auth_kb())
        return
    c = conn()
    c.execute("INSERT OR REPLACE INTO authorized_chats(chat_id, valid_until) VALUES(?,?)",
              (msg.chat.id, until))
    c.commit(); c.close()
    await msg.answer(f"✅ Доступ открыт {label} ({until[:10]}).", reply_markup=MENU)


PRICES = {"pw_day": ("Пароль на день", 198), "pw_month": ("Пароль на месяц", 5000)}


def auth_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔐 Авторизация", callback_data="auth")],
        [InlineKeyboardButton(text="🖼 Пароль на день — 198 ⭐", callback_data="buy:pw_day")],
        [InlineKeyboardButton(text="🖼 Пароль на месяц — 5000 ⭐", callback_data="buy:pw_month")],
    ])


@dp.callback_query(F.data.startswith("buy:"))
async def buy_pw(cb: CallbackQuery):
    payload = cb.data.split(":")[1]
    title, price = PRICES[payload]
    await cb.answer()
    await bot.send_invoice(
        cb.message.chat.id,
        title=title,
        description="Картинка с паролем доступа к боту.",
        payload=payload, currency="XTR",
        prices=[LabeledPrice(label=title, amount=price)])


@dp.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)


@dp.message(F.successful_payment)
async def paid(msg: Message):
    t = date.today()
    if msg.successful_payment.invoice_payload == "pw_month":
        img = imggen.make_password_image(month_password(), f"месяц {t.strftime('%m.%Y')}")
        note = "Действует до конца месяца."
    else:
        img = imggen.make_password_image(day_password(), t.strftime("%d.%m.%Y"))
        note = "Действует только сегодня."
    await msg.answer_photo(
        BufferedInputFile(img, "access.png"),
        caption=f"🔐 Ваш пароль — на картинке. Нажмите «Авторизация» и введите его. {note}",
        reply_markup=auth_kb())


@dp.message(CommandStart())
@dp.message(Command("help"))
async def start(msg: Message):
    if not allowed(msg):
        await msg.answer("Доступ закрыт. Авторизуйтесь паролем на сегодня "
                         "или купите пароль на месяц:", reply_markup=auth_kb())
        return
    await msg.answer(
        "Мониторинг Facebook-групп.\n\n"
        "📋 Посты — посты за день или неделю\n"
        "📤 CSV — выгрузка в файл\n"
        "🔑 Ключевые слова — по ним приходят оповещения\n"
        "🚫 Минус-слова — посты с ними игнорируются\n"
        "👥 Группы — какие группы мониторим\n"
        "📝 Мои посты — оповещения о любых комментариях под ними\n\n"
        "Скачивание новых постов — автоматически 6 раз в сутки (каждые 4 часа),"
        " каждый раз с места, где закончил.",
        reply_markup=MENU)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
