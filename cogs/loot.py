import discord
from discord.ext import commands, tasks
from discord import app_commands
import random
from datetime import datetime, timezone, timedelta

from database.db_setup import get_db
from database.models import LootItem, LootRoll, UserProfile, BotConfig

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

    # 🎲 THE NEW AUTO-ROLL & REROLL ENGINE
    @discord.ui.button(label="Auto Roll Winner", emoji="🎲", style=discord.ButtonStyle.danger, custom_id="pl_auto_roll", row=1)
    async def btn_auto_roll(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ **Permission Denied:** Only guild officers can trigger the loot roll.", ephemeral=True)
            return

        await interaction.response.defer()

        with next(get_db()) as db:
            item = db.query(LootItem).filter_by(message_id=interaction.message.id).first()
            if not item:
                await interaction.followup.send("❌ This loot item could not be found in the database.", ephemeral=True)
                return
            
            # 1. REROLL REFUND SEQUENCE
            is_reroll = False
            if item.winner_id:
                is_reroll = True
                old_winner = db.query(UserProfile).filter_by(discord_id=item.winner_id).first()
                # Refund their penalty
                if old_winner and old_winner.loot_wins > 0:
                    old_winner.loot_wins -= 1
                
                # Delete the old winner from the item's roll list completely so they don't win the reroll
                old_roll = db.query(LootRoll).filter_by(loot_item_id=item.id, discord_id=item.winner_id).first()
                if old_roll:
                    db.delete(old_roll)
                    
                db.commit() # Save the refund

            # 2. PULL REMAINING ELIGIBLE ROLLS
            all_rolls = db.query(LootRoll).filter_by(loot_item_id=item.id).all()
            rolls_dict = {"need": [], "alt_want": [], "greed": []}
            for r in all_rolls:
                if r.roll_type in rolls_dict:
                    rolls_dict[r.roll_type].append(r.discord_id)

            winner_id = None
            winning_category = ""
            
            # 3. WEIGHTED PROBABILITY ENGINE
            def pick_weighted_winner(candidates):
                if len(candidates) == 1:
                    return candidates[0] 
                
                weights = []
                for uid in candidates:
                    prof = db.query(UserProfile).filter_by(discord_id=uid).first()
                    wins = prof.loot_wins if prof else 0
                    
                    if wins == 0: weights.append(1.0)
                    elif wins == 1: weights.append(0.5)
                    else: weights.append(0.0)
                
                if sum(weights) == 0:
                    weights = [1.0] * len(candidates)
                    
                return random.choices(candidates, weights=weights, k=1)[0]

            # 4. WATERFALL SELECTION
            if rolls_dict["need"]:
                winner_id = pick_weighted_winner(rolls_dict["need"])
                winning_category = "Need 🟢"
            elif rolls_dict["alt_want"]:
                winner_id = pick_weighted_winner(rolls_dict["alt_want"])
                winning_category = "Alt / Want 🔵"
            elif rolls_dict["greed"]:
                winner_id = pick_weighted_winner(rolls_dict["greed"])
                winning_category = "Greed 🟡"

            # 5. LOCK ITEM AND PENALIZE NEW WINNER
            saved_item_name = item.item_name
            item.is_closed = True
            item.winner_id = winner_id

            if winner_id:
                prof = db.query(UserProfile).filter_by(discord_id=winner_id).first()
                if prof:
                    prof.loot_wins += 1
                else:
                    new_prof = UserProfile(discord_id=winner_id, ingame_name=f"User {winner_id}", loot_wins=1)
                    db.add(new_prof)
            db.commit()

        # 6. UPDATE UI FRAME (Grey out player buttons, keep Reroll button alive!)
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.dark_grey() 
        
        prefix = "🔁 **REROLL Winner:**" if is_reroll else "🎉 **Winner:**"

        if winner_id:
            embed.description = f"{prefix} <@{winner_id}> (Rolled: **{winning_category}**)"
        else:
            embed.description = "🛑 **Closed:** Nobody rolled for this item."

        for child in self.children:
            if child.custom_id != "pl_auto_roll":
                child.disabled = True
            else:
                child.label = "Reroll Item"
                child.emoji = "🔁"
                child.style = discord.ButtonStyle.primary

        await interaction.message.edit(embed=embed, view=self)
        
        # 7. SEND CHANNEL ANNOUNCEMENT
        announcement = f"🔁 The **REROLL** for **{saved_item_name}**" if is_reroll else f"🎲 The roll for **{saved_item_name}**"
        
        if winner_id:
            await interaction.channel.send(f"{announcement} has concluded! Congratulations <@{winner_id}> ({winning_category})! 🎉")
        else:
            await interaction.channel.send(f"🛑 {announcement} was closed with no participants.")


class LootCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(PersistentLootView())
        self.cleanup_loot_loop.start()
        self.auto_reset_priority_loop.start() 
        
    def cog_unload(self):
        self.cleanup_loot_loop.cancel()
        self.auto_reset_priority_loop.cancel()
        
    loot_group = app_commands.Group(name="loot", description="Manage guild loot distribution")

    @loot_group.command(name="distribute", description="Create a permanent loot distribution poll for an item")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(item_name="The name of the item", image="Optional screenshot")
    async def distribute(self, interaction: discord.Interaction, item_name: str, image: discord.Attachment = None):
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        with next(get_db()) as db:
            new_item = LootItem(
                item_name=item_name,
                image_url=image.url if image else None, 
                channel_id=interaction.channel.id,
                is_closed=False,
                created_at=now_utc
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

    @loot_group.command(name="priority_check", description="Check a member's current loot win penalty")
    async def priority_check(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        with next(get_db()) as db:
            prof = db.query(UserProfile).filter_by(discord_id=target.id).first()
            wins = prof.loot_wins if prof else 0
            
        weight = 100 if wins == 0 else (50 if wins == 1 else 0)
        await interaction.response.send_message(f"👤 {target.mention} has won **{wins}** items recently.\n🎲 Current roll weight: **{weight}%**", ephemeral=True)

    @loot_group.command(name="priority_reset", description="Reset loot penalties to 100% (Provide no member to reset the whole guild)")
    @app_commands.default_permissions(manage_guild=True)
    async def priority_reset(self, interaction: discord.Interaction, member: discord.Member = None):
        with next(get_db()) as db:
            if member:
                prof = db.query(UserProfile).filter_by(discord_id=member.id).first()
                if prof: prof.loot_wins = 0
                msg = f"✅ Reset loot priority for {member.mention} back to 100%."
            else:
                db.query(UserProfile).update({UserProfile.loot_wins: 0})
                now_unix = int(datetime.now(timezone.utc).timestamp())
                fourteen_days = 14 * 24 * 60 * 60
                cfg = db.query(BotConfig).filter_by(setting_key="next_loot_reset").first()
                if cfg:
                    cfg.setting_value = str(now_unix + fourteen_days)
                else:
                    db.add(BotConfig(setting_key="next_loot_reset", setting_value=str(now_unix + fourteen_days)))
                msg = "✅ Reset loot priority for **ALL guild members** back to 100%.\n*(The 14-day automatic reset timer has been aligned to start from right now.)*"
            db.commit()
        await interaction.response.send_message(msg, ephemeral=True)

    @tasks.loop(hours=24)
    async def cleanup_loot_loop(self):
        await self.bot.wait_until_ready()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cutoff_date = now - timedelta(days=30)
        
        with next(get_db()) as db:
            old_items = db.query(LootItem).filter(
                LootItem.is_closed == True,
                LootItem.created_at <= cutoff_date
            ).all()
            for item in old_items: db.delete(item)
            if old_items:
                db.commit()
                print(f"🧹 Database Cleanup: Purged {len(old_items)} old loot distributions.")

    @tasks.loop(hours=12)
    async def auto_reset_priority_loop(self):
        await self.bot.wait_until_ready()
        now_unix = int(datetime.now(timezone.utc).timestamp())
        fourteen_days = 14 * 24 * 60 * 60

        with next(get_db()) as db:
            cfg = db.query(BotConfig).filter_by(setting_key="next_loot_reset").first()
            if not cfg:
                db.add(BotConfig(setting_key="next_loot_reset", setting_value=str(now_unix + fourteen_days)))
                db.commit()
                return
            
            target_time = int(cfg.setting_value)
            if now_unix >= target_time:
                db.query(UserProfile).update({UserProfile.loot_wins: 0})
                cfg.setting_value = str(now_unix + fourteen_days)
                db.commit()
                print("🔄 Automated Bi-Weekly Loot Priority Reset executed successfully.")

async def setup(bot: commands.Bot):
    await bot.add_cog(LootCog(bot))