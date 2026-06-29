import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from database.db_setup import init_db

load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class TLGuildBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        print("Initializing persistence layer...")
        init_db()
        print("Database sync complete.")

        os.makedirs('./cogs', exist_ok=True)
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                await self.load_extension(f'cogs.{filename[:-3]}')
        
        # GLOBAL COMMAND SYNC: Automatically works in ANY server the bot joins!
        await self.tree.sync()
        print("Synced slash commands globally.")

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('Throne and Liberty Bot is active.')

bot = TLGuildBot()

if __name__ == '__main__':
    if not TOKEN:
        raise ValueError("No token found. Please set DISCORD_BOT_TOKEN in .env")
    bot.run(TOKEN)