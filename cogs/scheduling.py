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

    # Shared timezone choices for consistency
    tz_choices = [
        app_commands.Choice(name="Eastern Time (EST/EDT)", value="US/Eastern"),
        app_commands.Choice(name="Central Time (CST/CDT)", value="US/Central"),
        app_commands.Choice(name="Mountain Time (MST/MDT)", value="US/Mountain"),
        app_commands.Choice(name="Pacific Time (PST/PDT)", value="US/Pacific"),
        app_commands.Choice(name="Coordinated Universal Time (UTC)", value="UTC"),
    ]

    @app_commands.command(name="create_event", description="Schedule a guild event")
    @app_commands.describe(
        name="Event Name (e.g., Archboss Tevent)",
        date_time="Format: YYYY-MM-DD HH:MM (e.g., 2026-07-15 20:00)",
        tz_input="Select your input timezone",
        notify_schedule="Comma-separated minutes before start (e.g., '4320, 60, 5, 0')",
        recurrence="Does this event repeat?",
        requires_rsvp="True = Interactive Poll. False = Notification Only."
    )
    @app_commands.choices(tz_input=tz_choices)
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
        notify_schedule: str = "0", 
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

        try:
            schedule_list = [int(x.strip()) for x in notify_schedule.split(",") if x.strip()]
            if not schedule_list: raise ValueError
            clean_schedule_str = ",".join(map(str, sorted(schedule_list, reverse=True)))
        except ValueError:
            await interaction.response.send_message("❌ **Invalid notification schedule!** Use numbers (e.g., `4320, 60, 5`).", ephemeral=True)
            return

        with next(get_db()) as db:
            new_event = GuildEvent(
                name=name, description=description, start_time=utc_dt,
                recurrence_days=recurrence, requires_rsvp=requires_rsvp,
                notify_schedule=clean_schedule_str, notifies_sent="",
                is_posted=False, is_completed=False
            )
            db.add(new_event)
            db.commit()

        poll_type = "📊 Interactive Poll" if requires_rsvp else "🔔 Notification Only"
        await interaction.response.send_message(
            f"✅ **Event Scheduled!**\n**Event:** {name} `[{'Repeats every ' + str(recurrence) + 'd' if recurrence > 0 else 'One-time'}]`\n"
            f"**Type:** {poll_type}\n**Ping Warnings:** `{clean_schedule_str}` (Minutes prior)\n"
            f"**Time:** <t:{unix_timestamp}:F> (<t:{unix_timestamp}:R>)",
            ephemeral=True
        )

    @app_commands.command(name="edit_event", description="Edit an existing event's details")
    @app_commands.describe(
        event_id="The ID of the event to edit (Use /list_events to find IDs)",
        name="New event name",
        date_time="New Date/Time (YYYY-MM-DD HH:MM)",
        tz_input="Timezone for the new date/time (Required if changing time)",
        description="New description"
    )
    @app_commands.choices(tz_input=tz_choices)
    async def edit_event(
        self, interaction: discord.Interaction, event_id: int, 
        name: str = None, date_time: str = None, tz_input: str = None, description: str = None
    ):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        # 🛡️ TIMEZONE SAFEGUARD: Ensure both time and timezone are provided together
        if date_time and not tz_input:
            await interaction.response.send_message("❌ **Timezone is required** when updating the Date/Time.", ephemeral=True)
            return
        elif tz_input and not date_time:
            await interaction.response.send_message("❌ Please provide the **New Date/Time** along with the Timezone.", ephemeral=True)
            return

        with next(get_db()) as db:
            event = db.query(GuildEvent).filter_by(id=event_id).first()
            if not event:
                await interaction.response.send_message(f"❌ Event ID `{event_id}` not found.", ephemeral=True)
                return
            if event.is_completed:
                await interaction.response.send_message("❌ You cannot edit an event that is already completed.", ephemeral=True)
                return

            # Apply Updates
            if name: event.name = name
            if description: event.description = description
            
            # Since we validated above, we know if one exists, both exist
            if date_time and tz_input:
                try:
                    naive_dt = datetime.strptime(date_time, "%Y-%m-%d %H:%M")
                    user_tz = zoneinfo.ZoneInfo(tz_input)
                    localized_dt = naive_dt.replace(tzinfo=user_tz)
                    event.start_time = localized_dt.astimezone(timezone.utc)
                    # Reset the notification tracker so it re-evaluates ping times properly
                    event.notifies_sent = "" 
                except ValueError:
                    await interaction.response.send_message("❌ **Invalid date format!** Use `YYYY-MM-DD HH:MM`", ephemeral=True)
                    return

            db.commit()

            # If the event is currently live in the channel, update the actual message
            if event.is_posted and event.message_id:
                channel = self.bot.get_channel(int(os.getenv("SCHEDULE_CHANNEL_ID")))
                if channel:
                    try:
                        msg = await channel.fetch_message(event.message_id)
                        embed = msg.embeds[0]
                        embed.title = f"⚔️ {event.name}"
                        embed.description = event.description or ("Sign up using the buttons below." if event.requires_rsvp else "Mark your calendars!")
                        
                        # Recalculate target time string
                        unix_ts = int(event.start_time.replace(tzinfo=timezone.utc).timestamp())
                        embed.set_field_at(0, name="📅 Target Time", value=f"<t:{unix_ts}:F>\n(<t:{unix_ts}:R>)", inline=False)
                        
                        await msg.edit(embed=embed)
                    except discord.NotFound:
                        pass # Ignored if an admin manually deleted the message

        await interaction.response.send_message(f"✅ Event `{event_id}` has been updated.", ephemeral=True)

    @app_commands.command(name="delete_event", description="Cancel and delete an event")
    async def delete_event(self, interaction: discord.Interaction, event_id: int):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        with next(get_db()) as db:
            event = db.query(GuildEvent).filter_by(id=event_id).first()
            if not event:
                await interaction.response.send_message(f"❌ Event ID `{event_id}` not found.", ephemeral=True)
                return

            # If it is live, edit the message to show it was canceled
            if event.message_id:
                channel = self.bot.get_channel(int(os.getenv("SCHEDULE_CHANNEL_ID")))
                if channel:
                    try:
                        msg = await channel.fetch_message(event.message_id)
                        embed = msg.embeds[0]
                        embed.title = f"🛑 CANCELED: {event.name}"
                        embed.color = discord.Color.red()
                        embed.set_footer(text=f"Event ID: {event.id} | Event has been canceled by an Officer")
                        
                        # Disable any attached buttons
                        if event.requires_rsvp:
                            view = AttendanceView(event_id=event.id)
                            for child in view.children: child.disabled = True
                            await msg.edit(embed=embed, view=view)
                        else:
                            await msg.edit(embed=embed)
                    except discord.NotFound:
                        pass

            db.delete(event)
            db.commit()

        await interaction.response.send_message(f"🗑️ Event `{event_id}` has been successfully canceled and removed.", ephemeral=True)

    @app_commands.command(name="list_events", description="Debug command to view active scheduled events")
    async def list_events(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        with next(get_db()) as db:
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

        if len(report) > 2000: report = report[:1996] + "..."
        await interaction.response.send_message(report, ephemeral=True)

    @tasks.loop(seconds=15)
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
                                embed.add_field(name="❌ Not Attending", value="`0 players`", inline=True)
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
                                    name=event.name, description=event.description, start_time=next_time,
                                    recurrence_days=event.recurrence_days, requires_rsvp=event.requires_rsvp,
                                    notify_schedule=event.notify_schedule, notifies_sent="",
                                    is_posted=False, is_completed=False
                                )
                                db.add(next_event)
                        else:
                            poll_link = f"https://discord.com/channels/{guild_id}/{channel_id}/{event.message_id}" if event.message_id and guild_id else ""
                            link_text = f"\n👉 [Jump to Details]({poll_link})" if poll_link else ""
                            
                            if target_mins == 0:
                                reminder = f"{ping_text} ⚔️ **{event.name} is starting NOW!**{link_text}"
                            else:
                                reminder = f"{ping_text} ⏰ **Reminder:** {event.name} starts in **{target_mins} minutes**!{link_text}"
                            
                            await channel.send(reminder)
                        
                        sent.append(target_mins)
                        event.notifies_sent = ",".join(map(str, sent))
                        db.commit()

                # Garbage Collection
                if set(schedule).issubset(set(sent)) and delta_mins < 0:
                    event.is_completed = True
                    if event.requires_rsvp and event.message_id:
                        try:
                            msg = await channel.fetch_message(event.message_id)
                            view = AttendanceView(event_id=event.id)
                            for child in view.children: child.disabled = True
                            
                            embed = msg.embeds[0]
                            embed.color = discord.Color.dark_grey()
                            embed.set_footer(text=f"Event ID: {event.id} | 🛑 Event Concluded")
                            await msg.edit(embed=embed, view=view)
                        except discord.NotFound:
                            pass
                    db.commit()

async def setup(bot: commands.Bot):
    await bot.add_cog(SchedulingCog(bot))