import discord
from discord.ext import commands
from discord import app_commands
from database.db_setup import get_db
from database.models import UserProfile

# Maps weapon text to visual icons
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

class ProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    profile_group = app_commands.Group(name="profile", description="Manage your Throne and Liberty character profile")

    WEAPON_CHOICES = [
        app_commands.Choice(name="Greatsword", value="Greatsword"),
        app_commands.Choice(name="Sword and Shield", value="Sword and Shield"),
        app_commands.Choice(name="Dagger", value="Dagger"),
        app_commands.Choice(name="Crossbow", value="Crossbow"),
        app_commands.Choice(name="Longbow", value="Longbow"),
        app_commands.Choice(name="Staff", value="Staff"),
        app_commands.Choice(name="Wand and Tome", value="Wand and Tome"),
        app_commands.Choice(name="Spear", value="Spear"),
        app_commands.Choice(name="Orb", value="Orb"),
        app_commands.Choice(name="Gauntlets", value="Gauntlets"),
    ]

    @profile_group.command(name="setup", description="Register or update your character's weapons and gear score")
    @app_commands.describe(
        ingame_name="Your exact in-game character name",
        primary_weapon="Your main weapon",
        secondary_weapon="Your off-hand weapon",
        gear_score="Your current gear score"
    )
    @app_commands.choices(primary_weapon=WEAPON_CHOICES, secondary_weapon=WEAPON_CHOICES)
    async def setup(
        self, 
        interaction: discord.Interaction, 
        ingame_name: str, 
        primary_weapon: str, 
        secondary_weapon: str, 
        gear_score: int
    ):
        with next(get_db()) as db:
            profile = db.query(UserProfile).filter_by(discord_id=interaction.user.id).first()
            if profile:
                profile.ingame_name = ingame_name
                profile.primary_weapon = primary_weapon
                profile.secondary_weapon = secondary_weapon
                profile.gear_score = gear_score
            else:
                profile = UserProfile(
                    discord_id=interaction.user.id,
                    ingame_name=ingame_name,
                    primary_weapon=primary_weapon,
                    secondary_weapon=secondary_weapon,
                    gear_score=gear_score
                )
                db.add(profile)
            db.commit()

        await interaction.response.send_message(
            f"✅ **Profile Saved!**\n"
            f"👤 **Name:** {ingame_name}\n"
            f"⚔️ **Weapons:** {primary_weapon} & {secondary_weapon}\n"
            f"⭐ **Gear Score:** {gear_score}", 
            ephemeral=True
        )

    @profile_group.command(name="view", description="View a member's character profile")
    @app_commands.describe(member="The guild member whose profile you want to view")
    async def view(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        
        with next(get_db()) as db:
            profile = db.query(UserProfile).filter_by(discord_id=target.id).first()
            
        if not profile:
            await interaction.response.send_message(f"❌ {target.mention} has not registered a profile yet. They can use `/profile setup`.", ephemeral=True)
            return

        w1 = WEAPON_EMOJIS.get(profile.primary_weapon, "")
        w2 = WEAPON_EMOJIS.get(profile.secondary_weapon, "")

        embed = discord.Embed(title=f"👤 Character Profile: {profile.ingame_name}", color=discord.Color.purple())
        embed.add_field(name="Discord", value=target.mention, inline=False)
        embed.add_field(name="⚔️ Loadout", value=f"{w1} {profile.primary_weapon} / {w2} {profile.secondary_weapon}", inline=True)
        embed.add_field(name="⭐ Gear Score", value=f"{profile.gear_score}", inline=True)
        embed.set_thumbnail(url=target.display_avatar.url)
        
        await interaction.response.send_message(embed=embed)

    # ==========================================
    # NEW DIRECTORY COMMAND
    # ==========================================
    @profile_group.command(name="directory", description="View a list of all registered guild members (Sorted by Gear Score)")
    async def directory(self, interaction: discord.Interaction):
        # We restrict this to those with guild management perms so regular members don't spam large lists,
        # but you can remove this check if you want it to be public!
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ You do not have permission to view the entire guild directory.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        with next(get_db()) as db:
            # Query all profiles and sort them by Gear Score (Descending)
            profiles = db.query(UserProfile).order_by(UserProfile.gear_score.desc()).all()

        if not profiles:
            await interaction.followup.send("📭 No guild members have registered their profiles yet.", ephemeral=True)
            return

        report_lines = []
        for p in profiles:
            w1 = WEAPON_EMOJIS.get(p.primary_weapon, "")
            w2 = WEAPON_EMOJIS.get(p.secondary_weapon, "")
            # Format: • @DiscordName (InGameName) [⭐ 3500 | 🗡️🪄]
            report_lines.append(f"• <@{p.discord_id}> (`{p.ingame_name}`) [⭐ **{p.gear_score}** | {w1}{w2}]")

        # Discord descriptions have a 4096-character limit. We split into chunks if the guild gets massive.
        embeds = []
        current_desc = ""
        for line in report_lines:
            if len(current_desc) + len(line) > 4000:
                embeds.append(discord.Embed(title="🛡️ Guild Profile Directory", description=current_desc, color=discord.Color.purple()))
                current_desc = line + "\n"
            else:
                current_desc += line + "\n"
        
        if current_desc:
            embeds.append(discord.Embed(title="🛡️ Guild Profile Directory", description=current_desc, color=discord.Color.purple()))

        # Send up to 10 embeds at once (Discord limit per message)
        await interaction.followup.send(embeds=embeds[:10], ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(ProfileCog(bot))