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
        
        message = await channel.fetch_message(int(message_id))
        
        # Get all users who reacted with 🎉
        reactions = [r for r in message.reactions if str(r.emoji) == '🎉']
        if not reactions:
            await channel.send(f"No one entered the giveaway for **{giveaway_data['prize']}**!")
            del active_giveaways[message_id]
            save_giveaways(active_giveaways)
            return
        
        users = []
        async for user in reactions[0].users():
            if not user.bot:
                users.append(user)
        
        if not users:
            await channel.send(f"No valid entries for the giveaway of **{giveaway_data['prize']}**!")
            del active_giveaways[message_id]
            save_giveaways(active_giveaways)
            return
        
        # Pick winners
        num_winners = min(giveaway_data['winners'], len(users))
        
        if num_winners == 1:
            import random
            winner = random.choice(users)
            
            # Update winner's balance
            wallets = load_wallets()
            winner_id = str(winner.id)
            if winner_id not in wallets:
                wallets[winner_id] = {"balance": 0.0, "username": str(winner)}
            
            # Note: We don't save wallets here since this bot only reads from wallet bot
            
            embed = discord.Embed(
                title="🎉 Giveaway Ended! 🎉",
                description=f"**Prize:** {giveaway_data['prize']}\n**Winner:** {winner.mention}",
                color=discord.Color.gold()
            )
            await channel.send(embed=embed)
            await winner.send(f"Congratulations! You won **{giveaway_data['prize']}**!")
        else:
            import random
            winners = random.sample(users, num_winners)
            
            wallets = load_wallets()
            winner_mentions = []
            for winner in winners:
                winner_mentions.append(winner.mention)
                winner_id = str(winner.id)
                if winner_id not in wallets:
                    wallets[winner_id] = {"balance": 0.0, "username": str(winner)}
            
            # Note: We don't save wallets here since this bot only reads from wallet bot
            
            embed = discord.Embed(
                title="🎉 Giveaway Ended! 🎉",
                description=f"**Prize:** {giveaway_data['prize']}\n**Winners:**\n" + "\n".join(winner_mentions),
                color=discord.Color.gold()
            )
            await channel.send(embed=embed)
            
            for winner in winners:
                await winner.send(f"Congratulations! You won **{giveaway_data['prize']}**!")
        
        # Update the original message
        ended_embed = discord.Embed(
            title="🎉 GIVEAWAY ENDED 🎉",
            description=f"**Prize:** {giveaway_data['prize']}\n**Ended:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            color=discord.Color.red()
        )
        await message.edit(embed=ended_embed)
        
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
    winners="Number of winners (default: 1)"
)
async def start_giveaway(
    interaction: discord.Interaction,
    prize: str,
    duration: int,
    winners: int = 1
):
    """Start a new giveaway"""
    if duration < 1:
        await interaction.response.send_message("Duration must be at least 1 minute!", ephemeral=True)
        return
    
    if winners < 1:
        await interaction.response.send_message("Must have at least 1 winner!", ephemeral=True)
        return
    
    end_time = datetime.now() + timedelta(minutes=duration)
    
    embed = discord.Embed(
        title="🎉 GIVEAWAY 🎉",
        description=f"**Prize:** {prize}\n**Winners:** {winners}\n**Ends:** <t:{int(end_time.timestamp())}:R>\n\nReact with 🎉 to enter!",
        color=discord.Color.green()
    )
    embed.set_footer(text=f"Started by {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed)
    message = await interaction.original_response()
    await message.add_reaction('🎉')
    
    # Store giveaway data
    active_giveaways[str(message.id)] = {
        'prize': prize,
        'winners': winners,
        'end_time': end_time,
        'channel_id': interaction.channel.id,
        'host_id': interaction.user.id
    }
    save_giveaways(active_giveaways)

@bot.tree.command(name="reroll", description="Reroll a giveaway winner")
@app_commands.describe(message_id="The message ID of the ended giveaway")
async def reroll(interaction: discord.Interaction, message_id: str):
    """Reroll the winner of an ended giveaway"""
    try:
        message = await interaction.channel.fetch_message(int(message_id))
        
        # Check if it's a giveaway message
        if not message.embeds or "GIVEAWAY" not in message.embeds[0].title:
            await interaction.response.send_message("This doesn't appear to be a giveaway message!", ephemeral=True)
            return
        
        # Get reactions
        reactions = [r for r in message.reactions if str(r.emoji) == '🎉']
        if not reactions:
            await interaction.response.send_message("No reactions found on this giveaway!", ephemeral=True)
            return
        
        users = []
        async for user in reactions[0].users():
            if not user.bot:
                users.append(user)
        
        if not users:
            await interaction.response.send_message("No valid entries found!", ephemeral=True)
            return
        
        import random
        winner = random.choice(users)
        
        embed = discord.Embed(
            title="🎉 New Winner! 🎉",
            description=f"**New Winner:** {winner.mention}",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed)
        await winner.send(f"Congratulations! You won the rerolled giveaway!")
        
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