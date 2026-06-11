import discord
from discord.ext import commands, tasks
import json
import os
import re
import asyncio
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time

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
        "shops": [
            {"name": "Kleinanzeigen Booster", "url": "https://www.kleinanzeigen.de/s-pokemon-booster/k0", "enabled": True},
            {"name": "Kleinanzeigen Display", "url": "https://www.kleinanzeigen.de/s-pokemon-display/k0", "enabled": True},
            {"name": "Kleinanzeigen ETB", "url": "https://www.kleinanzeigen.de/s-elite-trainer-box-pokemon/k0", "enabled": True},
            {"name": "Kleinanzeigen TTB", "url": "https://www.kleinanzeigen.de/s-top-trainer-box-pokemon/k0", "enabled": True},
            {"name": "Kleinanzeigen Blister", "url": "https://www.kleinanzeigen.de/s-pokemon-blister/k0", "enabled": True},
            {"name": "Card Buddys", "url": "https://www.cardbuddys.de/home/produkte/pokemon-tcg/boxen/", "enabled": True},
            {"name": "Cardsrfun", "url": "https://cardsrfun.de/collections/pokemon", "enabled": True},
            {"name": "Comic Planet", "url": "https://www.comicplanet.de/collections/pokemon", "enabled": True},
            {"name": "Farmers Shop", "url": "https://farmers-shop.de/collections/pokemon", "enabled": True},
            {"name": "Games Island", "url": "https://games-island.eu/collections/pokemon", "enabled": True},
            {"name": "Alza", "url": "https://www.alza.de/pokemon/18866989.htm", "enabled": True},
            {"name": "Gate to the Games", "url": "https://www.gate-to-the-games.de/Pokemon___TCG", "enabled": True},
            {"name": "TCGviert", "url": "https://tcgviert.com/collections/pokemon-booster", "enabled": True},
            {"name": "Pokegeodude", "url": "https://pokegeodude.shop/collections/all", "enabled": True},
            {"name": "Man of Games", "url": "https://www.man-of-games.de/pokemon", "enabled": True},
            {"name": "Duo Shop", "url": "https://www.duo-shop.de/pokemon", "enabled": True},
            {"name": "Fantasia Cards", "url": "https://fantasiacards.de/collections/pokemon", "enabled": True},
            {"name": "Lotti Cards", "url": "https://www.lotticards.de/collections/pokemon", "enabled": True},
            {"name": "Sapphire Cards", "url": "https://sapphire-cards.de/collections/pokemon", "enabled": True},
            {"name": "Card Corner", "url": "https://www.card-corner.de/collections/pokemon", "enabled": True},
            {"name": "Maxpacks", "url": "https://www.maxpacks.de/collections/all", "enabled": True}
        ],
        "seen_products": []
    }

def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

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

def scrape_shop(shop, cfg):
    driver = None
    results = []
    seen_ids = set(cfg.get("seen_products", []))
    try:
        driver = get_driver()
        driver.get(shop["url"])
        time.sleep(4)

        links = driver.find_elements(By.TAG_NAME, "a")
        for link in links:
            try:
                title = link.text.strip()
                href = link.get_attribute("href") or ""
                if len(title) < 10 or not href.startswith("http"):
                    continue
                price = extract_price(title)

                # Versuche Preis aus Eltern-Element zu holen
                if not price:
                    try:
                        parent = link.find_element(By.XPATH, "./..")
                        price = extract_price(parent.text)
                    except:
                        pass

                if not matches(title, cfg["keywords"], cfg["blocked_keywords"]):
                    continue
                if price and price > cfg["max_price_eur"]:
                    continue

                product_id = f"{shop['name']}::{title[:80]}"
                if product_id in seen_ids:
                    continue

                results.append({
                    "shop": shop["name"],
                    "title": title[:120],
                    "price": price,
                    "link": href,
                    "id": product_id
                })
                seen_ids.add(product_id)

                if len(results) >= 8:
                    break
            except:
                continue
    except Exception as e:
        print(f"[FEHLER] {shop['name']}: {e}")
    finally:
        if driver:
            driver.quit()
    return results

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def build_embed(product):
    price_text = f"**{product['price']:.2f} €**" if product["price"] else "Preis — Link anklicken"
    embed = discord.Embed(
        title=product["title"][:256],
        url=product["link"],
        color=0xFFCC00,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="💰 Preis", value=price_text, inline=True)
    embed.add_field(name="🏪 Shop", value=product["shop"], inline=True)
    embed.set_footer(text="Pokemon Deal Bot")
    return embed

@tasks.loop(minutes=10)
async def scan_shops():
    cfg = load_config()
    channel = bot.get_channel(cfg["channel_id"])
    if not channel:
        print("[WARNUNG] Kanal nicht gefunden.")
        return
    scan_shops.change_interval(minutes=max(5, cfg["interval_minutes"]))
    active = [s for s in cfg["shops"] if s.get("enabled", True)]
    all_new = []
    for shop in active:
        print(f"[{datetime.now().strftime('%H:%M')}] Scanne {shop['name']}...")
        loop = asyncio.get_event_loop()
        new = await loop.run_in_executor(None, scrape_shop, shop, cfg)
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
    cfg["seen_products"] = seen[-2000:]
    save_config(cfg)
    print(f"[{datetime.now().strftime('%H:%M')}] {len(all_new)} neue Angebote gesendet.")

@bot.command(name="status")
async def status_cmd(ctx):
    cfg = load_config()
    shops_on = sum(1 for s in cfg["shops"] if s.get("enabled"))
    embed = discord.Embed(title="Pokemon Deal Bot - Status", color=0x00BFFF)
    embed.add_field(name="Keywords", value=", ".join(cfg["keywords"]) or "-", inline=False)
    embed.add_field(name="Shops aktiv", value=f"{shops_on}/{len(cfg['shops'])}", inline=True)
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
