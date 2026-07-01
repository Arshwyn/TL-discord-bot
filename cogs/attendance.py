import discord
from discord.ext import commands
from sqlalchemy.orm import joinedload

from database.db_setup import get_db
from database.models import EventAttendance, GuildEvent, UserProfile

WEAPON_EMOJIS = {
    "Greatsword": "🗡️", "Sword and Shield": "🛡️", "Dagger": "🔪",
    "Crossbow": "🏹", "Longbow": "🏹", "Staff": "🪄",
    "Wand and Tome": "📘", "Spear": "🔱", "Orb": "🔮", "Gauntlets": "🥊"
}

class AttendanceView(discord.ui.View):
    def __init__(self, event_id: int = None):
        super().__init__(timeout=None)
        self.event_id = event_id

    async def handle_rsvp(self, interaction: discord.Interaction, status: str):
        await interaction.response.defer(ephemeral=True)
        
        with next(get_db()) as db:
            current_event_id = self.event_id
            if not current_event_id:
                event_record = db.query(GuildEvent).filter_by(message_id=interaction.message.id).first()
                if event_record:
                    current_event_id = event_record.id

            event = db.query(GuildEvent).filter_by(id=current_event_id).first()
            if not event or event.is_completed:
                await interaction.followup.send("⛔ **This event has already concluded or cannot be found.**", ephemeral=True)
                return

            attendance = db.query(EventAttendance).filter_by(event_id=current_event_id, discord_id=interaction.user.id).first()
            if attendance:
                attendance.status = status
            else:
                attendance = EventAttendance(event_id=current_event_id, discord_id=interaction.user.id, status=status)
                db.add(attendance)
            db.commit()

            all_signups = db.query(EventAttendance).filter_by(event_id=current_event_id).all()
            user_ids = [s.discord_id for s in all_signups]
            
            # 🟢 NEW: Smart Fallback Logic (Exact Match > PvX Match > Nothing)
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
        absent_players = []
        tentative_players = []
        total_attending = 0

        for signup in all_signups:
            mention_tag = f"<@{signup.discord_id}>"
            user_prof = best_profiles.get(signup.discord_id)
            
            if user_prof:
                w1 = WEAPON_EMOJIS.get(user_prof.primary_weapon, "")
                w2 = WEAPON_EMOJIS.get(user_prof.secondary_weapon, "")
                s_group = user_prof.static_group or "Unassigned"
                entry = f"{mention_tag} {w1}{w2}"
            else:
                s_group = "Unassigned"
                entry = f"{mention_tag}"

            if signup.status == "attending":
                if s_group not in attending_dict:
                    attending_dict[s_group] = []
                attending_dict[s_group].append(entry)
                total_attending += 1
            elif signup.status == "absent":
                absent_players.append(entry)
            elif signup.status == "tentative":
                tentative_players.append(entry)

        attending_lines = []
        sorted_groups = sorted(attending_dict.keys(), key=lambda x: (x == "Unassigned", x))
        
        for group in sorted_groups:
            attending_lines.append(f"**🛡️ {group}**")
            for player in attending_dict[group]:
                attending_lines.append(player)
            attending_lines.append("") 

        def safe_join(player_list, default_text="`0 players`"):
            res = "\n".join(player_list).strip() if player_list else default_text
            return res[:1000] + "\n...*(Too many to display)*" if len(res) > 1024 else res

        embed = interaction.message.embeds[0]
        embed.set_field_at(1, name=f"✅ Attending ({total_attending})", value=safe_join(attending_lines), inline=True)
        embed.set_field_at(2, name=f"⛔ Not Attending ({len(absent_players)})", value=safe_join(absent_players), inline=True)
        embed.set_field_at(3, name=f"⏳ Tentative ({len(tentative_players)})", value=safe_join(tentative_players), inline=True)
        
        await interaction.message.edit(embed=embed)
        display_status = "Not Attending" if status == "absent" else status.capitalize()
        await interaction.followup.send(f"Your RSVP has been recorded as **{display_status}**.", ephemeral=True)

    @discord.ui.button(label="Attending", emoji="✅", style=discord.ButtonStyle.green, custom_id="btn_attend")
    async def attending(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_rsvp(interaction, "attending")

    @discord.ui.button(label="Not Attending", emoji="⛔", style=discord.ButtonStyle.red, custom_id="btn_absent")
    async def absent(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_rsvp(interaction, "absent")

    @discord.ui.button(label="Tentative", emoji="⏳", style=discord.ButtonStyle.blurple, custom_id="btn_tentative")
    async def tentative(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_rsvp(interaction, "tentative")

class AttendanceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(AttendanceView()) 

async def setup(bot: commands.Bot):
    await bot.add_cog(AttendanceCog(bot))