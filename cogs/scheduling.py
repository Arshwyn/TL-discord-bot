import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone, timedelta
import zoneinfo
import os

from database.db_setup import get_db
from database.models import GuildEvent, EventAttendance, AttendanceRecord, UserProfile, BotConfig
from cogs.attendance import AttendanceView

class SchedulingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_events_loop.start()
        self.cleanup_attendance_loop.start() 

    def cog_unload(self):
        self.check_events_loop.cancel()
        self.cleanup_attendance_loop.cancel() 

    tz_choices = [
        app_commands.Choice(name="Eastern Time (EST/EDT)", value="US/Eastern"),
        app_commands.Choice(name="Central Time (CST/CDT)", value="US/Central"),
        app_commands.Choice(name="Mountain Time (MST/MDT)", value="US/Mountain"),
        app_commands.Choice(name="Pacific Time (PST/PDT)", value="US/Pacific"),
        app_commands.Choice(name="Coordinated Universal Time (UTC)", value="UTC"),
    ]

    game_choices = [
        app_commands.Choice(name="PvE Content", value="PvE"),
        app_commands.Choice(name="PvP Content", value="PvP")
    ]

    @app_commands.command(name="set_ping_roles", description="Set up to 3 default roles to ping for event reminders")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(role1="Primary role to ping", role2="Second role to ping (Optional)", role3="Third role to ping (Optional)")
    async def set_ping_roles(self, interaction: discord.Interaction, role1: discord.Role, role2: discord.Role = None, role3: discord.Role = None):
        roles = [r for r in (role1, role2, role3) if r is not None]
        role_ids_str = ",".join(str(r.id) for r in roles)
        mentions_str = " ".join(r.mention for r in roles)

        with next(get_db()) as db:
            cfg = db.query(BotConfig).filter_by(setting_key="ping_role_ids").first()
            if cfg:
                cfg.setting_value = role_ids_str
            else:
                db.add(BotConfig(setting_key="ping_role_ids", setting_value=role_ids_str))
            db.commit()
            
        await interaction.response.send_message(f"✅ Event reminders will now automatically ping: {mentions_str}", ephemeral=True)

    @app_commands.command(name="view_ping_roles", description="Check which roles are currently configured for event pings")
    @app_commands.default_permissions(manage_guild=True)
    async def view_ping_roles(self, interaction: discord.Interaction):
        with next(get_db()) as db:
            cfg = db.query(BotConfig).filter_by(setting_key="ping_role_ids").first()

        if not cfg or not cfg.setting_value:
            await interaction.response.send_message("ℹ️ No ping roles are configured. The bot is currently defaulting to `@here`.", ephemeral=True)
            return

        role_ids = cfg.setting_value.split(",")
        mentions = " ".join([f"<@&{rid}>" for rid in role_ids])
        await interaction.response.send_message(f"📢 **Current Event Ping Configurations:**\nWhen an event notification fires, Codex will ping: {mentions}", ephemeral=True)

    @app_commands.command(name="delete_ping_roles", description="Reset and remove all configured ping roles")
    @app_commands.default_permissions(manage_guild=True)
    async def delete_ping_roles(self, interaction: discord.Interaction):
        with next(get_db()) as db:
            cfg = db.query(BotConfig).filter_by(setting_key="ping_role_ids").first()
            if cfg:
                db.delete(cfg)
                db.commit()
                await interaction.response.send_message("🗑️ **Ping roles reset!** The bot will now default to `@here`.", ephemeral=True)
            else:
                await interaction.response.send_message("ℹ️ No ping roles were configured.", ephemeral=True)

    @app_commands.command(name="create_event", description="Schedule a guild event")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        name="Event Name (e.g., Archboss Tevent)",
        game_type="Is this a PvE or PvP event?",
        date_time="Format: YYYY-MM-DD HH:MM (e.g., 2026-07-15 20:00)",
        tz_input="Select your input timezone",
        notify_schedule="Comma-separated minutes before start (e.g., '4320, 60, 5, 0')",
        recurrence="Does this event repeat?",
        requires_rsvp="True = Interactive Poll. False = Notification Only.",
        target_channel="The text channel to post this event in (Defaults to current)",
        voice_channel="The specific Voice Channel to audit for attendance (Optional)"
    )
    @app_commands.choices(tz_input=tz_choices, game_type=game_choices)
    @app_commands.choices(recurrence=[
        app_commands.Choice(name="Does not repeat", value=0),
        app_commands.Choice(name="Weekly", value=7),
        app_commands.Choice(name="Bi-Weekly", value=14),
    ])
    async def create_event(
        self, interaction: discord.Interaction, name: str, date_time: str, 
        game_type: str = "PvE", tz_input: str = "UTC", notify_schedule: str = "0", recurrence: int = 0,
        requires_rsvp: bool = True, target_channel: discord.TextChannel = None, 
        voice_channel: discord.VoiceChannel = None, description: str = None
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

        chosen_channel_id = target_channel.id if target_channel else interaction.channel.id

        with next(get_db()) as db:
            new_event = GuildEvent(
                name=name, description=description, game_type=game_type, start_time=utc_dt,
                recurrence_days=recurrence, requires_rsvp=requires_rsvp,
                notify_schedule=clean_schedule_str, notifies_sent="",
                channel_id=chosen_channel_id,
                voice_channel_id=voice_channel.id if voice_channel else None,
                is_posted=False, is_completed=False
            )
            db.add(new_event)
            db.commit()

        poll_type = "📊 Interactive Poll" if requires_rsvp else "🔔 Notification Only"
        vc_target = f"\n**Audit Target:** <#{voice_channel.id}>" if voice_channel else "\n**Audit Target:** All Voice Channels"
        
        await interaction.response.send_message(
            f"✅ **Event Scheduled!** (Posting in <#{chosen_channel_id}>)\n"
            f"**Event:** [{game_type}] {name} `[{'Repeats every ' + str(recurrence) + 'd' if recurrence > 0 else 'One-time'}]`\n"
            f"**Type:** {poll_type}\n**Ping Warnings:** `{clean_schedule_str}` (Minutes prior)"
            f"{vc_target}\n"
            f"**Time:** <t:{unix_timestamp}:F> (<t:{unix_timestamp}:R>)",
            ephemeral=True
        )

    @app_commands.command(name="edit_event", description="Edit an existing event's details")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.choices(tz_input=tz_choices, game_type=game_choices)
    async def edit_event(
        self, interaction: discord.Interaction, event_id: int, 
        name: str = None, game_type: str = None, date_time: str = None, tz_input: str = None, 
        description: str = None, voice_channel: discord.VoiceChannel = None
    ):
        if date_time and not tz_input:
            await interaction.response.send_message("❌ **Timezone is required** when updating the Date/Time.", ephemeral=True)
            return

        with next(get_db()) as db:
            event = db.query(GuildEvent).filter_by(id=event_id).first()
            if not event or event.is_completed:
                await interaction.response.send_message("❌ Event not found or already completed.", ephemeral=True)
                return

            if name: event.name = name
            if game_type: event.game_type = game_type
            if description: event.description = description
            if voice_channel: event.voice_channel_id = voice_channel.id
            
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

            if event.is_posted and event.message_id and event.channel_id:
                channel = self.bot.get_channel(event.channel_id)
                if channel:
                    try:
                        msg = await channel.fetch_message(event.message_id)
                        embed = msg.embeds[0]
                        embed.title = f"⚔️ [{event.game_type}] {event.name}"
                        embed.description = event.description or ("Sign up using the buttons below." if event.requires_rsvp else "Mark your calendars!")
                        unix_ts = int(event.start_time.replace(tzinfo=timezone.utc).timestamp())
                        embed.set_field_at(0, name="📅 Target Time", value=f"<t:{unix_ts}:F>\n(<t:{unix_ts}:R>)", inline=False)
                        await msg.edit(embed=embed)
                    except discord.NotFound:
                        pass

        await interaction.response.send_message(f"✅ Event `{event_id}` updated.", ephemeral=True)

    @app_commands.command(name="delete_event", description="Cancel and delete an event")
    @app_commands.default_permissions(manage_guild=True)
    async def delete_event(self, interaction: discord.Interaction, event_id: int):
        with next(get_db()) as db:
            event = db.query(GuildEvent).filter_by(id=event_id).first()
            if not event:
                await interaction.response.send_message(f"❌ Event ID `{event_id}` not found.", ephemeral=True)
                return

            if event.message_id and event.channel_id:
                channel = self.bot.get_channel(event.channel_id)
                if channel:
                    try:
                        msg = await channel.fetch_message(event.message_id)
                        embed = msg.embeds[0]
                        embed.title = f"🛑 CANCELED: [{event.game_type}] {event.name}"
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
        await interaction.response.send_message(f"🗑️ Event `{event_id}` removed.", ephemeral=True)

    @app_commands.command(name="list_events", description="View active scheduled events")
    @app_commands.default_permissions(manage_guild=True)
    async def list_events(self, interaction: discord.Interaction):
        with next(get_db()) as db:
            events = db.query(GuildEvent).filter_by(is_completed=False).order_by(GuildEvent.start_time.asc()).all()
        if not events:
            await interaction.response.send_message("📭 No active events pending.", ephemeral=True)
            return
        report = "📋 **Current Active Entries:**\n\n"
        for event in events:
            unix_ts = int(event.start_time.replace(tzinfo=timezone.utc).timestamp())
            chan_tag = f" <#{event.channel_id}>" if event.channel_id else ""
            report += f"🔹 **ID:** `{event.id}` | **Name:** [{event.game_type}] {event.name}{chan_tag}\n └ *Time:* <t:{unix_ts}:F> (<t:{unix_ts}:R>)\n\n"
        await interaction.response.send_message(report, ephemeral=True)

    @app_commands.command(name="view_roster", description="View a detailed signup breakdown")
    @app_commands.default_permissions(manage_guild=True)
    async def view_roster(self, interaction: discord.Interaction, event_id: int):
        await interaction.response.defer(ephemeral=True)
        with next(get_db()) as db:
            event = db.query(GuildEvent).filter_by(id=event_id).first()
            if not event:
                await interaction.followup.send(f"❌ Event ID `{event_id}` not found.", ephemeral=True)
                return
                
            records = db.query(EventAttendance).filter_by(event_id=event_id).all()
            user_ids = [r.discord_id for r in records]
            
            # 🟢 NEW: Smart Fallback Logic (Matches exact, falls back to PvX, gets highest GS)
            profiles = db.query(UserProfile).filter(UserProfile.discord_id.in_(user_ids)).all()
            best_profiles = {}
            for uid in user_ids:
                u_profs = [p for p in profiles if p.discord_id == uid]
                exact_matches = [p for p in u_profs if p.build_type == event.game_type]
                pvx_matches = [p for p in u_profs if p.build_type == "PvX"]

                if exact_matches:
                    best_profiles[uid] = max(exact_matches, key=lambda p: p.gear_score)
                elif pvx_matches:
                    best_profiles[uid] = max(pvx_matches, key=lambda p: p.gear_score)

        attending_dict = {}
        absent_list, tentative_list = [], []
        total_attending = 0

        for record in records:
            user_prof = best_profiles.get(record.discord_id)
            
            if user_prof:
                name_display = user_prof.ingame_name
                details = f" [⭐ {user_prof.gear_score} | {user_prof.primary_weapon} / {user_prof.secondary_weapon}]"
                s_group = user_prof.static_group or "Unassigned"
            else:
                member = interaction.guild.get_member(record.discord_id)
                name_display = member.display_name if member else f"Unregistered User (<@{record.discord_id}>)"
                details = " *(No Matching Profile)*"
                s_group = "Unassigned"

            entry = f"• **{name_display}**{details}"

            if record.status == "attending":
                if s_group not in attending_dict: attending_dict[s_group] = []
                attending_dict[s_group].append(entry)
                total_attending += 1
            elif record.status == "absent": absent_list.append(entry)
            elif record.status == "tentative": tentative_list.append(entry)

        attending_lines = []
        sorted_groups = sorted(attending_dict.keys(), key=lambda x: (x == "Unassigned", x))
        for group in sorted_groups:
            attending_lines.append(f"**🛡️ {group}**")
            attending_lines.extend(attending_dict[group])
            attending_lines.append("")

        unix_ts = int(event.start_time.replace(tzinfo=timezone.utc).timestamp())
        embed = discord.Embed(title=f"📋 Roster Breakdown: [{event.game_type}] {event.name}", description=f"**Time:** <t:{unix_ts}:F>\n**Event ID:** `{event.id}`", color=discord.Color.blue())

        def safe_join(lst):
            res = "\n".join(lst).strip() if lst else "*No sign-ups*"
            return res[:1000] + "\n..." if len(res) > 1024 else res

        embed.add_field(name=f"✅ Attending ({total_attending})", value=safe_join(attending_lines), inline=False)
        embed.add_field(name=f"⏳ Tentative ({len(tentative_list)})", value=safe_join(tentative_list), inline=False)
        embed.add_field(name=f"⛔ Not Attending ({len(absent_list)})", value=safe_join(absent_list), inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

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
            ign = log.ingame_name
            
            # If the database has an old ugly record or the new "Unregistered" fallback
            if ign.startswith("Discord User ID:") or ign == "Unregistered":
                # Try to get their server profile
                member = interaction.guild.get_member(log.discord_id)
                if member:
                    ign = member.display_name
                else:
                    # If they left the server, try to grab their global Discord username
                    user = self.bot.get_user(log.discord_id)
                    ign = user.name if user else "Unknown/Left Server"

            display = f"• {ign} (<@{log.discord_id}>)"
                
            if log.actual_presence == "Present": present.append(display)
            elif log.actual_presence == "Ghosted": ghosted.append(display)
            elif log.actual_presence == "Unregistered": unregistered.append(display)

        # Helper function to prevent Discord API 400 Bad Request errors (1024 char limit per field)
        def safe_join(lst):
            res = "\n".join(lst).strip() if lst else "*None*"
            return res[:1000] + "\n...*(Too many)*" if len(res) > 1024 else res

        embed = discord.Embed(title=f"📜 Presence Audit Ledger: {logs[0].event_name}", color=discord.Color.brand_green())
        embed.add_field(name=f"✅ Present ({len(present)})", value=safe_join(present), inline=False)
        embed.add_field(name=f"👻 Ghosted ({len(ghosted)})", value=safe_join(ghosted), inline=False)
        embed.add_field(name=f"⚠️ Unregistered ({len(unregistered)})", value=safe_join(unregistered), inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tasks.loop(seconds=15)
    async def check_events_loop(self):
        await self.bot.wait_until_ready()
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        with next(get_db()) as db:
            cfg = db.query(BotConfig).filter_by(setting_key="ping_role_ids").first()
            if not cfg:
                cfg = db.query(BotConfig).filter_by(setting_key="ping_role_id").first()
                
            ping_text = "@here"
            if cfg and cfg.setting_value:
                role_ids = cfg.setting_value.split(",")
                ping_text = " ".join([f"<@&{rid}>" for rid in role_ids])
            
            active_events = db.query(GuildEvent).filter_by(is_completed=False).all()

            for event in active_events:
                if not event.channel_id: continue
                channel = self.bot.get_channel(event.channel_id)
                if not channel: continue

                time_delta = event.start_time - now
                delta_mins = time_delta.total_seconds() / 60.0
                
                schedule = [int(x) for x in event.notify_schedule.split(",")] if event.notify_schedule else []
                sent = [int(x) for x in event.notifies_sent.split(",")] if event.notifies_sent else []

                for target_mins in sorted(schedule, reverse=True):
                    if target_mins not in sent and delta_mins <= target_mins:
                        
                        if not event.is_posted:
                            unix_ts = int(event.start_time.replace(tzinfo=timezone.utc).timestamp())
                            embed = discord.Embed(title=f"⚔️ [{event.game_type}] {event.name}", color=discord.Color.gold())
                            embed.add_field(name="📅 Target Time", value=f"<t:{unix_ts}:F>\n(<t:{unix_ts}:R>)", inline=False)
                            if event.requires_rsvp:
                                embed.add_field(name="✅ Attending (0)", value="`0 players`", inline=True)
                                embed.add_field(name="⛔ Not Attending (0)", value="`0 players`", inline=True)
                                embed.add_field(name="⏳ Tentative (0)", value="`0 players`", inline=True)
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
                                    name=event.name, description=event.description, game_type=event.game_type, start_time=next_time,
                                    recurrence_days=event.recurrence_days, requires_rsvp=event.requires_rsvp,
                                    notify_schedule=event.notify_schedule, channel_id=event.channel_id,
                                    voice_channel_id=event.voice_channel_id, 
                                    notifies_sent="", is_posted=False, is_completed=False
                                )
                                db.add(next_event)
                        else:
                            poll_link = f"https://discord.com/channels/{channel.guild.id}/{event.channel_id}/{event.message_id}" if event.message_id else ""
                            link_text = f"\n👉 [Jump to Details]({poll_link})" if poll_link else ""
                            if target_mins == 0:
                                reminder = f"{ping_text} ⚔️ **[{event.game_type}] {event.name} is starting NOW!**{link_text}"
                            else:
                                reminder = f"{ping_text} ⏰ **Reminder:** [{event.game_type}] {event.name} starts in **{target_mins} minutes**!{link_text}"
                            await channel.send(reminder)
                        
                        sent.append(target_mins)
                        event.notifies_sent = ",".join(map(str, sent))
                        db.commit()

                # AUDITING
                if delta_mins <= -20.0 and not event.is_completed:
                    event.is_completed = True
                    db.commit()

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

                    active_voice_member_ids = set()
                    
                    if event.voice_channel_id:
                        vc = channel.guild.get_channel(event.voice_channel_id)
                        if vc and isinstance(vc, discord.VoiceChannel):
                            for member in vc.members:
                                active_voice_member_ids.add(member.id)
                    else:
                        for vc in channel.guild.voice_channels:
                            for member in vc.members:
                                active_voice_member_ids.add(member.id)

                    signups = db.query(EventAttendance).filter_by(event_id=event.id).all()
                    
                    # 🟢 NEW: Apply Exact > PvX > Highest GS logic globally to the Auditor
                    user_ids = {s.discord_id for s in signups}
                    user_ids.update(active_voice_member_ids)
                    
                    profiles = db.query(UserProfile).filter(UserProfile.discord_id.in_(user_ids)).all()
                    best_profiles = {}
                    
                    for uid in user_ids:
                        u_profs = [p for p in profiles if p.discord_id == uid]
                        if not u_profs:
                            continue
                            
                        exact_matches = [p for p in u_profs if p.build_type == event.game_type]
                        pvx_matches = [p for p in u_profs if p.build_type == "PvX"]

                        if exact_matches:
                            best_profiles[uid] = max(exact_matches, key=lambda p: p.gear_score)
                        elif pvx_matches:
                            best_profiles[uid] = max(pvx_matches, key=lambda p: p.gear_score)
                        else:
                            # 🟢 Fallback to ANY profile they have just to get their name
                            best_profiles[uid] = max(u_profs, key=lambda p: p.gear_score)
                            
                    audited_user_ids = set()

                    for signup in signups:
                        audited_user_ids.add(signup.discord_id)
                        user_prof = best_profiles.get(signup.discord_id)

                        member = channel.guild.get_member(signup.discord_id)
                        ign = user_prof.ingame_name if user_prof else (member.display_name if member else "Unregistered")
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

                    for active_id in active_voice_member_ids:
                        if active_id not in audited_user_ids:
                            user_prof = best_profiles.get(active_id)
                            member = channel.guild.get_member(active_id)
                            ign = user_prof.ingame_name if user_prof else (member.display_name if member else "Unregistered")
                            record = AttendanceRecord(
                                event_id=event.id, event_name=event.name, event_date=event.start_time,
                                discord_id=active_id, ingame_name=ign, signup_status="none",
                                actual_presence="Unregistered"
                            )
                            db.add(record)
                    db.commit()

    @app_commands.command(name="attendance_leaderboard", description="View the 30-day guild attendance leaderboard")
    @app_commands.default_permissions(manage_guild=True)
    async def attendance_leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cutoff = now - timedelta(days=30)
        
        with next(get_db()) as db:
            records = db.query(AttendanceRecord).filter(AttendanceRecord.event_date >= cutoff).all()
            
        if not records:
            await interaction.followup.send("📭 No attendance records found in the last 30 days.")
            return
            
        stats = {}
        for r in records:
            if r.discord_id not in stats:
                stats[r.discord_id] = {"name": r.ingame_name, "present": 0, "ghosted": 0, "unregistered": 0, "total": 0}
            
            stats[r.discord_id]["total"] += 1
            
            if r.actual_presence == "Present":
                stats[r.discord_id]["present"] += 1
            elif r.actual_presence == "Ghosted":
                stats[r.discord_id]["ghosted"] += 1
            elif r.actual_presence == "Unregistered":
                stats[r.discord_id]["unregistered"] += 1
                
        leaderboard = []
        for uid, data in stats.items():
            pct = (data["present"] / data["total"]) * 100 if data["total"] > 0 else 0
            leaderboard.append({
                "uid": uid,
                "name": data["name"],
                "present": data["present"],
                "ghosted": data["ghosted"],
                "unregistered": data["unregistered"],
                "total": data["total"],
                "pct": pct
            })
            
        leaderboard.sort(key=lambda x: (x["pct"], x["present"]), reverse=True)
        
        lines = []
        for idx, user in enumerate(leaderboard[:25], 1): 
            lines.append(
                f"**{idx}.** <@{user['uid']}> (`{user['name']}`) — **{user['pct']:.1f}%** ({user['present']}/{user['total']}) "
                f"| 👻 {user['ghosted']} Ghosted | ⚠️ {user['unregistered']} Unregistered"
            )
            
        embed = discord.Embed(
            title="🏆 30-Day Attendance Leaderboard",
            description="\n".join(lines) if lines else "*No data*",
            color=discord.Color.brand_green()
        )
        embed.set_footer(text="Data compiled from automated voice channel audits. Unregistered appearances penalize score.")
        
        await interaction.followup.send(embed=embed)

    @tasks.loop(hours=24)
    async def cleanup_attendance_loop(self):
        """Automatically purges temporary event signups older than 14 days to prevent database bloat."""
        await self.bot.wait_until_ready()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cutoff_date = now - timedelta(days=14)
        
        with next(get_db()) as db:
            old_completed_events = db.query(GuildEvent).filter(
                GuildEvent.is_completed == True,
                GuildEvent.start_time <= cutoff_date
            ).all()
            
            if old_completed_events:
                event_ids = [e.id for e in old_completed_events]
                
                deleted_rows = db.query(EventAttendance).filter(
                    EventAttendance.event_id.in_(event_ids)
                ).delete(synchronize_session=False)
                
                db.commit()
                print(f"🧹 Database Cleanup: Purged {deleted_rows} temporary signup rows from events concluded over 2 weeks ago.")

async def setup(bot: commands.Bot):
    await bot.add_cog(SchedulingCog(bot))