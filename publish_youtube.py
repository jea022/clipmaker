#!/usr/bin/env python3
"""Sube un video como YouTube Short a una cuenta usando la API oficial (OAuth, sin guardar contrasenas)."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import captions

HERE = Path(__file__).parent
SECRETS = HERE / "secrets"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
MAX_SHORT_SECONDS = 180
GAMING_CATEGORY = "20"

NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # subprocess.CREATE_NO_WINDOW
_QUIET = {"creationflags": NO_WINDOW} if os.name == "nt" else {}


def secret_paths(account):
    client = SECRETS / f"client_secret_{account}.json"
    if not client.is_file():
        client = SECRETS / "client_secret.json"
    return client, SECRETS / f"token_{account}.json"


def validate_video(path):
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"No existe el video: {path}")
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(p)], text=True, **_QUIET)
    info = json.loads(out)
    w, h = info["streams"][0]["width"], info["streams"][0]["height"]
    dur = float(info["format"]["duration"])
    if h <= w:
        raise ValueError(f"YouTube solo trata como Short un video vertical o cuadrado (este es {w}x{h})")
    if dur > MAX_SHORT_SECONDS:
        raise ValueError(f"Dura {dur:.0f}s: los Shorts admiten hasta {MAX_SHORT_SECONDS}s")
    return {"width": w, "height": h, "duration": dur}


def build_body(account, title, people, privacy, cursor=0, game="gta6"):
    cap = captions.generate(account, title, people, cursor, game)
    tags = [t.lstrip("#") for t in cap["yt_hashtags"]][:15]
    return {
        "snippet": {
            "title": cap["yt_title"],
            "description": cap["yt_description"],
            "tags": tags,
            "categoryId": GAMING_CATEGORY,
            "defaultLanguage": "es",
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }


def get_credentials(account):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    client, token = secret_paths(account)
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.is_file() else None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not client.is_file():
            raise FileNotFoundError(
                f"Falta {client}. Descarga el client_secret.json de Google Cloud Console (ver README).")
        print(f"Se abrirá el navegador: inicia sesión con la cuenta de YouTube de {account}.")
        creds = InstalledAppFlow.from_client_secrets_file(str(client), SCOPES).run_local_server(port=0)
    SECRETS.mkdir(exist_ok=True)
    token.write_text(creds.to_json())
    os.chmod(token, 0o600)
    return creds


def upload(account, video, body):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    yt = build("youtube", "v3", credentials=get_credentials(account))
    media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"Subiendo… {int(status.progress() * 100)}%")
    return resp["id"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video")
    ap.add_argument("title")
    ap.add_argument("--account", required=True, choices=sorted(captions.ACCOUNTS))
    ap.add_argument("--people", nargs="*", default=[], help="ej. westcol samulx")
    ap.add_argument("--privacy", choices=["private", "unlisted", "public"], default="private")
    ap.add_argument("--dry-run", action="store_true", help="valida y muestra lo que se enviaría, sin subir")
    a = ap.parse_args()

    try:
        info = validate_video(a.video)
    except ValueError as e:
        sys.exit(str(e))
    body = build_body(a.account, a.title, a.people, a.privacy)
    print(f"Video OK: {info['width']}x{info['height']}, {info['duration']:.1f}s")
    print(json.dumps(body, ensure_ascii=False, indent=2))
    if a.dry_run:
        print("\n(dry-run: no se subió nada)")
        return
    try:
        vid = upload(a.account, a.video, body)
    except FileNotFoundError as e:
        sys.exit(str(e))
    print(f"Subido: https://youtube.com/shorts/{vid}  (privacidad: {a.privacy})")


if __name__ == "__main__":
    main()
