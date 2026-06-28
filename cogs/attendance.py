import discord
from discord.ext import commands
from sqlalchemy.orm import joinedload # NEW: Enables pulling joined data quickly

from database.db_setup import get_db
from database.models import EventAttendance, GuildEvent

# Maps weapon text to visual icons for the embed space saving
WEAPON_EMOJIS = {
    "Greatsword": "🗡️",
    "Sword and Shield": "🛡️",
    "Dagger": "🔪",
    "Crossbow": "🏹",
    "Longbow": "🏹",
    "Staff": "🪄",
    "Wand and Tome": "📘",
    "Spear": "🔱",
    "Orb": "🔮",
    "Gauntlets": "🥊"
}

class AttendanceView(discord.ui.View):
    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id

    async def handle_rsvp(self, interaction: discord.Interaction, status: str):
        await interaction.response.defer(ephemeral=True)
        
        with next(get_db()) as db:
            event = db.query(GuildEvent).filter_by(id=self.event_id).first()
            if not event or event.is_completed:
                await interaction.followup.send("❌ **This event has already concluded.**", ephemeral=True)
                return

            attendance = db.query(EventAttendance).filter_by(event_id=self.event_id, discord_id=interaction.user.id).first()
            if attendance:
                attendance.status = status
            else:
                attendance = EventAttendance(event_id=self.event_id, discord_id=interaction.user.id, status=status)
                db.add(attendance)
            db.commit()

            # NEW: Pull signups AND eagerly load the user profile data in a single rapid query
            all_signups = db.query(EventAttendance).options(joinedload(EventAttendance.user)).filter_by(event_id=self.event_id).all()

        attending_players = []
        absent_players = []
        tentative_players = []

        for signup in all_signups:
            mention_tag = f"<@{signup.discord_id}>"
            
            # If they have a profile, append the weapon icons
            if signup.user:
                w1 = WEAPON_EMOJIS.get(signup.user.primary_weapon, "")
                w2 = WEAPON_EMOJIS.get(signup.user.secondary_weapon, "")
                entry = f"{mention_tag} {w1}{w2}"
            else:
                entry = f"{mention_tag}"

            if signup.status == "attending": attending_players.append(entry)
            elif signup.status == "absent": absent_players.append(entry)
            elif signup.status == "tentative": tentative_players.append(entry)

        # Discord Field Safeguard: Fields fail if > 1024 characters.
        def safe_join(player_list):
            res = "\n".join(player_list) if player_list else "*None*"
            return res[:1000] + "\n...*(Too many to display)*" if len(res) > 1024 else res

        embed = interaction.message.embeds[0]
        embed.set_field_at(1, name=f"✅ Attending ({len(attending_players)})", value=safe_join(attending_players), inline=True)
        embed.set_field_at(2, name=f"❌ Not Attending ({len(absent_players)})", value=safe_join(absent_players), inline=True)
        embed.set_field_at(3, name=f"⏳ Tentative ({len(tentative_players)})", value=safe_join(tentative_players), inline=True)
        
        await interaction.message.edit(embed=embed)
        display_status = "Not Attending" if status == "absent" else status.capitalize()
        await interaction.followup.send(f"Your RSVP has been recorded as **{display_status}**.", ephemeral=True)

    @discord.ui.button(label="Attending", emoji="✅", style=discord.ButtonStyle.green, custom_id="btn_attend")
    async def attending(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_rsvp(interaction, "attending")

    @discord.ui.button(label="Not Attending", emoji="❌", style=discord.ButtonStyle.gray, custom_id="btn_absent")
    async def absent(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_rsvp(interaction, "absent")

    @discord.ui.button(label="Tentative", emoji="⏳", style=discord.ButtonStyle.blurple, custom_id="btn_tentative")
    async def tentative(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_rsvp(interaction, "tentative")

class AttendanceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print("Attendance UI system online.")

async def setup(bot: commands.Bot):
    await bot.add_cog(AttendanceCog(bot))