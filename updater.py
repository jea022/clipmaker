"""Actualizador: compara VERSION con la del repositorio y aplica el zip nuevo sin tocar tus datos."""
import io
import json
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).parent
VERSION_FILE = HERE / "VERSION"
CONFIG_FILES = (HERE / "data" / "update.json", HERE / "update.json")
PROTECTED = {".venv", "bin", "data", "secrets", "work", "out", "__pycache__", ".git"}
PROTECTED_FILES = {"update.json"}
DEFAULT_HOSTS = ["github.com", "raw.githubusercontent.com", "codeload.github.com"]
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
MAX_ZIP_BYTES = 60 * 1024 * 1024
MAX_FILE_BYTES = 30 * 1024 * 1024
MAX_FILES = 500
TIMEOUT = 8
VERSION_RE = re.compile(r"^\d+(\.\d+){0,3}$")


class UpdateError(Exception):
    pass


def parse_version(text):
    text = (text or "").strip()
    if not VERSION_RE.match(text):
        raise UpdateError(f"Versión no válida: {text[:30]!r}")
    return tuple(int(p) for p in text.split("."))


def local_version(root=HERE):
    try:
        return (Path(root) / "VERSION").read_text().strip() or "0"
    except OSError:
        return "0"


def load_config():
    for p in CONFIG_FILES:
        try:
            cfg = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(cfg, dict) and cfg.get("version_url") and cfg.get("zip_url"):
            return cfg
    return None


def check_url(url, cfg):
    u = urlparse(url)
    hosts = set(DEFAULT_HOSTS) | set(cfg.get("allowed_hosts", []))
    if u.hostname in LOCAL_HOSTS and u.hostname in hosts:
        if u.scheme not in ("http", "https"):
            raise UpdateError("Dirección de actualización no válida")
        return
    if u.scheme != "https":
        raise UpdateError("La actualización debe venir por https")
    if u.hostname not in hosts:
        raise UpdateError(f"Dominio no permitido para actualizar: {u.hostname}")


class _SafeRedirects(urllib.request.HTTPRedirectHandler):
    """Valida cada redireccion ANTES de seguirla: nunca se conecta a un dominio no permitido."""

    def __init__(self, cfg):
        self.cfg = cfg

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl, self.cfg)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, cfg, limit):
    check_url(url, cfg)
    req = urllib.request.Request(url, headers={"User-Agent": "clipmaker-updater"})
    opener = urllib.request.build_opener(_SafeRedirects(cfg))
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            check_url(r.geturl(), cfg)
            data = r.read(limit + 1)
    except UpdateError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UpdateError(f"No pude conectar para buscar actualizaciones ({type(e).__name__})")
    if len(data) > limit:
        raise UpdateError("La descarga es demasiado grande")
    return data


def check(root=HERE):
    cfg = load_config()
    cur = local_version(root)
    if not cfg:
        return {"enabled": False, "current": cur, "available": False}
    try:
        remote = fetch(cfg["version_url"], cfg, 64).decode("utf-8", "replace").strip()
        newer = parse_version(remote) > parse_version(cur)
    except UpdateError as e:
        return {"enabled": True, "current": cur, "available": False, "error": str(e)}
    return {"enabled": True, "current": cur, "available": newer, "latest": remote, "auto": bool(cfg.get("auto"))}


def _app_prefix(names):
    """Carpeta dentro del zip que contiene app.py (GitHub añade <repo>-main/)."""
    for n in names:
        parts = n.split("/")
        if parts[-1] == "app.py" and len(parts) <= 3:
            return "/".join(parts[:-1])
    return None


def _safe_target(rel, root):
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or not p.parts or "\\" in rel or ":" in rel:
        return None
    if p.parts[0] in PROTECTED or (len(p.parts) == 1 and p.name in PROTECTED_FILES):
        return None
    target = (Path(root) / p).resolve()
    if Path(root).resolve() not in target.parents:
        return None
    return target


def apply_zip(data, root=HERE):
    """Valida el zip, hace copia de seguridad y reemplaza solo archivos de codigo."""
    root = Path(root)
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        bad = z.testzip()
    except zipfile.BadZipFile:
        raise UpdateError("El archivo descargado no es un zip válido")
    if bad:
        raise UpdateError("El zip descargado está dañado")
    infos = [i for i in z.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES:
        raise UpdateError("El zip tiene demasiados archivos")
    prefix = _app_prefix([i.filename for i in infos])
    if prefix is None:
        raise UpdateError("El zip no parece ser de Clipmaker (no trae app.py)")
    plen = len(prefix) + 1 if prefix else 0

    staged = {}
    for i in infos:
        if prefix and not i.filename.startswith(prefix + "/"):
            continue
        rel = i.filename[plen:]
        if not rel:
            continue
        target = _safe_target(rel, root)
        if target is None:
            continue
        if i.file_size > MAX_FILE_BYTES:
            raise UpdateError(f"Archivo demasiado grande en el zip: {rel}")
        staged[target] = z.read(i)
    for needed in ("VERSION", "app.py", "clipmaker.py", "static/index.html"):
        if (root / needed).resolve() not in staged:
            raise UpdateError(f"Al zip le falta {needed}")
    new_version = staged[(root / "VERSION").resolve()].decode("utf-8", "replace").strip()
    parse_version(new_version)

    backup = root / "data" / "backups"
    stamp = f"{local_version(root)}_{time.strftime('%Y%m%d_%H%M%S')}"
    bdir = backup / stamp
    done, tmp = [], None
    try:
        for target, content in staged.items():
            if target.exists():
                dst = bdir / target.relative_to(root.resolve())
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, dst)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".new")
            tmp.write_bytes(content)
            tmp.replace(target)
            done.append(target)
    except OSError as e:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
        for target in done:
            saved = bdir / target.relative_to(root.resolve())
            if saved.exists():
                shutil.copy2(saved, target)
            else:
                target.unlink(missing_ok=True)
        raise UpdateError(f"No pude escribir los archivos ({type(e).__name__}); se restauró la versión anterior")
    _prune_backups(backup)
    return {"version": new_version, "files": len(staged), "backup": str(bdir)}


def _prune_backups(backup, keep=5):
    dirs = sorted((d for d in backup.glob("*") if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
    for d in dirs[keep:]:
        shutil.rmtree(d, ignore_errors=True)


def update(root=HERE):
    cfg = load_config()
    if not cfg:
        raise UpdateError("Las actualizaciones no están configuradas")
    info = check(root)
    if info.get("error"):
        raise UpdateError(info["error"])
    if not info["available"]:
        raise UpdateError("Ya tienes la última versión")
    data = fetch(cfg["zip_url"], cfg, MAX_ZIP_BYTES)
    result = apply_zip(data, root)
    result["from"] = info["current"]
    return result
