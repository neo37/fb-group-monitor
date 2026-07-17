"""Матчинг постов: пост релевантен, если есть слово намерения (ищу/посоветуйте...)
И гео-слово (Черногория/города). Ключевые фразы из БД дают дополнительные лексемы."""
import re
import pymorphy3

morph = pymorphy3.MorphAnalyzer()

INTENT = {"искать", "снять", "посоветовать", "подсказать", "порекомендовать",
          "нужный", "нужно", "требоваться", "интересовать"}
GEO = {"черногория", "будва", "бечичи", "петровац", "котор", "тиват", "бар",
       "герцег-нови", "рафаиловичи", "сутоморе", "ульцинь", "жабляк", "montenegro",
       "budva", "becici", "petrovac", "kotor", "tivat"}
STOP = {"в", "на", "с", "и", "у", "по", "за", "для"}

_lemma_cache = {}


def lemma(word):
    w = word.lower()
    if w not in _lemma_cache:
        _lemma_cache[w] = morph.parse(w)[0].normal_form
    return _lemma_cache[w]


def lemmas(text):
    return {lemma(w) for w in re.findall(r"[\w-]+", text.lower())}


def phrase_lemmas(p, drop_stop=True):
    words = re.findall(r"[\w-]+", p.lower())
    return {lemma(w) for w in words if not (drop_stop and w in STOP)}


def neg_hit(toks, negatives):
    """Минус-запись срабатывает, если ВСЕ её слова есть в посте.
    Возвращает сработавшую минус-фразу или None."""
    for n in negatives:
        need = phrase_lemmas(n, drop_stop=False)
        if need and need <= toks:
            return n
    return None


def match(text, phrases, negatives=()):
    """Пост совпадает с фразой, если содержит ВСЕ её слова (по леммам).
    Сработавшая минус-фраза отменяет совпадение. Возвращает фразу или None."""
    toks = lemmas(text)
    if neg_hit(toks, negatives):
        return None
    for p in phrases:
        need = phrase_lemmas(p)
        if need and need <= toks:
            return p
    return None
