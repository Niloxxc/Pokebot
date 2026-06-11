import discord
from discord.ext import commands, tasks
import urllib.request
import json
import os
import re
import asyncio
from datetime import datetime
from html.parser import HTMLParser

CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return default_config()

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

def default_config():
    return {
        "discord_token": "TOKEN_WIRD_AUS_RAILWAY_GELADEN",
        "channel_id": 1462919742179246322,
        "interval_minutes": 10,
        "max_price_eur": 200,
        "keywords": [
            "booster display","booster box","36er booster","booster bundle",
            "elite trainer box","top trainer box","etb","ttb","blister","tin",
            "display","booster","special collection","kollektion","vorbestellung",
            "restock","build & battle","build and battle"
        ],
        "blocked_keywords": [
            "einzelkarte","single","used","gebraucht","beschädigt","damaged",
            "sleeves","hülle","ordner","binder","playmat","psa","bgs","graded",
            "proxy","fake","suche","wanted","tausch","acryl case","spielbares deck",
            "structure deck","yugioh","one piece","lorcana","magic the gathering",
            "dragon ball","toploader","portfolio"
        ],
        "rossmann_products": [
            {"name": "Pokemon TCG Mini Tin", "url": "https://www.rossmann.de/de/ideenwelt-amigo-pokemon-tcg-mini-tin/p/4007396203073"},
            {"name": "Pokemon Boosterpack Ewige Rivalen", "url": "https://www.rossmann.de/de/baby-und-spielzeug-amigo-pokemon-boosterpack-karmesin-und-purpur---ewige-rivalen/p/0196214110779"},
            {"name": "Pokemon Booster Nr. 1", "url": "https://www.rossmann.de/de/baby-und-spielzeug-amigo-pokemon-booster-nr-1/p/0820650250170"}
        ],
        "shops": [],
        "seen_products": []
    }

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._text = []
        self._in_a = False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._in_a = True
            self._text = []
            for k, v in attrs:
                if k == "href":
                    self._href = v

    def handle_endtag(self, tag):
        if tag == "a" and self._in_a:
            text = " ".join(self._text).strip()
            if self._href and text:
                self.links.append((self._href, text))
            self._in_a = False
            self._href = None
            self._text = []

    def handle_data(self, data):
        if self._in_a:
            self._text.append(data.strip())

def fetch_html(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("latin-1", errors="replace")
    except Exception as e:
        print(f"[FEHLER] {url}: {e}", flush=True)
        return None

def extract_price(text):
    if not text:
        return None
    text = text.replace("\xa0", " ").replace(",", ".")
    m = re.search(r"(\d{1,4}\.?\d{0,2})\s*[€$£]|[€$£]\s*(\d{1,4}\.?\d{0,2})", text)
    if m:
        val = float(m.group(1) or m.group(2))
        if 0.5 < val < 10000:
            return val
    return None

def matches(text, keywords, blocked):
    t = text.lower()
    return any(k.lower() in t for k in keywords) and not any(b.lower() in t for b in blocked)

def check_rossmann(product):
    html = fetch_html(product["url"])
    if not html:
        return {"name": product["name"], "url": product["url"], "available": False, "price": None}
    page = html.lower()
    available_keywords = ["in den warenkorb", "jetzt kaufen", "zum warenkorb", "add to cart"]
    unavailable_keywords = ["nicht verfügbar", "ausverkauft", "nicht bestellbar", "out of stock"]
    is_available = any(kw in page for kw in available_keywords)
    is_unavailable = any(kw in page for kw in unavailable_keywords)
    available = is_available and not is_unavailable
    price = extract_price(html)
    return {"name": product["name"], "url": product["url"], "available": available, "price": price}

def scrape_shop(shop, cfg):
    print(f"Scanne {shop['name']}...", flush=True)
    html = fetch_html(shop["url"])
    if not html:
        return []
    parser = LinkParser()
    parser.feed(html)
    results = []
    seen_ids = set(cfg.get("seen_products", []))
    for href, text in parser.links:
        title = re.sub(r"\s+", " ", text).strip()
        if len(title) < 8:
            continue
        price = extract_price(title)
        if not matches(title, cfg["keywords"], cfg["blocked_keywords"]):
            continue
        if price and price > cfg["max_price_eur"]:
            continue
        if href.startswith("http"):
            link = href
        elif href.startswith("//"):
            link = "https:" + href
        elif href.startswith("/"):
            from urllib.parse import urlparse
            base = urlparse(shop["url"])
            link = f"{base.scheme}://{base.netloc}{href}"
        else:
            continue
        product_id = f"{shop['name']}::{title[:80]}"
        if product_id in seen_ids:
            continue
        results.append({"shop": shop["name"], "title": title[:120], "price": price, "link": link, "id": product_id})
        seen_ids.add(product_id)
    print(f"{shop['name']}: {len(results)} neue Produkte", flush=True)
    return results[:8]

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def build_embed(product):
    price_text = f"**{product['price']:.2f} €**" if product["price"] else "Preis — Link anklicken"
    embed = discord.Embed(title=product["title"][:256], url=product["link"], color=0xFFCC00, timestamp=datetime.utcnow())
    embed.add_field(name="💰 Preis", value=price_text, inline=True)
    embed.add_field(name="🏪 Shop", value=product["shop"], inline=True)
    embed.set_footer(text="Pokemon Deal Bot")
    return embed

def build_rossmann_embed(result):
    embed = discord.Embed(title=f"🟢 ROSSMANN VERFÜGBAR: {result['name']}", url=result["url"], color=0x00FF00, timestamp=datetime.utcnow())
    price_text = f"**{result['price']:.2f} €**" if result["price"] else "Preis im Link"
    embed.add_field(name="💰 Preis", value=price_text, inline=True)
    embed.add_field(name="🏪 Shop", value="Rossmann", inline=True)
    embed.set_footer(text="⚡ Schnell sein!")
    return embed

rossmann_status = {}

@tasks.loop(minutes=10)
async def scan_shops():
    cfg = load_config()
    channel = bot.get_channel(cfg["channel_id"])
    if not channel:
        print("[WARNUNG] Kanal nicht gefunden.", flush=True)
        return
    scan_shops.change_interval(minutes=max(5, cfg["interval_minutes"]))

    for product in cfg.get("rossmann_products", []):
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, check_rossmann, product)
        if result:
            was_available = rossmann_status.get(product["url"], False)
            if result["available"] and not was_available:
                await channel.send(embed=build_rossmann_embed(result))
            rossmann_status[product["url"]] = result["available"]
        await asyncio.sleep(2)

    active = [s for s in cfg["shops"] if s.get("enabled", True)]
    all_new = []
    for shop in active:
        loop = asyncio.get_event_loop()
        new = await loop.run_in_executor(None, scrape_shop, shop, cfg)
        all_new.extend(new)
        await asyncio.sleep(2)

    if not all_new:
        print(f"[{datetime.now().strftime('%H:%M')}] Keine neuen Angebote.", flush=True)
        return

    seen = cfg.get("seen_products", [])
    for product in all_new:
        await channel.send(embed=build_embed(product))
        seen.append(product["id"])
        await asyncio.sleep(0.5)
    cfg["seen_products"] = seen[-2000:]
    save_config(cfg)
    print(f"[{datetime.now().strftime('%H:%M')}] {len(all_new)} neue Angebote gesendet.", flush=True)

@bot.command(name="rossmann")
async def rossmann_status_cmd(ctx):
    cfg = load_config()
    embed = discord.Embed(title="Rossmann Verfügbarkeit", color=0xCC0000)
    for product in cfg.get("rossmann_products", []):
        status = rossmann_status.get(product["url"])
        val = "🟢 Verfügbar" if status is True else "🔴 Nicht verfügbar" if status is False else "⚪ Noch nicht geprüft"
        embed.add_field(name=product["name"], value=val, inline=False)
    await ctx.send(embed=embed)

@bot.command(name="status")
async def status_cmd(ctx):
    cfg = load_config()
    shops_on = sum(1 for s in cfg["shops"] if s.get("enabled"))
    embed = discord.Embed(title="Pokemon Deal Bot - Status", color=0x00BFFF)
    embed.add_field(name="Keywords", value=", ".join(cfg["keywords"]) or "-", inline=False)
    embed.add_field(name="Shops aktiv", value=f"{shops_on}/{len(cfg['shops'])}", inline=True)
    embed.add_field(name="Rossmann", value=f"{len(cfg.get('rossmann_products', []))} Produkte", inline=True)
    embed.add_field(name="Max. Preis", value=f"{cfg['max_price_eur']} EUR", inline=True)
    embed.add_field(name="Interval", value=f"{cfg['interval_minutes']} Min.", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="scan")
async def scan_now(ctx):
    await ctx.send("🔍 Starte sofortigen Scan...")
    await scan_shops()

@bot.command(name="setprice")
async def set_price(ctx, preis: float):
    cfg = load_config(); cfg["max_price_eur"] = preis; save_config(cfg)
    await ctx.send(f"✅ Maximaler Preis auf {preis:.2f} EUR gesetzt.")

@bot.command(name="addkeyword")
async def add_keyword(ctx, *, keyword: str):
    cfg = load_config()
    if keyword.lower() not in [k.lower() for k in cfg["keywords"]]:
        cfg["keywords"].append(keyword.lower()); save_config(cfg)
        await ctx.send(f"✅ Keyword '{keyword}' hinzugefugt.")
    else:
        await ctx.send(f"'{keyword}' ist bereits vorhanden.")

@bot.command(name="removekeyword")
async def remove_keyword(ctx, *, keyword: str):
    cfg = load_config()
    new_kws = [k for k in cfg["keywords"] if k.lower() != keyword.lower()]
    if len(new_kws) < len(cfg["keywords"]):
        cfg["keywords"] = new_kws; save_config(cfg)
        await ctx.send(f"✅ Keyword '{keyword}' entfernt.")
    else:
        await ctx.send(f"'{keyword}' nicht gefunden.")

@bot.command(name="hilfe")
async def hilfe(ctx):
    embed = discord.Embed(title="Bot-Befehle", color=0xFFCC00)
    for cmd, desc in [
        ("!status", "Aktuellen Status anzeigen"),
        ("!scan", "Sofort einen Scan starten"),
        ("!rossmann", "Rossmann Verfügbarkeit prüfen"),
        ("!setprice 100", "Max. Preis setzen"),
        ("!addkeyword charizard", "Keyword hinzufugen"),
        ("!removekeyword booster", "Keyword entfernen"),
    ]:
        embed.add_field(name=f"`{cmd}`", value=desc, inline=False)
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f"Bot eingeloggt als {bot.user}", flush=True)
    scan_shops.change_interval(minutes=max(5, load_config()["interval_minutes"]))
    scan_shops.start()

if __name__ == "__main__":
    cfg = load_config()
    token = os.environ.get("DISCORD_TOKEN") or cfg.get("discord_token", "")
    if not token or token in ("DEIN_DISCORD_TOKEN_HIER", "TOKEN_WIRD_AUS_RAILWAY_GELADEN", ""):
        print("Bitte DISCORD_TOKEN als Umgebungsvariable in Railway eintragen!")
    else:
        bot.run(token)
