import discord
from discord.ext import commands, tasks
import urllib.request
import json
import os
import re
import asyncio
import xml.etree.ElementTree as ET
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
            "elite trainer box","top trainer box","etb pokemon","ttb pokemon",
            "pokemon etb","pokemon ttb","blister pokemon","pokemon blister",
            "booster blister","3er blister","build & battle box","build and battle"
        ],
        "blocked_keywords": [
            "einzelkarte","single","used","gebraucht","beschädigt","damaged",
            "sleeves","hülle","ordner","binder","deck box","playmat","acryl",
            "case","psa","bgs","graded","proxy","fake","suche","wanted","tausch"
        ],
        "rss_feeds": [
            {"name": "Kleinanzeigen - Pokemon Booster", "url": "https://www.kleinanzeigen.de/s-pokemon-booster/k0/l0-rss.xml", "enabled": True},
            {"name": "Kleinanzeigen - Pokemon Display", "url": "https://www.kleinanzeigen.de/s-pokemon-display/k0/l0-rss.xml", "enabled": True},
            {"name": "Kleinanzeigen - Pokemon ETB", "url": "https://www.kleinanzeigen.de/s-pokemon-elite-trainer-box/k0/l0-rss.xml", "enabled": True},
            {"name": "Kleinanzeigen - Pokemon TTB", "url": "https://www.kleinanzeigen.de/s-pokemon-top-trainer-box/k0/l0-rss.xml", "enabled": True},
            {"name": "Kleinanzeigen - Pokemon Blister", "url": "https://www.kleinanzeigen.de/s-pokemon-blister/k0/l0-rss.xml", "enabled": True}
        ],
        "seen_products": []
    }

def fetch_url(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept": "application/rss+xml, text/xml, */*",
        "Accept-Language": "de-DE,de;q=0.9",
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
        print(f"[FEHLER] {url}: {e}")
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

def extract_image(description_html):
    if not description_html:
        return None
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', description_html)
    if m:
        return m.group(1)
    return None

def matches(text, keywords, blocked):
    t = text.lower()
    return any(k.lower() in t for k in keywords) and not any(b.lower() in t for b in blocked)

def scrape_rss(feed, cfg):
    xml_data = fetch_url(feed["url"])
    if not xml_data:
        return []

    results = []
    seen_ids = set(cfg.get("seen_products", []))

    try:
        # Namespace bereinigen
        xml_data = re.sub(r' xmlns[^"]*"[^"]*"', '', xml_data)
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        print(f"[XML FEHLER] {feed['name']}: {e}")
        return []

    items = root.findall(".//item")
    for item in items:
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        description = item.findtext("description", "")
        price_text = item.findtext("price", "") or item.findtext("preis", "")

        if not title or not link:
            continue

        # Preis aus Description oder eigenem Feld
        price = extract_price(price_text) or extract_price(description) or extract_price(title)

        # Bild aus Description
        image_url = extract_image(description)

        if not matches(title, cfg["keywords"], cfg["blocked_keywords"]):
            continue
        if price and price > cfg["max_price_eur"]:
            continue

        product_id = f"{feed['name']}::{title[:80]}"
        if product_id in seen_ids:
            continue

        results.append({
            "shop": "Kleinanzeigen",
            "title": title[:120],
            "price": price,
            "link": link,
            "image": image_url,
            "id": product_id
        })
        seen_ids.add(product_id)

    return results[:10]

# ── Discord Bot ───────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def build_embed(product):
    price_text = f"**{product['price']:.2f} €**" if product["price"] else "Preis nicht angegeben"
    embed = discord.Embed(
        title=product["title"][:256],
        url=product["link"],
        color=0xFFCC00,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="💰 Preis", value=price_text, inline=True)
    embed.add_field(name="🏪 Shop", value=product["shop"], inline=True)
    if product.get("image"):
        embed.set_thumbnail(url=product["image"])
    embed.set_footer(text="Pokemon Deal Bot • Jetzt kaufen")
    return embed

@tasks.loop(minutes=10)
async def scan_shops():
    cfg = load_config()
    channel = bot.get_channel(cfg["channel_id"])
    if not channel:
        print("[WARNUNG] Kanal nicht gefunden.")
        return

    scan_shops.change_interval(minutes=max(5, cfg["interval_minutes"]))
    active_feeds = [f for f in cfg.get("rss_feeds", []) if f.get("enabled", True)]

    all_new = []
    for feed in active_feeds:
        loop = asyncio.get_event_loop()
        new = await loop.run_in_executor(None, scrape_rss, feed, cfg)
        all_new.extend(new)
        await asyncio.sleep(2)

    if not all_new:
        print(f"[{datetime.now().strftime('%H:%M')}] Keine neuen Angebote.")
        return

    seen = cfg.get("seen_products", [])
    for product in all_new:
        await channel.send(embed=build_embed(product))
        seen.append(product["id"])
        await asyncio.sleep(0.5)

    cfg["seen_products"] = seen[-1000:]
    save_config(cfg)
    print(f"[{datetime.now().strftime('%H:%M')}] {len(all_new)} neue Angebote gesendet.")

@bot.command(name="status")
async def status_cmd(ctx):
    cfg = load_config()
    feeds_on = sum(1 for f in cfg.get("rss_feeds", []) if f.get("enabled"))
    embed = discord.Embed(title="Pokemon Deal Bot - Status", color=0x00BFFF)
    embed.add_field(name="Keywords", value=", ".join(cfg["keywords"]) or "-", inline=False)
    embed.add_field(name="RSS Feeds aktiv", value=f"{feeds_on}/{len(cfg.get('rss_feeds', []))}", inline=True)
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
        ("!setprice 100", "Max. Preis auf 100 EUR setzen"),
        ("!addkeyword charizard", "Keyword hinzufugen"),
        ("!removekeyword booster", "Keyword entfernen"),
    ]:
        embed.add_field(name=f"`{cmd}`", value=desc, inline=False)
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f"Bot eingeloggt als {bot.user}")
    scan_shops.change_interval(minutes=max(5, load_config()["interval_minutes"]))
    scan_shops.start()

if __name__ == "__main__":
    cfg = load_config()
    token = os.environ.get("DISCORD_TOKEN") or cfg.get("discord_token", "")
    if not token or token in ("DEIN_DISCORD_TOKEN_HIER", "TOKEN_WIRD_AUS_RAILWAY_GELADEN", ""):
        print("Bitte DISCORD_TOKEN als Umgebungsvariable in Railway eintragen!")
    else:
        bot.run(token)
