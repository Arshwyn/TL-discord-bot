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
        description="Schedule a guild event with multiple custom notification times"
    )
    @app_commands.describe(
        name="Event Name (e.g., Archboss Tevent)",
        date_time="Format: YYYY-MM-DD HH:MM (e.g., 2026-07-15 20:00)",
        tz_input="Select your input timezone",
        notify_schedule="Comma-separated minutes before start (e.g., '4320, 60, 5, 0')",
        recurrence="Does this event repeat?",
        requires_rsvp="True = Interactive Poll. False = Notification Only."
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
        notify_schedule: str = "0", # Default: Start Time
        recurrence: int = 0,
        requires_rsvp: bool = True,
        description: str = None
    ):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        # 1. Parse Timezone Math
        try:
            naive_dt = datetime.strptime(date_time, "%Y-%m-%d %H:%M")
            user_tz = zoneinfo.ZoneInfo(tz_input)
            localized_dt = naive_dt.replace(tzinfo=user_tz)
            unix_timestamp = int(localized_dt.timestamp())
            utc_dt = localized_dt.astimezone(timezone.utc)
        except ValueError:
            await interaction.response.send_message("❌ **Invalid date format!** Use `YYYY-MM-DD HH:MM`", ephemeral=True)
            return

        # 2. Parse and Validate Notification Schedule
        try:
            # Clean up user input, convert to ints, and sort largest to smallest (e.g., [4320, 60, 0])
            schedule_list = [int(x.strip()) for x in notify_schedule.split(",") if x.strip()]
            if not schedule_list:
                raise ValueError
            clean_schedule_str = ",".join(map(str, sorted(schedule_list, reverse=True)))
        except ValueError:
            await interaction.response.send_message("❌ **Invalid notification schedule!** Use numbers separated by commas (e.g., `4320, 60, 5`).", ephemeral=True)
            return

        # 3. Save Event
        with next(get_db()) as db:
            new_event = GuildEvent(
                name=name,
                description=description,
                start_time=utc_dt,
                recurrence_days=recurrence,
                requires_rsvp=requires_rsvp,
                notify_schedule=clean_schedule_str,
                notifies_sent="",
                is_posted=False,
                is_completed=False
            )
            db.add(new_event)
            db.commit()

        poll_type = "📊 Interactive Poll" if requires_rsvp else "🔔 Notification Only"
        await interaction.response.send_message(
            f"✅ **Event Scheduled!**\n"
            f"**Event:** {name} `[{'Repeats every ' + str(recurrence) + 'd' if recurrence > 0 else 'One-time'}]`\n"
            f"**Type:** {poll_type}\n"
            f"**Ping Warnings:** `{clean_schedule_str}` (Minutes prior)\n"
            f"**Time:** <t:{unix_timestamp}:F> (<t:{unix_timestamp}:R>)",
            ephemeral=True
        )

    @app_commands.command(
        name="list_events", 
        description="Debug command to view all pending scheduled events"
    )
    async def list_events(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        with next(get_db()) as db:
            # Only pull active events
            events = db.query(GuildEvent).filter_by(is_completed=False).order_by(GuildEvent.start_time.asc()).all()

        if not events:
            await interaction.response.send_message("📭 No active events pending in the database.", ephemeral=True)
            return

        report = "📋 **Current Active Entries:**\n\n"
        for event in events:
            unix_ts = int(event.start_time.replace(tzinfo=timezone.utc).timestamp())
            recurrence_str = f" | 🔁 Every {event.recurrence_days}d" if event.recurrence_days > 0 else ""
            report += (
                f"🔹 **ID:** `{event.id}` | **Name:** {event.name}{recurrence_str}\n"
                f" └ *Time:* <t:{unix_ts}:F> (<t:{unix_ts}:R>)\n"
                f" └ *Notifications Sent:* `[{event.notifies_sent}]` of `[{event.notify_schedule}]`\n\n"
            )

        if len(report) > 2000:
            report = report[:1996] + "..."
        await interaction.response.send_message(report, ephemeral=True)

    @tasks.loop(seconds=15) # ⏱️ Updated to 15 seconds for precision
    async def check_events_loop(self):
        await self.bot.wait_until_ready()
        
        channel_id = os.getenv("SCHEDULE_CHANNEL_ID")
        role_member_id = os.getenv("ROLE_GUILD_MEMBER")
        guild_id = os.getenv("GUILD_ID")
        
        if not channel_id: return
        channel = self.bot.get_channel(int(channel_id))
        if not channel: return

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        with next(get_db()) as db:
            active_events = db.query(GuildEvent).filter_by(is_completed=False).all()

            for event in active_events:
                time_delta = event.start_time - now
                delta_mins = time_delta.total_seconds() / 60.0
                
                schedule = [int(x) for x in event.notify_schedule.split(",")] if event.notify_schedule else []
                sent = [int(x) for x in event.notifies_sent.split(",")] if event.notifies_sent else []

                for target_mins in sorted(schedule, reverse=True):
                    if target_mins not in sent and delta_mins <= target_mins:
                        
                        ping_text = f"<@&{role_member_id}>" if role_member_id else "@here"

                        if not event.is_posted:
                            unix_ts = int(event.start_time.replace(tzinfo=timezone.utc).timestamp())
                            embed = discord.Embed(
                                title=f"⚔️ {event.name}",
                                description=event.description or ("Sign up using the buttons below." if event.requires_rsvp else "Mark your calendars!"),
                                color=discord.Color.gold()
                            )
                            embed.add_field(name="📅 Target Time", value=f"<t:{unix_ts}:F>\n(<t:{unix_ts}:R>)", inline=False)
                            
                            if event.requires_rsvp:
                                embed.add_field(name="✅ Attending", value="`0 players`", inline=True)
                                embed.add_field(name="❌ Absent", value="`0 players`", inline=True)
                                embed.add_field(name="⏳ Tentative", value="`0 players`", inline=True)
                            
                            footer_text = f"Event ID: {event.id}"
                            if event.recurrence_days > 0:
                                footer_text += f" | 🔁 Recurs every {event.recurrence_days} days"
                            embed.set_footer(text=footer_text)

                            if event.requires_rsvp:
                                view = AttendanceView(event_id=event.id)
                                message = await channel.send(content=ping_text, embed=embed, view=view)
                            else:
                                message = await channel.send(content=ping_text, embed=embed)
                            
                            event.is_posted = True
                            event.message_id = message.id

                            if event.recurrence_days > 0:
                                next_time = event.start_time + timedelta(days=event.recurrence_days)
                                next_event = GuildEvent(
                                    name=event.name,
                                    description=event.description,
                                    start_time=next_time,
                                    recurrence_days=event.recurrence_days,
                                    requires_rsvp=event.requires_rsvp,
                                    notify_schedule=event.notify_schedule,
                                    notifies_sent="",
                                    is_posted=False,
                                    is_completed=False
                                )
                                db.add(next_event)
                        else:
                            poll_link = f"https://discord.com/channels/{guild_id}/{channel_id}/{event.message_id}" if event.message_id and guild_id else ""
                            link_text = f"\n👉 [Jump to Sign-up/Details]({poll_link})" if poll_link else ""
                            
                            if target_mins == 0:
                                reminder = f"{ping_text} ⚔️ **{event.name} is starting NOW!**{link_text}"
                            else:
                                reminder = f"{ping_text} ⏰ **Reminder:** {event.name} starts in **{target_mins} minutes**!{link_text}"
                            
                            await channel.send(reminder)
                        
                        sent.append(target_mins)
                        event.notifies_sent = ",".join(map(str, sent))
                        db.commit()

                # 3. 🛑 GARBAGE COLLECTION: Disable old messages automatically
                # Triggers when ALL notifications have fired and the start time has fully passed (delta_mins < 0)
                if set(schedule).issubset(set(sent)) and delta_mins < 0:
                    event.is_completed = True
                    
                    # Only attempt to edit messages that had buttons
                    if event.requires_rsvp and event.message_id:
                        try:
                            # Fetch the original embed
                            msg = await channel.fetch_message(event.message_id)
                            view = AttendanceView(event_id=event.id)
                            
                            # Disable every button in the view
                            for child in view.children:
                                child.disabled = True
                                
                            # Grey out the embed and add a concluded tag
                            embed = msg.embeds[0]
                            embed.color = discord.Color.dark_grey()
                            embed.set_footer(text=f"Event ID: {event.id} | 🛑 Event Concluded")
                            
                            # Push the locked update to Discord
                            await msg.edit(embed=embed, view=view)
                        except discord.NotFound:
                            # Ignored safely if an admin manually deleted the message before the bot got to it
                            pass

                    db.commit()

        await self.bot.wait_until_ready()
        
        channel_id = os.getenv("SCHEDULE_CHANNEL_ID")
        role_member_id = os.getenv("ROLE_GUILD_MEMBER")
        guild_id = os.getenv("GUILD_ID")  # Used for generating jump links
        
        if not channel_id: return
        channel = self.bot.get_channel(int(channel_id))
        if not channel: return

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        with next(get_db()) as db:
            # Query all events that are NOT marked complete yet
            active_events = db.query(GuildEvent).filter_by(is_completed=False).all()

            for event in active_events:
                time_delta = event.start_time - now
                delta_mins = time_delta.total_seconds() / 60.0
                
                # Reconstruct lists from comma strings
                schedule = [int(x) for x in event.notify_schedule.split(",")] if event.notify_schedule else []
                sent = [int(x) for x in event.notifies_sent.split(",")] if event.notifies_sent else []

                # Find any notifications we are past-due for that haven't fired yet
                for target_mins in sorted(schedule, reverse=True):
                    if target_mins not in sent and delta_mins <= target_mins:
                        
                        ping_text = f"<@&{role_member_id}>" if role_member_id else "@here"

                        # 1. INITIAL DEPLOYMENT (Main Embed/Poll)
                        if not event.is_posted:
                            unix_ts = int(event.start_time.replace(tzinfo=timezone.utc).timestamp())
                            
                            embed = discord.Embed(
                                title=f"⚔️ {event.name}",
                                description=event.description or ("Sign up using the buttons below." if event.requires_rsvp else "Mark your calendars!"),
                                color=discord.Color.gold()
                            )
                            embed.add_field(name="📅 Target Time", value=f"<t:{unix_ts}:F>\n(<t:{unix_ts}:R>)", inline=False)
                            
                            if event.requires_rsvp:
                                embed.add_field(name="✅ Attending", value="`0 players`", inline=True)
                                embed.add_field(name="❌ Absent", value="`0 players`", inline=True)
                                embed.add_field(name="⏳ Tentative", value="`0 players`", inline=True)
                            
                            footer_text = f"Event ID: {event.id}"
                            if event.recurrence_days > 0:
                                footer_text += f" | 🔁 Recurs every {event.recurrence_days} days"
                            embed.set_footer(text=footer_text)

                            if event.requires_rsvp:
                                view = AttendanceView(event_id=event.id)
                                message = await channel.send(content=ping_text, embed=embed, view=view)
                            else:
                                message = await channel.send(content=ping_text, embed=embed)
                            
                            event.is_posted = True
                            event.message_id = message.id

                            # 🔄 Spawn next week's clone immediately after the main poll drops
                            if event.recurrence_days > 0:
                                next_time = event.start_time + timedelta(days=event.recurrence_days)
                                next_event = GuildEvent(
                                    name=event.name,
                                    description=event.description,
                                    start_time=next_time,
                                    recurrence_days=event.recurrence_days,
                                    requires_rsvp=event.requires_rsvp,
                                    notify_schedule=event.notify_schedule,
                                    notifies_sent="",
                                    is_posted=False,
                                    is_completed=False
                                )
                                db.add(next_event)

                        # 2. FOLLOW-UP REMINDER DEPLOYMENT (Small Text Pings)
                        else:
                            poll_link = f"https://discord.com/channels/{guild_id}/{channel_id}/{event.message_id}" if event.message_id and guild_id else ""
                            link_text = f"\n👉 [Jump to Sign-up/Details]({poll_link})" if poll_link else ""
                            
                            if target_mins == 0:
                                reminder = f"{ping_text} ⚔️ **{event.name} is starting NOW!**{link_text}"
                            else:
                                reminder = f"{ping_text} ⏰ **Reminder:** {event.name} starts in **{target_mins} minutes**!{link_text}"
                            
                            await channel.send(reminder)
                        
                        # Register this specific minute-target as sent
                        sent.append(target_mins)
                        event.notifies_sent = ",".join(map(str, sent))
                        db.commit()

                # 3. GARBAGE COLLECTION (Mark as finished if time has passed and all pings fired)
                if set(schedule).issubset(set(sent)) and delta_mins < 0:
                    event.is_completed = True
                    db.commit()

async def setup(bot: commands.Bot):
    await bot.add_cog(SchedulingCog(bot))