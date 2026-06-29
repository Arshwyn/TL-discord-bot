# Throne and Liberty Discord Bot

A fully-featured, database-backed Discord bot built for managing *Throne and Liberty* guilds. It automates roster management, event scheduling, automated attendance auditing, and features a weighted probability loot distribution system.

## 🌟 Core Features

* **Profile & Static Management:** Players register their gear score and weapons. Officers group them into Statics, generating dynamic views of party compositions and average gear scores.
* **Event Scheduling:** Create recurring or one-time events with automated warning pings. Interactive UI buttons handle RSVPs (Attending, Not Attending, Tentative).
* **Automated Attendance Auditing:** The bot scans Voice Channels shortly after an event begins to verify RSVPs. It penalizes "Ghosted" players (RSVP'd but no-show) and "Unregistered" players (Showed up but didn't RSVP) on a 30-day leaderboard.
* **Weighted Loot Roller:** Post loot drops with images. Players roll Need, Alt/Want, or Greed. The bot auto-rolls the winner using a decaying probability mechanic (100% -> 50% -> 0%) to prevent loot funneling. Loot penalties automatically reset bi-weekly.

## 🛠️ Prerequisites

* [Docker](https://docs.docker.com/get-docker/) & Docker Compose
* A Discord Bot Token (Grab one from the [Discord Developer Portal](https://discord.com/developers/applications))
* Server Role IDs (Member role, Officer role)

## 🚀 Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/yourusername/TL-discord-bot.git](https://github.com/yourusername/TL-discord-bot.git)
   cd TL-discord-bot