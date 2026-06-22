import discord
import requests
import re
import json
import asyncio
import os
import random
import aiosqlite
from datetime import datetime, timedelta
from discord import app_commands
from discord.ext import tasks
from typing import Union
from dotenv import load_dotenv
from rapidfuzz import process as fuzz_process

load_dotenv()

# ====================== DATABASE ======================
DB_PATH = os.environ.get("DB_PATH", "bot.db")

DEFAULT_CONFIG = {
    "cooldown_seconds": 0,
    "delete_after_pick": True,
    "delete_inline_trigger": False,
    "max_results": 10,
    "list_expire_seconds": 15,
    "channel_mode": "whitelist",
    "allowed_channels": [],
    "api_rate_limit_calls": 3,
    "api_rate_limit_seconds": 10,
}

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS guild_configs (
                guild_id INTEGER PRIMARY KEY,
                settings TEXT
            )
        """)
        await db.commit()

async def get_guild_config(guild_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT settings FROM guild_configs WHERE guild_id = ?", (guild_id,)) as cursor:
            row = await cursor.fetchone()
    if row:
        stored = json.loads(row[0])
        return {**DEFAULT_CONFIG, **stored}
    return dict(DEFAULT_CONFIG)

async def save_guild_config(guild_id: int, settings: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO guild_configs (guild_id, settings) VALUES (?, ?)",
            (guild_id, json.dumps(settings))
        )
        await db.commit()

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

active_searches = {}
user_cooldowns = {}
api_call_times = {}
card_name_cache = []

KNOWN_SET_CODES = ("sor", "shd", "twi", "jtl", "lof", "ibh", "sec", "law", "ash")

STATUSES = [
    (discord.ActivityType.watching, "Searching the galaxy for..."),
    (discord.ActivityType.playing,  "Meditating..."),
    (discord.ActivityType.playing,  "Searching my feelings..."),
    (discord.ActivityType.watching, "Fetching cards from a galaxy far, far away"),
    (discord.ActivityType.watching, "Giving in to the card side"),
]

def pick_status():
    if card_name_cache and random.random() < 0.5:
        card_name = random.choice(card_name_cache)
        return (discord.ActivityType.watching, f"Wanted: Warm or Cold - [[{card_name}]]")
    return random.choice(STATUSES)

@tasks.loop(minutes=15)
async def rotate_status():
    activity_type, name = pick_status()
    await bot.change_presence(activity=discord.Activity(type=activity_type, name=name))

# ====================== ON READY ======================
@bot.event
async def on_ready():
    await init_db()
    await tree.sync()
    print(f'✅ Bot is online as {bot.user}')
    await refresh_card_cache()
    print(f"✅ Bot ready | {len(card_name_cache)} card names cached | DB: {DB_PATH}")
    activity_type, name = pick_status()
    await bot.change_presence(activity=discord.Activity(type=activity_type, name=name))
    rotate_status.start()

# ====================== ADMIN COMMANDS ======================
@tree.command(name="swusettings", description="View current bot settings")
async def swusettings_command(interaction: discord.Interaction):
    cfg = await get_guild_config(interaction.guild_id)
    allowed = cfg.get('allowed_channels', [])
    channel_list = ' '.join(f'<#{cid}>' for cid in allowed) if allowed else "All channels"
    cache_status = f"{len(card_name_cache)} names loaded" if card_name_cache else "⚠️ Not loaded"
    embed = discord.Embed(title="⚙️ SWU Card Fetcher Settings", color=0x00b0f4)
    embed.add_field(name="Cooldown", value=f"{cfg.get('cooldown_seconds', 0)} seconds", inline=True)
    embed.add_field(name="Max Results", value=str(cfg.get('max_results', 10)), inline=True)
    embed.add_field(name="List Expire", value=f"{cfg.get('list_expire_seconds', 15)} seconds", inline=True)
    embed.add_field(name="Delete After Pick", value=str(cfg.get('delete_after_pick', True)), inline=True)
    embed.add_field(name="Delete Inline Trigger", value=str(cfg.get('delete_inline_trigger', False)), inline=True)
    embed.add_field(name="Card Cache", value=cache_status, inline=True)
    embed.add_field(name="Channel Mode", value=cfg.get('channel_mode', 'whitelist'), inline=True)
    embed.add_field(name="Allowed Channels", value=channel_list, inline=False)
    embed.add_field(name="Admin Commands", value="/swucooldown\n/swumaxresults\n/swuexpire\n/swuaddchannel\n/swuremovechannel\n/swuchannelmode", inline=False)
    await interaction.response.send_message(embed=embed)


@tree.command(name="swucooldown", description="Set cooldown (0 = disabled)")
@app_commands.describe(seconds="Seconds (0 to disable)")
async def swucooldown_command(interaction: discord.Interaction, seconds: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return
    cfg = await get_guild_config(interaction.guild_id)
    cfg["cooldown_seconds"] = max(0, seconds)
    await save_guild_config(interaction.guild_id, cfg)
    await interaction.response.send_message(f"✅ Cooldown set to **{cfg['cooldown_seconds']}** seconds.")


@tree.command(name="swumaxresults", description="Set max number of results shown")
@app_commands.describe(number="Number between 5 and 12")
async def swumaxresults_command(interaction: discord.Interaction, number: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return
    if not (5 <= number <= 12):
        await interaction.response.send_message("❌ Must be between 5 and 12.", ephemeral=True)
        return
    cfg = await get_guild_config(interaction.guild_id)
    cfg["max_results"] = number
    await save_guild_config(interaction.guild_id, cfg)
    await interaction.response.send_message(f"✅ Max results set to **{number}**.")


@tree.command(name="swuexpire", description="Set list auto-delete time")
@app_commands.describe(seconds="Seconds (30-300)")
async def swuexpire_command(interaction: discord.Interaction, seconds: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return
    cfg = await get_guild_config(interaction.guild_id)
    cfg["list_expire_seconds"] = max(10, seconds)
    await save_guild_config(interaction.guild_id, cfg)
    await interaction.response.send_message(f"✅ Lists will auto-delete after **{cfg['list_expire_seconds']}** seconds.")


@tree.command(name="swuaddchannel", description="Add a channel to the allowed channels list")
@app_commands.describe(channel="Channel to add")
async def swuaddchannel_command(interaction: discord.Interaction, channel: Union[discord.TextChannel, discord.ForumChannel]):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return
    cfg = await get_guild_config(interaction.guild_id)
    allowed = cfg.get('allowed_channels', [])
    if channel.id in allowed:
        await interaction.response.send_message(f"⚠️ {channel.mention} is already in the list.", ephemeral=True)
        return
    allowed.append(channel.id)
    cfg['allowed_channels'] = allowed
    await save_guild_config(interaction.guild_id, cfg)
    await interaction.response.send_message(f"✅ Added {channel.mention} to allowed channels.")


@tree.command(name="swuremovechannel", description="Remove a channel from the allowed channels list")
@app_commands.describe(channel="Channel to remove")
async def swuremovechannel_command(interaction: discord.Interaction, channel: Union[discord.TextChannel, discord.ForumChannel]):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return
    cfg = await get_guild_config(interaction.guild_id)
    allowed = cfg.get('allowed_channels', [])
    if channel.id not in allowed:
        await interaction.response.send_message(f"⚠️ {channel.mention} is not in the list.", ephemeral=True)
        return
    allowed.remove(channel.id)
    cfg['allowed_channels'] = allowed
    await save_guild_config(interaction.guild_id, cfg)
    await interaction.response.send_message(f"✅ Removed {channel.mention} from allowed channels.")


@tree.command(name="swuchannelmode", description="Set channel restriction mode to whitelist or blacklist")
@app_commands.describe(mode="whitelist or blacklist")
@app_commands.choices(mode=[
    app_commands.Choice(name="whitelist", value="whitelist"),
    app_commands.Choice(name="blacklist", value="blacklist"),
])
async def swuchannelmode_command(interaction: discord.Interaction, mode: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return
    cfg = await get_guild_config(interaction.guild_id)
    cfg['channel_mode'] = mode
    await save_guild_config(interaction.guild_id, cfg)
    await interaction.response.send_message(f"✅ Channel mode set to **{mode}**.")


@tree.command(name="swureloadcards", description="Reload the card name cache from swu-db.com")
async def swureloadcards_command(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    old_count = len(card_name_cache)
    await refresh_card_cache()
    new_count = len(card_name_cache)
    if new_count > 0:
        await interaction.followup.send(f"✅ Card cache reloaded: **{new_count}** names loaded.")
    else:
        await interaction.followup.send(f"⚠️ Cache reload failed. Still using **{old_count}** cached names.")


@tree.command(name="swudeleteinline", description="Toggle auto-delete of pure [[card]] trigger messages")
async def swudeleteinline_command(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return
    cfg = await get_guild_config(interaction.guild_id)
    cfg['delete_inline_trigger'] = not cfg.get('delete_inline_trigger', False)
    await save_guild_config(interaction.guild_id, cfg)
    state = "enabled" if cfg['delete_inline_trigger'] else "disabled"
    await interaction.response.send_message(f"✅ Inline trigger delete **{state}**.")


# ====================== SWUHELP ======================
@tree.command(name="swuhelp", description="Show detailed help for SWU Card Fetcher")
async def swuhelp_command(interaction: discord.Interaction):
    cfg = await get_guild_config(interaction.guild_id)
    embed = discord.Embed(title="🌟 SWU Card Fetcher Help", color=0x00b0f4)
    embed.add_field(name="1. Inline", value="Type `[[Card Name]]` in chat", inline=False)
    embed.add_field(name="2. Slash", value="Use `/swucard <name>`", inline=False)
    embed.add_field(name="Multi-Result", value="Use reactions 1️⃣–🔟 or reply with a number", inline=False)
    embed.add_field(name="Channel Restriction", value="Bot can be limited to specific channels — see `/swusettings`", inline=False)
    embed.add_field(name="Current Settings",
                    value=f"Max Results: **{cfg.get('max_results', 10)}**\n"
                          f"Cooldown: **{cfg.get('cooldown_seconds', 0)}**s\n"
                          f"List Expire: **{cfg.get('list_expire_seconds', 15)}**s", inline=False)
    embed.add_field(name="Privacy Policy",
                    value="🔒 https://github.com/ClanNorris/SWU-Card-Fetcher/blob/main/PRIVACY.md",
                    inline=False)
    await interaction.response.send_message(embed=embed)


# ====================== PING ======================
@tree.command(name="ping", description="Check the bot's websocket latency")
async def ping_command(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! 🏓 {latency_ms}ms")


# ====================== BOTINFO ======================
class BotInfoView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(discord.ui.Button(
            label="Add to your server",
            url="https://discord.com/oauth2/authorize?client_id=1426062447734820926&permissions=76864&integration_type=0&scope=bot+applications.commands",
            style=discord.ButtonStyle.link
        ))


@tree.command(name="botinfo", description="Show bot usage info and invite link")
async def botinfo_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="SWU Card Fetcher",
        description="Supports inline syntax, fuzzy search, set-specific filtering.",
        color=0xFFD700
    )
    embed.add_field(
        name="Inline Lookup",
        value="Type `[[Card Name]]` anywhere in chat.\nExample: `[[Darth Vader]]` or `[[Han Solo]]`",
        inline=False
    )
    embed.add_field(
        name="Slash Command",
        value="`/swucard <name>`",
        inline=True
    )
    embed.add_field(
        name="Fuzzy Search",
        value="`[[dath vader]]` → Darth Vader\n`[[han sollo]]` → Han Solo",
        inline=True
    )
    embed.add_field(
        name="Set-Specific Search",
        value="`[[Han Solo:SOR]]` or `[[Han Solo SOR]]` — either format works.\nSupported codes: `SOR` `SHD` `TWI` `JTL` `LOF` `IBH` `SEC` `LAW` `ASH`",
        inline=False
    )
    embed.add_field(
        name="Multi-Result Selection",
        value="The bot posts a numbered list. React with the emoji or reply with the number to pick your card.",
        inline=False
    )
    embed.set_footer(text="GitHub: https://github.com/ClanNorris/SWU-Card-Fetcher")
    await interaction.response.send_message(embed=embed, view=BotInfoView())


# ====================== CORE FUNCTIONS ======================
async def refresh_card_cache():
    global card_name_cache
    try:
        resp = requests.get("https://api.swu-db.com/catalog/card-names", timeout=10)
        if resp.status_code != 200:
            print(f"⚠️ Card name cache fetch returned {resp.status_code} — cache unchanged")
            return
        names = resp.json()
        if isinstance(names, dict):
            new_cache = names.get("data", [])
        elif isinstance(names, list):
            new_cache = names
        else:
            print(f"⚠️ Card name cache response malformed — cache unchanged")
            return
        if not new_cache:
            print(f"⚠️ Card name cache response was empty — cache unchanged")
            return
        card_name_cache = new_cache
        print(f"✅ Card name cache loaded: {len(card_name_cache)} names")
    except requests.exceptions.Timeout:
        print(f"⚠️ Card name cache fetch timed out — cache unchanged")
    except Exception as e:
        print(f"⚠️ Failed to load card name cache: {e}")


def parse_query(raw: str) -> tuple:
    # Colon-separated: "han solo:sor"
    if ':' in raw:
        name_part, _, code_part = raw.rpartition(':')
        if code_part.strip().lower() in KNOWN_SET_CODES:
            return name_part.strip(), code_part.strip().lower()
    # Space-separated: "han solo sor"
    parts = raw.rsplit(' ', 1)
    if len(parts) == 2 and parts[1].strip().lower() in KNOWN_SET_CODES:
        return parts[0].strip(), parts[1].strip().lower()
    return raw.strip(), None


def fuzzy_match_name(query: str) -> str:
    if not card_name_cache:
        return query
    base_names = [name.split(' - ', 1)[0].strip() for name in card_name_cache]
    result = fuzz_process.extractOne(query, base_names, score_cutoff=70)
    if result:
        return result[0]
    return query


def check_api_rate_limit(guild_id: int, user_id: int, cfg: dict) -> bool:
    limit = cfg.get("api_rate_limit_calls", 3)
    window = cfg.get("api_rate_limit_seconds", 10)
    key = (guild_id, user_id)
    now = datetime.now()
    cutoff = now - timedelta(seconds=window)
    times = [t for t in api_call_times.get(key, []) if t > cutoff]
    api_call_times[key] = times
    if len(times) >= limit:
        return False
    api_call_times[key].append(now)
    return True


def is_channel_allowed(channel_id: int, cfg: dict) -> bool:
    mode = cfg.get('channel_mode', 'whitelist')
    allowed = cfg.get('allowed_channels', [])
    if mode == 'whitelist':
        return channel_id in allowed
    return channel_id not in allowed


def search_card(query: str):
    try:
        card_name, set_code = parse_query(query)
        if set_code:
            api_name = card_name.replace("-", " ")
            q = f'{api_name} set:{set_code}'
        else:
            matched = fuzzy_match_name(card_name)
            base_name = matched.split(' - ', 1)[0].strip()
            api_name = base_name.replace("-", " ")
            q = api_name
        resp = requests.get("https://api.swu-db.com/cards/search", params={"q": q, "limit": 15}, timeout=10)
        if resp.status_code != 200:
            print(f"⚠️ API returned {resp.status_code} for query: {q}")
            return []
        data = resp.json()
        return data.get("data", [])
    except requests.exceptions.Timeout:
        print(f"⚠️ API timeout for query: {query}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"⚠️ API request error for query '{query}': {e}")
        return []
    except Exception as e:
        print(f"⚠️ search_card error for query '{query}': {e}")
        return []


async def expire_list(list_msg, channel_id, user_id, seconds):
    await asyncio.sleep(seconds)
    key = (channel_id, user_id, list_msg.id)
    if key in active_searches:
        try:
            await list_msg.delete()
        except Exception as e:
            print(f"⚠️ [expire list]: {e}")
        active_searches.pop(key, None)


def build_card_embed(card: dict) -> discord.Embed:
    subtitle = card.get('Subtitle', '')
    full_title = f"{card.get('Name', 'Unknown')} - {subtitle}" if subtitle else card.get('Name', 'Unknown')
    embed = discord.Embed(title=full_title, description=card.get('FrontText', 'No text available')[:500], color=0x00b0f4)
    if card.get('FrontArt'):
        embed.set_image(url=card['FrontArt'])
    embed.add_field(name="Set", value=f"{card.get('Set')} #{card.get('Number')}", inline=True)
    embed.add_field(name="Type", value=card.get('Type', 'N/A'), inline=True)
    embed.add_field(name="Cost", value=str(card.get('Cost', 'N/A')), inline=True)
    return embed


def build_results_list_embed(query: str, cards: list) -> discord.Embed:
    embed = discord.Embed(
        title=f"🔍 Multiple cards found for: **{query}**",
        description="Click a reaction or reply with a number",
        color=0x00b0f4
    )
    for i, card in enumerate(cards, 1):
        subtitle = card.get('Subtitle', '')
        full_name = f"{card.get('Name', '')} - {subtitle}" if subtitle else card.get('Name', '')
        embed.add_field(name=f"{i}. {full_name}", value=f"{card.get('Set')} #{card.get('Number')} • {card.get('Type')}", inline=False)
    return embed


async def post_results_list(query: str, send, channel_id: int, user_id: int, cards: list, cfg: dict) -> discord.Message:
    list_msg = await send(embed=build_results_list_embed(query, cards))
    active_searches[(channel_id, user_id, list_msg.id)] = cards
    reactions = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    for i in range(min(len(cards), 10)):
        try:
            await list_msg.add_reaction(reactions[i])
        except Exception as e:
            print(f"⚠️ [add reaction]: {e}")
    asyncio.create_task(expire_list(list_msg, channel_id, user_id, cfg.get("list_expire_seconds", 15)))
    return list_msg


# ====================== SWUCARD ======================
@tree.command(name="swucard", description="Fetch a Star Wars Unlimited card")
@app_commands.describe(name="Card name to search for")
async def swucard_command(interaction: discord.Interaction, name: str):
    cfg = await get_guild_config(interaction.guild_id)
    if not is_channel_allowed(interaction.channel_id, cfg):
        await interaction.response.send_message("❌ This bot is not enabled in this channel.", ephemeral=True)
        return
    if not check_api_rate_limit(interaction.guild_id, interaction.user.id, cfg):
        limit = cfg.get("api_rate_limit_calls", 3)
        window = cfg.get("api_rate_limit_seconds", 10)
        await interaction.response.send_message(f"⏳ Slow down — maximum {limit} card lookups per {window} seconds.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=False)
    results = search_card(name)
    if not results:
        await interaction.followup.send(f"❌ No card found for: **{name}**")
        return

    max_res = cfg.get("max_results", 10)
    displayed = results[:max_res]

    if len(displayed) == 1:
        await send_card_with_sides(interaction.channel, displayed[0])
        await asyncio.sleep(2.5)
        try: await interaction.delete_original_response()
        except Exception as e: print(f"⚠️ [delete original response]: {e}")
    else:
        await post_results_list(name, interaction.followup.send, interaction.channel.id, interaction.user.id, displayed, cfg)


# ====================== INLINE [[ ]] ======================
@bot.event
async def on_message(message):
    if message.author == bot.user or message.guild is None:
        return
    cfg = await get_guild_config(message.guild.id)
    if not is_channel_allowed(message.channel.id, cfg):
        return

    cooldown_sec = cfg.get("cooldown_seconds", 0)
    if cooldown_sec > 0:
        cooldown_key = (message.guild.id, message.author.id)
        now = datetime.now()
        if cooldown_key in user_cooldowns and (now - user_cooldowns[cooldown_key] < timedelta(seconds=cooldown_sec)):
            await message.channel.send(f"⏳ **{message.author.display_name}**, on {cooldown_sec}-second cooldown...", delete_after=8)
            return
        user_cooldowns[cooldown_key] = now

    matches = re.findall(r'\[\[(.+?)\]\]', message.content)
    if not matches:
        await handle_number_reply(message)
        return

    for query in matches:
        query = query.strip()
        if not query: continue
        if not check_api_rate_limit(message.guild.id, message.author.id, cfg):
            limit = cfg.get("api_rate_limit_calls", 3)
            window = cfg.get("api_rate_limit_seconds", 10)
            await message.channel.send(f"⏳ Slow down — maximum {limit} card lookups per {window} seconds.", delete_after=8)
            break
        try:
            results = search_card(query)
            if not results:
                await message.channel.send(f"❌ No card found for: **{query}**")
                continue

            max_res = cfg.get("max_results", 10)
            displayed = results[:max_res]

            if len(displayed) == 1:
                await send_card_with_sides(message.channel, displayed[0])
            else:
                await post_results_list(query, message.channel.send, message.channel.id, message.author.id, displayed, cfg)

        except Exception as e:
            print(f"⚠️ [inline search for '{query}']: {e}")

    if cfg.get('delete_inline_trigger', False):
        remaining = re.sub(r'\[\[.+?\]\]', '', message.content).strip()
        if not remaining:
            try: await message.delete()
            except Exception as e: print(f"⚠️ [delete inline trigger]: {e}")


# ====================== REACTION + NUMBER ======================
@bot.event
async def on_reaction_add(reaction, user):
    if user == bot.user: return
    message = reaction.message
    key = (message.channel.id, user.id, message.id)
    if key in active_searches:
        results = active_searches[key]
        emoji_map = {"1️⃣":1,"2️⃣":2,"3️⃣":3,"4️⃣":4,"5️⃣":5,"6️⃣":6,"7️⃣":7,"8️⃣":8,"9️⃣":9,"🔟":10}
        num = emoji_map.get(str(reaction.emoji))
        if num and 1 <= num <= len(results):
            await send_card_with_sides(message.channel, results[num-1])
            cfg = await get_guild_config(message.guild.id) if message.guild else dict(DEFAULT_CONFIG)
            if cfg.get('delete_after_pick', True):
                try: await message.delete()
                except Exception as e: print(f"⚠️ [delete after pick]: {e}")
            active_searches.pop(key, None)


async def handle_number_reply(message):
    content = message.content.strip()
    if not content.isdigit():
        return
    num = int(content)
    cfg = await get_guild_config(message.guild.id) if message.guild else dict(DEFAULT_CONFIG)
    if not (1 <= num <= cfg.get("max_results", 10)):
        return

    target_list_id = None
    if message.reference and message.reference.message_id:
        target_list_id = message.reference.message_id

    for key, results in list(active_searches.items()):
        ch_id, u_id, list_id = key
        if ch_id == message.channel.id and u_id == message.author.id:
            if target_list_id is None or list_id == target_list_id:
                if 1 <= num <= len(results):
                    await send_card_with_sides(message.channel, results[num-1])
                    if cfg.get('delete_after_pick', True):
                        try:
                            list_msg = await message.channel.fetch_message(list_id)
                            await list_msg.delete()
                        except Exception as e: print(f"⚠️ [delete list message]: {e}")
                        try: await message.delete()
                        except Exception as e: print(f"⚠️ [delete number reply]: {e}")
                    active_searches.pop(key, None)
                break


async def send_card_with_sides(channel, card):
    await channel.send(embed=build_card_embed(card))
    if card.get('DoubleSided') and card.get('BackArt'):
        subtitle = card.get('Subtitle', '')
        full_title = f"{card.get('Name', 'Unknown')} - {subtitle}" if subtitle else card.get('Name', 'Unknown')
        back_embed = discord.Embed(title=full_title + " (Back)", description=card.get('BackText', 'No back text available')[:500], color=0x00b0f4)
        back_embed.set_image(url=card['BackArt'])
        await channel.send(embed=back_embed)


# Run the bot
bot.run(os.environ["DISCORD_TOKEN"])