import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

# Load secrets from .env
load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
GUILD_ID = os.getenv('GUILD_ID')

# Intents are required to read member data and message content
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class TLGuildBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Load extensions/cogs dynamically
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                await self.load_extension(f'cogs.{filename[:-3]}')
        
        # Sync slash commands to your specific server instantly
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