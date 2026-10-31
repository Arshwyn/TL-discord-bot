# Codex - Throne and Liberty Discord Bot

Codex is a fully-featured, database-backed Discord bot built for managing *Throne and Liberty* guilds. It automates roster management, event scheduling, automated attendance auditing, and features a weighted-probability loot distribution system to enforce fair-play.

## 🌟 Core Features

* **Unlimited Multi-Build Profiles:** Players can register multiple distinct build variations (e.g., "GvG Evasion Tank", "Dungeon DPS", "Arena Healer") under a single Discord account. Build names and optimization tags (PvE/PvP) are mandatory during creation.
* **Smart UI Dropdowns (Autocomplete):** When updating or viewing active loadouts, Codex queries the SQLite database in real-time to populate interactive, zero-friction dropdown menus containing exact build names.
* **Gear Verification Receipt:** Built for competitive environments, profiles support an optional screenshot slot, rendering verified gear score captures directly within rich profile cards.
* **Event Scheduling & Channel Targeted Auditing:** Create recurring or one-time events with custom warning pings. Codex scans targeted Voice Channels exactly 20 minutes after an event begins, evaluating active raiders against interactive RSVP button logs to generate a 30-day attendance leaderboard.
* **Weighted Loot Roller:** Post loot drops with images. Players roll Need, Alt/Want, or Greed. The bot auto-rolls the winner using a decaying priority mechanic (100% -> 50% -> 0%) based on recent wins to prevent loot funneling — Need and Alt/Want each track their own decay independently, while Greed is always a flat, undecayed roll so unwanted loot doesn't sit around uncontested. Need/Alt-Want penalties automatically reset bi-weekly.

---

## 🛠️ Prerequisites

* [Docker](https://docs.docker.com/get-docker/) & Docker Compose, **or** Python 3.12+ with [uv](https://docs.astral.sh/uv/)
* A Discord application with a bot user (see below)

---

## 🚀 Installation & Setup

### 1. Create the Discord application and bot
1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**.
2. In the **Bot** tab, create the bot user and use **Reset Token** to copy its token (you will put it in `.env` later; never share or commit it).
3. In the same tab, under **Privileged Gateway Intents**, enable:
   * **Message Content Intent**
   * **Server Members Intent**
4. In **OAuth2 > URL Generator**, select the scopes `bot` and `applications.commands`, then grant these bot permissions:
   * View Channels
   * Send Messages
   * Send Messages in Threads
   * Create Public Threads
   * Manage Threads (used to archive/lock closed loot threads)
   * Embed Links
   * Attach Files
   * Read Message History
   * Manage Roles (onboarding assigns roles)
   * Manage Nicknames (onboarding sets members' nicknames to their in-game name)
5. Open the generated URL to invite the bot to your server.
6. In **Server Settings > Roles**, drag the bot's role **above** every role it needs to assign (and above the members whose nicknames it sets). Discord does not let a bot manage roles higher than its own.

### 2. Clone the repository
```bash
git clone https://github.com/<your-github-user>/TL-discord-bot.git
cd TL-discord-bot
```

### 3. Configure environment variables (.env)
```bash
cp .env.example .env
```
Open `.env` and set:
* `DISCORD_BOT_TOKEN`: the bot token from step 1 (required).
* `DATABASE_URL`: optional. Defaults to `sqlite:///./data/guild_bot.db` when unset.

### 4. Run the bot

**With Docker:**
```bash
docker compose up -d --build
```
`docker-compose.yml` mounts the local `./data` folder into the container, so the database survives restarts and rebuilds. Only `DISCORD_BOT_TOKEN` is passed through to the container by the compose file; if you want `DATABASE_URL` to apply in Docker, add it to the `environment:` list and keep it pointing inside the mounted `/app/data` folder.

The built image is named `tl-discord-bot:${IMAGE_TAG}`. `IMAGE_TAG` is optional (set it in your shell or `.env`) and defaults to `latest`. To tag a build with the current commit:
```bash
IMAGE_TAG=<short-commit-sha> docker compose build
```

The Docker image is built on `python:3.12.16-slim-trixie` (Python 3.12.16 on Debian 13), pinned to an exact tag for reproducible builds. To bump it, change the `FROM` line in the `Dockerfile` to a newer 3.12.x `slim-trixie` tag and rebuild. The `uv` binary is likewise copied from the pinned `ghcr.io/astral-sh/uv:0.13.6` image; bump the version in the `COPY --from=` line of the `Dockerfile` to update it.

**Without Docker:**
```bash
uv sync
uv run bot.py
```

### 5. Data location
Data is stored in SQLite at `./data/guild_bot.db` (created automatically, and migrated automatically on every start). Set `DATABASE_URL` to use a different SQLite file; the same value is used by the bot and by the Alembic migrations.

### 6. Initial Discord setup
Slash commands sync globally on startup; the first sync can take up to about an hour to appear in your server. Then an Admin (`Manage Server` permission) should run:
* `/set_ping_roles @Role1 [@Role2] [@Role3]`: roles pinged for event reminders.
* `/set_event_manager_role <role>`: (optional) a role allowed to manage events.
* `/set_onboarding_roles [member_role] [unverified_role]`: roles used by onboarding (the member role is added on verification; the unverified/guest role is removed).
* `/spawn_onboarding`: posts the persistent onboarding button in the current channel.

---

## 📜 Command Reference

*Note: Commands marked with **Admin Only** require the user to have the `Manage Server` permission in Discord. Commands marked with **Event Manager** are also usable by anyone holding the role configured via `/set_event_manager_role`.*

### ⚙️ Bot Configuration
| Command | Permission | Description |
| :--- | :--- | :--- |
| `/set_ping_roles` | Admin Only | Set up to 3 roles (e.g., @Member, @Raider) that Codex will automatically ping when event reminders trigger. |
| `/set_event_manager_role <role>` | Admin Only | Grant a role permission to create, edit, delete, and list events without needing `Manage Server`. |
| `/set_onboarding_roles [member_role] [unverified_role]` | Admin Only | Configure the base member role and the guest/unverified role used by onboarding. |
| `/view_onboarding_roles` | Admin Only | View the roles currently mapped for onboarding. |
| `/delete_onboarding_roles` | Admin Only | Clear all mapped onboarding roles. |
| `/spawn_onboarding` | Admin Only | Post the persistent onboarding button in the current channel. |
| `/view_ping_roles` | Admin Only | Check which roles are configured for event pings. |
| `/delete_ping_roles` | Admin Only | Reset and remove all configured ping roles. |
| `/view_event_manager_role` | Admin Only | Check which role is currently configured as Event Manager. |
| `/clear_event_manager_role` | Admin Only | Remove the configured Event Manager role, restricting event management back to `Manage Server` only. |

### 🛡️ Profile & Statics
| Command / Action | Permission | Description |
| :--- | :--- | :--- |
| `/profile setup` | Everyone | Create a brand new build configuration. Build name, tag (PvE/PvP), In-game name, and both weapons are **Mandatory**. Screen attachment is optional. |
| `/profile update` | Everyone | Modify parameters of an existing profile. Selection of target build name via dynamic **Autocomplete Dropdown** is **Mandatory**. All other text/stat inputs are optional. |
| `/profile view [user] [build]` | Everyone | View profile cards. If left completely blank, shows a directory summary of *all* active builds owned by that user. Select a specific build name using **Autocomplete** to display its detailed card and gear verification screenshot. |
| `/static list [group] [type]` | Everyone | View static rosters, class compositions, and average gear score filtered by structural target tags (PvE vs. PvP variants). |
| `/profile delete` | Everyone | Permanently delete one of your own build profiles (select the build via autocomplete). |
| `/profile admin_update` | Admin Only | Override and update a specific member's build or in-game name. |
| `/profile admin_delete` | Admin Only | Permanently delete a member's build profile. |
| `/profile prune` | Admin Only | Delete profiles of users who have left the server. |
| `/profile directory [type]` | Admin Only | View all registered guild profiles sorted sequentially by Gear Score based on target contents. |
| `/static assign <user> <group>` | Admin Only | Assign a user to a specific static party across all corresponding profiles. |
| `/static remove <user>` | Admin Only | Clear a user's static party layout completely. |

### 📅 Events & Attendance
| Command / Action | Permission | Description |
| :--- | :--- | :--- |
| `RSVP UI Buttons` | Everyone | Click on an active event to log attendance. |
| `/create_event` | Event Manager | Schedule an event with custom pings, recurrence, and specific VC targeting. |
| `/edit_event` | Event Manager | Modify an active event. |
| `/delete_event` | Event Manager | Cancel an event. |
| `/list_events` | Event Manager | View all upcoming events and their database IDs. |
| `/view_roster <id>` | Admin Only | View a detailed RSVP breakdown sorted by static. |
| `/attendance_summary <id>` | Admin Only | View the VC audit (Present, Ghosted, Unregistered). |
| `/attendance_leaderboard` | Admin Only | View the 30-day guild attendance leaderboard. |

### 🎁 Loot Distribution
| Command / Action | Permission | Description |
| :--- | :--- | :--- |
| `Roll UI Buttons` | Everyone | Click to log a roll for Need, Alt/Want, or Greed. |
| `/loot priority_check [user]` | Everyone | Check a user's current loot win penalty (100%, 50%, 0%). |
| `/loot distribute <name>` | Admin Only | Post an item (with an optional image) for rolling. |
| `Auto Roll Winner` | Admin Only | Rolls the item using priority logic, announces the winner, applies the loot penalty to the winner, and locks the post. |
| `Reroll Item` | Admin Only | Refunds the prior winner, removes them from the pool, and rerolls the item. |
| `/loot priority_reset` | Admin Only | Reset a specific user, or reset the whole guild to 100% and realign the 14-day automatic timer. |

---

## 🏗️ Architecture
* **Language:** Python 3.12+
* **Discord API:** discord.py (Slash commands, App Autocomplete, UI components, background tasks)
* **Database:** SQLite (Persistent local storage via composite primary data structures)
* **ORM:** SQLAlchemy 2.0
* **Package Manager:** uv (Ultra-fast Python package manager)
* **Deployment:** Docker & Docker Compose (base image pinned to `python:3.12.16-slim-trixie`)