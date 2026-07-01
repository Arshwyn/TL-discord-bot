import discord
from discord.ext import commands
from discord import app_commands
from database.db_setup import get_db
from database.models import UserProfile, BotConfig

WEAPON_EMOJIS = {
    "Greatsword": "🗡️", "Sword and Shield": "🛡️", "Dagger": "🔪", 
    "Crossbow": "🏹", "Longbow": "🏹", "Staff": "🪄", 
    "Wand and Tome": "📘", "Spear": "🔱", "Orb": "🔮", "Gauntlets": "🥊"
}
WEAPONS = list(WEAPON_EMOJIS.keys())

class GSModal(discord.ui.Modal, title="Final Step: Gear Score"):
    gs_input = discord.ui.TextInput(
        label="Current Gear Score",
        placeholder="e.g., 2500",
        required=True,
        max_length=5
    )

    def __init__(self, ign, primary, secondary, build_type):
        super().__init__()
        self.ign = ign
        self.primary = primary
        self.secondary = secondary
        self.build_type = build_type

    async def on_submit(self, interaction: discord.Interaction):
        try:
            gs = int(self.gs_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Gear Score must be a valid number. Please try again.", ephemeral=True)
            return

        with next(get_db()) as db:
            all_profiles = db.query(UserProfile).filter_by(discord_id=interaction.user.id).all()
            profile = db.query(UserProfile).filter_by(discord_id=interaction.user.id, build_name="Main Build").first()
            
            static_group = all_profiles[0].static_group if all_profiles else None

            if profile:
                profile.ingame_name = self.ign
                profile.primary_weapon = self.primary
                profile.secondary_weapon = self.secondary
                profile.build_type = self.build_type
                profile.gear_score = gs
            else:
                db.add(UserProfile(
                    discord_id=interaction.user.id,
                    build_name="Main Build",
                    build_type=self.build_type,
                    ingame_name=self.ign,
                    primary_weapon=self.primary,
                    secondary_weapon=self.secondary,
                    gear_score=gs,
                    static_group=static_group
                ))
            
            for p in all_profiles:
                p.ingame_name = self.ign
                
            db.commit()

        await interaction.response.send_message(
            f"🎉 **Verification Complete!**\n"
            f"👤 Name: `{self.ign}`\n"
            f"⚔️ Main Loadout: {self.primary} & {self.secondary}\n"
            f"⭐ Gear Score: {gs}\n\n"
            f"*(You can modify these stats later or add more sets using `/profile update` or `/profile setup`)*", 
            ephemeral=True
        )

class ProfileSetupView(discord.ui.View):
    def __init__(self, ign: str):
        super().__init__(timeout=600)
        self.ign = ign
        self.primary = None
        self.secondary = None
        self.build_type = None

    @discord.ui.select(placeholder="Select Primary Weapon...", options=[discord.SelectOption(label=w, emoji=WEAPON_EMOJIS[w]) for w in WEAPONS], row=0)
    async def select_primary(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.primary = select.values[0]
        await interaction.response.defer()

    @discord.ui.select(placeholder="Select Secondary Weapon...", options=[discord.SelectOption(label=w, emoji=WEAPON_EMOJIS[w]) for w in WEAPONS], row=1)
    async def select_secondary(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.secondary = select.values[0]
        await interaction.response.defer()

    @discord.ui.select(
        placeholder="Select Build Focus...", 
        options=[
            discord.SelectOption(label="PvE Content", value="PvE"), 
            discord.SelectOption(label="PvP Content", value="PvP"),
            discord.SelectOption(label="PvX (Both)", value="PvX")
        ], 
        row=2
    )
    async def select_type(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.build_type = select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="Complete Setup (Enter Gear Score)", style=discord.ButtonStyle.success, row=3)
    async def complete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.primary or not self.secondary or not self.build_type:
            await interaction.response.send_message("⚠️ Please make sure you have selected your Primary Weapon, Secondary Weapon, and Build Focus!", ephemeral=True)
            return
        await interaction.response.send_modal(GSModal(self.ign, self.primary, self.secondary, self.build_type))

class RoleSelectView(discord.ui.View):
    def __init__(self, ign: str):
        super().__init__(timeout=300)
        self.ign = ign

    @discord.ui.select(
        placeholder="Select your primary guild role...",
        options=[
            discord.SelectOption(label="Tank", description="Frontline mitigation and aggro", emoji="🛡️"),
            discord.SelectOption(label="DPS", description="Damage dealer", emoji="⚔️"),
            discord.SelectOption(label="Support", description="Healer or buffer", emoji="🪄"),
            discord.SelectOption(label="Associate", description="Social/Alliance Members", emoji="👋")
        ]
    )
    async def select_role(self, interaction: discord.Interaction, select: discord.ui.Select):
        role_choice = select.values[0].lower()
        
        with next(get_db()) as db:
            cfg_role = db.query(BotConfig).filter_by(setting_key=f"role_{role_choice}").first()
            cfg_unverified = db.query(BotConfig).filter_by(setting_key="role_unverified").first()
            cfg_member = db.query(BotConfig).filter_by(setting_key="role_member").first()
            
        role_id = int(cfg_role.setting_value) if cfg_role and cfg_role.setting_value else None
        unverified_id = int(cfg_unverified.setting_value) if cfg_unverified and cfg_unverified.setting_value else None
        member_id = int(cfg_member.setting_value) if cfg_member and cfg_member.setting_value else None
        
        try:
            await interaction.user.edit(nick=self.ign[:32])
            
            roles_to_add = []
            if role_id:
                target_role = interaction.guild.get_role(role_id)
                if target_role:
                    roles_to_add.append(target_role)
            
            if role_choice in ["tank", "dps", "support"] and member_id:
                member_role_obj = interaction.guild.get_role(member_id)
                if member_role_obj:
                    roles_to_add.append(member_role_obj)
            
            if roles_to_add:
                await interaction.user.add_roles(*roles_to_add)
            
            if unverified_id:
                unv_role = interaction.guild.get_role(unverified_id)
                if unv_role and unv_role in interaction.user.roles:
                    await interaction.user.remove_roles(unv_role)
                    
        except discord.Forbidden:
            pass 
        
        if role_choice == "associate":
            await interaction.response.send_message(f"✅ Welcome {self.ign}! Your Associate role has been applied. You are fully verified.", ephemeral=True)
        else:
            view = ProfileSetupView(self.ign)
            await interaction.response.send_message(
                f"✅ Verification partial! Roles applied.\n\nNow, let's configure your **MAIN** {role_choice.upper()} build for the guild directory:", 
                view=view, 
                ephemeral=True
            )

class IGNModal(discord.ui.Modal, title="Server Verification"):
    ign_input = discord.ui.TextInput(
        label="Exact In-Game Name (IGN)",
        placeholder="Type your character name here...",
        required=True,
        max_length=32
    )

    async def on_submit(self, interaction: discord.Interaction):
        ign = self.ign_input.value.strip()
        view = RoleSelectView(ign)
        await interaction.response.send_message(
            f"Hello **{ign}**! Please select your server role below:", 
            view=view, 
            ephemeral=True
        )

class OnboardingStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify & Setup Profile", emoji="📜", style=discord.ButtonStyle.primary, custom_id="persistent_onboarding_btn")
    async def verify_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(IGNModal())

class OnboardingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(OnboardingStartView()) 

    @app_commands.command(name="set_onboarding_roles", description="Configure the roles used for server onboarding")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        member_role="Optional: Base member role added to Tank/DPS/Support",
        unverified_role="Optional: A 'Guest' role that the bot will remove when they verify"
    )
    async def set_onboarding_roles(
        self, interaction: discord.Interaction, 
        tank_role: discord.Role, dps_role: discord.Role, support_role: discord.Role, 
        associate_role: discord.Role, member_role: discord.Role = None, unverified_role: discord.Role = None
    ):
        with next(get_db()) as db:
            def set_cfg(k, v):
                cfg = db.query(BotConfig).filter_by(setting_key=k).first()
                if cfg:
                    cfg.setting_value = str(v)
                else:
                    db.add(BotConfig(setting_key=k, setting_value=str(v)))
            
            set_cfg("role_tank", tank_role.id)
            set_cfg("role_dps", dps_role.id)
            set_cfg("role_support", support_role.id)
            set_cfg("role_associate", associate_role.id)
            
            if member_role:
                set_cfg("role_member", member_role.id)
            else:
                mr = db.query(BotConfig).filter_by(setting_key="role_member").first()
                if mr: db.delete(mr)
                
            if unverified_role:
                set_cfg("role_unverified", unverified_role.id)
            else:
                unv = db.query(BotConfig).filter_by(setting_key="role_unverified").first()
                if unv: db.delete(unv)
            
            db.commit()
        await interaction.response.send_message("✅ Onboarding roles successfully mapped in the database!", ephemeral=True)

    # 🟢 NEW: View configured onboarding roles
    @app_commands.command(name="view_onboarding_roles", description="View the current roles mapped for onboarding")
    @app_commands.default_permissions(manage_guild=True)
    async def view_onboarding_roles(self, interaction: discord.Interaction):
        keys = ["role_tank", "role_dps", "role_support", "role_associate", "role_member", "role_unverified"]
        lines = []
        with next(get_db()) as db:
            for k in keys:
                cfg = db.query(BotConfig).filter_by(setting_key=k).first()
                if cfg and cfg.setting_value:
                    lines.append(f"**{k.replace('role_', '').capitalize()}**: <@&{cfg.setting_value}>")
                else:
                    lines.append(f"**{k.replace('role_', '').capitalize()}**: *Not Set*")
        
        embed = discord.Embed(title="⚙️ Onboarding Role Configuration", description="\n".join(lines), color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # 🟢 NEW: Delete configured onboarding roles
    @app_commands.command(name="delete_onboarding_roles", description="Clear all mapped onboarding roles")
    @app_commands.default_permissions(manage_guild=True)
    async def delete_onboarding_roles(self, interaction: discord.Interaction):
        keys = ["role_tank", "role_dps", "role_support", "role_associate", "role_member", "role_unverified"]
        with next(get_db()) as db:
            deleted = 0
            for k in keys:
                cfg = db.query(BotConfig).filter_by(setting_key=k).first()
                if cfg:
                    db.delete(cfg)
                    deleted += 1
            if deleted > 0:
                db.commit()
        await interaction.response.send_message("🗑️ **Onboarding roles cleared!** Make sure to run `/set_onboarding_roles` again before users verify.", ephemeral=True)

    @app_commands.command(name="spawn_onboarding", description="Spawn the persistent onboarding button in this channel")
    @app_commands.default_permissions(manage_guild=True)
    async def spawn_onboarding(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🛡️ Guild Verification & Onboarding",
            description="Welcome! To gain full access to the server and set up your character profile, click the button below.\n\n"
                        "**Steps:**\n"
                        "1. Enter your exact **In-Game Name (IGN)**.\n"
                        "2. Select your desired guild role (Tank, DPS, Support, or Associate).\n"
                        "3. Configure your **main** build weapons and gear score.",
            color=discord.Color.blue()
        )
        await interaction.channel.send(embed=embed, view=OnboardingStartView())
        await interaction.response.send_message("✅ Onboarding panel spawned.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(OnboardingCog(bot))