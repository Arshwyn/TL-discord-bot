import discord
from discord.ext import commands, tasks
from discord import app_commands
import random
from datetime import datetime, timezone, timedelta

from database.db_setup import get_db
from database.models import LootItem, LootRoll

class PersistentLootView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def handle_roll(self, interaction: discord.Interaction, roll_type: str | None):
        await interaction.response.defer(ephemeral=True)
        
        with next(get_db()) as db:
            item = db.query(LootItem).filter_by(message_id=interaction.message.id).first()
            if not item or item.is_closed:
                await interaction.followup.send("❌ This loot roll is closed and locked.", ephemeral=True)
                return

            existing_roll = db.query(LootRoll).filter_by(loot_item_id=item.id, discord_id=interaction.user.id).first()

            if roll_type is None:
                if existing_roll:
                    db.delete(existing_roll)
                    msg = "🧹 Your roll has been cleared."
                else:
                    msg = "⚠️ You haven't rolled on this item yet."
            else:
                if existing_roll:
                    existing_roll.roll_type = roll_type
                else:
                    new_roll = LootRoll(loot_item_id=item.id, discord_id=interaction.user.id, roll_type=roll_type)
                    db.add(new_roll)
                
                display_name = "Alt / Want" if roll_type == "alt_want" else roll_type.capitalize()
                msg = f"✅ Roll registered as **{display_name}**."

            db.commit()

            all_rolls = db.query(LootRoll).filter_by(loot_item_id=item.id).all()

        rolls_dict = {"need": [], "alt_want": [], "greed": []}
        for r in all_rolls:
            if r.roll_type in rolls_dict:
                rolls_dict[r.roll_type].append(f"<@{r.discord_id}>")

        def safe_join(lst):
            res = "\n".join(lst) if lst else "*None*"
            return res[:1000] + "\n...*(Too many)*" if len(res) > 1024 else res

        embed = interaction.message.embeds[0]
        embed.set_field_at(0, name=f"🟢 Need ({len(rolls_dict['need'])})", value=safe_join(rolls_dict['need']), inline=True)
        embed.set_field_at(1, name=f"🔵 Alt / Want ({len(rolls_dict['alt_want'])})", value=safe_join(rolls_dict['alt_want']), inline=True)
        embed.set_field_at(2, name=f"🟡 Greed ({len(rolls_dict['greed'])})", value=safe_join(rolls_dict['greed']), inline=True)

        await interaction.message.edit(embed=embed, view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="Need", emoji="🟢", style=discord.ButtonStyle.success, custom_id="pl_need", row=0)
    async def btn_need(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_roll(interaction, "need")

    @discord.ui.button(label="Alt / Want", emoji="🔵", style=discord.ButtonStyle.primary, custom_id="pl_alt_want", row=0)
    async def btn_alt_want(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_roll(interaction, "alt_want")

    @discord.ui.button(label="Greed", emoji="🟡", style=discord.ButtonStyle.secondary, custom_id="pl_greed", row=0)
    async def btn_greed(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_roll(interaction, "greed")

    @discord.ui.button(label="Clear Roll", emoji="❌", style=discord.ButtonStyle.danger, custom_id="pl_clear", row=0)
    async def btn_clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_roll(interaction, None)

    @discord.ui.button(label="Auto Roll Winner", emoji="🎲", style=discord.ButtonStyle.danger, custom_id="pl_auto_roll", row=1)
    async def btn_auto_roll(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ **Permission Denied:** Only guild officers can trigger the loot roll.", ephemeral=True)
            return

        await interaction.response.defer()

        with next(get_db()) as db:
            item = db.query(LootItem).filter_by(message_id=interaction.message.id).first()
            if not item or item.is_closed:
                await interaction.followup.send("❌ This loot roll is already closed.", ephemeral=True)
                return
            
            all_rolls = db.query(LootRoll).filter_by(loot_item_id=item.id).all()
            
            rolls_dict = {"need": [], "alt_want": [], "greed": []}
            for r in all_rolls:
                if r.roll_type in rolls_dict:
                    rolls_dict[r.roll_type].append(r.discord_id)

            winner_id = None
            winning_category = ""
            
            if rolls_dict["need"]:
                winner_id = random.choice(rolls_dict["need"])
                winning_category = "Need 🟢"
            elif rolls_dict["alt_want"]:
                winner_id = random.choice(rolls_dict["alt_want"])
                winning_category = "Alt / Want 🔵"
            elif rolls_dict["greed"]:
                winner_id = random.choice(rolls_dict["greed"])
                winning_category = "Greed 🟡"

            saved_item_name = item.item_name
            item.is_closed = True
            db.commit()

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.dark_grey() 
        
        if winner_id:
            embed.description = f"🎉 **Winner:** <@{winner_id}> (Rolled: **{winning_category}**)"
        else:
            embed.description = "🛑 **Closed:** Nobody rolled for this item."

        for child in self.children:
            child.disabled = True

        await interaction.message.edit(embed=embed, view=self)
        
        if winner_id:
            await interaction.channel.send(f"🎲 The roll for **{saved_item_name}** has concluded! Congratulations <@{winner_id}> ({winning_category})! 🎉")
        else:
            await interaction.channel.send(f"🛑 The roll for **{saved_item_name}** was closed with no participants.")


class LootCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(PersistentLootView())
        self.cleanup_loot_loop.start() # Start the cleanup loop!
        
    def cog_unload(self):
        self.cleanup_loot_loop.cancel()
        
    loot_group = app_commands.Group(name="loot", description="Manage guild loot distribution")

    @loot_group.command(name="distribute", description="Create a permanent loot distribution poll for an item")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(item_name="The name of the item", image="Optional screenshot")
    async def distribute(self, interaction: discord.Interaction, item_name: str, image: discord.Attachment = None):
        
        # Calculate naive UTC time matching our database standard
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        with next(get_db()) as db:
            new_item = LootItem(
                item_name=item_name,
                image_url=image.url if image else None, 
                channel_id=interaction.channel.id,
                is_closed=False,
                created_at=now_utc # NEW: Log the exact creation time!
            )
            db.add(new_item)
            db.commit()
            item_db_id = new_item.id 

        embed = discord.Embed(
            title=f"🎁 Loot Roll: {item_name}",
            description="Click the buttons below to log your roll in the database.",
            color=discord.Color.gold()
        )
        if image:
            embed.set_image(url=image.url)
            
        embed.add_field(name="🟢 Need (0)", value="*None*", inline=True)
        embed.add_field(name="🔵 Alt / Want (0)", value="*None*", inline=True)
        embed.add_field(name="🟡 Greed (0)", value="*None*", inline=True)
        
        embed.set_footer(text=f"Item ID: {item_db_id} | Posted by {interaction.user.display_name}")
        
        view = PersistentLootView()
        
        await interaction.response.send_message(embed=embed, view=view)
        message = await interaction.original_response()

        with next(get_db()) as db:
            item = db.query(LootItem).filter_by(id=item_db_id).first()
            if item:
                item.message_id = message.id
                db.commit()

    # ==========================================
    # AUTOMATED GARBAGE COLLECTION
    # ==========================================
    @tasks.loop(hours=24)
    async def cleanup_loot_loop(self):
        """Wakes up once a day to silently purge closed loot items older than 30 days from the SQLite DB"""
        await self.bot.wait_until_ready()
        
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cutoff_date = now - timedelta(days=30)
        
        with next(get_db()) as db:
            # Query for items that are closed AND older than our 30 day cutoff
            old_items = db.query(LootItem).filter(
                LootItem.is_closed == True,
                LootItem.created_at <= cutoff_date
            ).all()
            
            for item in old_items:
                db.delete(item)
            
            if old_items:
                db.commit()
                print(f"🧹 Database Cleanup: Purged {len(old_items)} old loot distributions.")

async def setup(bot: commands.Bot):
    await bot.add_cog(LootCog(bot))