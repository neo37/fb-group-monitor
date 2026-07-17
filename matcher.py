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


def match(text, phrases, negatives=()):
    """Пост совпадает с фразой, если содержит ВСЕ её слова (по леммам).
    Минус-слово в тексте отменяет совпадение. Возвращает фразу или None."""
    toks = lemmas(text)
    if any(lemma(n) in toks for n in negatives):
        return None
    for p in phrases:
        need = {lemma(w) for w in re.findall(r"[\w-]+", p.lower()) if w not in STOP}
        if need and need <= toks:
            return p
    return None
