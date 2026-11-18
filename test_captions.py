#!/usr/bin/env python3
"""Pruebas del reparto de hashtags: validacion, rotacion equitativa, personas, juego RP, persistencia."""
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

import captions as cp

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name} {detail}")
    if not cond:
        fails.append(name)


tmp = Path(tempfile.mkdtemp())
cp.USER_FILE = tmp / "data" / "hashtags.json"
cp.CURSOR_FILE = tmp / "data" / "cursor.json"

# ---- lista recomendada cargada ----
for acc in cp.ACCOUNTS:
    d = cp.defaults(acc)
    check(f"{acc}: recomendados cargan y son validos", d["always"] == ["#GTA6", "#GTAVI"] and len(d["niche"]) >= 5 and len(d["people"]) >= 6, d["always"])
    check(f"{acc}: 5 en TikTok, 3 en Shorts, #Shorts activo", (d["count_tiktok"], d["count_shorts"], d["shorts_tag"]) == (5, 3, True))
    check(f"{acc}: GTA RP separado (no mezclado con GTA VI)", d["rp"] and not any(t.lower() in {x.lower() for x in d["niche"] + d["reserve"] + d["broad"]} for t in d["rp"]))
    check(f"{acc}: los 'por verificar' no se usan nunca",
          not (set(t.lower() for t in d["to_verify"]) & set(t.lower() for c in range(60) for t in cp.generate(acc, "x", list(d["people"]), c)["hashtags"])))
w, g = cp.defaults("wganga"), cp.defaults("gtahispa")
flat = lambda c: {t.lower() for k in ("always", "niche", "broad", "reserve") for t in c[k]} | {t.lower() for v in c["people"].values() for t in v}
check("las dos cuentas comparten solo #GTA6 y #GTAVI", flat(w) & flat(g) == {"#gta6", "#gtavi"}, sorted(flat(w) & flat(g)))
leaks = [t for c in (w, g) for k in ("always", "niche", "broad", "reserve", "rp") for t in c[k] if "leak" in t.lower() or t.lower() in ("#stake", "#bangta6", "#gta6spoilers")]
check("las listas activas no tienen filtraciones ni #stake", leaks == [], leaks)

# ---- validacion ----
ok = cp.validate_config({"always": ["gta6", "#GTAVI", "  #gta6  "], "niche": "#a1 #b2, c3;d4", "people": {"La Sapa": ["lasapa"], "ÉL Muñe": "#mune"}})
check("normaliza: agrega #, quita duplicados y espacios", ok["always"] == ["#gta6", "#GTAVI"] and ok["niche"] == ["#a1", "#b2", "#c3", "#d4"], ok["always"])
check("normaliza nombres de personas (sin acentos ni espacios)", set(ok["people"]) == {"lasapa", "elmune"}, set(ok["people"]))
check("acepta ñ y tildes en hashtags", cp.validate_config({"broad": ["#españa", "#laveladadelaño"]})["broad"] == ["#españa", "#laveladadelaño"])
for name, bad in (("espacio dentro", {"niche": [["#dos palabras"]]}), ("simbolo", {"niche": ["#ho!la"]}), ("muy corto", {"niche": ["#a"]}),
                  ("muy largo", {"niche": ["#" + "a" * 61]}), ("solo #", {"niche": ["##"]}), ("no texto", {"niche": [5]}),
                  ("lista rara", {"niche": 5}), ("demasiados en always", {"always": [f"#t{i}x" for i in range(6)]}),
                  ("demasiados en niche", {"niche": [f"#t{i}x" for i in range(81)]}), ("persona sin tags", {"people": {"ab": []}}),
                  ("persona nombre vacio", {"people": {"!!": ["#abc"]}}), ("people no dict", {"people": ["x"]}),
                  ("cuenta TikTok baja", {"count_tiktok": 1}), ("cuenta TikTok alta", {"count_tiktok": 99}), ("cuenta bool", {"count_shorts": True}),
                  ("cuenta texto", {"count_shorts": "5"}), ("cuenta nan", {"count_tiktok": float("nan")}), ("shorts_tag texto", {"shorts_tag": "si"}),
                  ("config no dict", ["x"]), ("persona con demasiados tags", {"people": {"ab": [f"#t{i}x" for i in range(6)]}})):
    try:
        cp.validate_config(bad)
        check(f"rechaza {name}", False)
    except ValueError as e:
        check(f"rechaza {name}", True, f"-> {str(e)[:50]}")
check("validate_config no modifica el original", (lambda c: (cp.validate_config(c), c)[1] == {"niche": "#a1 #b2"})({"niche": "#a1 #b2"}))

# ---- reparto: forma de cada caption ----
cfg = cp.validate_config({"always": ["#GTA6", "#GTAVI"], "niche": [f"#n{i}x" for i in range(10)], "broad": [f"#b{i}x" for i in range(6)],
                          "reserve": [f"#r{i}x" for i in range(4)], "rp": ["#rp1x", "#rp2x", "#rp3x"],
                          "people": {"ana": ["#ana1", "#ana2", "#ana3"], "luis": ["#luis1"], "eva": ["#eva1"], "pepe": ["#pepe1"]},
                          "count_tiktok": 5, "count_shorts": 3})
for n_people, who in ((0, []), (1, ["ana"]), (2, ["ana", "luis"]), (3, ["ana", "luis", "eva"]), (4, ["ana", "luis", "eva", "pepe"])):
    tags, known, unknown = cp.pick(cfg, who, 5, 7)
    check(f"{n_people} personas: siempre 5 hashtags, sin repetir, fijos primero",
          len(tags) == 5 and len({t.lower() for t in tags}) == 5 and tags[:2] == ["#GTA6", "#GTAVI"], tags)
    check(f"{n_people} personas: aparecen las del clip (max 3)", [t for t in tags if t in ("#ana1", "#luis1", "#eva1", "#pepe1")] == [{"ana": "#ana1", "luis": "#luis1", "eva": "#eva1", "pepe": "#pepe1"}[p] for p in who[:3]], tags)
ana_use = Counter(t for c in range(40) for t in cp.pick(cfg, ["ana"], 5, c)[0])
check("una persona con extras: sus hashtags extra participan en la rotacion", ana_use["#ana2"] > 0 and ana_use["#ana3"] > 0 and ana_use["#ana1"] == 40,
      (ana_use["#ana1"], ana_use["#ana2"], ana_use["#ana3"]))
check("y no acaparan: tambien salen los de nicho en clips de esa persona", sum(ana_use[t] for t in cfg["niche"]) > ana_use["#ana2"])
tags, known, unknown = cp.pick(cfg, ["Ana", "ÁNA", "nadie", "LUIS"], 5, 0)
check("nombres con mayusculas/acentos se reconocen y los desconocidos se informan", known == ["#ana1", "#luis1"] and unknown == ["nadie"], (known, unknown))
check("count mayor que el banco no rompe", len(cp.pick(cp.validate_config({"always": ["#aa1"], "niche": ["#bb1"]}), [], 15, 0)[0]) == 2)
check("banco vacio solo devuelve los fijos", cp.pick(cp.validate_config({"always": ["#aa1", "#bb1"]}), [], 5, 3)[0] == ["#aa1", "#bb1"])
check("count 3 con 2 fijos: 1 mas", len(cp.pick(cfg, [], 3, 0)[0]) == 3)

# ---- reparto equitativo ----
rot = [t for k in ("niche", "reserve") for t in cfg[k]]
use = Counter()
for c in range(70):
    for t in cp.pick(cfg, ["ana"], 5, c)[0]:
        use[t] += 1
rot_counts = [use[t] for t in rot if True]
check("rotacion: todos los de nicho/reserva se usan", min(rot_counts) > 0, rot_counts)
check("rotacion: reparto parejo (diferencia maxima 1) con las mismas personas", max(rot_counts) - min(rot_counts) <= 1, f"min={min(rot_counts)} max={max(rot_counts)}")
b_counts = [use[t] for t in cfg["broad"]]
check("rotacion: los generales tambien se reparten parejo", max(b_counts) - min(b_counts) <= 1, b_counts)
check("los fijos salen en todos los clips", use["#GTA6"] == 70 and use["#GTAVI"] == 70)
seq = [tuple(cp.pick(cfg, ["ana"], 5, c)[0]) for c in range(6)]
check("clips consecutivos no repiten el mismo set", len(set(seq)) == 6, seq[:2])
use2 = Counter(t for c in range(120) for who in (["ana"], [], ["ana", "luis"], ["luis"]) for t in cp.pick(cfg, who, 5, c)[0] if t in rot)
check("con numero de personas variable igual se usan todos", all(use2[t] > 0 for t in rot), min(use2[t] for t in rot))
check("la rotacion es determinista (mismo clip, mismo resultado)", cp.pick(cfg, ["ana"], 5, 9) == cp.pick(cfg, ["ana"], 5, 9))

# ---- juego RP ----
rp_tags, *_ = cp.pick(cfg, [], 5, 0, "gta5rp")
check("clip RP: no lleva #GTA6/#GTAVI", "#GTA6" not in rp_tags and "#GTAVI" not in rp_tags, rp_tags)
check("clip RP: lleva los dos primeros de RP como fijos", rp_tags[:2] == ["#rp1x", "#rp2x"], rp_tags)
used_rp = {t for c in range(60) for t in cp.pick(cfg, [], 5, c, "gta5rp")[0]}
check("clip RP: el resto de hashtags RP rota con los demas", "#rp3x" in used_rp)
gta6_used = {t.lower() for c in range(60) for t in cp.pick(cfg, ["ana"], 5, c, "gta6")[0]}
check("clip GTA VI: nunca lleva hashtags de RP", not ({"#rp1x", "#rp2x", "#rp3x"} & gta6_used))
try:
    cp.pick(cfg, [], 5, 0, "minecraft"); check("juego desconocido se rechaza", False)
except ValueError:
    check("juego desconocido se rechaza", True)

# ---- generate: captions de TikTok y YouTube ----
r = cp.generate("wganga", "Se le cae todo en pleno robo en GTA VI", ["westcol", "samulx"], cursor=0)
check("generate: caption de TikTok con titulo, CTA y 5 hashtags", r["tiktok_caption"].startswith("Se le cae todo") and len(r["hashtags"]) == 5 and all(t in r["tiktok_caption"] for t in r["hashtags"]))
check("generate: people_known son los hashtags principales", r["people_known"] == ["#westcol", "#samulx"], r["people_known"])
check("generate: YouTube lleva 3 hashtags y #Shorts al final", len(r["yt_hashtags"]) == 4 and r["yt_hashtags"][-1] == "#Shorts" and r["yt_hashtags"][:2] == ["#GTA6", "#GTAVI"], r["yt_hashtags"])
check("generate: titulo de YouTube termina en #Shorts y cabe en 100", r["yt_title"].endswith("#Shorts") and len(r["yt_title"]) <= 100)
check("generate: descripcion de YouTube incluye los hashtags", all(t in r["yt_description"] for t in r["yt_hashtags"]))
long_t = cp.generate("wganga", "x" * 400)
check("generate: titulo larguisimo se recorta", len(long_t["yt_title"]) <= 100 and len(long_t["tiktok_caption"].split(" #")[0]) <= 160)
off = cp.generate("wganga", "t", config={"shorts_tag": False, "always": ["#aa1"], "niche": ["#bb1", "#cc1", "#dd1"]})
check("sin #Shorts: ni en titulo ni en hashtags", "#Shorts" not in off["yt_title"] and "#Shorts" not in off["yt_hashtags"] and "#Shorts" not in off["yt_description"])
check("generate acepta cursor basura sin romper", cp.generate("wganga", "t", cursor=-5)["cursor"] == 0 and cp.generate("wganga", "t", cursor="x")["cursor"] == 0)
check("generate con cuentas distintas da sets distintos", set(cp.generate("wganga", "t")["hashtags"][2:]) != set(cp.generate("gtahispa", "t")["hashtags"][2:]))
try:
    cp.generate("otra", "t"); check("cuenta desconocida -> KeyError", False)
except KeyError:
    check("cuenta desconocida -> KeyError", True)

# ---- persistencia de lo editado ----
check("sin personalizar: usa los recomendados", not cp.is_customized("wganga") and cp.effective("wganga") == cp.defaults("wganga"))
saved = cp.save_config("wganga", {"always": ["#mio1"], "niche": ["#a1a", "#b1b"], "people": {"ana": ["#ana1"]}, "count_tiktok": 4})
check("guardar devuelve la config normalizada", saved["always"] == ["#mio1"] and saved["count_tiktok"] == 4)
check("lo guardado se usa y la cuenta queda personalizada", cp.is_customized("wganga") and cp.effective("wganga")["always"] == ["#mio1"] and cp.people_keys("wganga") == ["ana"])
check("la otra cuenta no cambia", cp.effective("gtahispa") == cp.defaults("gtahispa") and not cp.is_customized("gtahispa"))
try:
    cp.save_config("wganga", {"niche": ["#mal uno"]}); check("guardar invalido se rechaza", False)
except ValueError:
    check("guardar invalido se rechaza y no pisa lo anterior", cp.effective("wganga")["always"] == ["#mio1"])
cp.USER_FILE.write_text("{no es json")
check("archivo corrupto -> usa los recomendados", cp.effective("wganga") == cp.defaults("wganga") and not cp.is_customized("wganga"))
cp.USER_FILE.write_text(json.dumps({"wganga": {"niche": ["#mal uno"]}}))
check("config guardada invalida -> usa los recomendados", cp.effective("wganga") == cp.defaults("wganga"))
cp.save_config("wganga", {"always": ["#mio1"]})
cp.reset_config("wganga")
check("restablecer vuelve a los recomendados", cp.effective("wganga") == cp.defaults("wganga") and not cp.is_customized("wganga"))
cp.reset_config("wganga")
check("restablecer dos veces no rompe", True)

# ---- cursor persistente ----
check("cursor empieza en 0 y avanza de uno en uno", [cp.next_cursor("wganga") for _ in range(3)] == [0, 1, 2])
check("cada cuenta lleva su propio cursor", cp.next_cursor("gtahispa") == 0 and cp.next_cursor("wganga") == 3)
cp.CURSOR_FILE.write_text("basura")
check("cursor corrupto reinicia en 0", cp.next_cursor("wganga") == 0)
cp.CURSOR_FILE.write_text(json.dumps({"wganga": -4}))
check("cursor negativo reinicia en 0", cp.next_cursor("wganga") == 0)

print(f"\n{len(fails)} fallos")
sys.exit(1 if fails else 0)
