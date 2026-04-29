# SWU Card Fetcher

A Discord bot for looking up **Star Wars Unlimited** cards instantly in chat. Supports inline syntax, fuzzy search, set-specific filtering, and full per-server customization.

---

## ➕ Add to Your Server

**[Click here to invite SWU Card Fetcher](https://discord.com/oauth2/authorize?client_id=1426062447734820926&permissions=76864&integration_type=0&scope=bot+applications.commands)**

---

## Usage

### Inline Lookup
Type `[[Card Name]]` anywhere in chat and the bot will fetch the card automatically.

```
[[Darth Vader]]
[[Han Solo]]
[[luke skywalker]]
```

### Slash Command
```
/swucard <name>
```

### Set-Specific Search
Narrow your search to a specific set using a colon or space before the set code:
```
[[Han Solo:SOR]]
[[Han Solo SOR]]
```

**Supported set codes:**
| Code | Set |
|------|-----|
| `SOR` | Spark of Rebellion |
| `SHD` | Shadows of the Galaxy |
| `TWI` | Twilight of the Republic |
| `JTL` | Jump to Lightspeed |
| `LOF` | Legends of the Force |
| `IBH` | Intro Battle: Hoth |
| `SEC` | Secrets of Power |
| `LAW` | A Lawless Time |

### Fuzzy Search
Typos are no problem — the bot uses fuzzy matching to find the closest card name automatically.
```
[[dath vader]]      → Darth Vader
[[han sollo]]       → Han Solo
```

### Multi-Result Selection
If multiple cards match your search, the bot posts a numbered list. Pick your card by:
- Clicking a reaction emoji (1️⃣–🔟)
- Replying with the number

The list auto-deletes after a configurable timeout.

---

## Admin Commands

All admin commands require the **Administrator** permission.

| Command | Description |
|---------|-------------|
| `/swusettings` | View all current settings for this server |
| `/swuhelp` | Show usage help |
| `/swucooldown <seconds>` | Set per-user cooldown between lookups (0 = disabled) |
| `/swumaxresults <number>` | Set max results shown (5–12) |
| `/swuexpire <seconds>` | Set how long selection lists stay before auto-deleting |
| `/swuaddchannel <channel>` | Add a channel to the allowed list |
| `/swuremovechannel <channel>` | Remove a channel from the allowed list |
| `/swuchannelmode <mode>` | Set channel mode: `whitelist` or `blacklist` |
| `/swureloadcards` | Manually refresh the card name cache |

### Channel Modes
- **Whitelist** — bot only responds in listed channels (empty list = all channels allowed)
- **Blacklist** — bot responds everywhere except listed channels (empty list = all channels allowed)

---

## Permissions Required

| Permission | Reason |
|-----------|--------|
| Read Messages / View Channels | See messages to process lookups |
| Send Messages | Post card embeds |
| Manage Messages | Delete trigger messages and expired lists |
| Add Reactions | Add emoji reactions to selection lists |
| Read Message History | Resolve reaction-based selections |

---

## Self-Hosting

If you'd prefer to run your own instance:

**1. Clone the repo:**
```bash
git clone https://github.com/ClanNorris/SWU-Card-Fetcher.git
cd SWU-Card-Fetcher
```

**2. Install dependencies:**
```bash
pip install -r requirements.txt
```

**3. Create a `.env` file:**
```
DISCORD_TOKEN=your_bot_token_here
```

**4. Run the bot:**
```bash
python swuCardFetcher.py
```

Card data is provided by [swu-db.com](https://www.swu-db.com).

---

## Contributing

Issues and pull requests are welcome. Please open an issue first for any significant changes.
