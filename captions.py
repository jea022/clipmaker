"""Genera caption y hashtags por cuenta, repartiendo una lista editable entre los clips."""
import copy
import hashlib
import json
import re
import unicodedata
from pathlib import Path

HERE = Path(__file__).parent
DEFAULTS_FILE = HERE / "hashtags.json"
USER_FILE = HERE / "data" / "hashtags.json"
CURSOR_FILE = HERE / "data" / "hashtag_cursor.json"

ACCOUNTS = {
    "wganga": {
        "handle": "@wganga_clips",
        "ctas": [
            "¿Tú qué hubieras hecho?",
            "¿Quién tiene la culpa aquí?",
            "Etiqueta a tu parce que haría lo mismo",
            "¿Lo viste en directo?",
        ],
    },
    "gtahispa": {
        "handle": "@gtaHispaClips",
        "ctas": [
            "¿Lo conocías?",
            "¿Con quién lo jugarías?",
            "¿Cuál es tu momento favorito?",
            "Sigue para más clips de GTA VI",
        ],
    },
}

GAMES = ("gta6", "gta5rp")
MAX_CAPTION_TEXT = 150
MAX_PEOPLE_TAGS = 3
YT_TITLE_MAX = 100
COUNT_RANGE = (3, 15)
POOL_KEYS = ("always", "niche", "broad", "reserve", "rp", "to_verify")
LIMITS = {"always": 5, "niche": 80, "broad": 80, "reserve": 80, "rp": 40, "to_verify": 80}
MAX_PEOPLE = 40
MAX_TAGS_PER_PERSON = 5
TAG_RE = re.compile(r"^#\w{2,60}$")
KEY_RE = re.compile(r"^[a-z0-9]{2,30}$")
EMPTY = {"always": [], "niche": [], "broad": [], "reserve": [], "rp": [], "to_verify": [], "people": {},
         "count_tiktok": 5, "count_shorts": 3, "shorts_tag": True}


# ---------- validacion y normalizacion ----------
def normalize_tag(raw):
    if not isinstance(raw, str):
        raise ValueError("Hay un hashtag que no es texto")
    tag = raw.strip()
    if not tag:
        return None
    if not tag.startswith("#"):
        tag = "#" + tag
    if not TAG_RE.match(tag):
        raise ValueError(f"Hashtag no válido: {raw.strip()[:30]!r} (solo letras, números y _, sin espacios ni símbolos)")
    return tag


def normalize_list(items, label, limit):
    if isinstance(items, str):
        items = re.split(r"[\s,;]+", items)
    if not isinstance(items, (list, tuple)):
        raise ValueError(f"La lista «{label}» no es válida")
    seen, out = set(), []
    for raw in items:
        tag = normalize_tag(raw)
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            out.append(tag)
    if len(out) > limit:
        raise ValueError(f"La lista «{label}» admite como máximo {limit} hashtags (tiene {len(out)})")
    return out


def normalize_key(raw):
    if not isinstance(raw, str):
        raise ValueError("Hay un nombre de persona que no es texto")
    text = unicodedata.normalize("NFKD", raw.lower())
    key = re.sub(r"[^a-z0-9]", "", "".join(c for c in text if not unicodedata.combining(c)))
    if not KEY_RE.match(key):
        raise ValueError(f"Nombre de persona no válido: {raw.strip()[:30]!r} (2 a 30 letras o números)")
    return key


def normalize_people(obj):
    if not isinstance(obj, dict):
        raise ValueError("«Personas» no es válido")
    people = {}
    for raw_key, tags in obj.items():
        key = normalize_key(raw_key)
        lst = normalize_list(tags, f"persona {key}", MAX_TAGS_PER_PERSON)
        if not lst:
            raise ValueError(f"La persona «{key}» no tiene hashtags")
        merged = people.get(key, []) + [t for t in lst if t.lower() not in {x.lower() for x in people.get(key, [])}]
        people[key] = merged[:MAX_TAGS_PER_PERSON]
    if len(people) > MAX_PEOPLE:
        raise ValueError(f"Hay demasiadas personas (máximo {MAX_PEOPLE})")
    return people


def _count(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        raise ValueError(f"{label} no es un número")
    if not COUNT_RANGE[0] <= value <= COUNT_RANGE[1]:
        raise ValueError(f"{label} debe estar entre {COUNT_RANGE[0]} y {COUNT_RANGE[1]}")
    return int(round(value))


def validate_config(cfg):
    """Devuelve la configuración normalizada o lanza ValueError con un mensaje claro."""
    if not isinstance(cfg, dict):
        raise ValueError("La configuración de hashtags no es válida")
    out = copy.deepcopy(EMPTY)
    for key in POOL_KEYS:
        if key in cfg:
            out[key] = normalize_list(cfg[key], key, LIMITS[key])
    if "people" in cfg:
        out["people"] = normalize_people(cfg["people"])
    if "count_tiktok" in cfg:
        out["count_tiktok"] = _count(cfg["count_tiktok"], "La cantidad para TikTok")
    if "count_shorts" in cfg:
        out["count_shorts"] = _count(cfg["count_shorts"], "La cantidad para Shorts")
    if "shorts_tag" in cfg:
        if not isinstance(cfg["shorts_tag"], bool):
            raise ValueError("«#Shorts» debe ser sí o no")
        out["shorts_tag"] = cfg["shorts_tag"]
    return out


# ---------- lectura de configuracion ----------
def _read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _check_account(account):
    if account not in ACCOUNTS:
        raise KeyError(f"cuenta desconocida: {account} (opciones: {', '.join(ACCOUNTS)})")


def defaults(account):
    _check_account(account)
    try:
        return validate_config(_read_json(DEFAULTS_FILE).get(account) or {})
    except ValueError:
        return copy.deepcopy(EMPTY)


def effective(account):
    """Lo guardado por el usuario para la cuenta (si es válido) o los recomendados."""
    _check_account(account)
    saved = _read_json(USER_FILE).get(account)
    if isinstance(saved, dict):
        try:
            return validate_config(saved)
        except ValueError:
            pass
    return defaults(account)


def is_customized(account):
    saved = _read_json(USER_FILE).get(account)
    if not isinstance(saved, dict):
        return False
    try:
        validate_config(saved)
    except ValueError:
        return False
    return True


def save_config(account, cfg):
    _check_account(account)
    clean = validate_config(cfg)
    data = _read_json(USER_FILE)
    data[account] = clean
    _write_json(USER_FILE, data)
    return clean


def reset_config(account):
    _check_account(account)
    data = _read_json(USER_FILE)
    data.pop(account, None)
    _write_json(USER_FILE, data)


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def people_keys(account):
    return sorted(effective(account)["people"])


def next_cursor(account):
    """Numero de clip de la cuenta (empieza en 0); lo guarda para que la rotacion avance."""
    _check_account(account)
    data = _read_json(CURSOR_FILE)
    n = data.get(account, 0)
    n = n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else 0
    data[account] = n + 1
    try:
        _write_json(CURSOR_FILE, data)
    except OSError:
        pass
    return n


# ---------- reparto ----------
def _rotate(items, cursor, k, taken):
    """k hashtags de la lista a partir de la posicion cursor*k, sin repetir los ya elegidos."""
    out = []
    if not items or k <= 0:
        return out
    start = (cursor * k) % len(items)
    for i in range(len(items)):
        tag = items[(start + i) % len(items)]
        if tag.lower() not in taken:
            out.append(tag)
            taken.add(tag.lower())
            if len(out) == k:
                break
    return out


def pick(cfg, people, count, cursor, game="gta6"):
    """Elige `count` hashtags: fijos, de las personas del clip y el resto rotando por turnos."""
    if game not in GAMES:
        raise ValueError(f"Juego desconocido: {game} (opciones: {', '.join(GAMES)})")
    always = cfg["always"] if game == "gta6" else cfg["rp"][:2]
    pool_extra = [] if game == "gta6" else cfg["rp"][2:]
    taken, tags = set(), []

    def add(tag):
        if tag.lower() not in taken and len(tags) < count:
            taken.add(tag.lower())
            tags.append(tag)

    for t in always:
        add(t)

    known, unknown, firsts, extras = [], [], [], []
    for p in people:
        key = re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", str(p).lower()).encode("ascii", "ignore").decode())
        if key in cfg["people"]:
            lst = cfg["people"][key]
            if lst[0].lower() not in {x.lower() for x in known}:
                known.append(lst[0])
                firsts.append(lst[0])
                extras += lst[1:]
        else:
            unknown.append(p)
    for t in firsts[:MAX_PEOPLE_TAGS]:
        add(t)

    budget = count - len(tags)
    if budget > 0:
        broad_n = 0 if budget <= 1 else (1 if budget < 5 else 2)
        broad_n = min(broad_n, len(cfg["broad"]))
        main_n = budget - broad_n
        main = _rotate(extras + pool_extra + cfg["niche"] + cfg["reserve"], cursor, main_n, taken)
        broad = _rotate(cfg["broad"], cursor, broad_n, taken)
        tags += main
        tags += broad
        short = count - len(tags)
        if short > 0:
            tags += _rotate(cfg["broad"] + pool_extra + cfg["niche"] + cfg["reserve"], cursor, short, taken)
    return tags[:count], known, unknown


def _trim(text, limit):
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def _cta(account, title):
    ctas = ACCOUNTS[account]["ctas"]
    return ctas[hashlib.sha256(title.encode("utf-8")).digest()[0] % len(ctas)]


def generate(account, title, people=(), cursor=0, game="gta6", config=None):
    _check_account(account)
    cfg = validate_config(config) if config is not None else effective(account)
    title = " ".join(title.split())
    cta = _cta(account, title)
    cursor = cursor if isinstance(cursor, int) and not isinstance(cursor, bool) and cursor >= 0 else 0

    tags, known, unknown = pick(cfg, people, cfg["count_tiktok"], cursor, game)
    yt_tags, _, _ = pick(cfg, people, cfg["count_shorts"], cursor, game)
    if cfg["shorts_tag"]:
        yt_tags = yt_tags + ["#Shorts"]

    text = f"{_trim(title, MAX_CAPTION_TEXT - len(cta) - 1)} {cta}"
    yt_suffix = " #Shorts" if cfg["shorts_tag"] else ""
    return {
        "account": account,
        "handle": ACCOUNTS[account]["handle"],
        "game": game,
        "cursor": cursor,
        "tiktok_caption": f"{text} {' '.join(tags)}",
        "yt_title": _trim(title, YT_TITLE_MAX - len(yt_suffix)) + yt_suffix,
        "yt_description": f"{text}\n\n{' '.join(yt_tags)}",
        "hashtags": tags,
        "yt_hashtags": yt_tags,
        "people_known": known,
        "people_unknown": unknown,
    }


if __name__ == "__main__":
    import sys

    acct, title, *who = sys.argv[1:] or ["wganga", "Se le cae todo en pleno robo", "westcol", "samulx"]
    print(json.dumps(generate(acct, title, who), ensure_ascii=False, indent=2))
