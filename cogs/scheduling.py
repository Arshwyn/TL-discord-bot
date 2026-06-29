import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone, timedelta
import zoneinfo
import os

from database.db_setup import get_db
from database.models import GuildEvent, EventAttendance, AttendanceRecord, UserProfile
from sqlalchemy.orm import joinedload
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
    @app_commands.default_permissions(manage_guild=True) # 🔒 Protected Command Group
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
    @app_commands.default_permissions(manage_guild=True) # 🔒 Protected Command Group
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

            if name: event.name = name
            if description: event.description = description
            
            if date_time and tz_input:
                try:
                    naive_dt = datetime.strptime(date_time, "%Y-%m-%d %H:%M")
                    user_tz = zoneinfo.ZoneInfo(tz_input)
                    localized_dt = naive_dt.replace(tzinfo=user_tz)
                    event.start_time = localized_dt.astimezone(timezone.utc)
                    event.notifies_sent = "" 
                except ValueError:
                    await interaction.response.send_message("❌ **Invalid date format!** Use `YYYY-MM-DD HH:MM`", ephemeral=True)
                    return

            db.commit()

            if event.is_posted and event.message_id:
                channel = self.bot.get_channel(int(os.getenv("SCHEDULE_CHANNEL_ID")))
                if channel:
                    try:
                        msg = await channel.fetch_message(event.message_id)
                        embed = msg.embeds[0]
                        embed.title = f"⚔️ {event.name}"
                        embed.description = event.description or ("Sign up using the buttons below." if event.requires_rsvp else "Mark your calendars!")
                        unix_ts = int(event.start_time.replace(tzinfo=timezone.utc).timestamp())
                        embed.set_field_at(0, name="📅 Target Time", value=f"<t:{unix_ts}:F>\n(<t:{unix_ts}:R>)", inline=False)
                        await msg.edit(embed=embed)
                    except discord.NotFound:
                        pass

        await interaction.response.send_message(f"✅ Event `{event_id}` has been updated.", ephemeral=True)

    @app_commands.command(name="delete_event", description="Cancel and delete an event")
    @app_commands.default_permissions(manage_guild=True) # 🔒 Protected Command Group
    async def delete_event(self, interaction: discord.Interaction, event_id: int):
        with next(get_db()) as db:
            event = db.query(GuildEvent).filter_by(id=event_id).first()
            if not event:
                await interaction.response.send_message(f"❌ Event ID `{event_id}` not found.", ephemeral=True)
                return

            if event.message_id:
                channel = self.bot.get_channel(int(os.getenv("SCHEDULE_CHANNEL_ID")))
                if channel:
                    try:
                        msg = await channel.fetch_message(event.message_id)
                        embed = msg.embeds[0]
                        embed.title = f"🛑 CANCELED: {event.name}"
                        embed.color = discord.Color.red()
                        embed.set_footer(text=f"Event ID: {event.id} | Event has been canceled by an Officer")
                        
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
    @app_commands.default_permissions(manage_guild=True) # 🔒 Protected Command Group
    async def list_events(self, interaction: discord.Interaction):
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
                f" └ *Time:* <t:{unix_ts}:F> (<t:{unix_ts}:R>)\n\n"
            )

        if len(report) > 2000: report = report[:1996] + "..."
        await interaction.response.send_message(report, ephemeral=True)

    @app_commands.command(name="view_roster", description="View a deep breakdown of sign-ups and gear targets")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(event_id="The ID of the event roster you want to view")
    async def view_roster(self, interaction: discord.Interaction, event_id: int):
        await interaction.response.defer(ephemeral=True)

        with next(get_db()) as db:
            event = db.query(GuildEvent).filter_by(id=event_id).first()
            if not event:
                await interaction.followup.send(f"❌ Event ID `{event_id}` not found.", ephemeral=True)
                return
            records = db.query(EventAttendance).options(joinedload(EventAttendance.user)).filter_by(event_id=event_id).all()

        attending_dict = {}
        absent_list, tentative_list = [], []
        total_attending = 0

        for record in records:
            if record.user:
                name_display = record.user.ingame_name
                details = f" [⭐ {record.user.gear_score} | {record.user.primary_weapon} / {record.user.secondary_weapon}]"
                s_group = record.user.static_group or "Unassigned"
            else:
                member = interaction.guild.get_member(record.discord_id)
                name_display = member.display_name if member else f"Unregistered User (<@{record.discord_id}>)"
                details = " *(No Profile)*"
                s_group = "Unassigned"

            entry = f"• **{name_display}**{details}"

            if record.status == "attending":
                if s_group not in attending_dict: attending_dict[s_group] = []
                attending_dict[s_group].append(entry)
                total_attending += 1
            elif record.status == "absent": absent_list.append(entry)
            elif record.status == "tentative": tentative_list.append(entry)

        # Sort and Format Attending
        attending_lines = []
        sorted_groups = sorted(attending_dict.keys(), key=lambda x: (x == "Unassigned", x))
        for group in sorted_groups:
            attending_lines.append(f"**🛡️ {group}**")
            attending_lines.extend(attending_dict[group])
            attending_lines.append("")

        unix_ts = int(event.start_time.replace(tzinfo=timezone.utc).timestamp())
        embed = discord.Embed(title=f"📋 Roster Breakdown: {event.name}", description=f"**Time:** <t:{unix_ts}:F>\n**Event ID:** `{event.id}`", color=discord.Color.blue())

        def safe_join(lst):
            res = "\n".join(lst).strip() if lst else "*No sign-ups*"
            return res[:1000] + "\n..." if len(res) > 1024 else res

        embed.add_field(name=f"✅ Attending ({total_attending})", value=safe_join(attending_lines), inline=False)
        embed.add_field(name=f"⏳ Tentative ({len(tentative_list)})", value=safe_join(tentative_list), inline=False)
        embed.add_field(name=f"⛔ Not Attending ({len(absent_list)})", value=safe_join(absent_list), inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # =============================================================
    # NEW SLASH COMMAND: LOOK UP AUDITED PRESENT/GHOST DATA
    # =============================================================
    @app_commands.command(name="attendance_summary", description="View the logged presence ledger audit for an event")
    @app_commands.default_permissions(manage_guild=True)
    async def attendance_summary(self, interaction: discord.Interaction, event_id: int):
        await interaction.response.defer(ephemeral=True)
        
        with next(get_db()) as db:
            logs = db.query(AttendanceRecord).filter_by(event_id=event_id).all()
            
        if not logs:
            await interaction.followup.send(f"❌ No automated auditing summary entries located for Event ID `{event_id}`.", ephemeral=True)
            return

        present, ghosted, unregistered = [], [], []
        for log in logs:
            display = f"• {log.ingame_name} (<@{log.discord_id}>)"
            if log.actual_presence == "Present": present.append(display)
            elif log.actual_presence == "Ghosted": ghosted.append(display)
            elif log.actual_presence == "Unregistered": unregistered.append(display)

        embed = discord.Embed(title=f"📜 Presence Audit Ledger: {logs[0].event_name}", color=discord.Color.brand_green())
        embed.add_field(name=f"✅ Present in Comms Voice ({len(present)})", value="\n".join(present) if present else "*None*", inline=False)
        embed.add_field(name=f"👻 Ghosted Signed-Up Users ({len(ghosted)})", value="\n".join(ghosted) if ghosted else "*None*", inline=False)
        embed.add_field(name=f"⚠️ Unregistered Raiders in VC ({len(unregistered)})", value="\n".join(unregistered) if unregistered else "*None*", inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

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

                # Trigger warnings/initial frames
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
                            
                            embed.set_footer(text=f"Event ID: {event.id}")

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

                # 🛑 AUTOMATED PRESENT/GHOST AUDIT TIMER: Evaluates exactly 20 minutes after start time
                if delta_mins <= -20.0 and not event.is_completed:
                    event.is_completed = True
                    db.commit()

                    # Lockdown the frontend button layout
                    if event.requires_rsvp and event.message_id:
                        try:
                            msg = await channel.fetch_message(event.message_id)
                            view = AttendanceView(event_id=event.id)
                            for child in view.children: child.disabled = True
                            
                            embed = msg.embeds[0]
                            embed.color = discord.Color.dark_grey()
                            embed.set_footer(text=f"Event ID: {event.id} | 🛑 Concluded & Ledger Audited")
                            await msg.edit(embed=embed, view=view)
                        except discord.NotFound:
                            pass

                    # Scrape all active voice channels to pool real-time connections
                    active_voice_member_ids = set()
                    guild = channel.guild
                    for vc in guild.voice_channels:
                        for member in vc.members:
                            active_voice_member_ids.add(member.id)

                    # Gather roster signups and general user frames
                    signups = db.query(EventAttendance).options(joinedload(EventAttendance.user)).filter_by(event_id=event.id).all()
                    profile_map = {p.discord_id: p for p in db.query(UserProfile).all()}
                    audited_user_ids = set()

                    # A. Evaluate explicitly registered RSVPs
                    for signup in signups:
                        audited_user_ids.add(signup.discord_id)
                        ign = signup.user.ingame_name if signup.user else f"Discord User ID: {signup.discord_id}"
                        
                        presence = "Ghosted"
                        if signup.status == "attending" and signup.discord_id in active_voice_member_ids:
                            presence = "Present"
                        elif signup.status != "attending":
                            presence = "Present" if signup.discord_id in active_voice_member_ids else "Absent"

                        record = AttendanceRecord(
                            event_id=event.id, event_name=event.name, event_date=event.start_time,
                            discord_id=signup.discord_id, ingame_name=ign, signup_status=signup.status,
                            actual_presence=presence
                        )
                        db.add(record)

                    # B. Catch unregistered members sitting inside the voice comms channels
                    for active_id in active_voice_member_ids:
                        if active_id not in audited_user_ids:
                            user_prof = profile_map.get(active_id)
                            ign = user_prof.ingame_name if user_prof else f"Discord User ID: {active_id}"
                            
                            record = AttendanceRecord(
                                event_id=event.id, event_name=event.name, event_date=event.start_time,
                                discord_id=active_id, ingame_name=ign, signup_status="none",
                                actual_presence="Unregistered"
                            )
                            db.add(record)

                    db.commit()

async def setup(bot: commands.Bot):
    await bot.add_cog(SchedulingCog(bot))