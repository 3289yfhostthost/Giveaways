import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import re
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
import random

# Load environment variables from .env file
load_dotenv()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Data files
WALLET_FILE = "wallets.json"
GIVEAWAY_FILE = "giveaways.json"
SUPPORT_ROLE_ID = 1434628709452742747

# Load wallet data
def load_wallets():
    if os.path.exists(WALLET_FILE):
        with open(WALLET_FILE, 'r') as f:
            return json.load(f)
    return {}

# Save wallet data
def save_wallets(wallets):
    with open(WALLET_FILE, 'w') as f:
        json.dump(wallets, f, indent=4)

# Load giveaway data
def load_giveaways():
    if os.path.exists(GIVEAWAY_FILE):
        with open(GIVEAWAY_FILE, 'r') as f:
            return json.load(f)
    return {}

# Save giveaway data
def save_giveaways(giveaways):
    with open(GIVEAWAY_FILE, 'w') as f:
        json.dump(giveaways, f, indent=4)

# Parse amount (supports k, m, b suffixes)
def parse_amount(amount_str):
    amount_str = amount_str.lower().strip()
    multipliers = {'k': 1_000, 'm': 1_000_000, 'b': 1_000_000_000}
    
    match = re.match(r'^([\d.]+)([kmb]?)$', amount_str)
    if not match:
        return None
    
    number, suffix = match.groups()
    try:
        value = float(number)
        if suffix:
            value *= multipliers[suffix]
        return int(value)
    except ValueError:
        return None

# Format number with suffix
def format_amount(amount):
    if amount >= 1_000_000_000:
        return f"{amount / 1_000_000_000:.1f}b".rstrip('0').rstrip('.')
    elif amount >= 1_000_000:
        return f"{amount / 1_000_000:.1f}m".rstrip('0').rstrip('.')
    elif amount >= 1_000:
        return f"{amount / 1_000:.1f}k".rstrip('0').rstrip('.')
    return str(amount)

# Get user wallet balance
def get_balance(user_id):
    wallets = load_wallets()
    return wallets.get(str(user_id), 0)

# Set user wallet balance
def set_balance(user_id, amount):
    wallets = load_wallets()
    wallets[str(user_id)] = amount
    save_wallets(wallets)

# Parse duration string (e.g., "1d", "12h", "30m")
def parse_duration(duration_str):
    duration_str = duration_str.lower().strip()
    match = re.match(r'^(\d+)([dhm])$', duration_str)
    if not match:
        return None
    
    value, unit = match.groups()
    value = int(value)
    
    if unit == 'd':
        if value > 60:  # Max 60 days
            return None
        return timedelta(days=value)
    elif unit == 'h':
        return timedelta(hours=value)
    elif unit == 'm':
        return timedelta(minutes=value)
    
    return None

# Giveaway entry button
class GiveawayButton(discord.ui.View):
    def __init__(self, giveaway_id):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
    
    @discord.ui.button(label="🎉 Enter Giveaway", style=discord.ButtonStyle.primary, custom_id="enter_giveaway")
    async def enter_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaways = load_giveaways()
        giveaway = giveaways.get(self.giveaway_id)
        
        if not giveaway:
            await interaction.response.send_message("❌ This giveaway no longer exists!", ephemeral=True)
            return
        
        user_id = str(interaction.user.id)
        
        # Check if already entered
        if user_id in giveaway['entries']:
            await interaction.response.send_message("⚠️ You've already entered this giveaway!", ephemeral=True)
            return
        
        # Check role requirements
        if giveaway['required_role_id']:
            role = discord.utils.get(interaction.guild.roles, id=giveaway['required_role_id'])
            if role and role not in interaction.user.roles:
                await interaction.response.send_message(f"❌ You need the {role.mention} role to enter this giveaway!", ephemeral=True)
                return
        
        # Add entry
        giveaway['entries'].append(user_id)
        save_giveaways(giveaways)
        
        await interaction.response.send_message("✅ You've successfully entered the giveaway! Good luck!", ephemeral=True)
        
        # Update the giveaway message with new entry count
        try:
            channel = bot.get_channel(giveaway['channel_id'])
            message = await channel.fetch_message(giveaway['message_id'])
            
            embed = message.embeds[0]
            # Update entries field
            for i, field in enumerate(embed.fields):
                if field.name == "📊 Entries":
                    embed.set_field_at(i, name="📊 Entries", value=str(len(giveaway['entries'])), inline=True)
                    break
            
            await message.edit(embed=embed)
        except:
            pass

@bot.event
async def on_ready():
    # Add persistent view for giveaway buttons
    giveaways = load_giveaways()
    for giveaway_id in giveaways.keys():
        bot.add_view(GiveawayButton(giveaway_id))
    
    # Start giveaway checker
    check_giveaways.start()
    
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    print(f"{bot.user} is now online!")

# Background task to check for ended giveaways
@tasks.loop(seconds=30)
async def check_giveaways():
    giveaways = load_giveaways()
    current_time = datetime.utcnow()
    
    for giveaway_id, giveaway in list(giveaways.items()):
        end_time = datetime.fromisoformat(giveaway['end_time'])
        
        if current_time >= end_time and not giveaway.get('ended', False):
            await end_giveaway(giveaway_id, giveaway)

async def end_giveaway(giveaway_id, giveaway):
    """End a giveaway and pick winners"""
    giveaways = load_giveaways()
    
    # Mark as ended
    giveaway['ended'] = True
    giveaways[giveaway_id] = giveaway
    save_giveaways(giveaways)
    
    try:
        channel = bot.get_channel(giveaway['channel_id'])
        message = await channel.fetch_message(giveaway['message_id'])
        
        # Pick winners
        entries = giveaway['entries']
        num_winners = giveaway['winners']
        
        if len(entries) == 0:
            # No entries
            embed = discord.Embed(
                title="🎉 Giveaway Ended",
                description=f"**Prize:** {giveaway['prize']}\n\n❌ No one entered this giveaway!",
                color=discord.Color.red()
            )
            await message.edit(embed=embed, view=None)
            await channel.send(f"The giveaway for **{giveaway['prize']}** has ended with no entries!")
            return
        
        # Select winners (or all entries if not enough)
        num_to_pick = min(num_winners, len(entries))
        winner_ids = random.sample(entries, num_to_pick)
        
        # Award GP to winners
        gp_amount = giveaway['gp_amount']
        winners_text = []
        
        for winner_id in winner_ids:
            # Add GP to wallet
            current_balance = get_balance(int(winner_id))
            new_balance = current_balance + gp_amount
            set_balance(int(winner_id), new_balance)
            
            winners_text.append(f"<@{winner_id}>")
            
            # DM winner
            try:
                user = await bot.fetch_user(int(winner_id))
                dm_embed = discord.Embed(
                    title="🎉 Congratulations!",
                    description=f"You won the giveaway for **{giveaway['prize']}**!\n\n💰 **{format_amount(gp_amount)} GP** has been added to your wallet!",
                    color=discord.Color.gold()
                )
                dm_embed.set_footer(text=f"Server: {channel.guild.name}")
                await user.send(embed=dm_embed)
            except:
                pass  # Couldn't DM user
        
        # Update giveaway message
        winners_mention = ", ".join(winners_text)
        embed = discord.Embed(
            title="🎉 Giveaway Ended!",
            description=f"**Prize:** {giveaway['prize']}\n**GP Reward:** {format_amount(gp_amount)} GP\n\n🎊 **Winner(s):** {winners_mention}",
            color=discord.Color.gold()
        )
        await message.edit(embed=embed, view=None)
        
        # Announcement
        await channel.send(f"🎉 **Giveaway ended!**\n\nWinner(s): {winners_mention}\nPrize: **{giveaway['prize']}** + **{format_amount(gp_amount)} GP**\n\nCongratulations! 🎊")
        
    except Exception as e:
        print(f"Error ending giveaway {giveaway_id}: {e}")

# Giveaway command group
giveaway_group = app_commands.Group(name="giveaway", description="Giveaway commands")

@giveaway_group.command(name="create", description="Create a new giveaway (Support only)")
@app_commands.describe(
    prize="What the giveaway is for",
    gp_amount="GP amount to award winner (e.g., 20m, 500k, 1000)",
    duration="Duration (e.g., 1d, 12h, 30m) - max 60 days",
    winners="Number of winners (default: 1)",
    required_role="Role required to enter (optional)"
)
async def giveaway_create(
    interaction: discord.Interaction,
    prize: str,
    gp_amount: str,
    duration: str,
    winners: int = 1,
    required_role: discord.Role = None
):
    # Check if user has support role
    support_role = discord.utils.get(interaction.guild.roles, id=SUPPORT_ROLE_ID)
    if support_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You need the @support role to use this command!", ephemeral=True)
        return
    
    # Parse GP amount
    parsed_gp = parse_amount(gp_amount)
    if parsed_gp is None or parsed_gp <= 0:
        await interaction.response.send_message("❌ Invalid GP amount! Use formats like: 20m, 500k, 1000", ephemeral=True)
        return
    
    # Parse duration
    duration_delta = parse_duration(duration)
    if duration_delta is None:
        await interaction.response.send_message("❌ Invalid duration! Use format like: 1d, 12h, 30m (max 60 days)", ephemeral=True)
        return
    
    # Validate winners
    if winners < 1:
        await interaction.response.send_message("❌ Must have at least 1 winner!", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    # Create giveaway
    giveaway_id = str(datetime.utcnow().timestamp())
    end_time = datetime.utcnow() + duration_delta
    
    # Create embed
    embed = discord.Embed(
        title="🎉 GIVEAWAY 🎉",
        description=f"**Prize:** {prize}\n**GP Reward:** {format_amount(parsed_gp)} GP\n\nClick the button below to enter!",
        color=discord.Color.blue()
    )
    embed.add_field(name="⏰ Ends", value=f"<t:{int(end_time.timestamp())}:R>", inline=True)
    embed.add_field(name="🏆 Winners", value=str(winners), inline=True)
    embed.add_field(name="📊 Entries", value="0", inline=True)
    
    if required_role:
        embed.add_field(name="🔒 Required Role", value=required_role.mention, inline=False)
    
    embed.set_footer(text=f"Hosted by {interaction.user.display_name}")
    embed.timestamp = end_time
    
    # Send giveaway message
    view = GiveawayButton(giveaway_id)
    bot.add_view(view)  # Make button persistent
    
    message = await interaction.channel.send(embed=embed, view=view)
    
    # Save giveaway data
    giveaways = load_giveaways()
    giveaways[giveaway_id] = {
        'prize': prize,
        'gp_amount': parsed_gp,
        'winners': winners,
        'entries': [],
        'channel_id': interaction.channel.id,
        'message_id': message.id,
        'host_id': interaction.user.id,
        'end_time': end_time.isoformat(),
        'required_role_id': required_role.id if required_role else None,
        'ended': False
    }
    save_giveaways(giveaways)
    
    await interaction.followup.send(f"✅ Giveaway created! Ends <t:{int(end_time.timestamp())}:R>", ephemeral=True)

@giveaway_group.command(name="end", description="Manually end a giveaway early (Support only)")
@app_commands.describe(message_id="The message ID of the giveaway to end")
async def giveaway_end(interaction: discord.Interaction, message_id: str):
    # Check if user has support role
    support_role = discord.utils.get(interaction.guild.roles, id=SUPPORT_ROLE_ID)
    if support_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You need the @support role to use this command!", ephemeral=True)
        return
    
    # Find giveaway
    giveaways = load_giveaways()
    giveaway_id = None
    giveaway = None
    
    for gid, g in giveaways.items():
        if str(g['message_id']) == message_id:
            giveaway_id = gid
            giveaway = g
            break
    
    if not giveaway:
        await interaction.response.send_message("❌ Giveaway not found!", ephemeral=True)
        return
    
    if giveaway.get('ended', False):
        await interaction.response.send_message("❌ This giveaway has already ended!", ephemeral=True)
        return
    
    await interaction.response.send_message("⏳ Ending giveaway...", ephemeral=True)
    await end_giveaway(giveaway_id, giveaway)

@giveaway_group.command(name="reroll", description="Reroll a giveaway winner (Support only)")
@app_commands.describe(message_id="The message ID of the giveaway to reroll")
async def giveaway_reroll(interaction: discord.Interaction, message_id: str):
    # Check if user has support role
    support_role = discord.utils.get(interaction.guild.roles, id=SUPPORT_ROLE_ID)
    if support_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You need the @support role to use this command!", ephemeral=True)
        return
    
    # Find giveaway
    giveaways = load_giveaways()
    giveaway = None
    
    for g in giveaways.values():
        if str(g['message_id']) == message_id:
            giveaway = g
            break
    
    if not giveaway:
        await interaction.response.send_message("❌ Giveaway not found!", ephemeral=True)
        return
    
    if not giveaway.get('ended', False):
        await interaction.response.send_message("❌ This giveaway hasn't ended yet!", ephemeral=True)
        return
    
    if len(giveaway['entries']) == 0:
        await interaction.response.send_message("❌ No entries to reroll!", ephemeral=True)
        return
    
    # Pick new winner
    winner_id = random.choice(giveaway['entries'])
    gp_amount = giveaway['gp_amount']
    
    # Award GP
    current_balance = get_balance(int(winner_id))
    new_balance = current_balance + gp_amount
    set_balance(int(winner_id), new_balance)
    
    # DM winner
    try:
        user = await bot.fetch_user(int(winner_id))
        dm_embed = discord.Embed(
            title="🎉 Congratulations!",
            description=f"You won the reroll for **{giveaway['prize']}**!\n\n💰 **{format_amount(gp_amount)} GP** has been added to your wallet!",
            color=discord.Color.gold()
        )
        await user.send(embed=dm_embed)
    except:
        pass
    
    await interaction.response.send_message(f"🎉 **Reroll Winner:** <@{winner_id}>\n**Prize:** {giveaway['prize']} + {format_amount(gp_amount)} GP")

@giveaway_group.command(name="list", description="List all active giveaways")
async def giveaway_list(interaction: discord.Interaction):
    giveaways = load_giveaways()
    active = [g for g in giveaways.values() if not g.get('ended', False)]
    
    if not active:
        await interaction.response.send_message("❌ No active giveaways!", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="🎉 Active Giveaways",
        color=discord.Color.blue()
    )
    
    for g in active:
        end_time = datetime.fromisoformat(g['end_time'])
        embed.add_field(
            name=g['prize'],
            value=f"Reward: {format_amount(g['gp_amount'])} GP\nEntries: {len(g['entries'])}\nEnds: <t:{int(end_time.timestamp())}:R>\n[Jump to Giveaway](https://discord.com/channels/{interaction.guild.id}/{g['channel_id']}/{g['message_id']})",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed)

bot.tree.add_command(giveaway_group)

# /wallet command - check balance
@bot.tree.command(name="wallet", description="Check your GP balance")
async def wallet(interaction: discord.Interaction):
    user_id = interaction.user.id
    balance = get_balance(user_id)
    formatted_balance = format_amount(balance)
    
    embed = discord.Embed(
        title="💰 Wallet",
        description=f"**{interaction.user.display_name}** has **{formatted_balance} GP**",
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed)

# /wallet-add command - add GP (support only)
@bot.tree.command(name="wallet-add", description="Add GP to a user's wallet (Support only)")
@app_commands.describe(user="The user to add GP to", amount="Amount to add (e.g., 20m, 500k, 1000)")
async def wallet_add(interaction: discord.Interaction, user: discord.Member, amount: str):
    # Check if user has support role
    support_role = discord.utils.get(interaction.guild.roles, id=SUPPORT_ROLE_ID)
    if support_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You need the @support role to use this command!", ephemeral=True)
        return
    
    # Parse amount
    parsed_amount = parse_amount(amount)
    if parsed_amount is None or parsed_amount <= 0:
        await interaction.response.send_message("❌ Invalid amount! Use formats like: 20m, 500k, 1000", ephemeral=True)
        return
    
    # Add to wallet
    current_balance = get_balance(user.id)
    new_balance = current_balance + parsed_amount
    set_balance(user.id, new_balance)
    
    formatted_amount = format_amount(parsed_amount)
    formatted_new_balance = format_amount(new_balance)
    
    embed = discord.Embed(
        title="✅ GP Added",
        description=f"Added **{formatted_amount} GP** to {user.mention}'s wallet\nNew balance: **{formatted_new_balance} GP**",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

# /wallet-remove command - remove GP (support only)
@bot.tree.command(name="wallet-remove", description="Remove GP from a user's wallet (Support only)")
@app_commands.describe(user="The user to remove GP from", amount="Amount to remove (e.g., 20m, 500k, 1000)")
async def wallet_remove(interaction: discord.Interaction, user: discord.Member, amount: str):
    # Check if user has support role
    support_role = discord.utils.get(interaction.guild.roles, id=SUPPORT_ROLE_ID)
    if support_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You need the @support role to use this command!", ephemeral=True)
        return
    
    # Parse amount
    parsed_amount = parse_amount(amount)
    if parsed_amount is None or parsed_amount <= 0:
        await interaction.response.send_message("❌ Invalid amount! Use formats like: 20m, 500k, 1000", ephemeral=True)
        return
    
    # Check if sufficient balance
    current_balance = get_balance(user.id)
    if current_balance < parsed_amount:
        await interaction.response.send_message(f"❌ Insufficient balance! {user.mention} only has **{format_amount(current_balance)} GP**", ephemeral=True)
        return
    
    # Remove from wallet
    new_balance = current_balance - parsed_amount
    set_balance(user.id, new_balance)
    
    formatted_amount = format_amount(parsed_amount)
    formatted_new_balance = format_amount(new_balance)
    
    embed = discord.Embed(
        title="✅ GP Removed",
        description=f"Removed **{formatted_amount} GP** from {user.mention}'s wallet\nNew balance: **{formatted_new_balance} GP**",
        color=discord.Color.red()
    )
    await interaction.response.send_message(embed=embed)

# Run the bot
if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN not found in environment variables!")
        print("Please create a .env file or set the environment variable.")
    else:
        bot.run(TOKEN)