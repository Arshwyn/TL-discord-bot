import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone, timedelta
import zoneinfo
import os

from database.db_setup import get_db
from database.models import GuildEvent
from cogs.attendance import AttendanceView

class SchedulingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_events_loop.start()

    def cog_unload(self):
        self.check_events_loop.cancel()

    @app_commands.command(
        name="create_event", 
        description="Schedule a guild event"
    )
    @app_commands.describe(
        name="Name of the event (e.g., Archboss Tevent)",
        date_time="Format: YYYY-MM-DD HH:MM (e.g., 2026-07-15 20:00)",
        tz_input="Select your input timezone",
        recurrence="Does this event repeat?",
        requires_rsvp="True = Interactive Poll with buttons. False = Simple Notification."
    )
    @app_commands.choices(tz_input=[
        app_commands.Choice(name="Eastern Time (EST/EDT)", value="US/Eastern"),
        app_commands.Choice(name="Central Time (CST/CDT)", value="US/Central"),
        app_commands.Choice(name="Mountain Time (MST/MDT)", value="US/Mountain"),
        app_commands.Choice(name="Pacific Time (PST/PDT)", value="US/Pacific"),
        app_commands.Choice(name="Coordinated Universal Time (UTC)", value="UTC"),
    ])
    @app_commands.choices(recurrence=[
        app_commands.Choice(name="Does not repeat", value=0),
        app_commands.Choice(name="Weekly", value=7),
        app_commands.Choice(name="Bi-Weekly", value=14),
    ])
    async def create_event(
        self, 
        interaction: discord.Interaction, 
        name: str, 
        date_time: str, 
        tz_input: str = "UTC",
        recurrence: int = 0,
        requires_rsvp: bool = True,
        description: str = None
    ):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        try:
            naive_dt = datetime.strptime(date_time, "%Y-%m-%d %H:%M")
            user_tz = zoneinfo.ZoneInfo(tz_input)
            localized_dt = naive_dt.replace(tzinfo=user_tz)
            unix_timestamp = int(localized_dt.timestamp())
            utc_dt = localized_dt.astimezone(timezone.utc)
        except ValueError:
            await interaction.response.send_message("❌ **Invalid date format!** Use `YYYY-MM-DD HH:MM`", ephemeral=True)
            return

        with next(get_db()) as db:
            new_event = GuildEvent(
                name=name,
                description=description,
                start_time=utc_dt,
                recurrence_days=recurrence,
                requires_rsvp=requires_rsvp,
                is_posted=False
            )
            db.add(new_event)
            db.commit()

        poll_type = "📊 Interactive Poll" if requires_rsvp else "🔔 Notification Only"
        await interaction.response.send_message(
            f"✅ **Event Scheduled!**\n"
            f"**Event:** {name} `[{'Repeats every ' + str(recurrence) + ' days' if recurrence > 0 else 'One-time'}]`\n"
            f"**Type:** {poll_type}\n"
            f"**Time:** <t:{unix_timestamp}:F> (<t:{unix_timestamp}:R>)",
            ephemeral=True
        )

    @app_commands.command(
        name="list_events", 
        description="Debug command to view all scheduled events"
    )
    async def list_events(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        with next(get_db()) as db:
            events = db.query(GuildEvent).order_by(GuildEvent.start_time.asc()).all()

        if not events:
            await interaction.response.send_message("📭 The database is currently empty.", ephemeral=True)
            return

        report = "📋 **Current Database Entries:**\n\n"
        for event in events:
            unix_ts = int(event.start_time.replace(tzinfo=timezone.utc).timestamp())
            recurrence_str = f" | 🔁 Every {event.recurrence_days}d" if event.recurrence_days > 0 else ""
            rsvp_str = " | 📊 Poll" if event.requires_rsvp else " | 🔔 Notify"
            report += (
                f"🔹 **ID:** `{event.id}` | **Name:** {event.name}{recurrence_str}{rsvp_str}\n"
                f" └ *Time (UTC stored):* `{event.start_time}`\n"
                f" └ *Renders locally as:* <t:{unix_ts}:F> (<t:{unix_ts}:R>)\n"
                f" └ *Posted Status:* `{'✅ Yes' if event.is_posted else '❌ Pending 72h Loop'}`\n\n"
            )

        if len(report) > 2000:
            report = report[:1996] + "..."

        await interaction.response.send_message(report, ephemeral=True)

    @tasks.loop(seconds=60)
    async def check_events_loop(self):
        await self.bot.wait_until_ready()
        
        channel_id = os.getenv("SCHEDULE_CHANNEL_ID")
        role_member_id = os.getenv("ROLE_GUILD_MEMBER")
        if not channel_id: return
        channel = self.bot.get_channel(int(channel_id))
        if not channel: return

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        with next(get_db()) as db:
            unposted_events = db.query(GuildEvent).filter_by(is_posted=False).all()

            for event in unposted_events:
                time_delta = event.start_time - now
                
                # If event is <= 72 hours away, post it
                if time_delta.total_seconds() <= 259200: 
                    unix_ts = int(event.start_time.replace(tzinfo=timezone.utc).timestamp())
                    
                    embed = discord.Embed(
                        title=f"⚔️ {event.name}",
                        description=event.description or ("Sign up using the buttons below." if event.requires_rsvp else "Mark your calendars!"),
                        color=discord.Color.gold()
                    )
                    embed.add_field(name="📅 Target Time", value=f"<t:{unix_ts}:F>\n(<t:{unix_ts}:R>)", inline=False)
                    
                    # Only add the RSVP counters if the event requires RSVPs
                    if event.requires_rsvp:
                        embed.add_field(name="✅ Attending", value="`0 players`", inline=True)
                        embed.add_field(name="❌ Absent", value="`0 players`", inline=True)
                        embed.add_field(name="⏳ Tentative", value="`0 players`", inline=True)
                    
                    footer_text = f"Event ID: {event.id}"
                    if event.recurrence_days > 0:
                        footer_text += f" | 🔁 Recurs every {event.recurrence_days} days"
                    embed.set_footer(text=footer_text)

                    ping_text = f"<@&{role_member_id}>" if role_member_id else "@here"
                    
                    # Deploy with or without buttons based on flag
                    if event.requires_rsvp:
                        view = AttendanceView(event_id=event.id)
                        message = await channel.send(content=ping_text, embed=embed, view=view)
                    else:
                        message = await channel.send(content=ping_text, embed=embed)
                    
                    event.is_posted = True
                    event.message_id = message.id

                    # 🔄 RECURRENCE LOGIC: Spawn the next event and pass the required_rsvp flag
                    if event.recurrence_days > 0:
                        next_time = event.start_time + timedelta(days=event.recurrence_days)
                        next_event = GuildEvent(
                            name=event.name,
                            description=event.description,
                            start_time=next_time,
                            recurrence_days=event.recurrence_days,
                            requires_rsvp=event.requires_rsvp,
                            is_posted=False
                        )
                        db.add(next_event)
            
            db.commit()

async def setup(bot: commands.Bot):
    await bot.add_cog(SchedulingCog(bot))