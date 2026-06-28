import discord
from discord.ext import commands

from database.db_setup import get_db
from database.models import EventAttendance, GuildEvent

class AttendanceView(discord.ui.View):
    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id

    async def handle_rsvp(self, interaction: discord.Interaction, status: str):
        await interaction.response.defer(ephemeral=True)
        
        with next(get_db()) as db:
            # Security Check: Ensure the event is active
            event = db.query(GuildEvent).filter_by(id=self.event_id).first()
            if not event or event.is_completed:
                await interaction.followup.send("❌ **This event has already concluded.**", ephemeral=True)
                return

            # Save or update attendance record
            attendance = db.query(EventAttendance).filter_by(
                event_id=self.event_id, 
                discord_id=interaction.user.id
            ).first()

            if attendance:
                attendance.status = status
            else:
                attendance = EventAttendance(
                    event_id=self.event_id,
                    discord_id=interaction.user.id,
                    status=status
                )
                db.add(attendance)
            
            db.commit()

            # 📋 ROSTER GENERATION: Query all signups for this event
            all_signups = db.query(EventAttendance).filter_by(event_id=self.event_id).all()

        # Group players by their RSVP choice
        attending_players = []
        absent_players = []
        tentative_players = []

        for signup in all_signups:
            # Format as a clickable mention tag (e.g., @Derrick)
            mention_tag = f"<@{signup.discord_id}>"
            if signup.status == "attending":
                attending_players.append(mention_tag)
            elif signup.status == "absent":
                absent_players.append(mention_tag)
            elif signup.status == "tentative":
                tentative_players.append(mention_tag)

        # Create clean, scannable string lines (or display "None" if empty)
        attending_list = "\n".join(attending_players) if attending_players else "*None*"
        absent_list = "\n".join(absent_players) if absent_players else "*None*"
        tentative_list = "\n".join(tentative_players) if tentative_players else "*None*"

        # Rebuild and update the embed fields dynamically
        embed = interaction.message.embeds[0]
        embed.set_field_at(1, name=f"✅ Attending ({len(attending_players)})", value=attending_list, inline=True)
        embed.set_field_at(2, name=f"❌ Not Attending ({len(absent_players)})", value=absent_list, inline=True)
        embed.set_field_at(3, name=f"⏳ Tentative ({len(tentative_players)})", value=tentative_list, inline=True)
        
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