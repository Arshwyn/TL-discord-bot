import discord
from discord.ext import commands

from database.db_setup import get_db
from database.models import EventAttendance, GuildEvent

class AttendanceView(discord.ui.View):
    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id

    async def handle_rsvp(self, interaction: discord.Interaction, status: str):
        # Defer interaction to avoid timeout errors
        await interaction.response.defer(ephemeral=True)
        
        with next(get_db()) as db:
            # 🛡️ SECURITY CHECK: Ensure the event is active before allowing RSVPs
            event = db.query(GuildEvent).filter_by(id=self.event_id).first()
            if not event or event.is_completed:
                await interaction.followup.send("⛔ **This event has already concluded.**", ephemeral=True)
                return

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

            # Refresh roster counts
            total_attending = db.query(EventAttendance).filter_by(event_id=self.event_id, status="attending").count()
            total_absent = db.query(EventAttendance).filter_by(event_id=self.event_id, status="absent").count()
            total_tentative = db.query(EventAttendance).filter_by(event_id=self.event_id, status="tentative").count()

        # Dynamically update the embed
        embed = interaction.message.embeds[0]
        embed.set_field_at(1, name="✅ Attending", value=f"`{total_attending} players`", inline=True)
        embed.set_field_at(2, name="⛔ Not Attending", value=f"`{total_absent} players`", inline=True)
        embed.set_field_at(3, name="⏳ Tentative", value=f"`{total_tentative} players`", inline=True)
        
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

    @commands.Cog.listener()
    async def on_ready(self):
        print("Attendance UI system online.")

async def setup(bot: commands.Bot):
    await bot.add_cog(AttendanceCog(bot))