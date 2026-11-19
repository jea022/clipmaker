"""Descarga tramos de un directo/VOD (Twitch, Kick, YouTube...) con yt-dlp: pegas el link y una lista de
minutos, y baja un clip de 1 minuto (configurable) que empieza en cada minuto indicado."""
import re
from pathlib import Path

MAX_CLIPS = 60
MIN_DURATION, MAX_DURATION = 5, 300
DEFAULT_DURATION = 60
MAX_URL = 500
ALLOWED_HOST_SUFFIXES = ("twitch.tv", "kick.com", "youtube.com", "youtu.be", "tiktok.com", "x.com", "twitter.com",
                         "facebook.com", "fb.watch", "vimeo.com", "dailymotion.com")

_TOKEN_SPLIT = re.compile(r"[,;\n\r\t ]+")
_TIME_RE = re.compile(r"^(?:(\d{1,3}):)?(\d{1,2}):(\d{2})$")
_MIN_RE = re.compile(r"^\d{1,4}$")


class StreamClipError(Exception):
    """Error con mensaje listo para mostrar al usuario."""


def parse_marks(text):
    """'12, 45:30 1:05:10' -> [720, 2730, 3910] (segundos).
    Un numero suelto son minutos; mm:ss y h:mm:ss son la hora exacta dentro del directo."""
    marks, bad = [], []
    for tok in _TOKEN_SPLIT.split(str(text or "").strip()):
        if not tok:
            continue
        m = _TIME_RE.match(tok)
        if m:
            h, mi, s = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
            if s > 59 or (m.group(1) and mi > 59):
                bad.append(tok)
                continue
            marks.append(h * 3600 + mi * 60 + s)
        elif _MIN_RE.match(tok):
            marks.append(int(tok) * 60)
        else:
            bad.append(tok)
    if bad:
        raise StreamClipError("No entiendo estos minutos: " + ", ".join(bad[:5])
                              + ". Usa por ejemplo 12, 45:30 o 1:05:10.")
    marks = sorted(set(marks))
    if not marks:
        raise StreamClipError("Escribe al menos un minuto (por ejemplo: 12, 45:30, 1:05:10).")
    if len(marks) > MAX_CLIPS:
        raise StreamClipError(f"Máximo {MAX_CLIPS} clips por tanda.")
    return marks


def fmt_mark(sec):
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def check_url(url):
    from urllib.parse import urlparse
    url = str(url or "").strip()
    if not url or len(url) > MAX_URL:
        raise StreamClipError("Pega el link del directo.")
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme not in ("http", "https") or not host:
        raise StreamClipError("Ese link no es válido: debe empezar por https://")
    if not any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES):
        raise StreamClipError("Por ahora solo acepto links de Twitch, Kick, YouTube y similares.")
    return url


def _friendly(exc):
    msg = str(exc).lower()
    if "subscriber" in msg or "sub-only" in msg or "sub only" in msg:
        return "Ese VOD es solo para suscriptores."
    if "private" in msg or "sign in" in msg or "login" in msg or "members-only" in msg:
        return "El video es privado o necesita iniciar sesión."
    if "404" in msg or "not found" in msg or "does not exist" in msg or "removed" in msg or "unavailable" in msg:
        return "No encuentro ese directo/VOD: ¿el link es correcto y sigue disponible?"
    if "is live" in msg or "live event will begin" in msg:
        return "Ese directo aún no tiene VOD: usa el link del VOD cuando termine (o el de un directo ya guardado)."
    if "unsupported url" in msg:
        return "Ese link no es de un video/VOD compatible."
    if "ffmpeg" in msg:
        return "Falló ffmpeg al cortar el tramo."
    return "No pude descargar ese tramo."


def probe(url):
    """Devuelve (titulo, duracion_en_segundos_o_None) sin descargar nada."""
    import yt_dlp
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise StreamClipError(_friendly(e))
    if info.get("is_live"):
        raise StreamClipError(_friendly("is live"))
    return info.get("title") or "directo", info.get("duration")


def download_range(url, start, end, out_dir, ffmpeg_dir=None):
    """Descarga [start, end) en out_dir/source.mp4 y devuelve esa ruta."""
    import yt_dlp
    from yt_dlp.utils import download_range_func

    out_dir = Path(out_dir)
    opts = {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "download_ranges": download_range_func(None, [(start, end)]),
        "force_keyframes_at_cuts": True,
        "outtmpl": str(out_dir / "source.%(ext)s"),
        "retries": 3, "fragment_retries": 3,
        "overwrites": True,
    }
    if ffmpeg_dir:
        opts["ffmpeg_location"] = str(ffmpeg_dir)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as e:
        raise StreamClipError(_friendly(e))
    out = out_dir / "source.mp4"
    if not out.is_file() or out.stat().st_size == 0:
        found = next((p for p in out_dir.glob("source.*") if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov")), None)
        if not found:
            raise StreamClipError("No se generó el video de ese tramo.")
        return found
    return out
