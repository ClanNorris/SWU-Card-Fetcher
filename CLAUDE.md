# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Bot

```bash
python swuCardFetcher.py
```

Dependencies: `discord.py`, `requests`, `aiosqlite`, `python-dotenv`, `rapidfuzz`. Install via `pip install discord.py requests aiosqlite python-dotenv rapidfuzz`.

The Discord bot token is read from the `DISCORD_TOKEN` environment variable via `python-dotenv` (`.env` file). The same token is stored separately in `SWU key.txt`.

## Architecture

This is a single-file Discord bot (`swuCardFetcher.py`) that looks up Star Wars Unlimited cards from the [swu-db.com](https://api.swu-db.com) REST API and displays them as Discord embeds.

**Card lookup entry points:**
- Inline syntax: `[[Card Name]]` detected in `on_message`
- Slash command: `/swucard <name>` via `swucard_command`

Both paths call `search_card(query)` → `https://api.swu-db.com/cards/search`, then either display a single card directly via `send_card_with_sides()` or post a numbered selection list.

**Selection flow:** When multiple results are returned, they are stored in `active_searches` keyed by `(channel_id, user_id, message_id)`. The user resolves the selection via emoji reactions (`on_reaction_add`) or a plain number reply (`handle_number_reply`). The list auto-deletes after `list_expire_seconds` via `expire_list()`.

**Key in-memory state:**
- `active_searches`: `dict[(channel_id, user_id, msg_id) → list[card]]` — pending selections
- `user_cooldowns`: `dict[(guild_id, user_id) → datetime]` — per-message cooldown tracking
- `api_call_times`: `dict[(guild_id, user_id) → list[datetime]]` — rolling window for API rate limiting
- `card_name_cache`: `list[str]` — card names fetched from swu-db.com at startup for fuzzy matching

**Runtime config (SQLite: `bot.db`, table `guild_configs`, per-guild):**
| Key | Default | Set via |
|-----|---------|---------|
| `cooldown_seconds` | 0 | `/swucooldown` — 0 disables cooldown |
| `max_results` | 10 | `/swumaxresults` — clamped to 5–12 |
| `list_expire_seconds` | 15 | `/swuexpire` — auto-delete timeout for selection lists |
| `delete_after_pick` | true | (no command — edit DB directly) |
| `delete_inline_trigger` | false | `/swudeleteinline` — deletes pure `[[card]]` trigger messages |
| `channel_mode` | `"whitelist"` | `/swuchannelmode` — `"whitelist"` or `"blacklist"` |
| `allowed_channels` | `[]` | `/swuaddchannel`, `/swuremovechannel` |
| `api_rate_limit_calls` | 3 | (no command — edit DB directly) |
| `api_rate_limit_seconds` | 10 | (no command — edit DB directly) |

Settings are stored as JSON in the `settings` column. Missing keys always fall back to `DEFAULT_CONFIG` at read time, so new keys are safe to add without migrating existing rows. Admin slash commands fetch the guild config, mutate the relevant key, and call `save_guild_config()` — no global state or file I/O.

## Known Issues

- Double-sided card back is only shown when both `DoubleSided` is truthy **and** `BackArt` is present; `BackText` alone won't trigger a second embed.
