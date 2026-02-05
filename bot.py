import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
from datetime import datetime, timedelta
import json
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get bot token
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')

if not DISCORD_BOT_TOKEN:
    raise ValueError("Error: DISCORD_BOT_TOKEN not found in environment variables!\nPlease create a .env file or set the environment variable.")

# Path to wallet data from the Wallet bot
WALLET_FILE = os.path.expanduser('~/wallet/wallets.json')

# Role IDs
BOOSTER_ROLE_ID = 591776624547201025
WINNERS_CIRCLE_ROLE_ID = 1421659378523832431

# Image URLs
THUMBNAIL_URL = "https://oldschool.runescape.wiki/images/thumb/Coins_detail.png/240px-Coins_detail.png?404bc"
BANNER_URL = "https://i.postimg.cc/HkTwJVLb/thieving-giveaway-banner-1.png"

# Bot setup with necessary intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)

# File to store giveaway data
GIVEAWAY_FILE = 'giveaways.json'

def load_wallets():
    """Load wallet data from the Wallet bot's wallets.json file"""
    try:
        if os.path.exists(WALLET_FILE):
            with open(WALLET_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading wallet data: {e}")
    return {}

def load_giveaways():
    """Load giveaway data from file"""
    try:
        if os.path.exists(GIVEAWAY_FILE):
            with open(GIVEAWAY_FILE, 'r') as f:
                data = json.load(f)
                # Convert string timestamps back to datetime objects
                for giveaway in data.values():
                    giveaway['end_time'] = datetime.fromisoformat(giveaway['end_time'])
                return data
    except Exception as e:
        print(f"Error loading giveaways: {e}")
    return {}

def save_giveaways(giveaways):
    """Save giveaway data to file"""
    try:
        # Convert datetime objects to strings for JSON serialization
        serializable_data = {}
        for msg_id, giveaway in giveaways.items():
            serializable_data[msg_id] = {
                **giveaway,
                'end_time': giveaway['end_time'].isoformat()
            }
        
        with open(GIVEAWAY_FILE, 'w') as f:
            json.dump(serializable_data, f, indent=4)
    except Exception as e:
        print(f"Error saving giveaways: {e}")

# Dictionary to store active giveaways
active_giveaways = load_giveaways()

async def check_message_requirement(guild, user_id, required_messages=1):
    """Check if user has sent required number of messages in the past week"""
    # This is a simplified check - in production you'd want to track messages in a database
    # For now, we'll assume users meet the requirement
    # You can enhance this by tracking messages in a separate system
    return True

async def get_user_entries(member):
    """Calculate how many entries a user gets based on their roles"""
    entries = 1  # Base entry
    
    # Check for booster role - gets 2 extra entries
    if any(role.id == BOOSTER_ROLE_ID for role in member.roles):
        entries += 2
    
    # Check for winners circle role - gets 3 extra entries
    if any(role.id == WINNERS_CIRCLE_ROLE_ID for role in member.roles):
        entries += 3
    
    return entries

class ParticipantsView(discord.ui.View):
    def __init__(self, message_id, giveaway_data):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.giveaway_data = giveaway_data
    
    @discord.ui.button(label="👥 Participants", style=discord.ButtonStyle.secondary, custom_id="view_participants")
    async def view_participants(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            message = await interaction.channel.fetch_message(int(self.message_id))
            
            # Get all users who reacted with 🎉
            reactions = [r for r in message.reactions if str(r.emoji) == '🎉']
            if not reactions:
                await interaction.response.send_message("No participants yet!", ephemeral=True)
                return
            
            participants = []
            async for user in reactions[0].users():
                if not user.bot:
                    participants.append(user.mention)
            
            if not participants:
                await interaction.response.send_message("No participants yet!", ephemeral=True)
                return
            
            # Create embed showing participants
            embed = discord.Embed(
                title=f"👥 Giveaway Participants ({len(participants)})",
                description="\n".join(participants),
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            await interaction.response.send_message(f"Error fetching participants: {e}", ephemeral=True)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    
    # Start the giveaway checker task
    check_giveaways.start()

@tasks.loop(seconds=10)
async def check_giveaways():
    """Check for ended giveaways and pick winners"""
    current_time = datetime.utcnow()
    ended_giveaways = []
    
    for message_id, giveaway_data in active_giveaways.items():
        if current_time >= giveaway_data['end_time']:
            ended_giveaways.append(message_id)
    
    for message_id in ended_giveaways:
        await end_giveaway(message_id)

async def end_giveaway(message_id):
    """End a giveaway and pick winners"""
    if message_id not in active_giveaways:
        return
    
    giveaway_data = active_giveaways[message_id]
    
    try:
        channel = bot.get_channel(giveaway_data['channel_id'])
        if not channel:
            print(f"Channel not found for giveaway {message_id}")
            del active_giveaways[message_id]
            save_giveaways(active_giveaways)
            return
        
        guild = channel.guild
        message = await channel.fetch_message(int(message_id))
        
        # Get all users who reacted with 🎉
        reactions = [r for r in message.reactions if str(r.emoji) == '🎉']
        if not reactions:
            await channel.send(f"No one entered the giveaway for **{giveaway_data['prize']}**!")
            del active_giveaways[message_id]
            save_giveaways(active_giveaways)
            return
        
        # Build weighted entry list
        entry_pool = []
        valid_users = []
        
        async for user in reactions[0].users():
            if user.bot:
                continue
            
            member = guild.get_member(user.id)
            if not member:
                continue
            
            # Check message requirement
            meets_requirement = await check_message_requirement(guild, user.id, giveaway_data.get('message_requirement', 1))
            if not meets_requirement:
                continue
            
            valid_users.append(member)
            
            # Add entries based on roles
            user_entries = await get_user_entries(member)
            for _ in range(user_entries):
                entry_pool.append(member)
        
        if not entry_pool:
            await channel.send(f"No valid entries for the giveaway of **{giveaway_data['prize']}**!")
            del active_giveaways[message_id]
            save_giveaways(active_giveaways)
            return
        
        # Pick winners
        num_winners = min(giveaway_data['winners'], len(valid_users))
        
        import random
        winners = []
        for _ in range(num_winners):
            if not entry_pool:
                break
            winner = random.choice(entry_pool)
            if winner not in winners:
                winners.append(winner)
            # Remove all entries from this winner
            entry_pool = [m for m in entry_pool if m.id != winner.id]
        
        # Give winners the Winners Circle role
        winners_circle_role = guild.get_role(WINNERS_CIRCLE_ROLE_ID)
        
        winner_mentions = []
        for winner in winners:
            winner_mentions.append(winner.mention)
            if winners_circle_role:
                try:
                    await winner.add_roles(winners_circle_role)
                except:
                    pass
        
        # Send winner announcement
        embed = discord.Embed(
            title="🎉 GIVEAWAY ENDED 🎉",
            description=f"**Prize:** {giveaway_data['prize']}\n\n**Winner{'s' if len(winners) > 1 else ''}:**\n" + "\n".join(winner_mentions),
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=THUMBNAIL_URL)
        await channel.send(embed=embed)
        
        # DM winners
        for winner in winners:
            try:
                await winner.send(f"🎉 Congratulations! You won **{giveaway_data['prize']}** in {guild.name}!\nYou've been given the Winners Circle role!")
            except:
                pass
        
        # Update the original message
        ended_embed = discord.Embed(
            title="🎉 GIVEAWAY ENDED 🎉",
            description=f"**{giveaway_data['prize']}**\n\nThis giveaway has ended!",
            color=discord.Color.red()
        )
        ended_embed.set_thumbnail(url=THUMBNAIL_URL)
        ended_embed.set_image(url=BANNER_URL)
        await message.edit(embed=ended_embed, view=None)
        
        # Remove from active giveaways
        del active_giveaways[message_id]
        save_giveaways(active_giveaways)
        
    except Exception as e:
        print(f"Error ending giveaway {message_id}: {e}")
        if message_id in active_giveaways:
            del active_giveaways[message_id]
            save_giveaways(active_giveaways)

@bot.tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(
    prize="What are you giving away?",
    duration="Duration in minutes",
    winners="Number of winners (default: 1)",
    message_requirement="Minimum messages required in past week (default: 1)"
)
async def start_giveaway(
    interaction: discord.Interaction,
    prize: str,
    duration: int,
    winners: int = 1,
    message_requirement: int = 1
):
    """Start a new giveaway"""
    if duration < 1:
        await interaction.response.send_message("Duration must be at least 1 minute!", ephemeral=True)
        return
    
    if winners < 1:
        await interaction.response.send_message("Must have at least 1 winner!", ephemeral=True)
        return
    
    end_time = datetime.utcnow() + timedelta(minutes=duration)
    
    # Create the giveaway embed
    embed = discord.Embed(
        title=f"{prize}",
        color=discord.Color.purple()
    )
    
    # Add description with entry instructions
    description = f"Click 🎉 button to enter!\n**Winners:** {winners}\n\n"
    
    # Add extra entries info
    description += "**Extra Entries:**\n"
    description += f"<@&{WINNERS_CIRCLE_ROLE_ID}>: **2 entries**\n"
    description += f"<@&{BOOSTER_ROLE_ID}>: **3 entries**\n\n"
    
    # Add requirements
    description += "**Must have sent:**\n"
    description += f"• **{message_requirement} message{'s' if message_requirement > 1 else ''} this week**\n\n"
    
    # Add winner role info
    description += f"Winner will get the role: <@&{WINNERS_CIRCLE_ROLE_ID}>"
    
    embed.description = description
    embed.set_footer(text=f"Hosted by: @{interaction.user.display_name}")
    embed.timestamp = end_time
    embed.set_thumbnail(url=THUMBNAIL_URL)
    embed.set_image(url=BANNER_URL)
    
    # Add ending time
    embed.add_field(name="Ends at", value=f"<t:{int(end_time.timestamp())}:R>", inline=False)
    
    # Create view with participants button
    view = ParticipantsView(None, None)
    
    await interaction.response.send_message(embed=embed, view=view)
    message = await interaction.original_response()
    await message.add_reaction('🎉')
    
    # Update view with message ID
    view.message_id = str(message.id)
    
    # Store giveaway data
    active_giveaways[str(message.id)] = {
        'prize': prize,
        'winners': winners,
        'end_time': end_time,
        'channel_id': interaction.channel.id,
        'host_id': interaction.user.id,
        'message_requirement': message_requirement
    }
    save_giveaways(active_giveaways)

@bot.tree.command(name="reroll", description="Reroll a giveaway winner")
@app_commands.describe(message_id="The message ID of the ended giveaway")
async def reroll(interaction: discord.Interaction, message_id: str):
    """Reroll the winner of an ended giveaway"""
    try:
        message = await interaction.channel.fetch_message(int(message_id))
        guild = interaction.guild
        
        # Check if it's a giveaway message
        if not message.embeds or "GIVEAWAY" not in message.embeds[0].title.upper():
            await interaction.response.send_message("This doesn't appear to be a giveaway message!", ephemeral=True)
            return
        
        # Get reactions
        reactions = [r for r in message.reactions if str(r.emoji) == '🎉']
        if not reactions:
            await interaction.response.send_message("No reactions found on this giveaway!", ephemeral=True)
            return
        
        # Build entry pool
        entry_pool = []
        valid_users = []
        
        async for user in reactions[0].users():
            if user.bot:
                continue
            
            member = guild.get_member(user.id)
            if not member:
                continue
            
            valid_users.append(member)
            
            # Add entries based on roles
            user_entries = await get_user_entries(member)
            for _ in range(user_entries):
                entry_pool.append(member)
        
        if not entry_pool:
            await interaction.response.send_message("No valid entries found!", ephemeral=True)
            return
        
        import random
        winner = random.choice(entry_pool)
        
        # Give winner the Winners Circle role
        winners_circle_role = guild.get_role(WINNERS_CIRCLE_ROLE_ID)
        if winners_circle_role:
            try:
                await winner.add_roles(winners_circle_role)
            except:
                pass
        
        embed = discord.Embed(
            title="🎉 New Winner! 🎉",
            description=f"**New Winner:** {winner.mention}\nThey've been given the Winners Circle role!",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=THUMBNAIL_URL)
        await interaction.response.send_message(embed=embed)
        
        try:
            await winner.send(f"🎉 Congratulations! You won the rerolled giveaway in {guild.name}!")
        except:
            pass
        
    except discord.NotFound:
        await interaction.response.send_message("Message not found! Make sure you're using the correct message ID.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)

@bot.tree.command(name="gend", description="End a giveaway early")
@app_commands.describe(message_id="The message ID of the giveaway to end")
async def end_giveaway_command(interaction: discord.Interaction, message_id: str):
    """End a giveaway early"""
    if message_id not in active_giveaways:
        await interaction.response.send_message("This giveaway is not active or doesn't exist!", ephemeral=True)
        return
    
    giveaway_data = active_giveaways[message_id]
    if giveaway_data['host_id'] != interaction.user.id and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You don't have permission to end this giveaway!", ephemeral=True)
        return
    
    await interaction.response.send_message("Ending giveaway...", ephemeral=True)
    await end_giveaway(message_id)

# Run the bot
bot.run(DISCORD_BOT_TOKEN)
