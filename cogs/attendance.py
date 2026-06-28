# cogs/attendance.py
import discord
from discord.ext import commands

class AttendanceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print("Attendance Cog loaded successfully.")

async def setup(bot: commands.Bot):
    await bot.add_cog(AttendanceCog(bot))