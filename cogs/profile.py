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

    BUILD_CHOICES = [
        app_commands.Choice(name="PvE Content", value="PvE"),
        app_commands.Choice(name="PvP Content", value="PvP"),
        app_commands.Choice(name="PvX (Both)", value="PvX")
    ]

    async def update_build_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        with next(get_db()) as db:
            profiles = db.query(UserProfile).filter_by(discord_id=interaction.user.id).all()
            return [
                app_commands.Choice(name=p.build_name, value=p.build_name)
                for p in profiles if current.lower() in p.build_name.lower()
            ][:25] 

    async def view_build_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        target_id = interaction.namespace.member or interaction.user.id
        with next(get_db()) as db:
            profiles = db.query(UserProfile).filter_by(discord_id=target_id).all()
            return [
                app_commands.Choice(name=p.build_name, value=p.build_name)
                for p in profiles if current.lower() in p.build_name.lower()
            ][:25]

    @profile_group.command(name="setup", description="Create a new specific build loadout")
    @app_commands.describe(
        build_name="Name this build (e.g., 'Main Build', 'GvG Tank')",
        build_type="Is this build optimized for PvE, PvP, or PvX?",
        ingame_name="In-game name (Synchronizes across all your builds)", 
        primary_weapon="Main weapon", 
        secondary_weapon="Off-hand weapon", 
        gear_score="Gear score for this specific build",
        screenshot="Optional screenshot of your gear/stats for validation"
    )
    @app_commands.choices(primary_weapon=WEAPON_CHOICES, secondary_weapon=WEAPON_CHOICES, build_type=BUILD_CHOICES)
    async def setup(
        self, interaction: discord.Interaction, build_name: str, build_type: str,
        ingame_name: str, primary_weapon: str, secondary_weapon: str, 
        gear_score: int, screenshot: discord.Attachment = None
    ):
        pic_url = screenshot.url if screenshot else None

        with next(get_db()) as db:
            profile = db.query(UserProfile).filter_by(discord_id=interaction.user.id, build_name=build_name).first()
            
            existing_any_build = db.query(UserProfile).filter_by(discord_id=interaction.user.id).first()
            static_group = existing_any_build.static_group if existing_any_build else None

            if profile:
                profile.build_type = build_type
                profile.ingame_name = ingame_name
                profile.primary_weapon = primary_weapon
                profile.secondary_weapon = secondary_weapon
                profile.gear_score = gear_score
                if pic_url:
                    profile.gear_screenshot_url = pic_url
            else:
                profile = UserProfile(
                    discord_id=interaction.user.id, build_name=build_name, build_type=build_type, 
                    ingame_name=ingame_name, primary_weapon=primary_weapon, secondary_weapon=secondary_weapon, 
                    gear_score=gear_score, gear_screenshot_url=pic_url, static_group=static_group
                )
                db.add(profile)
            
            all_user_builds = db.query(UserProfile).filter_by(discord_id=interaction.user.id).all()
            for b in all_user_builds:
                b.ingame_name = ingame_name

            db.commit()

        photo_msg = "\n📸 **Screenshot:** Verified Image Saved!" if pic_url else ""
        await interaction.response.send_message(
            f"✅ **Build '{build_name}' Saved!**\n👤 **Name:** {ingame_name}\n🛡️ **Type:** {build_type}\n⚔️ **Weapons:** {primary_weapon} & {secondary_weapon}\n⭐ **Gear Score:** {gear_score}{photo_msg}", 
            ephemeral=True
        )

    @profile_group.command(name="update", description="Update parts of an existing build or your global IGN")
    @app_commands.autocomplete(build_name=update_build_autocomplete)
    @app_commands.describe(
        build_name="Required if updating stats. Leave blank if ONLY updating your IGN.",
        gear_score="Your updated gear score value",
        ingame_name="Update your name across all your builds if you used a name change ticket",
        primary_weapon="Change your main weapon selection",
        secondary_weapon="Change your off-hand weapon selection",
        build_type="Change the tag (PvE/PvP/PvX) for this build",
        screenshot="Upload a new screenshot to verify your gear modifications"
    )
    @app_commands.choices(primary_weapon=WEAPON_CHOICES, secondary_weapon=WEAPON_CHOICES, build_type=BUILD_CHOICES)
    async def update(
        self, interaction: discord.Interaction, 
        build_name: str = None, # Made optional
        gear_score: int = None, ingame_name: str = None,
        primary_weapon: str = None, secondary_weapon: str = None,
        build_type: str = None, screenshot: discord.Attachment = None
    ):
        # 1. Enforce build_name requirement for build-specific changes
        build_specific_changes = [gear_score, primary_weapon, secondary_weapon, build_type, screenshot]
        if not build_name and any(x is not None for x in build_specific_changes):
            await interaction.response.send_message("❌ You must specify a **build_name** if you want to update your gear score, weapons, or build type.", ephemeral=True)
            return

        with next(get_db()) as db:
            changes = []
            
            # 2. Handle Global IGN Change (doesn't need a specific build)
            if ingame_name is not None:
                all_builds = db.query(UserProfile).filter_by(discord_id=interaction.user.id).all()
                if not all_builds:
                    await interaction.response.send_message("⚠️ You don't have any profiles to update.", ephemeral=True)
                    return
                for b in all_builds:
                    b.ingame_name = ingame_name
                changes.append(f"👤 **In-Game Name:** Adjusted globally to `{ingame_name}`")

            # 3. Handle Build-Specific Changes
            if build_name is not None:
                profile = db.query(UserProfile).filter_by(discord_id=interaction.user.id, build_name=build_name).first()
                if not profile:
                    await interaction.response.send_message(f"⚠️ Could not find a build named **{build_name}**. Use `/profile view` to see your exact build names.", ephemeral=True)
                    return

                if gear_score is not None:
                    profile.gear_score = gear_score
                    changes.append(f"⭐ **Gear Score:** Updated to {gear_score}")
                if primary_weapon is not None:
                    profile.primary_weapon = primary_weapon
                    changes.append(f"⚔️ **Primary Weapon:** Changed to {primary_weapon}")
                if secondary_weapon is not None:
                    profile.secondary_weapon = secondary_weapon
                    changes.append(f"🛡️ **Secondary Weapon:** Changed to {secondary_weapon}")
                if build_type is not None:
                    profile.build_type = build_type
                    changes.append(f"🏷️ **Build Tag:** Changed to {build_type}")
                if screenshot is not None:
                    profile.gear_screenshot_url = screenshot.url
                    changes.append("📸 **Verification Screenshot:** Updated image track.")

            if not changes:
                await interaction.response.send_message("ℹ️ No parameters were provided. Profile left unchanged.", ephemeral=True)
                return
                
            db.commit()

        target_name = f"Build '{build_name}'" if build_name else "Global Profile"
        changes_msg = "\n".join(changes)
        await interaction.response.send_message(
            f"✅ **{target_name} Updated Successfully!**\n\n**Applied Modifications:**\n{changes_msg}", 
            ephemeral=True
        )

    @profile_group.command(name="admin_update", description="Admin: Override and update a specific member's build")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.autocomplete(build_name=view_build_autocomplete)
    @app_commands.describe(
        member="The guild member whose profile you want to update",
        build_name="Required if updating stats. Leave blank if ONLY updating their IGN.",
        gear_score="Updated gear score value",
        ingame_name="Update the name across all their builds (e.g. to fix a typo)",
        primary_weapon="Change main weapon selection",
        secondary_weapon="Change off-hand weapon selection",
        build_type="Change the tag (PvE/PvP/PvX) for this build"
    )
    @app_commands.choices(primary_weapon=WEAPON_CHOICES, secondary_weapon=WEAPON_CHOICES, build_type=BUILD_CHOICES)
    async def admin_update(
        self, interaction: discord.Interaction, member: discord.Member, 
        build_name: str = None, # Made Optional
        gear_score: int = None, ingame_name: str = None,
        primary_weapon: str = None, secondary_weapon: str = None,
        build_type: str = None
    ):
        # 1. Enforce build_name requirement for build-specific changes
        build_specific_changes = [gear_score, primary_weapon, secondary_weapon, build_type]
        if not build_name and any(x is not None for x in build_specific_changes):
            await interaction.response.send_message("❌ You must specify a **build_name** to update gear score, weapons, or build type for this user.", ephemeral=True)
            return

        with next(get_db()) as db:
            changes = []
            
            # 2. Handle Global IGN Change
            if ingame_name is not None:
                all_builds = db.query(UserProfile).filter_by(discord_id=member.id).all()
                if not all_builds:
                    await interaction.response.send_message(f"⚠️ {member.mention} doesn't have any profiles to update.", ephemeral=True)
                    return
                for b in all_builds:
                    b.ingame_name = ingame_name
                changes.append(f"👤 **In-Game Name:** Adjusted globally to `{ingame_name}`")

            # 3. Handle Build-Specific Changes
            if build_name is not None:
                profile = db.query(UserProfile).filter_by(discord_id=member.id, build_name=build_name).first()
                if not profile:
                    await interaction.response.send_message(f"⚠️ Could not find a build named **{build_name}** for {member.mention}.", ephemeral=True)
                    return

                if gear_score is not None:
                    profile.gear_score = gear_score
                    changes.append(f"⭐ **Gear Score:** Updated to {gear_score}")
                if primary_weapon is not None:
                    profile.primary_weapon = primary_weapon
                    changes.append(f"⚔️ **Primary Weapon:** Changed to {primary_weapon}")
                if secondary_weapon is not None:
                    profile.secondary_weapon = secondary_weapon
                    changes.append(f"🛡️ **Secondary Weapon:** Changed to {secondary_weapon}")
                if build_type is not None:
                    profile.build_type = build_type
                    changes.append(f"🏷️ **Build Tag:** Changed to {build_type}")

            if not changes:
                await interaction.response.send_message("ℹ️ No parameters were provided. Profile left unchanged.", ephemeral=True)
                return
                
            db.commit()

        target_name = f"Build '{build_name}'" if build_name else "Global Profile"
        changes_msg = "\n".join(changes)
        await interaction.response.send_message(
            f"✅ **{target_name} for {member.mention} Updated Successfully!**\n\n**Applied Modifications:**\n{changes_msg}", 
            ephemeral=True
        )

    @profile_group.command(name="admin_delete", description="Admin: Permanently delete a member's build profile")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.autocomplete(build_name=view_build_autocomplete)
    @app_commands.describe(
        member="The guild member whose profile you want to delete",
        build_name="Select the specific build profile to permanently delete"
    )
    async def admin_delete(self, interaction: discord.Interaction, member: discord.Member, build_name: str):
        with next(get_db()) as db:
            profile = db.query(UserProfile).filter_by(discord_id=member.id, build_name=build_name).first()
            
            if not profile:
                await interaction.response.send_message(
                    f"❌ Could not find a build named **{build_name}** for {member.mention}. Operation canceled.", 
                    ephemeral=True
                )
                return

            db.delete(profile)
            db.commit()

        await interaction.response.send_message(
            f"🗑️ **Build Profile Deleted!** The build **'{build_name}'** has been permanently removed from {member.mention}'s account.", 
            ephemeral=True
        )

    @profile_group.command(name="delete", description="Permanently delete one of your character build profiles")
    @app_commands.autocomplete(build_name=update_build_autocomplete)
    @app_commands.describe(build_name="Select the specific build profile you want to permanently delete")
    async def delete_build(self, interaction: discord.Interaction, build_name: str):
        with next(get_db()) as db:
            profile = db.query(UserProfile).filter_by(discord_id=interaction.user.id, build_name=build_name).first()
            
            if not profile:
                await interaction.response.send_message(
                    f"❌ Could not find a build named **{build_name}**. Operation canceled.", 
                    ephemeral=True
                )
                return

            db.delete(profile)
            db.commit()

        await interaction.response.send_message(
            f"🗑️ **Build Profile Deleted!** The build **'{build_name}'** has been permanently removed from your account.", 
            ephemeral=True
        )

    @profile_group.command(name="view", description="View a member's character profile(s)")
    @app_commands.autocomplete(build_name=view_build_autocomplete)
    @app_commands.describe(member="The user to check", build_name="Optional: Select a specific build. Leave blank to see all.")
    async def view(self, interaction: discord.Interaction, member: discord.Member = None, build_name: str = None):
        target = member or interaction.user
        with next(get_db()) as db:
            if build_name:
                profiles = db.query(UserProfile).filter_by(discord_id=target.id, build_name=build_name).all()
            else:
                profiles = db.query(UserProfile).filter_by(discord_id=target.id).all()
            
        if not profiles:
            msg = f"❌ {target.mention} has not registered the build '{build_name}'." if build_name else f"❌ {target.mention} has not registered any builds yet."
            await interaction.response.send_message(msg, ephemeral=True)
            return

        if not build_name and len(profiles) > 1:
            desc = ""
            for p in profiles:
                w1 = WEAPON_EMOJIS.get(p.primary_weapon, "")
                w2 = WEAPON_EMOJIS.get(p.secondary_weapon, "")
                desc += f"**{p.build_name}** ({p.build_type})\n> ⭐ {p.gear_score} GS | {w1}{w2} {p.primary_weapon} & {p.secondary_weapon}\n\n"
            
            embed = discord.Embed(title=f"👤 Character Builds: {profiles[0].ingame_name}", description=desc, color=discord.Color.blue())
            embed.set_footer(text=f"To view screenshots and details, run: /profile view build_name: <name>")
            await interaction.response.send_message(embed=embed)
            return

        profile = profiles[0]
        w1 = WEAPON_EMOJIS.get(profile.primary_weapon, "")
        w2 = WEAPON_EMOJIS.get(profile.secondary_weapon, "")
        static_tag = f"\n🛡️ **Static:** {profile.static_group}" if profile.static_group else ""

        # 🟢 Match Colors dynamically
        if profile.build_type == "PvE":
            card_color = discord.Color.purple()
        elif profile.build_type == "PvP":
            card_color = discord.Color.red()
        else:
            card_color = discord.Color.gold()

        embed = discord.Embed(
            title=f"👤 Profile: {profile.ingame_name} | {profile.build_name}", 
            description=f"Type: **{profile.build_type}**{static_tag}", 
            color=card_color
        )
        embed.add_field(name="Discord Account", value=target.mention, inline=False)
        embed.add_field(name="⚔️ Active Loadout", value=f"{w1} {profile.primary_weapon} / {w2} {profile.secondary_weapon}", inline=True)
        embed.add_field(name="⭐ Gear Score", value=f"{profile.gear_score}", inline=True)
        embed.set_thumbnail(url=target.display_avatar.url)
        
        if profile.gear_screenshot_url:
            embed.set_image(url=profile.gear_screenshot_url)

        await interaction.response.send_message(embed=embed)

    @profile_group.command(name="directory", description="View a unified list of all registered guild builds")
    @app_commands.default_permissions(manage_guild=True) 
    async def directory(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        with next(get_db()) as db:
            profiles = db.query(UserProfile).order_by(UserProfile.gear_score.desc()).all()

        if not profiles:
            await interaction.followup.send("📭 No guild members have registered any builds yet.", ephemeral=True)
            return

        pve_lines = []
        pvp_lines = []
        pvx_lines = []

        for p in profiles:
            w1 = WEAPON_EMOJIS.get(p.primary_weapon, "")
            w2 = WEAPON_EMOJIS.get(p.secondary_weapon, "")
            static_tag = f" [{p.static_group}]" if p.static_group else ""
            pic_tag = " 📸" if p.gear_screenshot_url else ""
            
            line_str = f"• <@{p.discord_id}> (`{p.ingame_name}`){static_tag} - *{p.build_name}* [⭐ **{p.gear_score}** | {w1}{w2}]{pic_tag}"
            
            # Segregate them internally for cleanly formatting the embed
            if p.build_type == "PvE":
                pve_lines.append(line_str)
            elif p.build_type == "PvP":
                pvp_lines.append(line_str)
            else:
                pvx_lines.append(line_str)

        embeds = []
        current_desc = ""

        def flush_embed(desc):
            if desc.strip():
                embeds.append(discord.Embed(title="🛡️ Guild Profile Directory", description=desc, color=discord.Color.blue()))

        if pve_lines:
            current_desc += "**🟢 PvE Configurations**\n"
            for line in pve_lines:
                if len(current_desc) + len(line) > 3900:
                    flush_embed(current_desc)
                    current_desc = "**🟢 PvE Configurations (Cont.)**\n" + line + "\n"
                else:
                    current_desc += line + "\n"
            current_desc += "\n" 

        if pvp_lines:
            header = "**🔴 PvP Configurations**\n"
            if len(current_desc) + len(header) > 3900:
                flush_embed(current_desc)
                current_desc = header
            else:
                current_desc += header

            for line in pvp_lines:
                if len(current_desc) + len(line) > 3900:
                    flush_embed(current_desc)
                    current_desc = "**🔴 PvP Configurations (Cont.)**\n" + line + "\n"
                else:
                    current_desc += line + "\n"
            current_desc += "\n" 

        if pvx_lines:
            header = "**🟡 PvX Configurations**\n"
            if len(current_desc) + len(header) > 3900:
                flush_embed(current_desc)
                current_desc = header
            else:
                current_desc += header

            for line in pvx_lines:
                if len(current_desc) + len(line) > 3900:
                    flush_embed(current_desc)
                    current_desc = "**🟡 PvX Configurations (Cont.)**\n" + line + "\n"
                else:
                    current_desc += line + "\n"

        flush_embed(current_desc)

        for i in range(0, len(embeds), 10):
            await interaction.followup.send(embeds=embeds[i:i+10], ephemeral=True)

    @profile_group.command(name="prune", description="Scan the guild database and delete profiles of users who have left the server")
    @app_commands.default_permissions(manage_guild=True)
    async def prune_left_members(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        with next(get_db()) as db:
            all_profiles = db.query(UserProfile).all()
            
            if not all_profiles:
                await interaction.followup.send("📭 The profile database is completely empty. Nothing to prune.", ephemeral=True)
                return

            pruned_count = 0
            checked_ids = set()

            for profile in all_profiles:
                if profile.discord_id in checked_ids:
                    continue
                checked_ids.add(profile.discord_id)

                member = interaction.guild.get_member(profile.discord_id)
                if not member:
                    ghost_builds = db.query(UserProfile).filter_by(discord_id=profile.discord_id).all()
                    for b in ghost_builds:
                        db.delete(b)
                    pruned_count += 1
            
            if pruned_count > 0:
                db.commit()

        if pruned_count > 0:
            await interaction.followup.send(f"✅ **Prune Complete!** Identified and permanently deleted profiles for **{pruned_count}** former members who are no longer in the server.", ephemeral=True)
        else:
            await interaction.followup.send("✅ **Scan Complete:** All registered profiles match active members currently inside the server. Zero ghosts found!", ephemeral=True)

    @static_group.command(name="assign", description="Assign a user to a specific Static Party")
    @app_commands.default_permissions(manage_guild=True)
    async def static_assign(self, interaction: discord.Interaction, member: discord.Member, group_name: str):
        with next(get_db()) as db:
            profiles = db.query(UserProfile).filter_by(discord_id=member.id).all()
            if not profiles:
                profile = UserProfile(discord_id=member.id, build_name="Default Build", build_type="PvE", ingame_name=member.display_name, static_group=group_name)
                db.add(profile)
            else:
                for p in profiles:
                    p.static_group = group_name
            db.commit()
            
        await interaction.response.send_message(f"✅ Assigned {member.mention} to **{group_name}** across all their builds.", ephemeral=True)

    @static_group.command(name="remove", description="Remove a user from their Static Party")
    @app_commands.default_permissions(manage_guild=True)
    async def static_remove(self, interaction: discord.Interaction, member: discord.Member):
        with next(get_db()) as db:
            profiles = db.query(UserProfile).filter_by(discord_id=member.id).all()
            if profiles:
                for p in profiles:
                    p.static_group = None
                db.commit()
                await interaction.response.send_message(f"✅ Removed {member.mention} from their static group.", ephemeral=True)
            else:
                await interaction.response.send_message(f"⚠️ {member.mention} does not have any profile records initialized.", ephemeral=True)

    @static_group.command(name="list", description="View static rosters based on build target selection")
    @app_commands.choices(build_type=BUILD_CHOICES)
    @app_commands.describe(group_name="Optional filter for specific group name", build_type="Filter by PvE, PvP, or PvX (Defaults to PvE)")
    async def static_list(self, interaction: discord.Interaction, group_name: str = None, build_type: str = "PvE"):
        await interaction.response.defer(ephemeral=False)

        with next(get_db()) as db:
            query = db.query(UserProfile).filter(UserProfile.static_group != None, UserProfile.build_type == build_type)
            if group_name:
                query = query.filter(UserProfile.static_group == group_name)
            profiles = query.all()

        if not profiles:
            msg = f"📭 No members found with an active **{build_type}** build configuration in group selection."
            await interaction.followup.send(msg)
            return

        statics_dict = {}
        for p in profiles:
            if p.static_group not in statics_dict:
                statics_dict[p.static_group] = []
            statics_dict[p.static_group].append(p)

        embeds = []
        for static_name, members in statics_dict.items():
            members.sort(key=lambda x: x.gear_score, reverse=True)
            avg_gs = sum(m.gear_score for m in members) // len(members)
            
            lines = []
            for m in members:
                w1 = WEAPON_EMOJIS.get(m.primary_weapon, "")
                w2 = WEAPON_EMOJIS.get(m.secondary_weapon, "")
                lines.append(f"• <@{m.discord_id}> (`{m.ingame_name}`) - *{m.build_name}* [⭐ **{m.gear_score}** | {w1}{w2}]")
                
            desc = "\n".join(lines)
            if len(desc) > 4096: desc = desc[:4090] + "..."

            if build_type == "PvE":
                card_color = discord.Color.gold()
            elif build_type == "PvP":
                card_color = discord.Color.dark_red()
            else:
                card_color = discord.Color.green()

            embed = discord.Embed(
                title=f"🛡️ Static Party Layout: {static_name} ({build_type})",
                description=desc,
                color=card_color
            )
            embed.set_footer(text=f"Total Builds: {len(members)} | Average GS: {avg_gs}")
            embeds.append(embed)

        for i in range(0, len(embeds), 10):
            await interaction.followup.send(embeds=embeds[i:i+10])

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        with next(get_db()) as db:
            profiles = db.query(UserProfile).filter_by(discord_id=member.id).all()
            if profiles:
                for p in profiles:
                    db.delete(p)
                db.commit()
                print(f"🗑️ Automated Prune: Removed all build profiles for {member.display_name} ({member.id}) because they left the server.")

async def setup(bot: commands.Bot):
    await bot.add_cog(ProfileCog(bot))