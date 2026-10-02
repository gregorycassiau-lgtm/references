#!/usr/bin/env python3
"""Construit le portfolio Les Conteurs à partir de la base Notion publique.

Étapes : lecture de la base → téléchargement des nouveaux médias → compression
(vidéos H.264 720p, images WebP) → génération de dist/ prêt pour Netlify.

Les médias déjà traités sont gardés dans media/ (cache) : seules les nouvelles
références, ou les fichiers remplacés dans Notion, sont retéléchargés.

Usage : python3 scripts/build.py [--only-data]
"""
import json, os, re, shutil, subprocess, sys, unicodedata, urllib.request, concurrent.futures as cf
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config/site.json").read_text())
TITLES = json.loads((ROOT / "config/titles.json").read_text())
MEDIA = ROOT / "media"          # cache persistant (vidéos, posters, images, PDF)
RAW = ROOT / ".raw"             # téléchargements bruts, supprimés après traitement
DIST = ROOT / "dist"
N = CFG["notion"]
API = N["site"].rstrip("/") + "/api/v3"

def log(*a): print(*a, flush=True)

UA = {"user-agent": "Mozilla/5.0 (portfolio-les-conteurs; +https://www.les-conteurs.com)"}

def post(path, body):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), headers={"content-type": "application/json", **UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())

def unwrap(v):
    v = v.get("value", v)
    return v.get("value", v) if isinstance(v, dict) and "value" in v and isinstance(v["value"], dict) else v

def rich(prop):
    return "".join(seg[0] for seg in (prop or []))

# ---------- 1. Lecture de la base ----------
def read_rows():
    d = post("/queryCollection", {
        "collection": {"id": N["collection_id"], "spaceId": N["space_id"]},
        "collectionView": {"id": N["view_id"], "spaceId": N["space_id"]},
        "loader": {"type": "reducer", "reducers": {"collection_group_results": {"type": "results", "limit": 1000}},
                   "searchQuery": "", "userTimeZone": "Europe/Paris"}})
    ids = d["result"]["reducerResults"]["collection_group_results"]["blockIds"]
    coll = unwrap(next(iter(d["recordMap"]["collection"].values())))
    schema = {k: (v["name"], v["type"]) for k, v in coll["schema"].items()}
    byname = {name: key for key, (name, _) in schema.items()}
    blocks = d["recordMap"]["block"]
    rows = []
    for bid in ids:
        b = unwrap(blocks[bid]); p = b.get("properties", {})
        def val(name):
            k = byname.get(name)
            return rich(p.get(k)) if k else ""
        def multi(name):
            v = val(name); return [x.strip() for x in v.split(",") if x.strip()]
        # Colonnes optionnelles : si « Publié » existe, seules les lignes cochées sont publiées.
        if "Publié" in byname and val("Publié") != "Yes":
            continue
        rows.append({"id": bid, "name": val("Nom").strip(), "cats": multi("Références"),
                     "supports": multi("Supports"), "markets": multi("Marchés"),
                     "client": val("Client").strip(), "sector": val("Secteur").strip(),
                     "context": val("Contexte").strip(), "results": val("Résultats").strip()})
    return rows

# ---------- 2. Contenu de chaque page ----------
_blocks = {}
def load_page(pid):
    cursor, chunk = {"stack": []}, 0
    while True:
        d = post("/loadCachedPageChunkV2", {"page": {"id": pid}, "limit": 100, "cursor": cursor,
                                             "chunkNumber": chunk, "verticalColumns": False})
        for k, v in d.get("recordMap", {}).get("block", {}).items():
            _blocks[k] = unwrap(v)
        cur = d.get("cursors") or []
        if not cur or chunk > 30: break
        cursor, chunk = cur[0], chunk + 1

def walk(bid, out, depth=0):
    if bid not in _blocks: load_page(bid)
    b = _blocks.get(bid)
    if not b or not b.get("alive", True): return
    t = b.get("type"); props = b.get("properties", {})
    if t in ("image", "video", "file", "pdf"):
        src = rich(props.get("source"))
        if src.startswith("attachment:"):
            out.append({"kind": "doc" if t in ("file", "pdf") else t, "id": bid, "src": src,
                        "caption": rich(props.get("caption")).strip()})
    if t == "page" and depth > 0: return
    for c in b.get("content", []) or []:
        walk(c, out, depth + 1)

# ---------- 3. Médias ----------
def signed_url(item):
    d = post("/getSignedFileUrls", {"urls": [{"url": item["src"], "permissionRecord": {"table": "block", "id": item["id"]},
                                               "spaceId": N["space_id"]}]})
    return d["signedUrls"][0]

def sh(*cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:stream_side_data=rotation:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    j = json.loads(r.stdout); s = j["streams"][0]
    return s["width"], s["height"], float(j["format"]["duration"])

POSTER_VERSION = 2   # augmenter pour forcer le recalcul des miniatures en CI

def make_poster(src, dst):
    """Miniature nette tirée de l'original : on teste 9 instants et on garde l'image la plus nette.

    Côté court de 1080 px (ou la taille d'origine si elle est plus petite), pour rester net
    une fois recadré en 4:5 sur un écran Retina.
    """
    from PIL import Image, ImageFilter, ImageStat
    _, _, d = probe(src)
    tmp = Path(str(dst) + ".cand.png")
    best = (-1.0, None)
    scale = "scale='if(gte(iw,ih),-2,min(1080,iw))':'if(gte(iw,ih),min(1080,ih),-2)'"
    for frac in (0.12, 0.2, 0.28, 0.36, 0.44, 0.52, 0.6, 0.68, 0.76):
        t = max(1.0, d * frac) if d > 2.5 else d * 0.5
        try:
            sh("ffmpeg", "-nostdin", "-y", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1", "-vf", scale, str(tmp))
            im = Image.open(tmp).convert("RGB")
        except Exception:
            continue
        g = im.convert("L")
        mean = ImageStat.Stat(g).mean[0]
        if mean < 28 or mean > 235:          # écran noir, fondu ou carton blanc
            continue
        small = g.resize((max(1, g.width // 2), max(1, g.height // 2)))
        sharp = ImageStat.Stat(small.filter(ImageFilter.FIND_EDGES)).var[0]
        if sharp > best[0]:
            best = (sharp, im.copy())
    tmp.unlink(missing_ok=True)
    if best[1] is None:                       # repli : image au milieu
        sh("ffmpeg", "-nostdin", "-y", "-ss", f"{d/2:.2f}", "-i", str(src), "-frames:v", "1", "-vf", scale, str(tmp))
        best = (0, Image.open(tmp).convert("RGB")); tmp.unlink(missing_ok=True)
    best[1].save(dst, "WEBP", quality=82, method=6)

def fetch_raw(item):
    RAW.mkdir(exist_ok=True)
    ext = os.path.splitext(item["src"].split(":")[-1])[1].lower() or ".bin"
    raw = RAW / f"{item['id']}{ext}"
    with urllib.request.urlopen(urllib.request.Request(signed_url(item), headers=UA), timeout=1800) as r, open(raw, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    return raw, ext

def refresh_poster(item, manifest):
    """Recalcule seulement la miniature d'une vidéo déjà compressée."""
    raw, _ = fetch_raw(item)
    make_poster(raw, MEDIA / "p" / f"{item['id']}.webp")
    raw.unlink(missing_ok=True)
    log("  ✓ miniature", item["id"])
    return item["id"], {**manifest[item["id"]], "pv": POSTER_VERSION}

def process(item, manifest):
    """Télécharge et compresse un média s'il est nouveau ou a changé. Renvoie ses métadonnées."""
    key = item["id"]
    if manifest.get(key, {}).get("src") == item["src"]:
        return key, manifest[key]
    raw, ext = fetch_raw(item)
    meta = {"src": item["src"]}
    if item["kind"] == "video":
        (MEDIA / "v").mkdir(parents=True, exist_ok=True); (MEDIA / "p").mkdir(parents=True, exist_ok=True)
        _, _, d = probe(raw)
        short = 540 if d > 80 else 720
        cap = max(250, min(600, int(13.5 * 8 * 1024 / d) - 70))   # < 14 Mo par fichier
        out = MEDIA / "v" / f"{key}.mp4"
        sh("ffmpeg", "-nostdin", "-y", "-i", str(raw), "-map", "0:v:0", "-map", "0:a:0?",
           "-vf", f"scale='if(gte(iw,ih),-2,{short})':'if(gte(iw,ih),{short},-2)'",
           "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-crf", "26", "-maxrate", f"{cap}k", "-bufsize", f"{cap*2}k",
           "-c:a", "aac", "-b:a", "64k", "-ac", "2", "-movflags", "+faststart", str(out))
        make_poster(raw, MEDIA / "p" / f"{key}.webp")
        w, h, d = probe(out)
        meta.update(w=w, h=h, d=round(d), pv=POSTER_VERSION)
    elif item["kind"] == "image":
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        (MEDIA / "i").mkdir(parents=True, exist_ok=True)
        im = Image.open(raw).convert("RGB"); w, h = im.size
        if max(w, h) > 1800:
            s = 1800 / max(w, h); im = im.resize((round(w * s), round(h * s)), Image.LANCZOS)
        im.save(MEDIA / "i" / f"{key}.webp", "WEBP", quality=80, method=6)
        meta.update(w=im.size[0], h=im.size[1])
    else:
        (MEDIA / "d").mkdir(parents=True, exist_ok=True)
        if ext == ".pdf":
            shutil.copy(raw, MEDIA / "d" / f"{key}.pdf")
            sh("pdftoppm", "-r", "60", "-f", "1", "-l", "1", "-singlefile", "-png", str(raw), str(RAW / key))
            sh("convert", str(RAW / f"{key}.png"), "-quality", "80", str(MEDIA / "d" / f"{key}.webp"))
            meta.update(ext="pdf")
        else:
            return key, None
    raw.unlink(missing_ok=True)
    log("  ✓", item["kind"], key)
    return key, meta

# ---------- 4. Assemblage ----------
def clean_title(src):
    n = re.sub(r"\.[a-z0-9]{2,4}$", "", src.split(":", 2)[-1], flags=re.I)
    n = re.sub(r"(_V\d+|_VF|_\(\d+\)|_4K|_HD)+", " ", n, flags=re.I)
    n = re.sub(r"[_-]+", " ", n).strip()
    return n[:1].upper() + n[1:].lower() if n else "Vidéo"

def slug(s):
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")

def main():
    only_data = "--only-data" in sys.argv
    MEDIA.mkdir(exist_ok=True)
    mpath = MEDIA / "manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {}

    rows = read_rows()
    log(f"{len(rows)} lignes dans la base Notion")
    for r in rows:
        items = []; walk(r["id"], items)
        # Une capture d'écran placée en tête de page n'est pas publiée :
        # la carte utilise une miniature vidéo (voir covers dans config/site.json).
        if items and items[0]["kind"] == "image" and re.match(r"(Capture|Screenshot)", items[0]["src"].split(":", 2)[-1], re.I):
            items.pop(0)
        r["items"] = items

    todo = [it for r in rows for it in r["items"] if manifest.get(it["id"], {}).get("src") != it["src"]]
    log(f"{len(todo)} média(s) nouveau(x) ou modifié(s)")
    if todo and not only_data:
        with cf.ThreadPoolExecutor(2) as ex:
            for key, meta in ex.map(lambda it: process(it, manifest), todo):
                if meta: manifest[key] = meta
        mpath.write_text(json.dumps(manifest, indent=1))

    stale = [it for r in rows for it in r["items"] if it["kind"] == "video" and it["id"] in manifest
             and manifest[it["id"]].get("src") == it["src"] and manifest[it["id"]].get("pv", 1) < POSTER_VERSION]
    if stale and not only_data:
        log(f"{len(stale)} miniature(s) à recalculer")
        with cf.ThreadPoolExecutor(3) as ex:
            for key, meta in ex.map(lambda it: refresh_poster(it, manifest), stale):
                manifest[key] = meta
        mpath.write_text(json.dumps(manifest, indent=1))

    aliases, cats_map = CFG["client_aliases"], CFG["categories"]
    clients, order = {}, []
    for r in rows:
        if not r["items"]: continue
        # « Client - Volet » regroupe plusieurs lignes sous un même client, chaque volet devient un chapitre.
        suffix = ""
        if r["client"]: name = r["client"]
        elif r["name"] in aliases: name = aliases[r["name"]]
        elif " - " in r["name"]: name, suffix = [x.strip() for x in r["name"].split(" - ", 1)]
        else: name = r["name"]
        if name not in clients:
            clients[name] = {"name": name, "sector": r["sector"] or CFG["sectors"].get(name, ""), "cats": [],
                             "supports": [], "markets": [], "chapters": [], "links": CFG["links"].get(name, []),
                             "context": "", "results": ""}
            order.append(name)
        c = clients[name]
        for k in ("context", "results"):
            if r[k] and r[k] not in c[k]: c[k] = (c[k] + "\n\n" + r[k]).strip()
        cats = [cats_map.get(x, x) for x in r["cats"]]
        if "UGC" in r["name"] and "UGC" not in cats: cats.append("UGC")
        for key, vals in (("cats", cats), ("supports", r["supports"]), ("markets", r["markets"])):
            for x in vals:
                if x not in c[key]: c[key].append(x)
        ch = {"label": suffix or " · ".join(cats), "videos": [], "images": [], "docs": []}
        n_auto = 0
        for it in r["items"]:
            m = manifest.get(it["id"])
            if not m: continue
            if it["kind"] == "video":
                t = it["caption"] or TITLES.get(it["id"])
                if not t:
                    n_auto += 1; t = f"Vidéo {n_auto}" if "copy" in it["src"] or "ssstik" in it["src"] else clean_title(it["src"])
                ch["videos"].append({"id": it["id"], "t": t, "w": m["w"], "h": m["h"], "d": m["d"]})
            elif it["kind"] == "image":
                ch["images"].append({"id": it["id"], "w": m["w"], "h": m["h"]})
            elif m.get("ext") == "pdf":
                ch["docs"].append({"id": it["id"], "t": it["caption"] or TITLES.get(it["id"]) or clean_title(it["src"]),
                                   "cover": f"{it['id']}.webp"})
        if ch["videos"] or ch["images"] or ch["docs"]:
            c["chapters"].append(ch)

    data = [clients[n] for n in order if clients[n]["chapters"]]
    covers = {}
    for c in data:
        # Miniature de carte : la vidéo choisie dans config/site.json, sinon la première vidéo.
        vid = CFG["covers"].get(c["name"])
        if vid and (MEDIA / "p" / f"{vid}.webp").exists(): covers[c["name"]] = f"p/{vid}.webp"

    # dist/
    shutil.rmtree(DIST, ignore_errors=True); DIST.mkdir()
    used = set()
    for c in data:
        for ch in c["chapters"]:
            used |= {f"v/{v['id']}.mp4" for v in ch["videos"]} | {f"p/{v['id']}.webp" for v in ch["videos"]}
            used |= {f"i/{i['id']}.webp" for i in ch["images"]}
            used |= {f"d/{d['id']}.pdf" for d in ch["docs"]} | {f"d/{d['id']}.webp" for d in ch["docs"]}
    used |= set(covers.values())
    for rel in used:
        (DIST / rel).parent.mkdir(parents=True, exist_ok=True)
        os.link(MEDIA / rel, DIST / rel)

    tpl = (ROOT / "src/template.html").read_text()
    page = (tpl.replace("/*DATA*/[]", json.dumps(data, ensure_ascii=False))
               .replace("/*COVER*/{}", json.dumps(covers, ensure_ascii=False)))
    cut = page.index("</style>") + len("</style>")         # titre, polices et styles vont dans <head>
    (DIST / "index.html").write_text(
        '<!doctype html>\n<html lang="fr">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<meta name="robots" content="noindex">\n<link rel="icon" href="favicon.svg">\n'
        + page[:cut] + "\n</head>\n<body>\n" + page[cut:] + "\n</body>\n</html>\n")
    (DIST / "fragment.html").write_text(page)          # version sans <head>, pour une page Claude
    shutil.copy(ROOT / "src/favicon.svg", DIST / "favicon.svg")
    (DIST / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))

    nv = sum(len(ch["videos"]) for c in data for ch in c["chapters"])
    ni = sum(len(ch["images"]) for c in data for ch in c["chapters"])
    log(f"OK : {len(data)} clients, {nv} vidéos, {ni} visuels → dist/")
    shutil.rmtree(RAW, ignore_errors=True)

if __name__ == "__main__":
    main()
