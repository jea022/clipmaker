"""Pruebas de streamclips (parser de minutos y validacion de links; sin red)."""
import sys

import streamclips as sc

fails = 0


def check(name, cond, extra=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name, extra if not cond else "")
    fails += 0 if cond else 1


def raises(fn, *a):
    try:
        fn(*a)
    except sc.StreamClipError as e:
        return str(e)
    return None


check("minutos sueltos", sc.parse_marks("12, 45") == [720, 2700])
check("mm:ss y h:mm:ss", sc.parse_marks("45:30 1:05:10") == [2730, 3910])
check("separadores mixtos y orden", sc.parse_marks("5;1\n3,\t2") == [60, 120, 180, 300])
check("duplicados", sc.parse_marks("1 1 1:00") == [60])
check("minuto 0", sc.parse_marks("0") == [0])
check("texto invalido", raises(sc.parse_marks, "abc 12") is not None)
check("segundos > 59", raises(sc.parse_marks, "10:75") is not None)
check("vacio", raises(sc.parse_marks, "  ") is not None)
check("demasiados", raises(sc.parse_marks, " ".join(str(i) for i in range(sc.MAX_CLIPS + 1))) is not None)
check("fmt_mark", sc.fmt_mark(65) == "1:05" and sc.fmt_mark(3910) == "1:05:10")

check("link twitch", sc.check_url("https://www.twitch.tv/videos/123") == "https://www.twitch.tv/videos/123")
check("link kick", sc.check_url("https://kick.com/video/abc").startswith("https://kick.com"))
check("link youtube corto", sc.check_url("https://youtu.be/abc") == "https://youtu.be/abc")
check("host ajeno", raises(sc.check_url, "https://evil.com/x") is not None)
check("subdominio falso", raises(sc.check_url, "https://twitch.tv.evil.com/x") is not None)
check("sin https", raises(sc.check_url, "ftp://twitch.tv/x") is not None)
check("file://", raises(sc.check_url, "file:///C:/Windows/win.ini") is not None)
check("vacio url", raises(sc.check_url, "") is not None)

print(f"\n{fails} fallos")
sys.exit(1 if fails else 0)
