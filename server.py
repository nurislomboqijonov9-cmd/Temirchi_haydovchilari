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

    async def kuzat(request):
        return await _file("kuzat.html")

    async def harita(request):
        return await _file("harita.html")

    async def manifest(request):
        return web.json_response({
            "name": "TEMIRCHI Kuzatuv", "short_name": "Kuzatuv",
            "start_url": ".", "display": "standalone",
            "background_color": "#0f1720", "theme_color": "#1E7A5A", "icons": []})

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
        db.haydovchi_seen(h["id"])
        return web.json_response({"ok": True, "saqlandi": n})

    async def api_ping(request):
        """Heartbeat: ilova ochiqligini bildiradi (nuqtasiz ham)."""
        try:
            b = await request.json()
        except Exception:
            return web.json_response({"ok": False}, status=400)
        h = db.haydovchi_by_token(b.get("token") or "")
        if not h:
            return web.json_response({"ok": False}, status=404)
        db.haydovchi_seen(h["id"])
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
                        "token": h.get("kuzat_token"), "km": x["km"],
                        "toxtash": len(x["toxtashlar"]), "nuqta": x["soni"], "ish": x["ish_vaqti"],
                        "online": (ls is not None and ls <= 5),
                        "last_daq": (round(ls) if ls is not None else None)})
        return web.json_response({"haydovchilar": out})

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
    app.router.add_get("/kuzat/{token}", kuzat)
    app.router.add_get("/harita", harita)
    app.router.add_get("/manifest.json", manifest)
    app.router.add_post("/api/gps", api_gps)
    app.router.add_post("/api/ping", api_ping)
    app.router.add_post("/api/gps_off", api_gps_off)
    app.router.add_get("/api/haydovchilar", api_haydovchilar)
    app.router.add_post("/api/haydovchi_qosh", api_haydovchi_qosh)
    app.router.add_post("/api/haydovchi_ochir", api_haydovchi_ochir)
    app.router.add_get("/api/haydovchi_kuzat", api_haydovchi_kuzat)
    app.router.add_get("/api/gps_view", api_gps_view)
    app.router.add_get("/api/token", api_owner_token)
    app.router.add_get("/api/whoami", api_whoami)
    app.router.add_get("/jonli/{token}", jonli)
    app.router.add_get("/api/jonli", api_jonli)
    app.router.add_get("/api/haydovchi_share", api_haydovchi_share)
    return app
