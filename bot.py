import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from database.db_setup import init_db  # <-- Import database runner

load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
GUILD_ID = os.getenv('GUILD_ID')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class TLGuildBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # 1. Initialize the SQLite Database Tables
        print("Initializing persistence layer...")
        init_db()
        print("Database sync complete.")

        # 2. Load Cog files
        os.makedirs('./cogs', exist_ok=True) # Ensure directory exists
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                await self.load_extension(f'cogs.{filename[:-3]}')
        
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"Synced slash commands to Guild ID: {GUILD_ID}")

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('Throne and Liberty Bot is active.')

bot = TLGuildBot()

if __name__ == '__main__':
    if not TOKEN:
        raise ValueError("No token found. Please set DISCORD_BOT_TOKEN in .env")
    bot.run(TOKEN)