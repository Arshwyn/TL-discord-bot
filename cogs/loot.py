import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import random
from datetime import datetime, timezone, timedelta
from sqlalchemy import func

from database.db_setup import get_db
from database.models import LootItem, LootRoll, UserProfile, BotConfig

ROLL_LABELS = {"need": "Need", "alt_want": "Alt / Want", "greed": "Greed"}
EPHEMERAL_TOAST_DELAY = 5.0


def auto_dismiss(message: discord.Message, delay: float = EPHEMERAL_TOAST_DELAY):
    """Fire-and-forget delete of a short-lived ephemeral confirmation toast."""
    async def _dismiss():
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except discord.HTTPException:
            pass
    asyncio.create_task(_dismiss())


def resolve_display_name(db, interaction: discord.Interaction, discord_id: int) -> str:
    """Resolve a roller's card name: profile ingame_name -> server nickname -> username."""
    profile = db.query(UserProfile).filter_by(discord_id=discord_id).first()
    if profile:
        return profile.ingame_name

    member = interaction.guild.get_member(discord_id) if interaction.guild else None
    if member:
        return member.display_name

    user = interaction.client.get_user(discord_id)
    if user:
        return user.name

    return "Unknown User"


def build_rolls_dict(db, interaction: discord.Interaction, all_rolls) -> dict:
    rolls_dict = {"need": [], "alt_want": [], "greed": []}
    for r in all_rolls:
        if r.roll_type in rolls_dict:
            rolls_dict[r.roll_type].append(resolve_display_name(db, interaction, r.discord_id))
    return rolls_dict


def safe_join(lst):
    res = "\n".join(lst) if lst else "*None*"
    return res[:1000] + "\n...*(Too many)*" if len(res) > 1024 else res


def apply_rolls_to_embed(embed: discord.Embed, rolls_dict: dict):
    embed.set_field_at(0, name=f"🟢 Need ({len(rolls_dict['need'])})", value=safe_join(rolls_dict['need']), inline=True)
    embed.set_field_at(1, name=f"🔵 Alt / Want ({len(rolls_dict['alt_want'])})", value=safe_join(rolls_dict['alt_want']), inline=True)
    embed.set_field_at(2, name=f"🟡 Greed ({len(rolls_dict['greed'])})", value=safe_join(rolls_dict['greed']), inline=True)


async def fetch_channel_safe(bot, channel_id: int | None):
    if not channel_id:
        return None
    channel = bot.get_channel(channel_id)
    if channel is not None:
        return channel
    try:
        return await bot.fetch_channel(channel_id)
    except discord.HTTPException:
        return None


def build_card_view(is_closed: bool, thread_id: int | None = None, guild_id: int | None = None) -> "PersistentLootView":
    """A fresh main-card view with the voting + roll buttons enabled/disabled to match the item's state.

    Once a management thread exists, Manage Roll is swapped from an interactive button into a direct
    link button pointing at that thread — clicking it is then pure client-side navigation with no
    round-trip to the bot at all, so every officer lands straight in the thread with one click.
    (Only holds within this process's lifetime: a persistent view registered via bot.add_view() can't
    vary per-message, so after a restart the button reverts to interactive until clicked once more,
    which re-discovers the thread and swaps it back to a link.)"""
    view = PersistentLootView()
    for child in view.children:
        if child.custom_id in ("pl_need", "pl_alt_want", "pl_greed", "pl_clear", "pl_auto_roll"):
            child.disabled = is_closed

    if thread_id and guild_id:
        for child in list(view.children):
            if getattr(child, "custom_id", None) == "pl_manage":
                view.remove_item(child)
                view.add_item(discord.ui.Button(
                    label="Manage Roll", emoji="🛠️", style=discord.ButtonStyle.link,
                    url=f"https://discord.com/channels/{guild_id}/{thread_id}", row=1
                ))
                break
    return view


def sync_manage_view_state(view: "ManageThreadView", is_closed: bool):
    """Flip the officer thread panel's buttons to match the item's open/closed state. Reassign only
    makes sense pre-close. The roll button is always clickable from the thread too (not just the main
    card) so an officer already in there — say, after Reassigning — never has to leave to conclude it;
    it just relabels itself Auto Roll Winner / Reroll Item like the main card's button does. Re-Open
    only makes sense once there's something closed to reopen."""
    for child in view.children:
        if child.custom_id == "mt_reassign":
            child.disabled = is_closed
        elif child.custom_id == "mt_roll":
            child.label = "Reroll Item" if is_closed else "Auto Roll Winner"
            child.emoji = "🔁" if is_closed else "🎲"
            child.style = discord.ButtonStyle.primary if is_closed else discord.ButtonStyle.danger
        elif child.custom_id == "mt_reopen":
            child.disabled = not is_closed


def render_status(embed: discord.Embed, status: str, winner_id: int | None, winning_category: str, thread_link: str):
    if status == "won":
        embed.color = discord.Color.dark_grey()
        embed.description = f"✅ **Won by** <@{winner_id}> *(Rolled {winning_category})*{thread_link}"
    elif status == "empty":
        embed.color = discord.Color.dark_grey()
        embed.description = f"🛑 **Closed:** Nobody rolled for this item.{thread_link}"
    elif status == "reopened":
        embed.color = discord.Color.gold()
        embed.description = f"Click the buttons below to log your roll in the database.{thread_link}"


async def sync_main_card(bot: commands.Bot, interaction: discord.Interaction, item: LootItem, status: str, winner_id: int | None = None, winning_category: str = ""):
    """Refresh the main channel card's tally + status from a thread-hosted action. status: 'won' | 'empty' | 'reopened'."""
    channel = await fetch_channel_safe(bot, item.channel_id)
    if channel is None or not item.message_id:
        return

    try:
        message = await channel.fetch_message(item.message_id)
    except discord.HTTPException:
        return

    if not message.embeds:
        return

    embed = message.embeds[0]
    with next(get_db()) as db:
        all_rolls = db.query(LootRoll).filter_by(loot_item_id=item.id).all()
        rolls_dict = build_rolls_dict(db, interaction, all_rolls)
    apply_rolls_to_embed(embed, rolls_dict)

    thread_link = f"\n🧵 [Manage this roll](https://discord.com/channels/{message.guild.id}/{item.thread_id})" if item.thread_id else ""
    render_status(embed, status, winner_id, winning_category, thread_link)

    try:
        await message.edit(embed=embed, view=build_card_view(item.is_closed, thread_id=item.thread_id, guild_id=message.guild.id))
    except discord.HTTPException:
        pass


async def sync_thread_panel(bot: commands.Bot, item: LootItem, is_closed: bool):
    """Reflect an is_closed change (made from the main card) onto an already-existing thread panel, if any."""
    if not item.thread_id or not item.manage_message_id:
        return

    thread = await fetch_channel_safe(bot, item.thread_id)
    if thread is None:
        return

    try:
        panel_message = await thread.fetch_message(item.manage_message_id)
    except discord.HTTPException:
        return

    panel_view = ManageThreadView()
    sync_manage_view_state(panel_view, is_closed)
    try:
        await panel_message.edit(view=panel_view)
    except discord.HTTPException:
        pass


# 🟢 Private, per-click Officer Reassign Menu (ephemeral, never persistent — see note on ManageThreadView
# for why the select-a-user-then-act flow can't be a shared/persistent view).
class OfficerManageView(discord.ui.View):
    def __init__(self, item_id: int, original_message: discord.Message, parent_view: discord.ui.View):
        super().__init__(timeout=300)
        self.item_id = item_id
        self.original_message = original_message
        self.parent_view = parent_view
        self.selected_user = None

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="1. Select a member to modify...", row=0)
    async def select_user(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.selected_user = select.values[0]
        await interaction.response.send_message(f"✅ Selected {self.selected_user.mention}. Now click an action button below.", ephemeral=True)
        auto_dismiss(await interaction.original_response())

    async def force_roll(self, interaction: discord.Interaction, roll_type: str | None):
        if not self.selected_user:
            await interaction.response.send_message("⚠️ Please select a user first from the dropdown menu above.", ephemeral=True)
            auto_dismiss(await interaction.original_response())
            return

        await interaction.response.defer(ephemeral=True)
        with next(get_db()) as db:
            item = db.query(LootItem).filter_by(id=self.item_id).first()
            if not item or item.is_closed:
                auto_dismiss(await interaction.followup.send("❌ This loot roll is closed.", ephemeral=True))
                return

            existing_roll = db.query(LootRoll).filter_by(loot_item_id=item.id, discord_id=self.selected_user.id).first()
            if roll_type is None:
                if existing_roll:
                    db.delete(existing_roll)
            else:
                if existing_roll:
                    existing_roll.roll_type = roll_type
                else:
                    db.add(LootRoll(loot_item_id=item.id, discord_id=self.selected_user.id, roll_type=roll_type))
            db.commit()

            all_rolls = db.query(LootRoll).filter_by(loot_item_id=item.id).all()
            rolls_dict = build_rolls_dict(db, interaction, all_rolls)

        # Overwrite the original card with the new forced data
        embed = self.original_message.embeds[0]
        apply_rolls_to_embed(embed, rolls_dict)

        await self.original_message.edit(embed=embed, view=self.parent_view)

        action_text = "removed from the roll" if roll_type is None else f"forced to roll **{roll_type.capitalize()}**"
        toast = await interaction.followup.send(f"✅ **Success!** {self.selected_user.mention} was {action_text}.", ephemeral=True)
        auto_dismiss(toast)

    @discord.ui.button(label="Force Need", emoji="🟢", style=discord.ButtonStyle.success, row=1)
    async def f_need(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.force_roll(interaction, "need")

    @discord.ui.button(label="Force Alt/Want", emoji="🔵", style=discord.ButtonStyle.primary, row=1)
    async def f_alt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.force_roll(interaction, "alt_want")

    @discord.ui.button(label="Force Greed", emoji="🟡", style=discord.ButtonStyle.secondary, row=1)
    async def f_greed(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.force_roll(interaction, "greed")

    @discord.ui.button(label="Remove Player", emoji="❌", style=discord.ButtonStyle.danger, row=1)
    async def f_remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.force_roll(interaction, None)


class PersistentLootView(discord.ui.View):
    """Lives on the main channel card. Just Need/Alt/Greed/Clear voting, plus the entry point into
    officer management. Rolling/reassigning/reopening all happen in a lazily-created thread instead,
    so a normal item that never needs manual intervention never spawns one."""

    def __init__(self):
        super().__init__(timeout=None)

    async def handle_roll(self, interaction: discord.Interaction, roll_type: str | None):
        await interaction.response.defer(ephemeral=True)

        with next(get_db()) as db:
            item = db.query(LootItem).filter_by(message_id=interaction.message.id).first()
            if not item or item.is_closed:
                auto_dismiss(await interaction.followup.send("❌ This loot roll is closed and locked.", ephemeral=True))
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

                display_name = ROLL_LABELS[roll_type]
                msg = f"✅ Roll registered as **{display_name}**."

            db.commit()
            all_rolls = db.query(LootRoll).filter_by(loot_item_id=item.id).all()
            rolls_dict = build_rolls_dict(db, interaction, all_rolls)
            thread_id = item.thread_id

        embed = interaction.message.embeds[0]
        apply_rolls_to_embed(embed, rolls_dict)

        # Rebuild fresh rather than reusing `self` — after a bot restart, `self` may be the generic
        # fallback view (unaware of this item's thread), so always re-derive from the DB instead.
        guild_id = interaction.guild.id if interaction.guild else None
        view = build_card_view(is_closed=False, thread_id=thread_id, guild_id=guild_id)
        await interaction.message.edit(embed=embed, view=view)
        toast = await interaction.followup.send(msg, ephemeral=True)
        auto_dismiss(toast)

    @discord.ui.button(label="Need", emoji="🟢", style=discord.ButtonStyle.success, custom_id="pl_need", row=0)
    async def btn_need(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_roll(interaction, "need")

    @discord.ui.button(label="Alt / Want", emoji="🔵", style=discord.ButtonStyle.primary, custom_id="pl_alt_want", row=0)
    async def btn_alt_want(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_roll(interaction, "alt_want")

    @discord.ui.button(label="Greed", emoji="🟡", style=discord.ButtonStyle.secondary, custom_id="pl_greed", row=0)
    async def btn_greed(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_roll(interaction, "greed")

    @discord.ui.button(label="Clear Roll", emoji="❌", style=discord.ButtonStyle.secondary, custom_id="pl_clear", row=0)
    async def btn_clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_roll(interaction, None)

    # 🎲 THE AUTO-ROLL ENGINE — first-time roll only. Lives on the main card so an officer never needs
    # a thread just to conclude a normal item. Once closed, reroll/reassign/reopen move to the thread.
    @discord.ui.button(label="Auto Roll Winner", emoji="🎲", style=discord.ButtonStyle.danger, custom_id="pl_auto_roll", row=1)
    async def btn_auto_roll(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ **Permission Denied:** Only guild officers can trigger the loot roll.", ephemeral=True)
            auto_dismiss(await interaction.original_response())
            return

        await interaction.response.defer()
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        with next(get_db()) as db:
            item = db.query(LootItem).filter_by(message_id=interaction.message.id).first()
            if not item:
                auto_dismiss(await interaction.followup.send("❌ This loot item could not be found in the database.", ephemeral=True))
                return
            if item.is_closed:
                auto_dismiss(await interaction.followup.send("❌ This item was already rolled — use Reroll in its management thread instead.", ephemeral=True))
                return

            all_rolls = db.query(LootRoll).filter_by(loot_item_id=item.id).all()
            rolls_dict = {"need": [], "alt_want": [], "greed": []}
            for r in all_rolls:
                if r.roll_type in rolls_dict:
                    rolls_dict[r.roll_type].append(r.discord_id)

            winner_id = None
            winning_category = ""
            winner_penalized = False

            # WEIGHTED PROBABILITY ENGINE
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

            # WATERFALL SELECTION
            if rolls_dict["need"]:
                winner_id = pick_weighted_winner(rolls_dict["need"])
                winning_category = "Need 🟢"
                winner_penalized = True
            elif rolls_dict["alt_want"]:
                winner_id = pick_weighted_winner(rolls_dict["alt_want"])
                winning_category = "Alt / Want 🔵"
                winner_penalized = True
            elif rolls_dict["greed"]:
                winner_id = pick_weighted_winner(rolls_dict["greed"])
                winning_category = "Greed 🟡"
                # An uncontested greed roll (nobody else claimed need/alt-want/greed) isn't a real
                # contest, so the sole roller shouldn't have their priority docked for taking it.
                winner_penalized = len(rolls_dict["greed"]) > 1

            saved_item_id = item.id
            saved_item_name = item.item_name
            saved_thread_id = item.thread_id
            item.is_closed = True
            item.winner_id = winner_id
            item.winner_penalized = winner_penalized
            item.closed_at = now_utc

            if winner_id and winner_penalized:
                prof = db.query(UserProfile).filter_by(discord_id=winner_id).first()
                if prof:
                    prof.loot_wins += 1
                else:
                    new_prof = UserProfile(
                        discord_id=winner_id, build_name="Default Build", build_type="PvE",
                        ingame_name=f"User {winner_id}", loot_wins=1
                    )
                    db.add(new_prof)
            db.commit()

        # Update the main card directly — we're already editing it
        embed = interaction.message.embeds[0]
        thread_link = f"\n🧵 [Manage this roll](https://discord.com/channels/{interaction.guild.id}/{saved_thread_id})" if saved_thread_id else ""
        render_status(embed, "won" if winner_id else "empty", winner_id, winning_category, thread_link)
        view = build_card_view(is_closed=True, thread_id=saved_thread_id, guild_id=interaction.guild.id)
        await interaction.message.edit(embed=embed, view=view)

        # Announce right here in the main channel
        if winner_id:
            await interaction.channel.send(f"🎲 The roll for **{saved_item_name}** has concluded! Congratulations <@{winner_id}> ({winning_category})! 🎉")
        else:
            await interaction.channel.send(f"🛑 The roll for **{saved_item_name}** was closed with no participants.")

        # If a management thread already exists, flip its panel to the closed state (enable Reroll/Re-Open)
        with next(get_db()) as db:
            fresh_item = db.query(LootItem).filter_by(id=saved_item_id).first()
            await sync_thread_panel(interaction.client, fresh_item, is_closed=True)

    @discord.ui.button(label="Manage Roll", emoji="🛠️", style=discord.ButtonStyle.secondary, custom_id="pl_manage", row=1)
    async def btn_manage(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ **Permission Denied:** Only guild officers can manage rolls manually.", ephemeral=True)
            auto_dismiss(await interaction.original_response())
            return

        await interaction.response.defer(ephemeral=True)

        with next(get_db()) as db:
            item = db.query(LootItem).filter_by(message_id=interaction.message.id).first()
            if not item:
                auto_dismiss(await interaction.followup.send("❌ This loot item could not be found in the database.", ephemeral=True))
                return
            item_id = item.id
            item_name = item.item_name
            is_closed = item.is_closed
            thread_id = item.thread_id

        thread = await fetch_channel_safe(interaction.client, thread_id) if thread_id else None

        if thread is None:
            try:
                thread = await interaction.message.create_thread(name=f"🛠️ {item_name}"[:100], auto_archive_duration=10080)
            except discord.HTTPException:
                thread = await interaction.message.create_thread(name=f"🛠️ {item_name}"[:100], auto_archive_duration=4320)

            panel_view = ManageThreadView()
            sync_manage_view_state(panel_view, is_closed)
            panel_embed = discord.Embed(
                title=f"🛠️ Officer Controls — {item_name}",
                description=f"Reassign rolls, reroll the winner, or re-open voting for this item.\n🔗 [Jump to roll card]({interaction.message.jump_url})",
                color=discord.Color.blurple()
            )
            panel_message = await thread.send(content=interaction.user.mention, embed=panel_embed, view=panel_view)

            with next(get_db()) as db:
                fresh = db.query(LootItem).filter_by(id=item_id).first()
                if fresh:
                    fresh.thread_id = thread.id
                    fresh.manage_message_id = panel_message.id
                    db.commit()
        else:
            # Thread already exists — ping so it surfaces for whoever clicked, even if they've never opened it
            try:
                await thread.send(f"👋 {interaction.user.mention}, jump in here to manage this roll.")
            except discord.HTTPException:
                pass

        # Discord has no API to force a client to open a thread; adding the officer as a member is the
        # closest approximation — it shows up in their thread list immediately instead of staying hidden
        try:
            await thread.add_user(interaction.user)
        except discord.HTTPException:
            pass

        # Swap the card's own Manage Roll button into a direct link to this thread. This handler only
        # ever runs while it's still an interactive button (link buttons never reach the bot at all), so
        # from here on every future click — by anyone — is a one-step, zero-round-trip jump into the thread.
        new_card_view = build_card_view(is_closed=is_closed, thread_id=thread.id, guild_id=interaction.guild.id)
        try:
            await interaction.message.edit(view=new_card_view)
        except discord.HTTPException:
            pass

        # A link button beats a plain hyperlink in a toast that might auto-dismiss before it's clicked —
        # link buttons are pure client-side navigation, so there's no round-trip to keep alive anyway.
        link_view = discord.ui.View(timeout=None)
        link_view.add_item(discord.ui.Button(label="Open Management Thread", emoji="🧵", style=discord.ButtonStyle.link, url=thread.jump_url))
        await interaction.followup.send("Your officer management thread is ready.", view=link_view, ephemeral=True)


class ManageThreadView(discord.ui.View):
    """Lives inside the lazily-created officer thread. Persistent + shared across every item's thread,
    so (like PersistentLootView) it must stay stateless and re-derive everything from the DB via
    interaction.channel.id (the thread == the item). The select-a-user-then-force-a-category flow can't
    live here directly for that reason — it'd leak selections between concurrent officers/threads — so
    Reassign Rolls instead spawns a fresh, per-click OfficerManageView exactly like the old ephemeral panel."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Reassign Rolls", emoji="🎯", style=discord.ButtonStyle.secondary, custom_id="mt_reassign", row=0)
    async def btn_reassign(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ **Permission Denied:** Only guild officers can manage rolls manually.", ephemeral=True)
            auto_dismiss(await interaction.original_response())
            return

        with next(get_db()) as db:
            item = db.query(LootItem).filter_by(thread_id=interaction.channel.id).first()
            if not item or item.is_closed:
                await interaction.response.send_message("❌ This loot roll is closed or could not be found.", ephemeral=True)
                auto_dismiss(await interaction.original_response())
                return
            item_id = item.id
            channel_id = item.channel_id
            message_id = item.message_id

        main_channel = await fetch_channel_safe(interaction.client, channel_id)
        main_message = None
        if main_channel is not None and message_id:
            try:
                main_message = await main_channel.fetch_message(message_id)
            except discord.HTTPException:
                main_message = None

        if main_message is None:
            await interaction.response.send_message("❌ Could not locate the roll card for this item.", ephemeral=True)
            auto_dismiss(await interaction.original_response())
            return

        parent_view = build_card_view(is_closed=False, thread_id=interaction.channel.id, guild_id=interaction.guild.id)
        view = OfficerManageView(item_id, main_message, parent_view)
        await interaction.response.send_message(
            "🛠️ **Officer Roll Management**\nSelect a user below, then click a button to instantly assign or remove their roll.",
            view=view, ephemeral=True
        )

    # 🎲 THE AUTO-ROLL & REROLL ENGINE — dual-purpose just like the main card's button, so an officer
    # already in the thread (say, after Reassigning) never has to leave it to conclude the roll. Both
    # entry points share the same underlying logic and stay in sync via sync_main_card/sync_thread_panel.
    @discord.ui.button(label="Auto Roll Winner", emoji="🎲", style=discord.ButtonStyle.danger, custom_id="mt_roll", row=1)
    async def btn_roll(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ **Permission Denied:** Only guild officers can trigger the loot roll.", ephemeral=True)
            auto_dismiss(await interaction.original_response())
            return

        await interaction.response.defer(ephemeral=True)
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        with next(get_db()) as db:
            item = db.query(LootItem).filter_by(thread_id=interaction.channel.id).first()
            if not item:
                auto_dismiss(await interaction.followup.send("❌ This loot item could not be found in the database.", ephemeral=True))
                return

            saved_channel_id = item.channel_id
            is_reroll = item.is_closed

            # 1. REROLL REFUND SEQUENCE
            if item.winner_id:
                # Only refund a penalty that was actually applied to the previous winner
                if item.winner_penalized:
                    old_winner = db.query(UserProfile).filter_by(discord_id=item.winner_id).first()
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
            winner_penalized = False

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
                winner_penalized = True
            elif rolls_dict["alt_want"]:
                winner_id = pick_weighted_winner(rolls_dict["alt_want"])
                winning_category = "Alt / Want 🔵"
                winner_penalized = True
            elif rolls_dict["greed"]:
                winner_id = pick_weighted_winner(rolls_dict["greed"])
                winning_category = "Greed 🟡"
                # An uncontested greed roll (nobody else claimed need/alt-want/greed) isn't a real
                # contest, so the sole roller shouldn't have their priority docked for taking it.
                winner_penalized = len(rolls_dict["greed"]) > 1

            # 5. LOCK ITEM AND PENALIZE NEW WINNER
            saved_item_id = item.id
            saved_item_name = item.item_name
            item.is_closed = True
            item.winner_id = winner_id
            item.winner_penalized = winner_penalized
            item.closed_at = now_utc

            if winner_id and winner_penalized:
                prof = db.query(UserProfile).filter_by(discord_id=winner_id).first()
                if prof:
                    prof.loot_wins += 1
                else:
                    new_prof = UserProfile(
                        discord_id=winner_id, build_name="Default Build", build_type="PvE",
                        ingame_name=f"User {winner_id}", loot_wins=1
                    )
                    db.add(new_prof)
            db.commit()

        # 6. UPDATE THE PANEL (stays closed-state: Reassign disabled, Reroll/Re-Open enabled)
        sync_manage_view_state(self, is_closed=True)
        await interaction.message.edit(view=self)

        # 7. ANNOUNCE IN THE MAIN CHANNEL, NOT THE THREAD
        main_channel = await fetch_channel_safe(interaction.client, saved_channel_id)
        if main_channel is not None:
            announcement = f"🔁 The **REROLL** for **{saved_item_name}**" if is_reroll else f"🎲 The roll for **{saved_item_name}**"
            if winner_id:
                await main_channel.send(f"{announcement} has concluded! Congratulations <@{winner_id}> ({winning_category})! 🎉")
            else:
                await main_channel.send(f"🛑 {announcement} was closed with no participants.")

        # 8. REFLECT THE OUTCOME ON THE MAIN CARD
        with next(get_db()) as db:
            fresh_item = db.query(LootItem).filter_by(id=saved_item_id).first()
            await sync_main_card(interaction.client, interaction, fresh_item, "won" if winner_id else "empty", winner_id, winning_category)

        toast = await interaction.followup.send("✅ Roll resolved — see the main channel for the announcement.", ephemeral=True)
        auto_dismiss(toast)

    # 🔓 RE-OPEN: undo a close entirely so voting happens again, distinct from Reroll (which only
    # re-picks a winner from the same already-locked-in pool).
    @discord.ui.button(label="Re-Open", emoji="🔓", style=discord.ButtonStyle.success, custom_id="mt_reopen", row=1, disabled=True)
    async def btn_reopen(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ **Permission Denied:** Only guild officers can reopen a roll.", ephemeral=True)
            auto_dismiss(await interaction.original_response())
            return

        await interaction.response.defer(ephemeral=True)

        with next(get_db()) as db:
            item = db.query(LootItem).filter_by(thread_id=interaction.channel.id).first()
            if not item or not item.is_closed:
                auto_dismiss(await interaction.followup.send("❌ This roll isn't closed, so there's nothing to reopen.", ephemeral=True))
                return

            # Refund the previous winner's penalty if one was actually applied. Every existing roll
            # entry, including the old winner's, is left untouched so nobody has to re-click.
            if item.winner_penalized and item.winner_id:
                old_winner = db.query(UserProfile).filter_by(discord_id=item.winner_id).first()
                if old_winner and old_winner.loot_wins > 0:
                    old_winner.loot_wins -= 1

            saved_item_id = item.id
            saved_item_name = item.item_name
            saved_channel_id = item.channel_id
            was_archived = item.is_archived

            item.is_closed = False
            item.winner_id = None
            item.winner_penalized = False
            item.closed_at = None
            item.is_archived = False
            db.commit()

        # This thread is exactly the one we're inside of, so unarchive/unlock it if the 7-day
        # cleanup had already archived it
        if was_archived:
            try:
                await interaction.channel.edit(archived=False, locked=False)
            except discord.HTTPException:
                pass

        sync_manage_view_state(self, is_closed=False)
        await interaction.message.edit(view=self)

        main_channel = await fetch_channel_safe(interaction.client, saved_channel_id)
        if main_channel is not None:
            await main_channel.send(f"🔓 **Re-Opened:** An officer reopened the roll for **{saved_item_name}** — rolls are open again!")

        with next(get_db()) as db:
            fresh_item = db.query(LootItem).filter_by(id=saved_item_id).first()
            await sync_main_card(interaction.client, interaction, fresh_item, "reopened")

        toast = await interaction.followup.send("✅ Roll reopened — voting is live again.", ephemeral=True)
        auto_dismiss(toast)


class LootCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(PersistentLootView())
        self.bot.add_view(ManageThreadView())
        self.cleanup_loot_loop.start()
        self.auto_reset_priority_loop.start()
        self.archive_loot_threads_loop.start()

    def cog_unload(self):
        self.cleanup_loot_loop.cancel()
        self.auto_reset_priority_loop.cancel()
        self.archive_loot_threads_loop.cancel()

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
                func.coalesce(LootItem.closed_at, LootItem.created_at) <= cutoff_date
            ).all()
            for item in old_items: db.delete(item)
            if old_items:
                db.commit()
                print(f"🧹 Database Cleanup: Purged {len(old_items)} old loot distributions.")

    @tasks.loop(hours=24)
    async def archive_loot_threads_loop(self):
        """7 days after a roll concludes, archive+lock its management thread (if one was ever created)."""
        await self.bot.wait_until_ready()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cutoff_date = now - timedelta(days=7)

        with next(get_db()) as db:
            items = db.query(LootItem).filter(
                LootItem.is_closed == True,
                LootItem.is_archived == False,
                LootItem.closed_at.isnot(None),
                LootItem.closed_at <= cutoff_date
            ).all()

            archived_count = 0
            for item in items:
                if not item.thread_id:
                    item.is_archived = True
                    continue

                thread = self.bot.get_channel(item.thread_id)
                if thread is None:
                    try:
                        thread = await self.bot.fetch_channel(item.thread_id)
                    except discord.NotFound:
                        item.is_archived = True
                        continue
                    except discord.HTTPException:
                        continue

                try:
                    await thread.edit(archived=True, locked=True)
                except discord.HTTPException:
                    continue

                item.is_archived = True
                archived_count += 1

            if items:
                db.commit()
                print(f"🗄️ Loot Archive: Archived {archived_count} loot management threads.")

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
