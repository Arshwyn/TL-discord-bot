import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
import zoneinfo

from database.db_setup import get_db
from database.models import GuildEvent

class SchedulingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="create_event", 
        description="Schedule a guild event (Automatically alerts users in their local timezone)"
    )
    @app_commands.describe(
        name="Name of the event (e.g., Archboss Tevent)",
        description="Details about requirements or groups",
        date_time="Format: YYYY-MM-DD HH:MM (e.g., 2026-07-15 20:00)",
        tz_input="Select your input timezone"
    )
    # Limit choices to standard NA options to keep it simple for officers
    @app_commands.choices(tz_input=[
        app_commands.Choice(name="Eastern Time (EST/EDT)", value="US/Eastern"),
        app_commands.Choice(name="Central Time (CST/CDT)", value="US/Central"),
        app_commands.Choice(name="Mountain Time (MST/MDT)", value="US/Mountain"),
        app_commands.Choice(name="Pacific Time (PST/PDT)", value="US/Pacific"),
        app_commands.Choice(name="Coordinated Universal Time (UTC)", value="UTC"),
    ])
    async def create_event(
        self, 
        interaction: discord.Interaction, 
        name: str, 
        date_time: str, 
        tz_input: str = "UTC",
        description: str = None
    ):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ You do not have permission to schedule events.", ephemeral=True)
            return

        try:
            naive_dt = datetime.strptime(date_time, "%Y-%m-%d %H:%M")
            user_tz = zoneinfo.ZoneInfo(tz_input)
            localized_dt = naive_dt.replace(tzinfo=user_tz)
            
            unix_timestamp = int(localized_dt.timestamp())
            utc_dt = localized_dt.astimezone(timezone.utc)

        except ValueError:
            await interaction.response.send_message(
                "❌ **Invalid date format!** Please use `YYYY-MM-DD HH:MM` (e.g., `2026-06-30 19:30`).", 
                ephemeral=True
            )
            return

        with next(get_db()) as db:
            new_event = GuildEvent(
                name=name,
                description=description,
                start_time=utc_dt,
                is_posted=False
            )
            db.add(new_event)
            db.commit()
            event_id = new_event.id

        discord_time_full = f"<t:{unix_timestamp}:F>"
        discord_time_relative = f"<t:{unix_timestamp}:R>"

        await interaction.response.send_message(
            f"✅ **Event Scheduled successfully!** (Event ID: `{event_id}`)\n"
            f"**Event:** {name}\n"
            f"**Your local display time:** {discord_time_full} ({discord_time_relative})",
            ephemeral=True
        )

    @app_commands.command(
        name="list_events", 
        description="Debug command to view all scheduled events inside the database"
    )
    async def list_events(self, interaction: discord.Interaction):
        # Permission check matching our creation tool
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        with next(get_db()) as db:
            # Query all events sorted by upcoming start time
            events = db.query(GuildEvent).order_by(GuildEvent.start_time.asc()).all()

        if not events:
            await interaction.response.send_message("📭 The database is currently empty.", ephemeral=True)
            return

        # Build a scannable markdown list
        report = "📋 **Current Database Entries:**\n\n"
        for event in events:
            unix_ts = int(event.start_time.replace(tzinfo=timezone.utc).timestamp())
            report += (
                f"🔹 **ID:** `{event.id}` | **Name:** {event.name}\n"
                f" └ *Time (UTC stored):* `{event.start_time}`\n"
                f" └ *Renders locally as:* <t:{unix_ts}:F> (<t:{unix_ts}:R>)\n"
                f" └ *Posted Status:* `{'✅ Yes' if event.is_posted else '❌ Pending 72h Loop'}`\n\n"
            )

        await interaction.response.send_message(report, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(SchedulingCog(bot))