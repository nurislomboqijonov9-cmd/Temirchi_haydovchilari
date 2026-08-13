"""TEMIRCHI — Haydovchi GPS kuzatuv (alohida ilova). SQLite baza."""
import os, sqlite3, secrets, math
from datetime import datetime, timedelta, timezone

DATA_DIR = os.getenv("DATA_DIR", "/data")
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "gps.db")
TZ = timezone(timedelta(hours=5))  # Asia/Tashkent

try:
    OWNER_ID = int(os.getenv("OWNER_ID", "0") or "0")
except Exception:
    OWNER_ID = 0


def now_tk():
    return datetime.now(TZ)


def today_tk():
    return now_tk().date()


def _con():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = _con()
    con.execute("""CREATE TABLE IF NOT EXISTS haydovchilar(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ism TEXT, tel TEXT,
        kuzat_token TEXT, share_token TEXT, faol INTEGER DEFAULT 1, created TEXT)""")
    try:
        con.execute("ALTER TABLE haydovchilar ADD COLUMN share_token TEXT")
    except Exception:
        pass
    for col in ("last_seen TEXT", "offline_xabar INTEGER DEFAULT 0"):
        try:
            con.execute(f"ALTER TABLE haydovchilar ADD COLUMN {col}")
        except Exception:
            pass
    con.execute("""CREATE TABLE IF NOT EXISTS gps_nuqta(
        id INTEGER PRIMARY KEY AUTOINCREMENT, hid INTEGER, lat REAL, lon REAL,
        vaqt TEXT, acc REAL)""")
    con.execute("CREATE INDEX IF NOT EXISTS ix_gps ON gps_nuqta(hid, vaqt)")
    try:
        con.execute("ALTER TABLE haydovchilar ADD COLUMN kod TEXT")
    except Exception:
        pass
    con.commit()
    con.close()


# ---------------- Haydovchilar ----------------
def _yangi_kod(con):
    import random
    for _ in range(50):
        k = str(random.randint(100000, 999999))
        if not con.execute("SELECT 1 FROM haydovchilar WHERE kod=?", (k,)).fetchone():
            return k
    return str(random.randint(100000, 999999))


def haydovchi_qosh(ism, tel=None):
    con = _con()
    tok = secrets.token_urlsafe(10)
    kod = _yangi_kod(con)
    cur = con.execute("INSERT INTO haydovchilar(ism,tel,kuzat_token,kod,faol,created) VALUES(?,?,?,?,1,?)",
                      (ism, tel, tok, kod, now_tk().isoformat()))
    con.commit()
    rid = cur.lastrowid
    con.close()
    return rid


def haydovchi_by_kod(kod):
    con = _con()
    r = con.execute("SELECT * FROM haydovchilar WHERE kod=? AND faol=1", (str(kod).strip(),)).fetchone()
    con.close()
    return dict(r) if r else None


def haydovchi_kod(hid):
    """Kodni oladi (eski haydovchilarda bo'lmasa yaratadi)."""
    con = _con()
    r = con.execute("SELECT kod FROM haydovchilar WHERE id=?", (hid,)).fetchone()
    kod = r["kod"] if r and r["kod"] else None
    if not kod:
        kod = _yangi_kod(con)
        con.execute("UPDATE haydovchilar SET kod=? WHERE id=?", (kod, hid))
        con.commit()
    con.close()
    return kod


def haydovchi_ochir(hid):
    con = _con()
    con.execute("UPDATE haydovchilar SET faol=0 WHERE id=?", (hid,))
    con.commit()
    con.close()


def haydovchilar(faqat_faol=True):
    con = _con()
    q = "SELECT * FROM haydovchilar" + (" WHERE faol=1" if faqat_faol else "") + " ORDER BY ism, id"
    rows = con.execute(q).fetchall()
    con.close()
    return [dict(r) for r in rows]


def haydovchi_get(hid):
    con = _con()
    r = con.execute("SELECT * FROM haydovchilar WHERE id=?", (hid,)).fetchone()
    con.close()
    return dict(r) if r else None


def haydovchi_by_token(token):
    con = _con()
    r = con.execute("SELECT * FROM haydovchilar WHERE kuzat_token=?", (token,)).fetchone()
    con.close()
    return dict(r) if r else None


# ---------------- GPS ----------------
def gps_qosh(hid, points):
    if not points:
        return 0
    con = _con()
    con.executemany("INSERT INTO gps_nuqta(hid,lat,lon,vaqt,acc) VALUES(?,?,?,?,?)",
                    [(hid, float(p["lat"]), float(p["lon"]), str(p.get("vaqt") or "")[:19], float(p.get("acc") or 0))
                     for p in points if p.get("lat") is not None and p.get("lon") is not None])
    con.commit()
    con.close()
    return len(points)


def gps_kunlik(hid, sana):
    con = _con()
    rows = con.execute(
        "SELECT lat,lon,vaqt,acc FROM gps_nuqta WHERE hid=? AND substr(vaqt,1,10)=? ORDER BY vaqt",
        (hid, str(sana)[:10])).fetchall()
    con.close()
    return [dict(r) for r in rows]


def _dist_m(a, b):
    R = 6371000.0
    la1, lo1, la2, lo2 = map(math.radians, [a["lat"], a["lon"], b["lat"], b["lon"]])
    dla, dlo = la2 - la1, lo2 - lo1
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * R * math.asin(min(1, math.sqrt(h)))


def _min(t1, t2):
    try:
        return (datetime.fromisoformat(str(t2)[:19]) - datetime.fromisoformat(str(t1)[:19])).total_seconds() / 60.0
    except Exception:
        return 0.0


def gps_stops(points, min_daq=5, radius_m=60):
    stops = []
    n = len(points); i = 0
    while i < n:
        j = i + 1
        while j < n and _dist_m(points[i], points[j]) <= radius_m:
            j += 1
        dur = _min(points[i]["vaqt"], points[j - 1]["vaqt"]) if j - 1 > i else 0
        if dur >= min_daq:
            seg = points[i:j]
            stops.append({"lat": sum(p["lat"] for p in seg) / len(seg),
                          "lon": sum(p["lon"] for p in seg) / len(seg),
                          "boshlanish": points[i]["vaqt"], "tugash": points[j - 1]["vaqt"], "daqiqa": round(dur)})
            i = j
        else:
            i += 1
    return stops


def kunlik_xulosa(hid, sana):
    pts = gps_kunlik(hid, sana)
    stops = gps_stops(pts)
    dist = sum(_dist_m(pts[k - 1], pts[k]) for k in range(1, len(pts)))
    ish = ""
    if pts:
        ish = pts[0]["vaqt"][11:16] + " – " + pts[-1]["vaqt"][11:16]
    return {"nuqtalar": pts, "toxtashlar": stops, "km": round(dist / 1000, 1),
            "soni": len(pts), "ish_vaqti": ish, "toxtash_daq": sum(s["daqiqa"] for s in stops)}


def haydovchi_share_token(hid):
    """Mijozga yuborish uchun jonli-kuzatuv tokeni (o'qishga)."""
    con = _con()
    r = con.execute("SELECT share_token FROM haydovchilar WHERE id=?", (hid,)).fetchone()
    tok = r["share_token"] if r and r["share_token"] else None
    if not tok:
        tok = secrets.token_urlsafe(8)
        con.execute("UPDATE haydovchilar SET share_token=? WHERE id=?", (tok, hid))
        con.commit()
    con.close()
    return tok


def haydovchi_by_share(token):
    con = _con()
    r = con.execute("SELECT * FROM haydovchilar WHERE share_token=?", (token,)).fetchone()
    con.close()
    return dict(r) if r else None


def gps_oxirgi(hid):
    """Haydovchining eng oxirgi joylashuvi (jonli)."""
    con = _con()
    r = con.execute("SELECT lat,lon,vaqt,acc FROM gps_nuqta WHERE hid=? ORDER BY vaqt DESC LIMIT 1", (hid,)).fetchone()
    con.close()
    return dict(r) if r else None


# ---------------- Faollik (heartbeat) ----------------
def haydovchi_seen(hid):
    """Signal keldi: last_seen yangilanadi, offline belgisi olinadi.
    Agar oldin offline (xabar berilgan) bo'lsa True qaytaradi (qayta ulandi)."""
    con = _con()
    r = con.execute("SELECT offline_xabar FROM haydovchilar WHERE id=?", (hid,)).fetchone()
    edi_offline = bool(r and r["offline_xabar"])
    con.execute("UPDATE haydovchilar SET last_seen=?, offline_xabar=0 WHERE id=?",
                (now_tk().isoformat(), hid))
    con.commit()
    con.close()
    return edi_offline


def haydovchi_offline_belgila(hid):
    con = _con()
    con.execute("UPDATE haydovchilar SET offline_xabar=1 WHERE id=?", (hid,))
    con.commit()
    con.close()


def haydovchi_online(hid, daqiqa=5):
    h = haydovchi_get(hid)
    if not h or not h.get("last_seen"):
        return False
    try:
        d = (now_tk() - datetime.fromisoformat(h["last_seen"])).total_seconds() / 60
        return d <= daqiqa
    except Exception:
        return False


def last_seen_daqiqa(last_seen):
    if not last_seen:
        return None
    try:
        return (now_tk() - datetime.fromisoformat(last_seen)).total_seconds() / 60
    except Exception:
        return None


def gps_age_daqiqa(vaqt):
    """GPS nuqta vaqti (Toshkent, naive) dan hozirgacha necha daqiqa."""
    try:
        d = datetime.fromisoformat(str(vaqt)[:19])
        now = now_tk().replace(tzinfo=None)
        return (now - d).total_seconds() / 60
    except Exception:
        return None


# ---------------- Yetkazish (mijozga jonli ssilka) ----------------
def yetkazish_qosh(haydovchi_id, lat, lon, izoh=None):
    """Yangi yetkazish yaratadi, token qaytaradi."""
    tok = secrets.token_urlsafe(8)
    con = _con()
    con.execute("""CREATE TABLE IF NOT EXISTS yetkazish(
        token TEXT PRIMARY KEY, haydovchi_id INTEGER,
        mlat REAL, mlon REAL, izoh TEXT,
        holat TEXT DEFAULT 'faol', created TEXT, yakun TEXT)""")
    con.execute("INSERT INTO yetkazish(token,haydovchi_id,mlat,mlon,izoh,holat,created) VALUES(?,?,?,?,?,'faol',?)",
                (tok, int(haydovchi_id), float(lat), float(lon), izoh, now_tk().isoformat()))
    con.commit()
    con.close()
    return tok


def yetkazish_get(token):
    con = _con()
    con.execute("""CREATE TABLE IF NOT EXISTS yetkazish(
        token TEXT PRIMARY KEY, haydovchi_id INTEGER,
        mlat REAL, mlon REAL, izoh TEXT,
        holat TEXT DEFAULT 'faol', created TEXT, yakun TEXT)""")
    r = con.execute("SELECT * FROM yetkazish WHERE token=?", (token,)).fetchone()
    con.close()
    return dict(r) if r else None


def yetkazish_yakunla(token):
    con = _con()
    con.execute("UPDATE yetkazish SET holat='yakunlandi', yakun=? WHERE token=?",
                (now_tk().isoformat(), token))
    con.commit()
    con.close()
