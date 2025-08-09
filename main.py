import os
import shlex
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import yt_dlp
import tempfile
from pathlib import Path
import shlex
from pathlib import Path
from collections import deque, defaultdict
import asyncio
import json
import random
import time
from datetime import datetime, timedelta, timezone
import io
import numpy as np
from aiohttp import web

# =========================
# Boot / Config
# =========================
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
FFMPEG_PATH = "/opt/homebrew/bin/ffmpeg"

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# Files / Constants
# =========================
MARRIAGE_FILE = "marriages.json"
COIN_DATA_FILE = "coins.json"
SHOP_FILE = "stocks.json"
INVENTORY_FILE = "inventories.json"
PLAYLIST_FILE = "playlists.json"
QUEST_FILE = "quests.json"
EVENT_FILE = "events.json"
STOCK_FILE = "stocks.json"
SUGGESTION_FILE = "suggestions.json"

ANNOUNCEMENT_CHANNEL_ID = 1339731366677577759
WELCOME_CHANNEL_ID = 1339586633527197727
MARKET_ANNOUNCE_CHANNEL_ID = 1402314077107261541
SUGGESTION_CHANNEL_ID = 1402758234825162893  # set to your #suggestions channel

TOP_ROLE_NAME = "🌟 EXP Top"

INTEREST_RATE = 0.02          # 2% bank interest
INTEREST_INTERVAL = 3600      # hourly
DIVIDEND_RATE = 0.01          # 1% portfolio value
DIVIDEND_INTERVAL = 86400     # daily
XP_PER_MESSAGE = 10

# Economy / Items
SHOP_ITEMS = ["Anime body pillow", "Oreo plush", "Rtx5090", "Imran's nose", "Crash token"]
ITEM_PRICES = {
    "Anime body pillow": 300,
    "Oreo plush": 150,
    "Rtx5090": 1500,
    "Crash token": 1750,
    "Imran's nose": 9999,
}
CRASH_TOKEN_NAME = "Crash token"  # normalize on this

# Stocks (consistent casing everywhere)
STOCKS = ["Oreobux", "QMkoin", "Seelsterling", "Fwizfinance"]
STOCK_PURCHASE_COUNT = {stock: 0 for stock in STOCKS}

# Blackjack (solo + placeholder for future lobbies)
SOLO_BLACKJACK_GAMES = {}
blackjack_lobbies = defaultdict(lambda: {
    "players": [],
    "bets": {},
    "dealer_hand": [],
    "game_started": False,
    "current_turn": 0,
    "hands": {},
    "scores": {},
})

# Quests / Events
QUEST_POOL = [
    {"task": "Rob someone", "command": "!rob", "reward": 100},
    {"task": "Win a gamble", "command": "!gamble", "reward": 150},
    {"task": "Use !daily", "command": "!daily", "reward": 75},
    {"task": "Buy stock", "command": "!buy <stock> <amount>", "reward": 200},
    {"task": "Reach 1 level up", "command": "Chat", "reward": 100},
]
EVENTS = {
    "Double XP": {"xp_mult": 2},
    "Crash Week": {"crash_odds": 0.3},
    "Boom Frenzy": {"boom_odds": 0.3},
    "Coin Rain": {"bonus_daily": 100},
}

# AFK / XP
AFK_STATUS = {}
DATA_FILE = "data.json"
COOLDOWN_FILE = "cooldowns.json"
VOICE_XP_COOLDOWN = {}

# Role colour reactions
ROLE_COLOR_EMOJIS = {
    "🟥": "Red",
    "🟩": "Green",
    "🟦": "Blue",
    "🟨": "Yellow",
    "🟪": "Purple",
    "⬛": "Black",
}

# Music
SONG_QUEUES = {}
LAST_PLAYED_SONG = {}
SONG_PLAY_COUNT = 0
CACHE_FOLDER = os.path.join(os.path.dirname(__file__), "cache_audio")

# Snake
wall = "⬜"
innerWall = "⬛"
energy = "🍎"
snakeHead = "😍"
snakeBody = "🟨"
snakeLoose = "😵"

WEB_RUNNER = None
# =========================
# WebRun
# =========================

async def sse_generator(request: web.Request):
    """
    Stream Server-Sent Events. Loop stops as soon as the client disconnects.
    Do whatever work you want inside the while loop.
    """
    resp = web.StreamResponse(
        status=200,
        reason='OK',
        headers={
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*',
        },
    )
    await resp.prepare(request)

    i = 0
    try:
        while True:
            # example "work": you can call your functions here
            i += 1
            # you can report bot stats, queue length, etc.
            guild_count = len(bot.guilds)
            payload = f"tick {i} | guilds={guild_count} | time={datetime.utcnow().isoformat()}"
            await resp.write(f"data: {payload}\n\n".encode("utf-8"))
            await asyncio.sleep(1)

            # stop if client left
            if request.transport is None or request.transport.is_closing():
                break
    except asyncio.CancelledError:
        pass
    except ConnectionResetError:
        pass
    finally:
        with contextlib.suppress(Exception):
            await resp.write_eof()
    return resp

async def home_page(_request: web.Request):
    html = """
<!doctype html>
<title>Bot Runner</title>
<h1>Live job (closes when you leave)</h1>
<pre id="out"></pre>
<script>
  const out = document.getElementById('out');
  const es = new EventSource('/events');
  es.onmessage = (e) => { out.textContent += e.data + "\\n"; };
  es.onerror = () => { out.textContent += "connection closed\\n"; es.close(); };
</script>
"""
    return web.Response(text=html, content_type="text/html")

async def health(_request: web.Request):
    return web.json_response({"ok": True, "guilds": len(bot.guilds)})

async def start_web():
    """Start aiohttp web server (once)."""
    global WEB_RUNNER
    if WEB_RUNNER is not None:
        return
    app = web.Application()
    app.router.add_get("/", home_page)
    app.router.add_get("/events", sse_generator)
    app.router.add_get("/health", health)

    WEB_RUNNER = web.AppRunner(app)
    await WEB_RUNNER.setup()
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(WEB_RUNNER, "0.0.0.0", port)
    await site.start()
    print(f"[web] listening on 0.0.0.0:{port}")

async def stop_web():
    global WEB_RUNNER
    if WEB_RUNNER:
        await WEB_RUNNER.cleanup()
        WEB_RUNNER = None

# optional: clean shutdown when bot closes
import contextlib
async def _close_web_on_bot_close():
    await stop_web()

# =========================
# Utilities: File I/O
# =========================
def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default

def _save_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=4)

def load_data():
    return _load_json(DATA_FILE, {})

def save_data(d):
    _save_json(DATA_FILE, d)

def load_cooldowns():
    return _load_json(COOLDOWN_FILE, {})

def save_cooldowns(d):
    _save_json(COOLDOWN_FILE, d)

def load_coins():
    return _load_json(COIN_DATA_FILE, {})

def save_coins(d):
    _save_json(COIN_DATA_FILE, d)

def load_marriages():
    return _load_json(MARRIAGE_FILE, {})

def save_marriages(d):
    _save_json(MARRIAGE_FILE, d)

def load_shop_stock():
    if not os.path.exists(SHOP_FILE):
        return {item: 0 for item in SHOP_ITEMS}
    return _load_json(SHOP_FILE, {item: 0 for item in SHOP_ITEMS})

def save_shop_stock(d):
    _save_json(SHOP_FILE, d)

def load_inventory():
    return _load_json(INVENTORY_FILE, {})

def save_inventory(d):
    _save_json(INVENTORY_FILE, d)

def load_playlists():
    return _load_json(PLAYLIST_FILE, {})

def save_playlists(d):
    _save_json(PLAYLIST_FILE, d)

def load_quests():
    return _load_json(QUEST_FILE, {})

def save_quests(d):
    _save_json(QUEST_FILE, d)

def load_event():
    return _load_json(EVENT_FILE, {})

def save_event(d):
    _save_json(EVENT_FILE, d)

def save_stocks(d):
    _save_json(STOCK_FILE, d)

def load_stocks():
    if not os.path.exists(STOCK_FILE):
        data = {
            "Oreobux": {"price": 100, "history": [100]},
            "QMkoin": {"price": 150, "history": [150]},
            "Seelsterling": {"price": 200, "history": [200]},
            "Fwizfinance": {"price": 250, "history": [250]},
        }
        save_stocks(data)
        return data
    data = _load_json(STOCK_FILE, {})
    # Repair unknown/missing structure & enforce keys/casing
    changed = False
    template = {
        "Oreobux": {"price": 100, "history": [100]},
        "QMkoin": {"price": 150, "history": [150]},
        "Seelsterling": {"price": 200, "history": [200]},
        "Fwizfinance": {"price": 250, "history": [250]},
    }
    fixed = {}
    for key in STOCKS:
        entry = data.get(key)
        if not entry:
            # try to map wrong-cased keys
            for k in data.keys():
                if k.lower() == key.lower():
                    entry = data[k]
                    changed = True
                    break
        if not entry or "price" not in entry or "history" not in entry:
            fixed[key] = template[key]
            changed = True
        else:
            fixed[key] = entry
    if changed:
        save_stocks(fixed)
    return fixed

# =========================
# Snake (reaction + command controls)
# =========================
SNAKE_GAMES = {}  # channel_id -> {"matrix": np.ndarray, "points": int, "is_out": bool, "msg_id": int}

SNAKE_CONTROLS = {
    "⬆️": "up",
    "⬇️": "down",
    "⬅️": "left",
    "➡️": "right",
    "🔄": "reset",
}

def _snake_new_matrix():
    # 12x12 with border = 0 (wall), inside = 1 (empty), head = 2, body = 3, energy = 4, lose = 5
    m = np.array([
        [0]*12,
        [0]+[1]*10+[0],
        [0]+[1]*10+[0],
        [0]+[1]*9 +[2]+[0],  # start head at (3,10)
        [0]+[1]*10+[0],
        [0]+[1]*10+[0],
        [0]+[1]*10+[0],
        [0]+[1]*10+[0],
        [0]+[1]*10+[0],
        [0]+[1]*10+[0],
        [0]+[1]*10+[0],
        [0]*12,
    ])
    return m

def _snake_generate_energy(state):
    m = state["matrix"]
    # keep trying until we place on an empty cell (1)
    for _ in range(200):
        i = random.randint(1,10)
        j = random.randint(1,10)
        if m[i][j] == 1:
            m[i][j] = 4
            return

def _snake_grid_to_text(m):
    out = []
    for row in m:
        line = []
        for v in row:
            if v == 0:
                line.append(wall)
            elif v == 1:
                line.append(innerWall)
            elif v == 2:
                line.append(snakeHead)
            elif v == 3:
                line.append(snakeBody)
            elif v == 4:
                line.append(energy)
            else:
                line.append(snakeLoose)
        out.append("".join(line))
    return "\n".join(out)

def _snake_is_boundary(i, j):
    return i == 0 or j == 0 or i == 11 or j == 11

def _snake_handle_energy(state, i, j):
    m = state["matrix"]
    if m[i][j] == 4:
        state["points"] += 1
        _snake_generate_energy(state)

def _snake_update_head(state, ni, nj):
    m = state["matrix"]
    # current head
    head = np.argwhere(m == 2)
    if head.size == 0:
        return
    hi, hj = head[0]
    m[ni][nj] = 2
    m[hi][hj] = 1  # turn old head to empty (we aren't tracking tail segments; body is cosmetic)
    # optional: leave a short body trail
    # You can comment this next line if you don't want trail:
    # m[hi][hj] = 3

def _snake_move(state, direction):
    if state["is_out"]:
        return
    m = state["matrix"]
    hi, hj = np.argwhere(m == 2)[0]
    di, dj = 0, 0
    if direction == "up":
        di, dj = -1, 0
    elif direction == "down":
        di, dj = 1, 0
    elif direction == "left":
        di, dj = 0, -1
    elif direction == "right":
        di, dj = 0, 1
    ni, nj = hi + di, hj + dj

    if _snake_is_boundary(ni, nj):
        m[hi][hj] = 5  # lose face on current head
        state["is_out"] = True
        return

    _snake_handle_energy(state, ni, nj)
    _snake_update_head(state, ni, nj)

async def _snake_render(ctx_or_channel, state, *, title="Pick Apple Game"):
    desc = _snake_grid_to_text(state["matrix"])
    embed = discord.Embed(title=title, description=desc, color=discord.Color.green())
    embed.add_field(name="Your Score", value=state["points"], inline=True)
    # edit if we already have a message, else send a new one
    channel = ctx_or_channel.channel if hasattr(ctx_or_channel, "channel") else ctx_or_channel
    if state.get("msg_id"):
        try:
            msg = await channel.fetch_message(state["msg_id"])
            await msg.edit(embed=embed)
            return msg
        except discord.NotFound:
            state["msg_id"] = None
    msg = await channel.send(embed=embed)
    state["msg_id"] = msg.id
    # add controls on first post
    for emoji in ("⬆️","⬇️","⬅️","➡️","🔄"):
        try:
            await msg.add_reaction(emoji)
        except Exception:
            pass
    return msg

def _snake_reset_state():
    state = {"matrix": _snake_new_matrix(), "points": 0, "is_out": False, "msg_id": None}
    _snake_generate_energy(state)
    return state

@bot.command(name="snake", help="Play the emoji snake! Usage: !snake start | !snake w/a/s/d | !snake reset")
async def snake_cmd(ctx, action: str = "start"):
    ch_id = ctx.channel.id
    action = action.lower()

    if action in ("start", "reset"):
        SNAKE_GAMES[ch_id] = _snake_reset_state()
        await _snake_render(ctx, SNAKE_GAMES[ch_id], title=f"Pick Apple Game • {ctx.author.display_name}")
        await ctx.send("Use reactions ⬆️ ⬇️ ⬅️ ➡️ to move, or `!snake w/a/s/d`. `!snake reset` to restart.")
        return

    if ch_id not in SNAKE_GAMES:
        SNAKE_GAMES[ch_id] = _snake_reset_state()

    move_map = {"w":"up","a":"left","s":"down","d":"right","up":"up","down":"down","left":"left","right":"right"}
    if action not in move_map:
        return await ctx.send("❌ Invalid action. Use `start`, `reset`, or one of `w/a/s/d`.")

    state = SNAKE_GAMES[ch_id]
    if state["is_out"]:
        return await ctx.send(embed=discord.Embed(title="Game Over", description=f"Final score: **{state['points']}**", color=discord.Color.red()))

    _snake_move(state, move_map[action])
    if state["is_out"]:
        # render once more with the lose face, then say Game Over
        await _snake_render(ctx, state)
        return await ctx.send(embed=discord.Embed(title="Game Over", description=f"Scored: **{state['points']}**", color=discord.Color.red()))
    await _snake_render(ctx, state)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    # keep your existing handler logic first (you already have one for role colours) —
    # we'll append snake handling after it.
    # --- SNAKE HANDLER ---
    if payload.user_id == bot.user.id:
        return
    ch_id = payload.channel_id
    state = SNAKE_GAMES.get(ch_id)
    if not state or not state.get("msg_id") or payload.message_id != state["msg_id"]:
        return
    emoji = str(payload.emoji)
    action = SNAKE_CONTROLS.get(emoji)
    if not action:
        return

    guild = bot.get_guild(payload.guild_id)
    channel = guild.get_channel(ch_id) if guild else None
    if not channel:
        return

    if action == "reset":
        SNAKE_GAMES[ch_id] = _snake_reset_state()
        await _snake_render(channel, SNAKE_GAMES[ch_id])
        return

    if state["is_out"]:
        await channel.send(embed=discord.Embed(title="Game Over", description=f"Scored: **{state['points']}**", color=discord.Color.red()))
        return

    _snake_move(state, action)
    if state["is_out"]:
        await _snake_render(channel, state)
        await channel.send(embed=discord.Embed(title="Game Over", description=f"Scored: **{state['points']}**", color=discord.Color.red()))
    else:
        await _snake_render(channel, state)

# NOTE: If you already have an on_raw_reaction_add, merge the "SNAKE HANDLER"
# block into it after your other logic.


# =========================
# Economy helpers
# =========================
def ensure_user_coins(user_id):
    user_id = str(user_id)
    coins = load_coins()
    if user_id not in coins:
        coins[user_id] = {
            "wallet": 100,
            "bank": 0,
            "last_daily": 0,
            "last_rob": 0,
            "last_bankrob": 0,
            "portfolio": {s: 0 for s in STOCKS},
        }
        save_coins(coins)
    else:
        # backfill keys
        data = coins[user_id]
        data.setdefault("last_rob", 0)
        data.setdefault("last_bankrob", 0)
        data.setdefault("portfolio", {})
        for s in STOCKS:
            data["portfolio"].setdefault(s, 0)
        save_coins(coins)
    return coins

# =========================
# XP helpers
# =========================
def calculate_level(xp):
    return int(xp ** 0.5)

async def update_top_exp_role(guild):
    data = load_data()
    gid = str(guild.id)
    if gid not in data or not data[gid]:
        return
    top_user_id, _ = max(data[gid].items(), key=lambda x: x[1]["xp"])
    top_member = guild.get_member(int(top_user_id))
    if not top_member:
        return

    role = discord.utils.get(guild.roles, name=TOP_ROLE_NAME)
    if not role:
        try:
            role = await guild.create_role(name=TOP_ROLE_NAME)
        except discord.Forbidden:
            return

    for m in guild.members:
        if role in m.roles and m != top_member:
            await m.remove_roles(role)
    if role not in top_member.roles:
        await top_member.add_roles(role)

async def update_xp(user_id, guild_id, xp_amount):
    data = load_data()
    gid = str(guild_id)
    uid = str(user_id)
    data.setdefault(gid, {})
    user = data[gid].setdefault(uid, {"xp": 0})
    prev_xp = user["xp"]
    prev_level = user.get("level", calculate_level(prev_xp))

    # Event: Double XP
    event = load_event()
    mult = EVENTS.get(event.get("active", ""), {}).get("xp_mult", 1)
    user["xp"] = prev_xp + xp_amount * mult
    new_level = calculate_level(user["xp"])
    user["level"] = new_level
    save_data(data)

    if new_level > prev_level and new_level % 5 == 0:
        channel = bot.get_channel(1339608149707198474)
        if channel:
            u = await bot.fetch_user(user_id)
            await channel.send(f"🎉 **{u.mention}** just reached level **{new_level}**! 🚀")

    if new_level % 10 == 0:
        role_name = f"Level {new_level}"
        guild = bot.get_guild(int(gid))
        if guild:
            role = discord.utils.get(guild.roles, name=role_name)
            if not role:
                try:
                    role = await guild.create_role(name=role_name)
                except discord.Forbidden:
                    role = None
            member = guild.get_member(int(uid))
            if role and member:
                await member.add_roles(role)

    guild = bot.get_guild(int(gid))
    if guild:
        await update_top_exp_role(guild)

# =========================
# yt-dlp / FFmpeg resolver (SABR/HLS safe)
# =========================
# --- helpers used by !play (put near your other yt-dlp helpers) ---
import shlex
from pathlib import Path

YTDL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-GB,en;q=0.9",
}

YTDL_STREAM_OPTS = {
    # Prefer direct, non-HLS audio: opus webm, then m4a
    "format": "bestaudio[ext=webm][acodec=opus]/bestaudio[ext=m4a]/bestaudio",
    "extractor_args": {"youtube": {"player_client": ["ios", "web"]}},  # avoid android (PO token)
    "default_search": "ytsearch",
    "noplaylist": True,
    "quiet": True,
    "geo_bypass": True,
    "nocheckcertificate": True,
    "http_headers": YTDL_HEADERS,
}

PLAYLIST_MAX = 50  # cap so users can't queue hundreds

async def _extract_playlist_entries(query: str, limit: int = PLAYLIST_MAX):
    """
    If query is a playlist, return [{'title': str, 'url': str}, ...].
    Otherwise return [].
    """
    opts = dict(YTDL_STREAM_OPTS)
    opts.update({
        "noplaylist": False,
        "extract_flat": True,   # don't resolve every video here
        "quiet": True,
        "default_search": "ytsearch",
    })
    info = await _extract_async(query, opts)
    if not info:
        return []

    entries = info.get("entries") or []
    out = []
    for e in entries:
        if not e:
            continue
        vid_id = e.get("id")
        title = e.get("title") or "Untitled"
        url = e.get("url") or ""
        if url and not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={url}"
        elif not url and vid_id:
            url = f"https://www.youtube.com/watch?v={vid_id}"
        if url:
            out.append({"title": title, "url": url})
        if len(out) >= limit:
            break
    return out if len(out) >= 2 else []

def _extract_sync(query: str, ydl_opts: dict):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(query, download=False)

async def _extract_async(query: str, ydl_opts: dict):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _extract_sync(query, ydl_opts))

def _pick_entry(info):
    if not info:
        return None
    return (info.get("entries") or [info])[0]

def _is_hls_format(entry) -> bool:
    # If any chosen URL/protocol looks like HLS/m3u8
    url = entry.get("url") or ""
    proto = entry.get("protocol") or ""
    ext = entry.get("ext") or ""
    return ("m3u8" in url) or proto.startswith("m3u8") or ext == "m3u8"

def _pick_best_audio_url(entry):
    # If yt-dlp resolved a direct URL, use it
    if entry.get("url"):
        return entry["url"], _is_hls_format(entry)

    fmts = entry.get("formats") or []
    candidates = [f for f in fmts if f.get("url") and f.get("acodec") and f["acodec"] != "none"]
    if not candidates:
        return None, True
    def score(f):
        proto = (f.get("protocol") or "")
        abr = f.get("abr") or 0
        is_hls = proto.startswith("m3u8") or "m3u8" in (f.get("ext") or "")
        is_https = proto.startswith("https")
        # prefer https direct, then allow hls, then higher abr
        return (is_https, not is_hls, abr)
    best = sorted(candidates, key=score, reverse=True)[0]
    return best["url"], _is_hls_format(best)

async def resolve_stream_or_hls(query: str):
    """
    Try to get a direct HTTPS audio stream. Returns (title, url, header_lines, is_hls).
    """
    info = await _extract_async(f"ytsearch1:{query}", YTDL_STREAM_OPTS)
    entry = _pick_entry(info)
    if not entry:
        raise RuntimeError("No results.")
    title = entry.get("title") or "Untitled"
    url, is_hls = _pick_best_audio_url(entry)
    if not url:
        raise RuntimeError("No playable audio formats found.")
    headers = (info.get("http_headers") or entry.get("http_headers") or YTDL_STREAM_OPTS.get("http_headers") or {})
    header_lines = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
    return title, url, header_lines, is_hls

def _download_audio_sync(query: str) -> str:
    """
    Download best audio to cache_audio/ and return absolute filepath.
    """
    cache_dir = Path("cache_audio")
    cache_dir.mkdir(exist_ok=True)
    ydl_opts = {
        "quiet": True,
        "noplaylist": True,
        "format": "bestaudio[ext=m4a]/bestaudio[acodec=mp4a]/bestaudio",
        "outtmpl": str(cache_dir / "%(id)s.%(ext)s"),
        "paths": {"home": str(cache_dir)},
        "restrictfilenames": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch1:{query}", download=True)
        entry = info["entries"][0] if "entries" in info else info
        return str(Path(ydl.prepare_filename(entry)).resolve())

async def _download_audio_async(query: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _download_audio_sync(query))

# --- put this near your other globals / after CACHE_FOLDER ---
def _clear_cache_folder() -> int:
    """Delete all files in cache_audio/ and return how many were removed."""
    if not os.path.isdir(CACHE_FOLDER):
        return 0
    cleared = 0
    for f in os.listdir(CACHE_FOLDER):
        p = os.path.join(CACHE_FOLDER, f)
        if os.path.isfile(p):
            try:
                os.remove(p)
                cleared += 1
            except Exception:
                pass
    return cleared

# --- the command itself ---
@bot.command(name="play", help="Play a song with HLS fix.")
async def play(ctx: commands.Context, *, song_query: str):
    await ctx.defer()

    # --- Parse optional --limit N flag ---
    parts = song_query.split()
    limit_override = None
    for i, p in enumerate(parts):
        if p.startswith("--limit"):
            try:
                # Handle "--limit=10" or "--limit 10"
                if "=" in p:
                    limit_override = int(p.split("=", 1)[1])
                else:
                    limit_override = int(parts[i + 1])
            except (ValueError, IndexError):
                pass
            # Remove the flag parts from the query so yt-dlp doesn't get confused
            parts_to_remove = [p]
            if i + 1 < len(parts) and parts[i + 1].isdigit():
                parts_to_remove.append(parts[i + 1])
            song_query = " ".join([x for x in parts if x not in parts_to_remove])
            break

    voice_channel = ctx.author.voice and ctx.author.voice.channel
    if not voice_channel:
        return await ctx.send(embed=discord.Embed(
            description="❌ You must be in a voice channel.",
            color=discord.Color.red()
        ))

    vc = ctx.guild.voice_client
    if not vc:
        try:
            vc = await voice_channel.connect(timeout=20)
        except asyncio.TimeoutError:
            return await ctx.send(embed=discord.Embed(
                description="⚠️ Connection to the voice channel timed out. Please try again.",
                color=discord.Color.red()
            ))
        except Exception as e:
            return await ctx.send(embed=discord.Embed(
                description=f"❌ Failed to connect: `{type(e).__name__}: {e}`",
                color=discord.Color.red()
            ))
    elif vc.channel != voice_channel:
        await vc.move_to(voice_channel)

    gid = str(ctx.guild.id)

    # ---- Playlist handling ----
    try:
        playlist_entries = await _extract_playlist_entries(
            song_query,
            limit=limit_override or PLAYLIST_MAX
        )
    except Exception:
        playlist_entries = []

    if playlist_entries:
        await ctx.send(embed=discord.Embed(
            title="📜 Playlist detected",
            description=f"Queuing & downloading up to **{len(playlist_entries)}** tracks one by one…",
            color=discord.Color.teal()
        ))

        added = 0
        for e in playlist_entries:
            try:
                local_path = await _download_audio_async(e["url"])
                SONG_QUEUES.setdefault(gid, deque()).append((local_path, e["title"], "", e["url"]))
                added += 1
            except Exception as de:
                await ctx.send(embed=discord.Embed(
                    description=f"⚠️ Skipped **{e.get('title','Unknown')}** ({type(de).__name__})",
                    color=discord.Color.orange()
                ))

        if added == 0:
            return await ctx.send(embed=discord.Embed(
                description="❌ Failed to queue any tracks from that playlist.",
                color=discord.Color.red()
            ))

        if vc.is_playing() or vc.is_paused():
            await ctx.send(embed=discord.Embed(
                description=f"✅ Added **{added}** tracks to the queue.",
                color=discord.Color.purple()
            ))
        else:
            await _play_next(vc, gid, ctx.channel)
        return  # Done for playlist case

    # ---- Single-track handling (unchanged) ----
    try:
        title, stream_url, header_lines, is_hls = await resolve_stream_or_hls(song_query)
    except Exception as e:
        return await ctx.send(embed=discord.Embed(
            description=f"❌ Couldn't resolve audio: `{type(e).__name__}: {e}`",
            color=discord.Color.red()
        ))

    if is_hls:
        try:
            await ctx.send(embed=discord.Embed(
                description=f"⚠️ YouTube returned HLS for **{title}**. Downloading a local copy…",
                color=discord.Color.orange()
            ))
            local_path = await _download_audio_async(song_query)
            SONG_QUEUES.setdefault(gid, deque()).append((local_path, title, "", song_query))
        except Exception as e:
            return await ctx.send(embed=discord.Embed(
                description=f"❌ HLS fallback failed for **{title}**: `{type(e).__name__}: {e}`",
                color=discord.Color.red()
            ))
    else:
        SONG_QUEUES.setdefault(gid, deque()).append((stream_url, title, header_lines, song_query))

    if vc.is_playing() or vc.is_paused():
        await ctx.send(embed=discord.Embed(
            description=f"🎶 Added to queue: **{title}**",
            color=discord.Color.purple()
        ))
    else:
        await _play_next(vc, gid, ctx.channel)

# =========================
# Music core
# =========================
import shlex

async def _play_next(vc: discord.VoiceClient, guild_id: str, channel: discord.abc.Messageable):
    """
    Pull next track and play it.
    - If item is a URL and FFmpeg can't open it, fallback to downloading a local file.
    - If item is a local file, play it directly.
    """
    queue = SONG_QUEUES.get(guild_id)

    # Nothing left: disconnect + reset the empty deque
    if not queue or len(queue) == 0:
        try:
            if vc and vc.is_connected():
                await vc.disconnect()
        finally:
            SONG_QUEUES[guild_id] = deque()
        return

    url_or_path, title, header_lines, orig_query = queue.popleft()
    LAST_PLAYED_SONG[guild_id] = (url_or_path, title, header_lines, orig_query)

    # Decide if this is a local file path or a remote URL
    is_local_file = not (url_or_path.startswith("http://") or url_or_path.startswith("https://"))

    def build_source_from_url(u: str, headers: str):
        # Robust FFmpeg flags for streaming (reconnect + whitelist + headers)
        before = (
            "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
            "-rw_timeout 15000000 "
            "-protocol_whitelist file,crypto,data,http,https,tcp,tls "
            f"-headers {shlex.quote(headers)}"
        )
        return discord.FFmpegOpusAudio(u, executable=FFMPEG_PATH, before_options=before, options="-vn -c:a libopus -b:a 96k")

    def build_source_from_file(p: str):
        # Local files don’t need headers/before_options
        return discord.FFmpegOpusAudio(p, executable=FFMPEG_PATH)

    # Try to create the audio source
    try:
        if is_local_file:
            source = build_source_from_file(url_or_path)
        else:
            source = build_source_from_url(url_or_path, header_lines)
    except Exception as e:
        # If it's a URL, try downloading and playing local file as a fallback
        if not is_local_file:
            try:
                await channel.send(embed=discord.Embed(
                    description=f"⚠️ Streaming failed for **{title}** — downloading a local copy…",
                    color=discord.Color.orange()
                ))
                local_path = await _download_audio_async(orig_query)
                # Update last played to the local file so !repeat works
                LAST_PLAYED_SONG[guild_id] = (local_path, title, "", orig_query)
                source = build_source_from_file(local_path)
            except Exception as e2:
                try:
                    await channel.send(embed=discord.Embed(
                        description=f"❌ Couldn’t play **{title}** (`{type(e).__name__}` then `{type(e2).__name__}`) — skipping.",
                        color=discord.Color.red()
                    ))
                except Exception:
                    pass
                # Move on
                await _play_next(vc, guild_id, channel)
                return
        else:
            # Local file failed — skip
            try:
                await channel.send(embed=discord.Embed(
                    description=f"❌ Couldn’t play local file for **{title}** (`{type(e).__name__}: {e}`) — skipping.",
                    color=discord.Color.red()
                ))
            except Exception:
                pass
            await _play_next(vc, guild_id, channel)
            return

    # after-callback: advance queue (runs off the voice thread)
    def _after_play(err: Exception | None):
        async def _advance():
            if err:
                try:
                    await channel.send(embed=discord.Embed(
                        description=f"⚠️ Error during playback: `{err}` — moving on.",
                        color=discord.Color.red()
                    ))
                except Exception:
                    pass
            await _play_next(vc, guild_id, channel)
        bot.loop.create_task(_advance())

    # Start playback
    try:
        vc.play(source, after=_after_play)
    except Exception as e:
        try:
            await channel.send(embed=discord.Embed(
                description=f"⚠️ Failed to start **{title}** (`{type(e).__name__}: {e}`) — skipping.",
                color=discord.Color.red()
            ))
        except Exception:
            pass
        await _play_next(vc, guild_id, channel)
        return

    global SONG_PLAY_COUNT
    SONG_PLAY_COUNT += 1

    # Every 10 songs, clear cache
    if SONG_PLAY_COUNT >= 10:
        SONG_PLAY_COUNT = 0  # reset
        try:
            cleared_files = 0
            for f in os.listdir(CACHE_FOLDER):
                file_path = os.path.join(CACHE_FOLDER, f)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    cleared_files += 1
            await channel.send(embed=discord.Embed(
                description=f"🗑️ Cleared {cleared_files} cached audio files.",
                color=discord.Color.green()
            ))
        except Exception as e:
            await channel.send(embed=discord.Embed(
                description=f"⚠️ Couldn’t clear cache: `{e}`",
                color=discord.Color.orange()
            ))

    # Announce now playing
    try:
        await channel.send(embed=discord.Embed(
            description=f"🎵 Now playing: **{title}**",
            color=discord.Color.purple()
        ))
    except Exception:
        pass

# =========================
# Commands
# =========================
@bot.command(name="play2", help="Play a song or playlist. Use --limit N to limit playlist tracks.")
async def play2(ctx, *, song_query: str):
    await ctx.defer()
    voice_channel = ctx.author.voice and ctx.author.voice.channel
    if not voice_channel:
        return await ctx.send(embed=discord.Embed(
            description="❌ You must be in a voice channel.",
            color=discord.Color.red()
        ))

    vc = ctx.guild.voice_client
    if not vc:
        try:
            vc = await voice_channel.connect(timeout=20)
        except asyncio.TimeoutError:
            return await ctx.send(embed=discord.Embed(
                description="⚠️ Connection to the voice channel timed out. Please try again.",
                color=discord.Color.red()
            ))
        except Exception as e:
            return await ctx.send(embed=discord.Embed(
                description=f"❌ Failed to connect: `{type(e).__name__}: {e}`",
                color=discord.Color.red()
            ))
    elif vc.channel != voice_channel:
        await vc.move_to(voice_channel)

    try:
        title, stream_url, header_lines = await ytdlp_resolve(song_query)
    except Exception as e:
        return await ctx.send(embed=discord.Embed(
            description=f"❌ Couldn't resolve audio: `{type(e).__name__}: {e}`",
            color=discord.Color.red()
        ))

    gid = str(ctx.guild.id)
    SONG_QUEUES.setdefault(gid, deque()).append((stream_url, title, header_lines, song_query))

    if vc.is_playing() or vc.is_paused():
        await ctx.send(embed=discord.Embed(description=f"🎶 Added to queue: **{title}**", color=discord.Color.purple()))
    else:
        await _play_next(vc, gid, ctx.channel)

@bot.command(name="queue", help="Show the current song queue.")
async def queue_cmd(ctx: commands.Context):
    gid = str(ctx.guild.id)
    queue = SONG_QUEUES.get(gid, deque())
    if not queue:
        return await ctx.send(embed=discord.Embed(description="The queue is currently empty.", color=discord.Color.red()))
    msg = "\n".join([f"{i}. {title}" for i, (_, title, _) in enumerate(queue, start=1)])
    await ctx.send(embed=discord.Embed(title="🎶 Current Queue", description=msg, color=discord.Color.purple()))

@bot.command(name="pause", help="Pause the currently playing song.")
async def pause(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if not vc:
        return await ctx.send(embed=discord.Embed(description="I'm not in a voice channel.", color=discord.Color.red()))
    if not vc.is_playing():
        return await ctx.send(embed=discord.Embed(description="Nothing is currently playing.", color=discord.Color.red()))
    vc.pause()
    await ctx.send(embed=discord.Embed(description="⏸️ Playback paused!", color=discord.Color.purple()))

@bot.command(name="resume", help="Resume the currently paused song.")
async def resume(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if not vc:
        return await ctx.send(embed=discord.Embed(description="I'm not in a voice channel.", color=discord.Color.red()))
    if not vc.is_paused():
        return await ctx.send(embed=discord.Embed(description="I'm not paused right now.", color=discord.Color.red()))
    vc.resume()
    await ctx.send(embed=discord.Embed(description="▶️ Playback resumed!", color=discord.Color.purple()))

@bot.command(name="skip", help="Skip the currently playing song.")
async def skip(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()
        await ctx.send(embed=discord.Embed(description="⏭️ Skipped the current song.", color=discord.Color.purple()))
    else:
        await ctx.send(embed=discord.Embed(description="❌ Not playing anything to skip.", color=discord.Color.red()))

@bot.command(name="repeat", help="Repeat the currently playing song.")
async def repeat(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if not vc or not vc.is_playing():
        return await ctx.send(embed=discord.Embed(description="❌ No song is currently playing.", color=discord.Color.red()))
    gid = str(ctx.guild.id)
    song = LAST_PLAYED_SONG.get(gid)
    if not song:
        return await ctx.send(embed=discord.Embed(description="⚠️ I couldn't find the current song to repeat.", color=discord.Color.red()))
    SONG_QUEUES.setdefault(gid, deque()).appendleft(song)
    await ctx.send(embed=discord.Embed(description=f"🔁 Repeating **{song[1]}**", color=discord.Color.purple()))

@bot.command(name="clearcache", help="Delete all cached audio files.")
@commands.has_permissions(administrator=True)  # Optional: limit to admins
async def clearcache(ctx):
    cleared = _clear_cache_folder()
    await ctx.send(embed=discord.Embed(
        description=f"🗑️ Cleared **{cleared}** cached audio file(s).",
        color=discord.Color.green()
    ))

# =========================
# Suggestions
# =========================
def load_suggestions():
    return _load_json(SUGGESTION_FILE, [])

def save_suggestions(d):
    _save_json(SUGGESTION_FILE, d)

@bot.command(name="suggest", help="Submit a suggestion to the server.")
async def suggest(ctx, *, message: str):
    suggestions = load_suggestions()
    suggestions.append({
        "user_id": ctx.author.id,
        "username": ctx.author.name,
        "suggestion": message,
        "timestamp": datetime.utcnow().isoformat()
    })
    save_suggestions(suggestions)

    channel = bot.get_channel(SUGGESTION_CHANNEL_ID)
    if not channel:
        return await ctx.send("❌ Suggestion channel not found. Please contact an admin.")

    embed = discord.Embed(title="📬 New Suggestion", description=message, color=discord.Color.teal())
    embed.set_footer(text=f"Suggested by {ctx.author.display_name}")
    msg = await channel.send(embed=embed)
    await msg.add_reaction("👍")
    await msg.add_reaction("👎")
    await ctx.send("✅ Your suggestion has been submitted!")

# =========================
# Economy: wallet/bank/daily/beg/donate/pay
# =========================
@bot.command(name="balance", help="Check your or someone else's wallet and bank balance.")
async def balance(ctx, member: discord.Member = None):
    member = member or ctx.author
    coins = ensure_user_coins(member.id)
    data = coins[str(member.id)]
    embed = discord.Embed(title=f"💰 {member.display_name}'s Balance", color=discord.Color.purple())
    embed.add_field(name="Wallet", value=f"💵 {data['wallet']} coins")
    embed.add_field(name="Bank", value=f"🏦 {data['bank']} coins")
    await ctx.send(embed=embed)

@bot.command(name="deposit", help="Deposit to bank. Usage: !deposit <amount> or !deposit all")
async def deposit(ctx, amount: str):
    uid = str(ctx.author.id)
    coins = ensure_user_coins(uid)
    data = coins[uid]
    if amount.lower() == "all":
        amt = data["wallet"]
    else:
        if not amount.isdigit():
            return await ctx.send(embed=discord.Embed(description="❌ Enter a number or 'all'.", color=discord.Color.orange()))
        amt = int(amount)
    if amt <= 0 or amt > data["wallet"]:
        return await ctx.send(embed=discord.Embed(description="❌ Not enough wallet balance.", color=discord.Color.orange()))
    data["wallet"] -= amt
    data["bank"] += amt
    save_coins(coins)
    await ctx.send(embed=discord.Embed(description=f"🏦 Deposited **{amt}** coins.", color=discord.Color.orange()))

@bot.command(name="withdraw", help="Withdraw from bank. Usage: !withdraw <amount> or !withdraw all")
async def withdraw(ctx, amount: str):
    uid = str(ctx.author.id)
    coins = ensure_user_coins(uid)
    data = coins[uid]
    if amount.lower() == "all":
        amt = data["bank"]
    else:
        if not amount.isdigit():
            return await ctx.send(embed=discord.Embed(description="❌ Enter a number or 'all'.", color=discord.Color.orange()))
        amt = int(amount)
    if amt <= 0 or amt > data["bank"]:
        return await ctx.send(embed=discord.Embed(description="❌ Not enough bank balance.", color=discord.Color.orange()))
    data["bank"] -= amt
    data["wallet"] += amt
    save_coins(coins)
    await ctx.send(embed=discord.Embed(description=f"💰 Withdrew **{amt}** coins.", color=discord.Color.orange()))

@bot.command(name="daily", help="Claim your daily reward.")
async def daily(ctx):
    uid = str(ctx.author.id)
    coins = ensure_user_coins(uid)
    data = coins[uid]

    now = datetime.now(timezone.utc)
    last_ts = data.get("last_daily", 0)
    last_claim = datetime.fromtimestamp(last_ts, tz=timezone.utc)

    if last_claim.date() == now.date():
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        remaining = (tomorrow - now).total_seconds()
        h = int(remaining // 3600)
        m = int((remaining % 3600) // 60)
        s = int(remaining % 60)
        return await ctx.send(embed=discord.Embed(
            description=f"🕒 Already claimed. Try again in **{h}h {m}m {s}s** (resets at midnight UTC).",
            color=discord.Color.purple()
        ))

    reward = random.randint(200, 350)
    # Event: Coin Rain bonus
    event = load_event()
    if event.get("active") == "Coin Rain":
        reward += EVENTS["Coin Rain"]["bonus_daily"]
    data["wallet"] += reward
    data["last_daily"] = now.timestamp()
    save_coins(coins)

    await ctx.send(embed=discord.Embed(description=f"💰 Daily claimed: **{reward}** coins!", color=discord.Color.purple()))

@bot.command(name="beg", help="Beg for coins (random outcome).")
async def beg(ctx):
    uid = str(ctx.author.id)
    coins = ensure_user_coins(uid)
    data = coins[uid]
    responses = [
        ("A kind stranger gave you", random.randint(20, 50)),
        ("Your sob story worked. You received", random.randint(30, 70)),
        ("You found coins on the floor:", random.randint(10, 30)),
        ("No one cared... but someone dropped", random.randint(5, 15)),
        ("A rich NPC tipped you", random.randint(50, 100)),
    ]
    msg, amount = random.choice(responses)
    data["wallet"] += amount
    save_coins(coins)
    await ctx.send(embed=discord.Embed(description=f"🙏 {msg} **{amount}** coins!", color=discord.Color.orange()))
    await ctx.send(f"💸 Feeling generous? Use `!donate {ctx.author.mention} <amount>` to help them out even more.")

@bot.command(name="donate", help="Donate coins to someone.")
async def donate(ctx, member: discord.Member, amount: int):
    if member == ctx.author:
        return await ctx.send(embed=discord.Embed(description="❌ You can't donate to yourself.", color=discord.Color.orange()))
    if member.bot:
        return await ctx.send(embed=discord.Embed(description="🤖 Bots don't need donations.", color=discord.Color.orange()))
    if amount <= 0:
        return await ctx.send(embed=discord.Embed(description="❌ Amount must be > 0.", color=discord.Color.orange()))

    coins = ensure_user_coins(ctx.author.id)
    ensure_user_coins(member.id)
    donor = coins[str(ctx.author.id)]
    recipient = coins[str(member.id)]

    if donor["wallet"] < amount:
        return await ctx.send(embed=discord.Embed(description="💸 Not enough wallet balance.", color=discord.Color.orange()))

    donor["wallet"] -= amount
    recipient["wallet"] += amount
    save_coins(coins)
    await ctx.send(embed=discord.Embed(description=f"💖 {ctx.author.mention} donated **{amount}** to {member.mention}!", color=discord.Color.orange()))

@bot.command(name="pay", help="Send coins to another user.")
async def pay(ctx, member: discord.Member, amount: int):
    if member == ctx.author:
        return await ctx.send("❌ You can't pay yourself.")
    if member.bot:
        return await ctx.send("🤖 You can't pay bots.")
    if amount <= 0:
        return await ctx.send("❌ Enter a valid amount greater than 0.")

    coins = ensure_user_coins(ctx.author.id)
    ensure_user_coins(member.id)
    sender = coins[str(ctx.author.id)]
    recipient = coins[str(member.id)]

    if sender["wallet"] < amount:
        return await ctx.send("💸 You don't have enough coins in your wallet to send that much.")

    sender["wallet"] -= amount
    recipient["wallet"] += amount
    save_coins(coins)
    await ctx.send(embed=discord.Embed(description=f"✅ You sent **{amount}** coins to {member.mention}!", color=discord.Color.green()))

# =========================
# Robbery / Gambling
# =========================
@bot.command(name="rob", help="Attempt to rob someone.")
async def rob(ctx, member: discord.Member):
    if member == ctx.author or member.bot:
        return await ctx.send(embed=discord.Embed(description="❌ You can't rob that person.", color=discord.Color.purple()))

    coins = ensure_user_coins(ctx.author.id)
    ensure_user_coins(member.id)
    thief = coins[str(ctx.author.id)]
    victim = coins[str(member.id)]

    now = time.time()
    cooldown = 300
    if now - thief.get("last_rob", 0) < cooldown:
        remaining = int(cooldown - (now - thief["last_rob"]))
        return await ctx.send(embed=discord.Embed(description=f"⏳ Cooldown: **{remaining}**s", color=discord.Color.purple()))

    if victim["wallet"] < 50:
        return await ctx.send(embed=discord.Embed(description="😒 That user doesn't have enough to rob.", color=discord.Color.purple()))

    stolen = random.randint(10, int(victim["wallet"] // 2))
    victim["wallet"] -= stolen
    thief["wallet"] += stolen
    thief["last_rob"] = now
    save_coins(coins)
    await ctx.send(embed=discord.Embed(description=f"💸 You robbed **{member.display_name}** and got **{stolen}** coins!", color=discord.Color.purple()))

@bot.command(name="bankrob", help="Attempt to rob someone’s bank account (risky!).")
async def bankrob(ctx):
    uid = str(ctx.author.id)
    coins = ensure_user_coins(uid)
    user = coins[uid]
    now = time.time()
    cooldown = 600
    if now - user.get("last_bankrob", 0) < cooldown:
        remaining = int(cooldown - (now - user.get("last_bankrob", 0)))
        return await ctx.send(embed=discord.Embed(
            description=f"🚨 Try again in **{remaining//60}m {remaining%60}s**.",
            color=discord.Color.purple()
        ))
    user["last_bankrob"] = now

    victims = [(i, d) for i, d in coins.items() if i != uid and d.get("bank", 0) >= 100]
    if not victims:
        return await ctx.send(embed=discord.Embed(description="😓 No rich victims available to rob!", color=discord.Color.purple()))
    victim_id, victim_data = random.choice(victims)

    success = random.choices([True, False], weights=[20, 80])[0]
    if success:
        amount = random.randint(100, min(500, victim_data["bank"]))
        victim_data["bank"] -= amount
        user["wallet"] += amount
        victim_user = await bot.fetch_user(int(victim_id))
        message = f"🏦 Success! You stole **{amount}** coins from **{victim_user.name}**."
    else:
        if user["wallet"] < 50:
            message = "🚔 Caught, but too broke to fine. Warning issued."
        else:
            fine = random.randint(50, int(min(user["wallet"], 150)))
            user["wallet"] -= fine
            message = f"🚔 You got caught and lost **{fine}** coins in legal fees."
    save_coins(coins)
    await ctx.send(embed=discord.Embed(description=message, color=discord.Color.purple()))

@bot.command(name="gamble", help="Gamble coins on red or black 🎰")
async def gamble(ctx, amount: int):
    if amount <= 0:
        return await ctx.send("❌ Invalid amount to gamble.")
    coins = ensure_user_coins(ctx.author.id)
    user = coins[str(ctx.author.id)]
    if user["wallet"] < amount:
        return await ctx.send("💸 You don’t have enough coins in your wallet to gamble that much.")

    result = random.choice(["red", "black"])
    embed = discord.Embed(title="🎰 Place Your Bet!", description="React with 🟥 for Red or ⬛ for Black.\nYou have 5 seconds...", color=discord.Color.gold())
    message = await ctx.send(embed=embed)
    await message.add_reaction("🟥")
    await message.add_reaction("⬛")

    def check(reaction, u):
        return u == ctx.author and str(reaction.emoji) in ["🟥", "⬛"] and reaction.message.id == message.id

    try:
        reaction, _ = await bot.wait_for("reaction_add", timeout=5.0, check=check)
    except asyncio.TimeoutError:
        return await ctx.send("⏰ You didn’t react in time. Bet cancelled.")

    choice = "red" if str(reaction.emoji) == "🟥" else "black"
    win = choice == result
    user["wallet"] -= amount
    if win:
        winnings = amount * 2
        user["wallet"] += winnings
        resp = discord.Embed(title="🎉 You Win!", description=f"The wheel landed on **{result.upper()}**!\nYou won **{winnings}** coins!", color=discord.Color.green())
    else:
        resp = discord.Embed(title="😢 You Lose!", description=f"The wheel landed on **{result.upper()}**.\nYou lost **{amount}** coins.", color=discord.Color.red())
    save_coins(coins)
    await ctx.send(embed=resp)

# =========================
# Shop / Inventory
# =========================
@bot.command(name="shop", help="Browse items currently in stock.")
async def shop(ctx):
    stock = load_shop_stock()
    embed = discord.Embed(title="🛒 QMUL Shop", color=discord.Color.purple())
    for item in SHOP_ITEMS:
        price = ITEM_PRICES[item]
        count = stock.get(item, 0)
        embed.add_field(name=item, value=f"💰 {price} coins\n📦 Stock: {count}", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="inventory", help="View your or someone else's inventory.")
async def inventory(ctx, member: discord.Member = None):
    member = member or ctx.author
    uid = str(member.id)
    inv = load_inventory()
    user_inv = inv.get(uid, {})
    if not user_inv:
        return await ctx.send(embed=discord.Embed(description=f"{member.display_name} has nothing in their inventory 🪫", color=discord.Color.orange()))
    embed = discord.Embed(title=f"🎒 {member.display_name}'s Inventory", color=discord.Color.orange())
    for item, qty in user_inv.items():
        embed.add_field(name=item, value=f"🧮 Quantity: {qty}", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="buy", help="Buy a stock or shop item. Stocks: !buy <stock> <amount>; Items: !buy <item>.")
async def buy(ctx, *, name: str):
    name = name.strip()
    uid = str(ctx.author.id)
    parts = name.split()
    # Try stock buy
    if len(parts) == 2 and parts[1].isdigit():
        stock_candidate = parts[0]
        amount = int(parts[1])
        stock_names = {s.lower(): s for s in STOCKS}
        if stock_candidate.lower() in stock_names:
            stock = stock_names[stock_candidate.lower()]
            stocks = load_stocks()
            coins = ensure_user_coins(uid)
            user = coins[uid]
            price = float(stocks[stock]["price"])
            cost = int(price * amount)
            if user["wallet"] < cost:
                return await ctx.send(f"💸 You need {cost} coins to buy {amount} shares of {stock}.")
            user["wallet"] -= cost
            user["portfolio"][stock] += amount
            STOCK_PURCHASE_COUNT[stock] += amount
            save_coins(coins)
            return await ctx.send(f"✅ You bought {amount} shares of **{stock}** at {int(price)} coins each!")
    # Item buy
    item_name = name.title()
    if item_name not in SHOP_ITEMS:
        return await ctx.send("❌ Invalid item or stock format.\nUse `!buy <stock> <amount>` or `!buy <shop item>`.")
    stock = load_shop_stock()
    if stock.get(item_name, 0) <= 0:
        return await ctx.send(f"❌ {item_name} is out of stock.")
    coins = ensure_user_coins(uid)
    user = coins[uid]
    price = ITEM_PRICES[item_name]
    if user["wallet"] < price:
        return await ctx.send("💸 You don’t have enough coins to buy this item.")
    user["wallet"] -= price
    stock[item_name] = stock.get(item_name, 0) - 1
    save_shop_stock(stock)
    save_coins(coins)
    inv = load_inventory()
    inv.setdefault(uid, {})
    inv[uid][item_name] = inv[uid].get(item_name, 0) + 1
    save_inventory(inv)
    await ctx.send(f"✅ You bought **{item_name}** for **{price}** coins!")

@bot.command(name="claim", help="Use a Crash token to halve the value of a stock. Usage: !claim <stock>")
async def claim(ctx, stock_name: str):
    uid = str(ctx.author.id)
    stock_names = {s.lower(): s for s in STOCKS}
    key = stock_name.lower()
    if key not in stock_names:
        return await ctx.send(embed=discord.Embed(description="❌ Invalid stock name.", color=discord.Color.orange()))
    inv = load_inventory()
    qty = inv.get(uid, {}).get(CRASH_TOKEN_NAME, 0)
    if qty < 1:
        return await ctx.send(embed=discord.Embed(description=f"❌ You don’t have any **{CRASH_TOKEN_NAME}** to use.", color=discord.Color.orange()))
    stocks = load_stocks()
    s = stock_names[key]
    old = int(stocks[s]["price"])
    new = max(1, old // 2)
    stocks[s]["price"] = new
    stocks[s]["history"].append(new)
    if len(stocks[s]["history"]) > 24:
        stocks[s]["history"] = stocks[s]["history"][-24:]
    save_stocks(stocks)
    inv[uid][CRASH_TOKEN_NAME] -= 1
    if inv[uid][CRASH_TOKEN_NAME] <= 0:
        del inv[uid][CRASH_TOKEN_NAME]
    save_inventory(inv)
    await ctx.send(embed=discord.Embed(
        title="💥 Crash Token Used!",
        description=f"{ctx.author.mention} halved **{s}** from **{old}** → **{new}** coins!",
        color=discord.Color.orange()
    ))

@bot.command(name="sell", help="Sell shares of a stock. Usage: !sell <stock> <amount>")
async def sell(ctx, stock: str, amount: int):
    if amount <= 0:
        return await ctx.send("❌ Invalid amount.")
    stock_names = {s.lower(): s for s in STOCKS}
    key = stock.lower()
    if key not in stock_names:
        return await ctx.send("❌ Invalid stock.")
    s = stock_names[key]
    stocks = load_stocks()
    coins = ensure_user_coins(ctx.author.id)
    user = coins[str(ctx.author.id)]
    owned = user["portfolio"].get(s, 0)
    if owned < amount:
        return await ctx.send(f"❌ You only own {owned} shares of **{s}**.")
    try:
        price = float(stocks[s]["price"])
    except (KeyError, ValueError):
        return await ctx.send("⚠️ Couldn't get stock price. Try again later.")
    total = int(round(price * amount))
    user["wallet"] += total
    user["portfolio"][s] -= amount
    save_coins(coins)
    await ctx.send(f"💰 You sold {amount} shares of **{s}** for **{total}** coins.")

@bot.command(name="stocks", help="View current stock prices.")
async def stocks_cmd(ctx):
    stock_data = load_stocks()
    embed = discord.Embed(title="📈 Current Stock Prices", color=discord.Color.green())
    for name in STOCKS:
        price = int(stock_data[name]["price"])
        embed.add_field(name=name, value=f"💰 {price} coins", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="stockvalue", help="Show graph of stock growth.")
async def stockvalue(ctx, stock: str):
    stock_names = {s.lower(): s for s in STOCKS}
    key = stock.lower()
    if key not in stock_names:
        return await ctx.send("❌ Invalid stock.")
    s = stock_names[key]
    stocks = load_stocks()
    if s not in stocks:
        return await ctx.send("❌ Stock not found in database.")
    history = stocks[s]["history"]
    if len(history) < 2:
        return await ctx.send("📉 Not enough data to generate a graph yet.")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    ax.plot(history, marker='o', label=s)
    ax.set_title(f"{s} Price Trend")
    ax.set_xlabel("Update #")
    ax.set_ylabel("Price")
    ax.grid(True)
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    plt.close()
    file = discord.File(buf, filename="stock.png")
    embed = discord.Embed(title=f"{s} Stock Value 📈", color=discord.Color.green())
    embed.set_image(url="attachment://stock.png")
    await ctx.send(embed=embed, file=file)

@bot.command(name="portfolio", help="View your stock portfolio.")
async def portfolio(ctx, member: discord.Member = None):
    member = member or ctx.author
    uid = str(member.id)
    coins = load_coins()
    stocks = load_stocks()
    if uid not in coins or "portfolio" not in coins[uid]:
        return await ctx.send("❌ No portfolio data found for this user.")
    pf = coins[uid]["portfolio"]
    embed = discord.Embed(title=f"📦 {member.display_name}'s Portfolio", color=discord.Color.blue())
    total_value = 0
    for s in STOCKS:
        shares = pf.get(s, 0)
        price = int(stocks[s]["price"])
        value = shares * price
        total_value += value
        embed.add_field(name=s, value=f"📊 Shares: `{shares}`\n💰 Price: `{price}`\n📦 Value: `{value}`", inline=False)
    embed.set_footer(text=f"Total Portfolio Value: {total_value} coins")
    await ctx.send(embed=embed)

# =========================
# Quests / Events (continued)
# =========================
@bot.command(name="startevent", help="(Admin) Start a server-wide event.")
@commands.has_permissions(administrator=True)
async def startevent(ctx, name: str):
    if name not in EVENTS:
        return await ctx.send("❌ Invalid event name. Options: " + ", ".join(EVENTS.keys()))
    save_event({"active": name})
    await ctx.send(f"🎉 Event **{name}** is now active!")

@bot.command(name="endevent", help="(Admin) End the currently active event.")
@commands.has_permissions(administrator=True)
async def endevent(ctx):
    save_event({})
    await ctx.send("⛔ All events have ended.")

@bot.command(name="currentevent", help="View the currently active event.")
async def currentevent(ctx):
    data = load_event()
    name = data.get("active")
    if name:
        await ctx.send(f"🎊 Current Event: **{name}**")
    else:
        await ctx.send("📭 No event is currently running.")

@bot.command(name="quest", help="View your daily quest and reward.")
async def quest(ctx):
    user_id = str(ctx.author.id)
    quests = load_quests()
    if user_id not in quests:
        quests[user_id] = random.choice(QUEST_POOL)
        save_quests(quests)
    q = quests[user_id]
    embed = discord.Embed(
        title="📜 Your Daily Quest",
        description=f"**Task:** {q['task']}\n**Command Hint:** `{q['command']}`\n**Reward:** 💰 {q['reward']} coins",
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

@bot.command(name="complete", help="Complete your current quest and claim the reward.")
async def complete(ctx):
    user_id = str(ctx.author.id)
    quests = load_quests()
    if user_id not in quests:
        return await ctx.send("❌ You have no active quest.")
    coins = ensure_user_coins(user_id)
    reward = quests[user_id]["reward"]
    coins[user_id]["wallet"] += reward
    del quests[user_id]
    save_coins(coins)
    save_quests(quests)
    await ctx.send(f"✅ Quest completed! You earned **{reward}** coins!")

# =========================
# Announcements
# =========================
@bot.command(name="announcement", help="Post a yellow-embed announcement with @everyone")
async def announcement(ctx, *, message: str):
    channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    if not channel:
        return await ctx.send("❌ Announcement channel not found.")
    embed = discord.Embed(description=message, color=discord.Color.yellow())
    await channel.send(
        content="@everyone",
        embed=embed,
        allowed_mentions=discord.AllowedMentions(everyone=True)
    )
    await ctx.send(f"✅ Announcement sent in {channel.mention}")

# =========================
# AFK + Role Colours
# =========================
@bot.command(name="afk", help="Set your AFK status with a reason")
async def afk(ctx, *, reason: str = "AFK"):
    key = f"{ctx.guild.id}-{ctx.author.id}"
    AFK_STATUS[key] = reason
    embed = discord.Embed(description=f"{ctx.author.mention} is now AFK: {reason}", color=discord.Color.green())
    await ctx.send(embed=embed)

@bot.command(name="rolecolour", help="Post a message where users can choose their color role.")
@commands.has_permissions(manage_roles=True)
async def rolecolour(ctx):
    desc = "\n".join([f"{emoji} = **{role}**" for emoji, role in ROLE_COLOR_EMOJIS.items()])
    embed = discord.Embed(title="🎨 Pick Your Colour!", description=desc, color=discord.Color.purple())
    msg = await ctx.send(embed=embed)
    for emoji in ROLE_COLOR_EMOJIS.keys():
        await msg.add_reaction(emoji)
    # Save the message ID for tracking
    with open("role_colour_msg.txt", "w") as f:
        f.write(str(msg.id))

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.member and payload.member.bot:
        return
    # Load tracked message ID
    try:
        with open("role_colour_msg.txt", "r") as f:
            target_msg_id = int(f.read())
    except FileNotFoundError:
        return
    if payload.message_id != target_msg_id:
        return

    guild = bot.get_guild(payload.guild_id)
    member = payload.member or guild.get_member(payload.user_id)
    if not guild or not member:
        return

    role_name = ROLE_COLOR_EMOJIS.get(str(payload.emoji))
    if not role_name:
        return

    # Ensure role exists
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        try:
            role = await guild.create_role(name=role_name, colour=discord.Colour.default())
        except discord.Forbidden:
            return

    # Remove other color roles
    color_roles = [discord.utils.get(guild.roles, name=r) for r in ROLE_COLOR_EMOJIS.values()]
    for r in color_roles:
        if r and r in member.roles and r.name != role_name:
            await member.remove_roles(r)

    # Add the new role
    if role not in member.roles:
        await member.add_roles(role)

    # Remove other reactions by this user on the same message
    channel = guild.get_channel(payload.channel_id)
    if channel:
        msg = await channel.fetch_message(payload.message_id)
        for reaction in msg.reactions:
            if str(reaction.emoji) != str(payload.emoji):
                async for u in reaction.users():
                    if u.id == member.id:
                        await reaction.remove(member)

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    # Load tracked message ID
    try:
        with open("role_colour_msg.txt", "r") as f:
            target_msg_id = int(f.read())
    except FileNotFoundError:
        return
    if payload.message_id != target_msg_id:
        return

    guild = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id) if guild else None
    if not guild or not member or member.bot:
        return

    role_name = ROLE_COLOR_EMOJIS.get(str(payload.emoji))
    if not role_name:
        return
    role = discord.utils.get(guild.roles, name=role_name)
    if role and role in member.roles:
        await member.remove_roles(role)

# =========================
# Message events (AFK + XP)
# =========================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    # Clear AFK on message
    key = f"{message.guild.id}-{message.author.id}"
    if key in AFK_STATUS:
        del AFK_STATUS[key]
        await message.channel.send(embed=discord.Embed(
            description=f"{message.author.mention} is no longer AFK.",
            color=discord.Color.red()
        ))

    # Notify if mentioning AFK users
    for user in message.mentions:
        mention_key = f"{message.guild.id}-{user.id}"
        if mention_key in AFK_STATUS:
            reason = AFK_STATUS[mention_key]
            await message.channel.send(embed=discord.Embed(
                description=f"{user.display_name} is currently AFK: {reason}",
                color=discord.Color.purple()
            ))

    # XP gain per message
    await update_xp(message.author.id, message.guild.id, XP_PER_MESSAGE)

    await bot.process_commands(message)

# =========================
# Background Tasks
# =========================
@tasks.loop(seconds=INTEREST_INTERVAL)
async def apply_bank_interest():
    await bot.wait_until_ready()
    coins = load_coins()
    changed = False
    for _, balances in coins.items():
        bank_balance = balances.get("bank", 0)
        if bank_balance > 0:
            interest = int(bank_balance * INTEREST_RATE)
            if interest > 0:
                balances["bank"] += interest
                changed = True
    if changed:
        save_coins(coins)
        print("[Interest] Applied interest to bank balances.")

@tasks.loop(minutes=5)
async def update_stock_prices():
    await bot.wait_until_ready()
    global STOCK_PURCHASE_COUNT
    stocks = load_stocks()
    total_purchases = sum(STOCK_PURCHASE_COUNT.values())
    growth_bias = random.uniform(0.01, 0.02)

    # Random market events
    crash_triggered = random.randint(1, 15) == 1
    boom_triggered  = random.randint(1, 15) == 1
    mega_crash_triggered = random.randint(1, 100) == 1
    mega_boom_triggered  = random.randint(1, 100) == 1

    crash_multiplier       = random.uniform(0.4, 0.8)  # -20% to -60%
    boom_multiplier        = random.uniform(1.3, 1.8)  # +30% to +80%
    mega_crash_multiplier  = random.uniform(0.1, 0.3)  # -70% to -90%
    mega_boom_multiplier   = random.uniform(2.0, 3.0)  # +100% to +200%

    crashed, boomed, mega_crashed, mega_boomed = [], [], [], []

    for s in STOCKS:
        current_price = int(stocks[s]["price"])
        purchase_count = STOCK_PURCHASE_COUNT.get(s, 0)

        if mega_crash_triggered and current_price > 1500:
            new_price = max(1, int(current_price * mega_crash_multiplier))
            mega_crashed.append((s, current_price, new_price))
        elif crash_triggered and current_price > 1000:
            new_price = max(1, int(current_price * crash_multiplier))
            crashed.append((s, current_price, new_price))
        elif mega_boom_triggered and current_price < 200:
            new_price = int(current_price * mega_boom_multiplier)
            mega_boomed.append((s, current_price, new_price))
        elif boom_triggered and current_price < 300:
            new_price = int(current_price * boom_multiplier)
            boomed.append((s, current_price, new_price))
        else:
            if total_purchases > 0:
                purchase_ratio = purchase_count / total_purchases
                change = 0.5 * (purchase_ratio - 0.25) + growth_bias
            else:
                change = random.uniform(-0.05, 0.05) + growth_bias
            new_price = max(1, int(current_price * (1 + change)))

        stocks[s]["price"] = new_price
        stocks[s]["history"].append(new_price)
        if len(stocks[s]["history"]) > 24:
            stocks[s]["history"] = stocks[s]["history"][-24:]

    save_stocks(stocks)
    STOCK_PURCHASE_COUNT = {s: 0 for s in STOCKS}

    # Announce
    channel = bot.get_channel(MARKET_ANNOUNCE_CHANNEL_ID)
    if not channel:
        return

    if mega_crashed:
        desc = "\n".join(f"💥 **{s}** plummeted from **{old}** → **{new}** coins" for s, old, new in mega_crashed)
        await channel.send(embed=discord.Embed(title="💀 MEGA CRASH!", description=f"A catastrophic collapse hit the market!\n\n{desc}", color=discord.Color.dark_red()))
    if crashed:
        desc = "\n".join(f"🔻 **{s}** crashed from **{old}** → **{new}** coins" for s, old, new in crashed)
        await channel.send(embed=discord.Embed(title="📉 Market Crash!", description=f"Some overvalued stocks took a hit:\n\n{desc}", color=discord.Color.red()))
    if mega_boomed:
        desc = "\n".join(f"🚀 **{s}** exploded from **{old}** → **{new}** coins" for s, old, new in mega_boomed)
        await channel.send(embed=discord.Embed(title="🚨 MEGA BOOM!", description=f"Insane surges swept the market!\n\n{desc}", color=discord.Color.gold()))
    if boomed:
        desc = "\n".join(f"📈 **{s}** rose from **{old}** → **{new}** coins" for s, old, new in boomed)
        await channel.send(embed=discord.Embed(title="📈 Market Boom!", description=f"Undervalued stocks surged upward:\n\n{desc}", color=discord.Color.green()))

@tasks.loop(seconds=DIVIDEND_INTERVAL)
async def pay_dividends():
    await bot.wait_until_ready()
    coins = load_coins()
    stocks = load_stocks()
    any_payout = False
    for user_id, data in coins.items():
        pf = data.get("portfolio", {})
        total_value = sum(pf.get(s, 0) * int(stocks[s]["price"]) for s in STOCKS)
        payout = int(total_value * DIVIDEND_RATE)
        if payout > 0:
            data["wallet"] += payout
            any_payout = True
    if any_payout:
        save_coins(coins)
        channel = bot.get_channel(MARKET_ANNOUNCE_CHANNEL_ID)
        if channel:
            await channel.send("💸 Dividends have been paid out to all shareholders!")

# =========================
# Ready
# =========================
@bot.event
async def on_ready():
    print(f"{bot.user} is online and ready!")
    # start your background loops
    if not apply_bank_interest.is_running():
        apply_bank_interest.start()
    if not update_stock_prices.is_running():
        update_stock_prices.start()
    if not pay_dividends.is_running():
        pay_dividends.start()

    # start the tiny web server
    await start_web()

# =========================
# Boot
# =========================
if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN not set in environment.")

    # ensure folder exists, then clear any leftover downloads
    os.makedirs(CACHE_FOLDER, exist_ok=True)
    wiped = _clear_cache_folder()
    print(f"[Cache] Cleared {wiped} cached audio file(s) on startup.")

    bot.run(TOKEN)