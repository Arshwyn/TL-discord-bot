# Throne and Liberty Discord Bot

A fully-featured, database-backed Discord bot built for managing *Throne and Liberty* guilds. It automates roster management, event scheduling, automated attendance auditing, and features a weighted-probability loot distribution system to enforce fair-play.

## 🌟 Core Features

* **Profile & Static Management:** Players register their gear score and weapons. Officers group them into Statics, generating dynamic views of party compositions and average gear scores.
* **Event Scheduling:** Create recurring or one-time events with automated warning pings. Interactive UI buttons handle RSVPs (Attending, Not Attending, Tentative).
* **Automated Attendance Auditing:** The bot scans Voice Channels 20 minutes after an event begins to verify RSVPs. It penalizes "Ghosted" players (RSVP'd but no-show) and "Unregistered" players (Showed up but didn't RSVP) on a 30-day leaderboard.
* **Weighted Loot Roller:** Post loot drops with images. Players roll Need, Alt/Want, or Greed. The bot auto-rolls the winner using a decaying priority mechanic (100% -> 50% -> 0%) based on recent wins to prevent loot funneling. Loot penalties automatically reset bi-weekly.

---

## 🛠️ Prerequisites

* [Docker](https://docs.docker.com/get-docker/) & Docker Compose
* A Discord Bot Token (Grab one from the [Discord Developer Portal](https://discord.com/developers/applications))

---

## 🚀 Installation & Setup

**1. Clone the repository:**
```bash
git clone [https://github.com/yourusername/TL-discord-bot.git](https://github.com/yourusername/TL-discord-bot.git)
cd TL-discord-bot
```

**2. Configure Environment Variables (.env):**
Because this bot is built for plug-and-play deployment, you only need to provide your bot's secret token.
```bash
cp .env.example .env
```
Open the `.env` file and add your token:
* `DISCORD_BOT_TOKEN=your_discord_bot_token_here`

**3. Deploy with Docker:**
The bot utilizes SQLite for easy, portable data storage. The `docker-compose.yml` automatically mounts a local `./data` folder to persist your database across container reboots.
```bash
docker-compose up -d --build
```

**4. Initial Discord Setup:**
Once the bot joins your server, its slash commands will sync globally. An Admin must run the following command inside your server so the bot knows who to ping for events:
* `/set_ping_roles @Role1 [@Role2] [@Role3]`

---

## 📜 Command Reference

*Note: Commands marked with **Admin Only** require the user to have the `Manage Server` permission in Discord.*

### ⚙️ Bot Configuration
| Command | Permission | Description |
| :--- | :--- | :--- |
| `/set_ping_roles` | Admin Only | Set up to 3 roles (e.g., @Member, @Raider) that the bot will automatically ping when event reminders trigger. |

### 🛡️ Profile & Statics
| Command | Permission | Description |
| :--- | :--- | :--- |
| `/profile setup` | Everyone | Register In-game name, Weapons, and Gear Score. |
| `/profile view [user]` | Everyone | View a member's profile card. |
| `/static list [group]` | Everyone | View statics, class compositions, and average Gear Score. |
| `/profile directory` | Admin Only | View all registered members sorted by Gear Score. |
| `/static assign <user> <group>` | Admin Only | Assign a user to a specific static. |
| `/static remove <user>` | Admin Only | Remove a user from a static. |

### 📅 Events & Attendance
| Command / Action | Permission | Description |
| :--- | :--- | :--- |
| `RSVP UI Buttons` | Everyone | Click on an active event to log attendance. |
| `/create_event` | Admin Only | Schedule an event with custom pings, recurrence, and specific VC targeting. |
| `/edit_event` | Admin Only | Modify an active event. |
| `/delete_event` | Admin Only | Cancel an event. |
| `/list_events` | Admin Only | View all upcoming events and their database IDs. |
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
* **Discord API:** discord.py (Slash commands, UI components, background tasks)
* **Database:** SQLite (Persistent local storage)
* **ORM:** SQLAlchemy 2.0
* **Package Manager:** uv (Ultra-fast Python package manager)
* **Deployment:** Docker & Docker Compose