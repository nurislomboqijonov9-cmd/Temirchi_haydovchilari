"""TEMIRCHI GPS — aiohttp server (haydovchi kuzatuv + ega paneli)."""
import os, json, hmac, hashlib, time, urllib.parse
from pathlib import Path
from aiohttp import web
import db

HERE = Path(__file__).parent


def validate_init_data(init_data, bot_token):
    uid, _ = _validate_debug(init_data, bot_token)
    return uid


def _validate_debug(init_data, bot_token):
    """initData ni tekshiradi (signature bilan ham, siz ham) -> (uid|None, info)."""
    info = {"init_bormi": bool(init_data), "keys": [], "sig_bormi": False,
            "hash_bormi": False, "hash_mos": False, "usul": "", "sabab": ""}
    try:
        if not init_data:
            info["sabab"] = "initData yo'q"
            return None, info
        data = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        info["keys"] = sorted(data.keys())
        info["sig_bormi"] = "signature" in data
        got = data.pop("hash", "")
        info["hash_bormi"] = bool(got)
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()

        def _hmac(d):
            chk = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
            return hmac.new(secret, chk.encode(), hashlib.sha256).hexdigest()

        # Usul A: signature CHIQARILGAN
        dA = {k: v for k, v in data.items() if k != "signature"}
        # Usul B: signature QO'SHILGAN (hamma maydon)
        okA = hmac.compare_digest(_hmac(dA), got)
        okB = hmac.compare_digest(_hmac(data), got)
        info["hash_mos"] = okA or okB
        info["usul"] = "A(sig chiqarilgan)" if okA else ("B(sig qo'shilgan)" if okB else "hech biri")
        if not info["hash_mos"]:
            info["sabab"] = "hash mos emas (BOT_TOKEN boshqa bot?)"
            return None, info
        u = json.loads(data.get("user", "{}"))
        uid = int(u.get("id")) if u.get("id") else None
        info["sabab"] = "ok" if uid else "user id yo'q"
        return uid, info
    except Exception as e:
        info["sabab"] = f"xato: {e}"
        return None, info


def make_token(uid, bot_token, kun=60):
    xom = f"{uid}.{int(time.time()) + kun*86400}"
    imzo = hmac.new(bot_token.encode(), xom.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{xom}.{imzo}"


def read_token(token, bot_token):
    try:
        uid, exp, imzo = token.rsplit(".", 2) if token.count(".") >= 2 else (None, None, None)
        xom = f"{uid}.{exp}"
        kut = hmac.new(bot_token.encode(), xom.encode(), hashlib.sha256).hexdigest()[:32]
        if hmac.compare_digest(kut, imzo) and int(exp) > time.time():
            return int(uid)
    except Exception:
        pass
    return None


def make_web_app(bot_token):
    app = web.Application()

    def _osmand_vaqt(ts):
        """OsmAnd timestamp (epoch/ISO) -> Toshkent naive vaqt."""
        import datetime as _dt
        TZ = _dt.timezone(_dt.timedelta(hours=5))
        if ts:
            try:
                v = float(ts)
                if v > 1e12:
                    v /= 1000.0
                return _dt.datetime.fromtimestamp(v, TZ).replace(tzinfo=None).isoformat()[:19]
            except Exception:
                pass
            try:
                d = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if d.tzinfo:
                    d = d.astimezone(TZ).replace(tzinfo=None)
                return d.isoformat()[:19]
            except Exception:
                pass
        return db.now_tk().replace(tzinfo=None).isoformat()[:19]

    def owner_uid(request):
        uid = validate_init_data(request.headers.get("X-Init-Data", ""), bot_token)
        if not uid:
            uid = read_token(request.headers.get("X-Token", "") or request.query.get("tok", ""), bot_token)
        return uid

    def is_owner(request):
        uid = owner_uid(request)
        return uid and (not db.OWNER_ID or uid == db.OWNER_ID)

    async def tg_xabar(chat_id, matn):
        try:
            import aiohttp as _ah
            async with _ah.ClientSession() as ss:
                await ss.post(f"https://api.telegram.org/bot{bot_token}/sendMessage",
                              json={"chat_id": chat_id, "text": matn, "parse_mode": "Markdown"},
                              timeout=_ah.ClientTimeout(total=12))
        except Exception:
            pass

    # ---------- Sahifalar ----------
    async def _file(nom, ctype="text/html"):
        yol = HERE / nom
        if not yol.exists():
            return web.Response(status=404, text="topilmadi")
        return web.FileResponse(yol, headers={"Cache-Control": "no-cache"})

    async def panel(request):
        return await _file("panel.html")

    async def api_kirish(request):
        """Haydovchi APK/brauzerda kod kiritadi -> kuzat tokenini oladi."""
        try:
            b = await request.json()
        except Exception:
            return web.json_response({"ok": False}, status=400)
        h = db.haydovchi_by_kod(b.get("kod") or "")
        if not h:
            return web.json_response({"ok": False, "xato": "Kod noto'g'ri"}, status=404)
        return web.json_response({"ok": True, "token": h["kuzat_token"], "ism": h["ism"]})

    async def manifest_hayd(request):
        return web.json_response({
            "name": "TEMIRCHI Haydovchi", "short_name": "TEMIRCHI",
            "start_url": "/kuzat", "display": "standalone", "orientation": "portrait",
            "background_color": "#0f1720", "theme_color": "#0f1720",
            "icons": [
                {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
                {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}
            ]})

    async def kuzat_kirish(request):
        """Tokensiz /kuzat — kod kiritish sahifasi (APK uchun)."""
        return await _file("kuzat.html")

    async def harita(request):
        return await _file("harita.html")

    async def manifest(request):
        return web.json_response({
            "name": "TEMIRCHI Kuzatuv", "short_name": "Kuzatuv",
            "start_url": "./", "display": "standalone",
            "background_color": "#0f1720", "theme_color": "#1E7A5A",
            "icons": [
                {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
                {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}
            ]})

    async def icon(request):
        nom = request.match_info.get("nom", "")
        if nom not in ("icon-192.png", "icon-512.png", "icon-180.png"):
            return web.Response(status=404)
        yol = HERE / nom
        if not yol.exists():
            return web.Response(status=404)
        return web.FileResponse(yol, headers={"Cache-Control": "public, max-age=86400"})

    # ---------- Haydovchi (kuzat.html) ----------
    async def api_gps(request):
        try:
            b = await request.json()
        except Exception:
            return web.json_response({"ok": False}, status=400)
        h = db.haydovchi_by_token(b.get("token") or "")
        if not h:
            return web.json_response({"ok": False, "xato": "token"}, status=404)
        n = db.gps_qosh(h["id"], b.get("points") or [])
        if db.haydovchi_seen(h["id"]) and db.OWNER_ID:
            await tg_xabar(db.OWNER_ID, f"🟢 *{h.get('ism') or 'Haydovchi'}* — qayta ulandi (davom etmoqda)")
        return web.json_response({"ok": True, "saqlandi": n})

    async def osmand(request):
        """Traccar Client (OsmAnd protokoli) — fonda GPS. id = haydovchi kodi."""
        q = dict(request.query)
        if request.method == "POST":
            try:
                post = await request.post()
                for k, v in post.items():
                    q.setdefault(k, v)
            except Exception:
                pass
        dev = (q.get("id") or q.get("deviceid") or "").strip()
        h = db.haydovchi_by_kod(dev) or db.haydovchi_by_token(dev)
        if not h:
            return web.Response(status=400, text="unknown device")
        lat = q.get("lat"); lon = q.get("lon")
        if (lat is None or lon is None) and q.get("location"):
            try:
                lat, lon = q["location"].split(",")[:2]
            except Exception:
                pass
        if lat is None or lon is None:
            db.haydovchi_seen(h["id"])
            return web.Response(status=200, text="ok")
        try:
            lat = float(lat); lon = float(lon)
        except Exception:
            return web.Response(status=200, text="ok")
        try:
            acc = float(q.get("accuracy") or q.get("hdop") or 0)
        except Exception:
            acc = 0.0
        vaqt = _osmand_vaqt(q.get("timestamp"))
        db.gps_qosh(h["id"], [{"lat": lat, "lon": lon, "vaqt": vaqt, "acc": acc}])
        if db.haydovchi_seen(h["id"]) and db.OWNER_ID:
            await tg_xabar(db.OWNER_ID, f"🟢 *{h.get('ism') or 'Haydovchi'}* — qayta ulandi (davom etmoqda)")
        return web.Response(status=200, text="ok")

    async def api_ping(request):
        """Heartbeat: ilova ochiqligini bildiradi (nuqtasiz ham)."""
        try:
            b = await request.json()
        except Exception:
            return web.json_response({"ok": False}, status=400)
        h = db.haydovchi_by_token(b.get("token") or "")
        if not h:
            return web.json_response({"ok": False}, status=404)
        if db.haydovchi_seen(h["id"]) and db.OWNER_ID:
            await tg_xabar(db.OWNER_ID, f"🟢 *{h.get('ism') or 'Haydovchi'}* — qayta ulandi (davom etmoqda)")
        return web.json_response({"ok": True})

    async def api_gps_off(request):
        try:
            b = await request.json()
        except Exception:
            return web.json_response({"ok": False}, status=400)
        h = db.haydovchi_by_token(b.get("token") or "")
        if not h:
            return web.json_response({"ok": False}, status=404)
        if db.OWNER_ID:
            vaqt = db.now_tk().strftime("%H:%M")
            await tg_xabar(db.OWNER_ID, f"⚠️ *{h.get('ism') or 'Haydovchi'}* — {b.get('sabab') or 'GPS o‘chirildi'} ({vaqt})")
        return web.json_response({"ok": True})

    # ---------- Ega (panel.html / harita.html) ----------
    async def api_haydovchilar(request):
        if not is_owner(request):
            return web.json_response({"xato": "ruxsat yo'q"}, status=401)
        sana = db.today_tk().isoformat()
        out = []
        for h in db.haydovchilar():
            x = db.kunlik_xulosa(h["id"], sana)
            ls = db.last_seen_daqiqa(h.get("last_seen"))
            out.append({"id": h["id"], "ism": h["ism"], "tel": h.get("tel"),
                        "token": h.get("kuzat_token"), "kod": h.get("kod"), "km": x["km"],
                        "toxtash": len(x["toxtashlar"]), "nuqta": x["soni"], "ish": x["ish_vaqti"],
                        "online": (ls is not None and ls <= 5),
                        "last_daq": (round(ls) if ls is not None else None)})
        return web.json_response({"haydovchilar": out})

    async def api_tv(request):
        """TV dashboard uchun ochiq (kalitli) — haydovchilar + joylashuv. CORS ochiq."""
        cors = {"Access-Control-Allow-Origin": "*"}
        kalit = os.environ.get("TV_KEY")
        if kalit and request.query.get("k") != kalit:
            return web.json_response({"xato": "ruxsat yo'q"}, status=403, headers=cors)
        sana = db.today_tk().isoformat()
        out = []
        for h in db.haydovchilar():
            x = db.kunlik_xulosa(h["id"], sana)
            ls = db.last_seen_daqiqa(h.get("last_seen"))
            p = db.gps_oxirgi(h["id"])
            out.append({"id": h["id"], "ism": h["ism"], "km": x["km"], "toxtash": len(x["toxtashlar"]),
                        "online": (ls is not None and ls <= 5),
                        "last_daq": (round(ls) if ls is not None else None),
                        "lat": (p["lat"] if p else None), "lon": (p["lon"] if p else None),
                        "vaqt": (p["vaqt"][11:16] if p and p.get("vaqt") else None)})
        return web.json_response({"haydovchilar": out}, headers=cors)

    async def api_tv_marshrut(request):
        """TV uchun — bitta haydovchining kunlik marshruti (ochiq, CORS)."""
        cors = {"Access-Control-Allow-Origin": "*"}
        kalit = os.environ.get("TV_KEY")
        if kalit and request.query.get("k") != kalit:
            return web.json_response({"xato": "ruxsat yo'q"}, status=403, headers=cors)
        try:
            hid = int(request.query.get("id"))
        except Exception:
            return web.json_response({"xato": "id kerak"}, status=400, headers=cors)
        sana = request.query.get("sana") or db.today_tk().isoformat()
        x = db.kunlik_xulosa(hid, str(sana)[:10])
        p = db.gps_oxirgi(hid)
        x["hozir"] = {"lat": p["lat"], "lon": p["lon"], "vaqt": (p["vaqt"][11:16] if p.get("vaqt") else None)} if p else None
        return web.json_response(x, headers=cors)

    async def api_haydovchi_qosh(request):
        if not is_owner(request):
            return web.json_response({"xato": "ruxsat yo'q"}, status=401)
        b = await request.json()
        ism = (b.get("ism") or "").strip()
        if not ism:
            return web.json_response({"xato": "Ism kerak"}, status=400)
        hid = db.haydovchi_qosh(ism, (b.get("tel") or "").strip() or None)
        return web.json_response({"ok": True, "id": hid})

    async def api_haydovchi_ochir(request):
        if not is_owner(request):
            return web.json_response({"xato": "ruxsat yo'q"}, status=401)
        b = await request.json()
        db.haydovchi_ochir(int(b.get("id")))
        return web.json_response({"ok": True})

    async def api_haydovchi_kuzat(request):
        if not is_owner(request):
            return web.json_response({"xato": "ruxsat yo'q"}, status=401)
        h = db.haydovchi_get(int(request.query.get("hid")))
        if not h:
            return web.json_response({"xato": "topilmadi"}, status=404)
        base = str(request.url.origin())
        return web.json_response({"havola": f"{base}/kuzat/{h['kuzat_token']}"})

    async def api_gps_view(request):
        if not is_owner(request):
            return web.json_response({"xato": "ruxsat yo'q"}, status=401)
        hid = int(request.query.get("hid"))
        sana = request.query.get("sana") or db.today_tk().isoformat()
        return web.json_response(db.kunlik_xulosa(hid, str(sana)[:10]))

    async def api_owner_token(request):
        """Panel ochilganda ega uchun token beradi (harita havolasi uchun)."""
        uid = validate_init_data(request.headers.get("X-Init-Data", ""), bot_token)
        if not uid or (db.OWNER_ID and uid != db.OWNER_ID):
            return web.json_response({"xato": "ruxsat yo'q"}, status=401)
        return web.json_response({"tok": make_token(uid, bot_token)})

    async def api_whoami(request):
        """Diagnostika: Telegram ID + OWNER_ID + tekshiruv tafsiloti."""
        uid, info = _validate_debug(request.headers.get("X-Init-Data", ""), bot_token)
        return web.json_response({
            "uid": uid, "owner_id": db.OWNER_ID or None,
            "is_owner": bool(uid and (not db.OWNER_ID or uid == db.OWNER_ID)),
            "init_bormi": info["init_bormi"], "keys": info["keys"],
            "sig_bormi": info["sig_bormi"], "hash_mos": info["hash_mos"],
            "usul": info.get("usul", ""),
            "sabab": info["sabab"], "bot_id": (bot_token.split(":")[0] if bot_token else None)})

    async def api_haydovchi_share(request):
        """Ega uchun: mijozga yuboriladigan JONLI kuzatuv havolasi."""
        if not is_owner(request):
            return web.json_response({"xato": "ruxsat yo'q"}, status=401)
        h = db.haydovchi_get(int(request.query.get("hid")))
        if not h:
            return web.json_response({"xato": "topilmadi"}, status=404)
        tok = db.haydovchi_share_token(h["id"])
        base = str(request.url.origin())
        return web.json_response({"havola": f"{base}/jonli/{tok}"})

    async def jonli(request):
        return await _file("jonli.html")

    async def api_jonli(request):
        """Ochiq (mijoz uchun): haydovchining hozirgi joylashuvi."""
        h = db.haydovchi_by_share(request.query.get("token") or "")
        if not h:
            return web.json_response({"xato": "topilmadi"}, status=404)
        p = db.gps_oxirgi(h["id"])
        age = db.gps_age_daqiqa(p["vaqt"]) if p else None
        return web.json_response({"ism": h["ism"], "nuqta": p,
                                  "daqiqa_oldin": (round(age) if age is not None else None)})

    app.router.add_get("/", panel)
    app.router.add_get("/kuzat", kuzat_kirish)
    app.router.add_get("/kuzat/{token}", kuzat_kirish)
    app.router.add_post("/api/kirish", api_kirish)
    app.router.add_get("/manifest-hayd.json", manifest_hayd)
    app.router.add_get("/harita", harita)
    app.router.add_get("/manifest.json", manifest)
    app.router.add_get("/{nom:icon-\\d+\\.png}", icon)
    app.router.add_post("/api/gps", api_gps)
    app.router.add_post("/api/ping", api_ping)
    app.router.add_post("/api/gps_off", api_gps_off)
    app.router.add_get("/api/haydovchilar", api_haydovchilar)
    app.router.add_get("/api/tv", api_tv)
    app.router.add_get("/api/tv_marshrut", api_tv_marshrut)
    app.router.add_post("/api/haydovchi_qosh", api_haydovchi_qosh)
    app.router.add_post("/api/haydovchi_ochir", api_haydovchi_ochir)
    app.router.add_get("/api/haydovchi_kuzat", api_haydovchi_kuzat)
    app.router.add_get("/osmand", osmand)
    app.router.add_post("/osmand", osmand)
    app.router.add_get("/api/gps_view", api_gps_view)
    app.router.add_get("/api/token", api_owner_token)
    app.router.add_get("/api/whoami", api_whoami)
    app.router.add_get("/jonli/{token}", jonli)
    app.router.add_get("/api/jonli", api_jonli)
    app.router.add_get("/api/haydovchi_share", api_haydovchi_share)
    return app
