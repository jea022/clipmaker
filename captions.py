"""Genera caption y hashtags por cuenta (formula: gancho + CTA, 1-2 hashtags amplios + nicho)."""
import hashlib
import re

ACCOUNTS = {
    "wganga": {
        "handle": "@wganga_clips",
        "broad": ["#fyp", "#parati"],
        "niche": ["#GTA6", "#GTAVI", "#Kick"],
        "people": {
            "westcol": "#westcol",
            "lonche": "#lonchedehuevito",
            "willito": "#willito",
            "lasapa": "#lasapa",
            "elchanty": "#elchanty",
            "samulx": "#samulx",
        },
        "ctas": [
            "¿Tú qué hubieras hecho?",
            "¿Quién tiene la culpa aquí?",
            "Etiqueta a tu parce que haría lo mismo",
            "¿Lo viste en directo?",
        ],
    },
    "gtahispa": {
        "handle": "@gtaHispaClips",
        "broad": ["#fyp", "#parati"],
        "niche": ["#GTA6", "#GTAVI", "#gaming"],
        "people": {
            "illojuan": "#illojuan",
            "elxokas": "#elxokas",
            "rubius": "#rubius",
            "ibai": "#ibai",
        },
        "ctas": [
            "¿Lo conocías?",
            "¿Con quién lo jugarías?",
            "¿Cuál es tu momento favorito?",
            "Sigue para más clips de GTA VI",
        ],
    },
}

MAX_CAPTION_TEXT = 150
MAX_PEOPLE_TAGS = 3
YT_TITLE_MAX = 100


def _pick(options, seed):
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return options[digest[0] % len(options)]


def _trim(text, limit):
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def generate(account, title, people=()):
    if account not in ACCOUNTS:
        raise KeyError(f"cuenta desconocida: {account} (opciones: {', '.join(ACCOUNTS)})")
    acc = ACCOUNTS[account]
    title = " ".join(title.split())
    cta = _pick(acc["ctas"], title)

    known = []
    for p in people:
        key = re.sub(r"[^a-z0-9]", "", p.lower())
        if key in acc["people"] and acc["people"][key] not in known:
            known.append(acc["people"][key])
    tags = acc["niche"] + known[:MAX_PEOPLE_TAGS] + acc["broad"]

    text_budget = MAX_CAPTION_TEXT - len(cta) - 1
    text = f"{_trim(title, text_budget)} {cta}"
    hashtags = " ".join(tags)

    yt_suffix = " #Shorts"
    yt_title = _trim(title, YT_TITLE_MAX - len(yt_suffix)) + yt_suffix
    return {
        "account": account,
        "handle": acc["handle"],
        "tiktok_caption": f"{text} {hashtags}",
        "yt_title": yt_title,
        "yt_description": f"{text}\n\n{hashtags} #Shorts",
        "hashtags": tags,
        "people_known": known,
        "people_unknown": [p for p in people if re.sub(r"[^a-z0-9]", "", p.lower()) not in acc["people"]],
    }


if __name__ == "__main__":
    import json
    import sys

    acct, title, *who = sys.argv[1:] or ["wganga", "Se le cae todo en pleno robo", "westcol", "samulx"]
    print(json.dumps(generate(acct, title, who), ensure_ascii=False, indent=2))
