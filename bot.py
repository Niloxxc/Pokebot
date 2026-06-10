import discord
from discord.ext import commands, tasks
import urllib.request
import urllib.error
import json
import os
import re
import asyncio
from datetime import datetime
from html.parser import HTMLParser

# ── Config ────────────────────────────────────────────────────────────────────
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
        "discord_token": "DEIN_DISCORD_TOKEN_HIER",
        "channel_id": 0,
        "interval_minutes": 30,
        "max_price_eur": 200,
        "keywords": ["booster","display","etb","elite trainer box","tin","scarlet violet","pikachu","ex box","pokemon karten"],
        "blocked_keywords": ["einzelkarte","used","gebraucht","beschadigt"],
        "shops": [
            {"name": "eBay Kleinanzeigen", "url": "https://www.kleinanzeigen.de/s-pokemon-booster/k0", "enabled": True},
            {"name": "Galaxus", "url": "https://www.galaxus.de/s1/q?q=pokemon+booster", "enabled": True},
            {"name": "GameStop", "url": "https://www.gamestop.de/search/?q=pokemon+booster", "enabled": False}
        ],
        "seen_products": []
    }

# ── Einfacher HTML-Parser (kein lxml/bs4 nötig) ───────────────────────────────
class LinkTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []       # (href, text)
        self._current_href = None
        self._current_text = []
        self._in_a = False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._in_a = True
            self._current_text = []
            for k, v in attrs:
                if k == "href":
                    self._current_href = v

    def handle_endtag(self, tag):
        if tag == "a" and self._in_a:
            text = " ".join(self._current_text).strip()
            if self._current_href and text:
                self.links.append((self._current_href, text))
            self._in_a = False
            self._current_href = None
            self._current_text = []

    def handle_data(self, data):
        if self._in_a:
            self._current_text.append(data.strip())

def fetch_html(url: str) -> str | None:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
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

def extract_price(text: str) -> float | None:
    text = text.replace("\xa0", " ").replace(",", ".")
    m = re.search(r"(\d{1,4}\.?\d{0,2})\s*[€$£]|[€$£]\s*(\d{1,4}\.?\d{0,2})", text)
    if m:
        val = float(m.group(1) or m.group(2))
        if 0.5 < val < 10000:
            return val
    return None

def matches(text: str, keywords: list, blocked: list) -> bool:
    t = text.lower()
    return any(k.lower() in t for k in keywords) and not any(b.lower() in t for b in blocked)

def scrape_shop(shop: dict, cfg: dict) -> list:
    html = fetch_html(shop["url"])
    if not html:
        return []
    
    parser = LinkTextParser()
    parser.feed(html)
    
    results = []
    seen_ids = set(cfg.get("seen_products", []))
    
    for href, text in parser.links:
        # Text säubern
        title = re.sub(r"\s+", " ", text).strip()
        if len(title) < 10:
            continue
        
        price = extract_price(title)
        
        if not matches(title, cfg["keywords"], cfg["blocked_keywords"]):
            continue
        if price and price > cfg["max_price_eur"]:
            continue
        
        # Vollständige URL bauen
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
        
        results.append({
            "shop": shop["name"],
            "title": title[:120],
            "price": price,
            "link": link,
            "id": product_id
        })
        seen_ids.add(product_id)
    
    return results[:10]  # max 10 pro Shop

# ── Discord Bot ───────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def build_embed(product: dict) -> discord.Embed:
    price_text = f"**{product['price']:.2f} €**" if product["price"] else "Preis unbekannt"
    embed = discord.Embed(
        title=product["title"][:256],
        url=product["link"],
        color=0xFFCC00,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Preis", value=price_text, inline=True)
    embed.add_field(name="Shop", value=product["shop"], inline=True)
    embed.set_footer(text="Pokemon Deal Bot")
    return embed

@tasks.loop(minutes=30)
async def scan_shops():
    cfg = load_config()
    channel = bot.get_channel(cfg["channel_id"])
    if not channel:
        print("[WARNUNG] Kanal nicht gefunden. Bitte channel_id in config.json setzen.")
        return

    scan_shops.change_interval(minutes=max(5, cfg["interval_minutes"]))
    active = [s for s in cfg["shops"] if s.get("enabled", True)]

    all_new = []
    for shop in active:
        loop = asyncio.get_event_loop()
        new = await loop.run_in_executor(None, scrape_shop, shop, cfg)
        all_new.extend(new)
        await asyncio.sleep(3)

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
    shops_on = sum(1 for s in cfg["shops"] if s.get("enabled"))
    embed = discord.Embed(title="Pokemon Deal Bot - Status", color=0x00BFFF)
    embed.add_field(name="Schlusselworter", value=", ".join(cfg["keywords"]) or "-", inline=False)
    embed.add_field(name="Shops aktiv", value=f"{shops_on}/{len(cfg['shops'])}", inline=True)
    embed.add_field(name="Max. Preis", value=f"{cfg['max_price_eur']} EUR", inline=True)
    embed.add_field(name="Interval", value=f"{cfg['interval_minutes']} Min.", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="scan")
async def scan_now(ctx):
    await ctx.send("Starte sofortigen Scan...")
    await scan_shops()

@bot.command(name="setprice")
async def set_price(ctx, preis: float):
    cfg = load_config(); cfg["max_price_eur"] = preis; save_config(cfg)
    await ctx.send(f"Maximaler Preis auf {preis:.2f} EUR gesetzt.")

@bot.command(name="addkeyword")
async def add_keyword(ctx, *, keyword: str):
    cfg = load_config()
    if keyword.lower() not in [k.lower() for k in cfg["keywords"]]:
        cfg["keywords"].append(keyword.lower()); save_config(cfg)
        await ctx.send(f"Schlusselwort '{keyword}' hinzugefugt.")
    else:
        await ctx.send(f"'{keyword}' ist bereits in der Liste.")

@bot.command(name="removekeyword")
async def remove_keyword(ctx, *, keyword: str):
    cfg = load_config()
    new_kws = [k for k in cfg["keywords"] if k.lower() != keyword.lower()]
    if len(new_kws) < len(cfg["keywords"]):
        cfg["keywords"] = new_kws; save_config(cfg)
        await ctx.send(f"Schlusselwort '{keyword}' entfernt.")
    else:
        await ctx.send(f"'{keyword}' nicht gefunden.")

@bot.command(name="hilfe")
async def hilfe(ctx):
    embed = discord.Embed(title="Bot-Befehle", color=0xFFCC00)
    for cmd, desc in [
        ("!status", "Aktuellen Status anzeigen"),
        ("!scan", "Sofort einen Scan starten"),
        ("!setprice 100", "Max. Preis auf 100 EUR setzen"),
        ("!addkeyword charizard", "Schlusselwort hinzufugen"),
        ("!removekeyword booster", "Schlusselwort entfernen"),
    ]:
        embed.add_field(name=f"`{cmd}`", value=desc, inline=False)
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f"Bot eingeloggt als {bot.user}")
    if load_config()["channel_id"] == 0:
        print("WICHTIG: Bitte channel_id in config.json eintragen!")
    scan_shops.change_interval(minutes=max(5, load_config()["interval_minutes"]))
    scan_shops.start()

if __name__ == "__main__":
    cfg = load_config()
    token = cfg.get("discord_token", "")
    if not token or token == "DEIN_DISCORD_TOKEN_HIER":
        print("Bitte erst discord_token in config.json eintragen!")
    else:
        bot.run(token)
