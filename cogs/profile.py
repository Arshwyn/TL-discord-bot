import discord
from discord.ext import commands
from discord import app_commands
from database.db_setup import get_db
from database.models import UserProfile

WEAPON_EMOJIS = {
    "Greatsword": "🗡️", "Sword and Shield": "🛡️", "Dagger": "🔪", 
    "Crossbow": "🏹", "Longbow": "🏹", "Staff": "🪄", 
    "Wand and Tome": "📘", "Spear": "🔱", "Orb": "🔮", "Gauntlets": "🥊"
}

class ProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    profile_group = app_commands.Group(name="profile", description="Manage your character profile")
    static_group = app_commands.Group(name="static", description="Manage guild static parties")

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
    @app_commands.describe(ingame_name="In-game name", primary_weapon="Main weapon", secondary_weapon="Off-hand weapon", gear_score="Gear score")
    @app_commands.choices(primary_weapon=WEAPON_CHOICES, secondary_weapon=WEAPON_CHOICES)
    async def setup(self, interaction: discord.Interaction, ingame_name: str, primary_weapon: str, secondary_weapon: str, gear_score: int):
        with next(get_db()) as db:
            profile = db.query(UserProfile).filter_by(discord_id=interaction.user.id).first()
            if profile:
                profile.ingame_name = ingame_name
                profile.primary_weapon = primary_weapon
                profile.secondary_weapon = secondary_weapon
                profile.gear_score = gear_score
            else:
                profile = UserProfile(
                    discord_id=interaction.user.id, ingame_name=ingame_name,
                    primary_weapon=primary_weapon, secondary_weapon=secondary_weapon, gear_score=gear_score
                )
                db.add(profile)
            db.commit()

        await interaction.response.send_message(
            f"✅ **Profile Saved!**\n👤 **Name:** {ingame_name}\n⚔️ **Weapons:** {primary_weapon} & {secondary_weapon}\n⭐ **Gear Score:** {gear_score}", 
            ephemeral=True
        )

    @profile_group.command(name="view", description="View a member's character profile")
    async def view(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        with next(get_db()) as db:
            profile = db.query(UserProfile).filter_by(discord_id=target.id).first()
            
        if not profile:
            await interaction.response.send_message(f"❌ {target.mention} has not registered a profile yet.", ephemeral=True)
            return

        w1 = WEAPON_EMOJIS.get(profile.primary_weapon, "")
        w2 = WEAPON_EMOJIS.get(profile.secondary_weapon, "")
        static_tag = f"\n🛡️ **Static:** {profile.static_group}" if profile.static_group else ""

        embed = discord.Embed(title=f"👤 Character Profile: {profile.ingame_name}", description=static_tag, color=discord.Color.purple())
        embed.add_field(name="Discord", value=target.mention, inline=False)
        embed.add_field(name="⚔️ Loadout", value=f"{w1} {profile.primary_weapon} / {w2} {profile.secondary_weapon}", inline=True)
        embed.add_field(name="⭐ Gear Score", value=f"{profile.gear_score}", inline=True)
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @profile_group.command(name="directory", description="View a list of all registered guild members")
    @app_commands.default_permissions(manage_guild=True) 
    async def directory(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        with next(get_db()) as db:
            profiles = db.query(UserProfile).order_by(UserProfile.gear_score.desc()).all()

        if not profiles:
            await interaction.followup.send("📭 No guild members have registered their profiles yet.", ephemeral=True)
            return

        report_lines = []
        for p in profiles:
            w1 = WEAPON_EMOJIS.get(p.primary_weapon, "")
            w2 = WEAPON_EMOJIS.get(p.secondary_weapon, "")
            static_tag = f" [{p.static_group}]" if p.static_group else ""
            report_lines.append(f"• <@{p.discord_id}> (`{p.ingame_name}`){static_tag} [⭐ **{p.gear_score}** | {w1}{w2}]")

        embeds, current_desc = [], ""
        for line in report_lines:
            if len(current_desc) + len(line) > 4000:
                embeds.append(discord.Embed(title="🛡️ Guild Profile Directory", description=current_desc, color=discord.Color.purple()))
                current_desc = line + "\n"
            else:
                current_desc += line + "\n"
        if current_desc: embeds.append(discord.Embed(title="🛡️ Guild Profile Directory", description=current_desc, color=discord.Color.purple()))
        await interaction.followup.send(embeds=embeds[:10], ephemeral=True)

    # ==========================================
    # STATIC MANAGEMENT COMMANDS
    # ==========================================
    @static_group.command(name="assign", description="Assign a user to a specific Static Party")
    @app_commands.default_permissions(manage_guild=True)
    async def static_assign(self, interaction: discord.Interaction, member: discord.Member, group_name: str):
        with next(get_db()) as db:
            profile = db.query(UserProfile).filter_by(discord_id=member.id).first()
            if not profile:
                # Silently init a blank profile if they haven't registered yet so we can still group them
                profile = UserProfile(discord_id=member.id, ingame_name=member.display_name)
                db.add(profile)
            
            profile.static_group = group_name
            db.commit()
            
        await interaction.response.send_message(f"✅ Assigned {member.mention} to **{group_name}**.", ephemeral=True)

    @static_group.command(name="remove", description="Remove a user from their Static Party")
    @app_commands.default_permissions(manage_guild=True)
    async def static_remove(self, interaction: discord.Interaction, member: discord.Member):
        with next(get_db()) as db:
            profile = db.query(UserProfile).filter_by(discord_id=member.id).first()
            if profile and profile.static_group:
                profile.static_group = None
                db.commit()
                await interaction.response.send_message(f"✅ Removed {member.mention} from their static group.", ephemeral=True)
            else:
                await interaction.response.send_message(f"⚠️ {member.mention} is not currently in a static.", ephemeral=True)

    @static_group.command(name="list", description="View all static parties, their members, and average gear scores")
    @app_commands.describe(group_name="Optional: View a specific static party only")
    async def static_list(self, interaction: discord.Interaction, group_name: str = None):
        await interaction.response.defer(ephemeral=False) # Not ephemeral, so the guild can see their statics!

        with next(get_db()) as db:
            # Query all profiles that are assigned to a static (or a specific static if requested)
            if group_name:
                profiles = db.query(UserProfile).filter(UserProfile.static_group == group_name).all()
            else:
                profiles = db.query(UserProfile).filter(UserProfile.static_group != None).all()

        if not profiles:
            msg = f"📭 No members found in static '{group_name}'." if group_name else "📭 No static parties have been formed yet."
            await interaction.followup.send(msg)
            return

        # Sort the results into buckets based on static name
        statics_dict = {}
        for p in profiles:
            if p.static_group not in statics_dict:
                statics_dict[p.static_group] = []
            statics_dict[p.static_group].append(p)

        embeds = []
        # Build one Discord Embed card per Static Party
        for static_name, members in statics_dict.items():
            # Sort members within the static by highest Gear Score
            members.sort(key=lambda x: x.gear_score, reverse=True)
            
            # Calculate the group's average GS
            avg_gs = sum(m.gear_score for m in members) // len(members)
            
            lines = []
            for m in members:
                w1 = WEAPON_EMOJIS.get(m.primary_weapon, "")
                w2 = WEAPON_EMOJIS.get(m.secondary_weapon, "")
                lines.append(f"• <@{m.discord_id}> (`{m.ingame_name}`) [⭐ **{m.gear_score}** | {w1}{w2}]")
                
            desc = "\n".join(lines)
            if len(desc) > 4096:
                desc = desc[:4090] + "..."

            embed = discord.Embed(
                title=f"🛡️ Static: {static_name}",
                description=desc,
                color=discord.Color.gold()
            )
            embed.set_footer(text=f"Total Members: {len(members)} | Average Gear Score: {avg_gs}")
            embeds.append(embed)

        # Discord allows up to 10 embeds per message. Chunk if they have a ton of statics.
        for i in range(0, len(embeds), 10):
            await interaction.followup.send(embeds=embeds[i:i+10])

async def setup(bot: commands.Bot):
    await bot.add_cog(ProfileCog(bot))