import discord
import os
import json
import asyncio
import re
from pathlib import Path
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from dotenv import load_dotenv
from datetime import datetime

# --- Load env and config ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
CONFIG_FILE = "config.json"

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

# --- Setup logs ---
LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)
msg_log_path = os.path.join(LOGS_DIR, "message_logs.log")
user_log_path = os.path.join(LOGS_DIR, "user_logs.log")


def setup_logging():
    import logging
    from logging.handlers import RotatingFileHandler
    from datetime import datetime

    # Create date-based directory structure
    current_datetime = datetime.now()
    date_hour_dir = os.path.join(LOGS_DIR, current_datetime.strftime('%Y-%m-%d_%H'))
    os.makedirs(date_hour_dir, exist_ok=True)

    # Define log paths with date-based directory
    msg_log_path = os.path.join(date_hour_dir, "message_logs.log")
    user_log_path = os.path.join(date_hour_dir, "user_logs.log")

    # Configure rotating log files with UTF-8 encoding
    msg_handler = RotatingFileHandler(msg_log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8')
    user_handler = RotatingFileHandler(user_log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8')

    formatter = logging.Formatter('%(asctime)s - %(message)s')
    msg_handler.setFormatter(formatter)
    user_handler.setFormatter(formatter)

    msg_logger = logging.getLogger('message_log')
    user_logger = logging.getLogger('user_log')

    msg_logger.setLevel(logging.INFO)
    user_logger.setLevel(logging.INFO)

    msg_logger.propagate = False
    user_logger.propagate = False

    # Clear any existing handlers
    if msg_logger.handlers:
        msg_logger.handlers.clear()
    if user_logger.handlers:
        user_logger.handlers.clear()

    msg_logger.addHandler(msg_handler)
    user_logger.addHandler(user_handler)

    return msg_logger, user_logger, msg_log_path, user_log_path


msg_logger, user_logger, msg_log_path, user_log_path = setup_logging()

# --- Init bot ---
intents = discord.Intents.all()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


# --- Utils ---
def save_config():
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(CONFIG, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")


def log_to_file(path, content):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"Error writing to log {path}: {e}")


def keyword_match(text):
    return any(k.lower() in text.lower() for k in CONFIG["search_keywords"])


def is_admin(ctx):
    return ctx.author.guild_permissions.administrator


def format_time_interval(minutes):
    """Format time interval in appropriate units"""
    if minutes < 1:
        # Less than a minute, show seconds
        seconds = int(minutes * 60)
        return f"{seconds} seconds"
    elif minutes < 60:
        # Less than an hour, show minutes
        return f"{minutes} minutes"
    elif minutes < 1440:  # 24 hours
        # Less than a day, show hours and minutes
        hours = int(minutes // 60)
        mins = int(minutes % 60)
        if mins == 0:
            return f"{hours} hours"
        else:
            return f"{hours} hours, {mins} minutes"
    elif minutes < 10080:  # 7 days
        # Less than a week, show days and hours
        days = int(minutes // 1440)
        hours = int((minutes % 1440) // 60)
        if hours == 0:
            return f"{days} days"
        else:
            return f"{days} days, {hours} hours"
    else:
        # More than a week, show weeks and days
        weeks = int(minutes // 10080)
        days = int((minutes % 10080) // 1440)
        if days == 0:
            return f"{weeks} weeks"
        else:
            return f"{weeks} weeks, {days} days"


def update_scheduled_tasks():
    """Update scheduled tasks based on current config"""
    if CONFIG.get("auto_scan_enabled", False):
        interval = CONFIG.get("auto_scan_interval_minutes", 60)

        # Convert to seconds for more precision
        seconds = int(interval * 60)

        # Need to restart the task to change interval
        if auto_scan.is_running():
            auto_scan.cancel()

        # Update interval and restart
        auto_scan.change_interval(seconds=seconds)
        auto_scan.start()

        print(f"🔄 Auto-scan enabled (every {format_time_interval(interval)})")
    else:
        if auto_scan.is_running():
            auto_scan.cancel()
            print("🛑 Auto-scan disabled")


# --- Events ---
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    print("🔍 Keywords:", ', '.join(CONFIG["search_keywords"]))
    print(f"📁 Logs at {os.path.dirname(msg_log_path)}")

    update_scheduled_tasks()
    print()

    for guild in bot.guilds:
        print(f"🔍 Scanning guild: {guild.name} ({guild.id})")
        # Chunk only if necessary
        if not guild.chunked:
            await guild.chunk()
        for member in guild.members:
            name_fields = f"{member.name} {member.display_name}"
            if keyword_match(name_fields):
                entry = f"[AUTO] {member} ({member.id}) in {guild.name}"
                user_logger.info(entry)
                if CONFIG["print_user_matches"]:
                    print(entry)


@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild:
        return
    if keyword_match(msg.content):
        entry = f"[AUTO] {msg.author} in #{msg.channel} ({msg.guild.name}) > {msg.content}"
        msg_logger.info(entry)
        if CONFIG["print_message_matches"]:
            print(entry)
    await bot.process_commands(msg)


# --- Commands ---
@bot.command(name="setkeywords")
async def set_keywords(ctx, *, words):
    if not is_admin(ctx):
        return await ctx.send("❌ You must be a server admin to use this.")
    new_words = [w.strip() for w in words.split(",") if w.strip()]
    CONFIG["search_keywords"] = new_words
    save_config()
    await ctx.send(f"✅ Keywords updated: {', '.join(new_words)}")


@bot.command(name="toggleprints")
async def toggle_prints(ctx, category: str):
    if not is_admin(ctx):
        return await ctx.send("❌ You must be a server admin to use this.")
    if category not in ["user", "message"]:
        return await ctx.send("⚠️ Use `user` or `message`.")
    key = f"print_{category}_matches"
    CONFIG[key] = not CONFIG[key]
    save_config()
    await ctx.send(f"✅ {category.capitalize()} print set to {CONFIG[key]}")


@bot.command(name="showkeywords")
async def show_keywords(ctx):
    if not is_admin(ctx):
        return await ctx.send("❌ You must be a server admin to use this.")
    await ctx.send("🔍 Current keywords:\n" + ", ".join(CONFIG["search_keywords"]))


@bot.command(name="scan")
async def scan_members(ctx, *args):
    """
    Scan server with customizable options
    Usage: !scan [--users/-u] [--messages/-m] [--all/-a]
    """
    if not is_admin(ctx):
        return await ctx.send("❌ You must be a server admin to use this.")

    # Parse arguments
    scan_users = False
    scan_messages = False

    # Check arguments (converted to lowercase for easier comparison)
    args_lower = [arg.lower() for arg in args]

    # Check for specific flags
    if "--all" in args_lower or "-a" in args_lower:
        scan_users = True
        scan_messages = True
    else:
        if "--users" in args_lower or "-u" in args_lower:
            scan_users = True
        if "--messages" in args_lower or "-m" in args_lower:
            scan_messages = True

    # If no valid flags provided, show help
    if not args or (not scan_users and not scan_messages):
        return await ctx.send(
            "⚠️ Usage: `!scan [--users/-u] [--messages/-m] [--all/-a]`\nYou must specify what to scan.")

    # Inform what's being scanned
    scan_types = []
    if scan_users:
        scan_types.append("members")
    if scan_messages:
        scan_types.append("messages")

    await ctx.send(f"🔍 Starting scan of {' and '.join(scan_types)}...")

    user_count = 0
    message_count = 0

    # Ensure guild is chunked
    if not ctx.guild.chunked:
        await ctx.guild.chunk()

    # Scan users if requested
    if scan_users:
        for member in ctx.guild.members:
            name_fields = f"{member.name} {member.display_name}"
            if keyword_match(name_fields):
                entry = f"[MANUAL-SCAN] {member} ({member.id}) in {ctx.guild.name}"
                user_logger.info(entry)
                user_count += 1

    # Scan messages if requested
    if scan_messages:
        for channel in ctx.guild.text_channels:
            try:
                # Get last 100 messages per channel
                messages = [msg async for msg in channel.history(limit=100)]
                for msg in messages:
                    if not msg.author.bot and keyword_match(msg.content):
                        entry = f"[MANUAL-SCAN] {msg.author} in #{msg.channel} ({msg.guild.name}) > {msg.content}"
                        msg_logger.info(entry)
                        message_count += 1
            except discord.Forbidden:
                # Skip channels where we don't have permissions
                continue

    # Build summary message
    results = []
    if scan_users:
        results.append(f"{user_count} matching members")
    if scan_messages:
        results.append(f"{message_count} matching messages")

    summary = f"✅ Scan complete! Found {' and '.join(results)}."
    await ctx.send(summary)
    print(f"\n{summary}\n")


# Define search cooldowns dictionary
search_cooldowns = {}

# Global search cancellation flag
search_cancelled = False


@bot.command(name="search")
async def search_messages(ctx, *args):
    """Search for messages containing a keyword with filters"""
    global search_cancelled, search_cooldowns

    # Check if this is a cancellation request
    if len(args) == 1 and args[0].lower() == "cancel":
        if hasattr(search_messages, "is_running") and search_messages.is_running:
            search_cancelled = True
            await ctx.send("⏹️ Attempting to cancel the current search... Please wait.")
            return
        else:
            await ctx.send("ℹ️ No search is currently running.")
            return

    if not is_admin(ctx):
        return await ctx.send("❌ You must be a server admin to use this.")

    search_stats["total_searches"] += 1

    guild_name = ctx.guild.name
    if guild_name not in search_stats["searches_by_guild"]:
        search_stats["searches_by_guild"][guild_name] = 0
    search_stats["searches_by_guild"][guild_name] += 1

    user_name = f"{ctx.author.name}"
    if user_name not in search_stats["searches_by_user"]:
        search_stats["searches_by_user"][user_name] = 0
    search_stats["searches_by_user"][user_name] += 1

    # Global execution tracker
    if not hasattr(search_messages, "is_running"):
        search_messages.is_running = False

    if search_messages.is_running:
        return await ctx.send(
            "⚠️ A search is already running on the server. Please wait for it to complete or use `!search cancel` to stop it.")

    # Reset cancellation flag for new search
    search_cancelled = False

    # Parse arguments
    deep_search = False
    query_limit = 500  # Default limit
    custom_query = False
    include_channels = []  # Channels to specifically include
    exclude_channels = []  # Channels to exclude

    # Process arguments
    processed_args = []
    i = 0
    while i < len(args):
        # Check for deep search flag
        if args[i].lower() in ("--all", "-a", "--a"):
            deep_search = True
            query_limit = None  # Unlimited search
            i += 1
            continue

        # Check for custom query limit flag
        elif i + 1 < len(args) and args[i].lower() in ("--q", "--query"):
            try:
                limit_str = args[i + 1].lower()
                # Handle k/m suffixes (e.g., 100k = 100,000)
                if limit_str.endswith('k'):
                    query_limit = int(float(limit_str[:-1]) * 1000)
                elif limit_str.endswith('m'):
                    query_limit = int(float(limit_str[:-1]) * 1000000)
                else:
                    query_limit = int(limit_str)

                custom_query = True
                deep_search = query_limit > 1000  # Consider deep if over 1000 messages
                i += 2
                continue
            except (ValueError, IndexError):
                return await ctx.send("⚠️ Invalid query limit format. Example: `--q 10k` for 10,000 messages")

        # Check for include channels flag
        elif args[i].lower() in ("--in", "--channel"):
            if i + 1 >= len(args):
                return await ctx.send("⚠️ Please specify channel(s) after --in/--channel flag.")

            # Extract channel mentions or IDs
            channels_arg = args[i + 1]
            for channel_mention in channels_arg.split(','):
                channel_mention = channel_mention.strip()
                try:
                    # Extract channel ID from mention format <#123456789>
                    if channel_mention.startswith("<#") and channel_mention.endswith(">"):
                        channel_id = int(channel_mention[2:-1])
                        channel = ctx.guild.get_channel(channel_id)
                    else:
                        # Try direct ID
                        channel = ctx.guild.get_channel(int(channel_mention))

                    if channel and isinstance(channel, discord.TextChannel):
                        include_channels.append(channel)
                except (ValueError, TypeError):
                    pass

            if not include_channels:
                return await ctx.send("⚠️ No valid channels found. Use #channel-mentions or channel IDs.")

            i += 2
            continue

        # Check for exclude channels flag
        elif args[i].lower() in ("--exclude", "--not"):
            if i + 1 >= len(args):
                return await ctx.send("⚠️ Please specify channel(s) after --exclude/--not flag.")

            # Extract channel mentions or IDs
            channels_arg = args[i + 1]
            for channel_mention in channels_arg.split(','):
                channel_mention = channel_mention.strip()
                try:
                    # Extract channel ID from mention format <#123456789>
                    if channel_mention.startswith("<#") and channel_mention.endswith(">"):
                        channel_id = int(channel_mention[2:-1])
                        channel = ctx.guild.get_channel(channel_id)
                    else:
                        # Try direct ID
                        channel = ctx.guild.get_channel(int(channel_mention))

                    if channel and isinstance(channel, discord.TextChannel):
                        exclude_channels.append(channel)
                except (ValueError, TypeError):
                    pass

            if not exclude_channels:
                return await ctx.send("⚠️ No valid channels found to exclude. Use #channel-mentions or channel IDs.")

            i += 2
            continue

        # Keep other arguments
        processed_args.append(args[i])
        i += 1

    # Check for cooldown on deep searches
    if deep_search or custom_query:
        search_stats["deep_searches"] += 1
        guild_id = ctx.guild.id
        current_time = datetime.now()
        if guild_id in search_cooldowns:
            time_diff = (current_time - search_cooldowns[guild_id]).total_seconds()
            if time_diff < 600:  # 10 minutes cooldown
                minutes = int((600 - time_diff) // 60)
                seconds = int((600 - time_diff) % 60)
                return await ctx.send(f"⚠️ Deep search on cooldown! Try again in {minutes}m {seconds}s.")

    # First argument should be a user mention or ID
    if not processed_args:
        return await ctx.send(
            "⚠️ Usage: `!search @user keyword [--a/--all] [--q limit] [--in #channel1,#channel2] [--exclude #channel3]`")

    try:
        # Try to extract user from first argument
        user_arg = processed_args[0]
        if user_arg.startswith("<@") and user_arg.endswith(">"):
            user_id = user_arg[2:-1]
            if user_id.startswith("!"):
                user_id = user_id[1:]
        else:
            user_id = user_arg

        user = await bot.fetch_user(int(user_id))

        # Rest of args is the keyword
        if len(processed_args) > 1:
            keyword = " ".join(processed_args[1:])
        else:
            return await ctx.send("⚠️ Usage: `!search @user keyword [options]`")

    except Exception:
        return await ctx.send("⚠️ Invalid user format. Use @mention or user ID.")

    # Set search operation running state
    search_messages.is_running = True

    try:
        # Prepare search channels
        search_channels = []
        if include_channels:
            search_channels = include_channels
        else:
            search_channels = [c for c in ctx.guild.text_channels if c not in exclude_channels]

        total_channels = len(search_channels)

        # Post search status message with channel info
        search_msg_prefix = ""
        if include_channels:
            channel_names = ", ".join([f"#{c.name}" for c in include_channels])
            search_msg_prefix = f"in {channel_names} "
        elif exclude_channels:
            channel_names = ", ".join([f"#{c.name}" for c in exclude_channels])
            search_msg_prefix = f"excluding {channel_names} "

        if deep_search:
            # Send a different message if user specified a quantity
            if custom_query:
                status_msg = await ctx.send(
                    f"🔍 Deep searching {search_msg_prefix}for up to {query_limit:,} messages from {user.name} containing `{keyword}`. This may take a while...")
            else:
                status_msg = await ctx.send(
                    f"🔍 Deep searching {search_msg_prefix}for all messages from {user.name} containing `{keyword}`. This may take a while...")
            # Set cooldown timestamp
            search_cooldowns[ctx.guild.id] = datetime.now()
        elif custom_query:
            status_msg = await ctx.send(
                f"🔍 Searching {search_msg_prefix}for up to {query_limit:,} messages from {user.name} containing `{keyword}`...")
            # Set cooldown if it's a large query
            if query_limit > 1000:
                search_cooldowns[ctx.guild.id] = datetime.now()
        else:
            status_msg = await ctx.send(
                f"🔍 Searching {search_msg_prefix}for recent messages from {user.name} containing `{keyword}`...")

        found_messages = []
        total_searched = 0
        start_time = datetime.now()
        last_update_time = start_time
        channels_searched = 0

        # Search through the selected channels
        for channel in search_channels:
            channels_searched += 1
            channel_searched = 0

            # Check if search was cancelled
            if search_cancelled:
                await status_msg.edit(
                    content=f"🛑 Search cancelled after checking {total_searched:,} messages in {channels_searched}/{total_channels} channels.")
                return

            try:
                # Get message history with the specified limit
                async for msg in channel.history(limit=query_limit):
                    total_searched += 1
                    channel_searched += 1

                    # Check if search was cancelled (check periodically to avoid overhead)
                    if search_cancelled and total_searched % 100 == 0:
                        await status_msg.edit(
                            content=f"🛑 Search cancelled after checking {total_searched:,} messages in {channels_searched}/{total_channels} channels.")
                        return

                    # Skip bot messages
                    if msg.author.bot:
                        continue

                    # Check for the specific user
                    if msg.author.id != user.id:
                        continue

                    # Check keyword match
                    if keyword.lower() in msg.content.lower():
                        found_messages.append((msg, channel))

                        # Limit results to prevent Discord message limits
                        max_results = 15
                        if len(found_messages) >= max_results:
                            break

                # Break search if we've reached the limit
                if len(found_messages) >= 15:
                    break

                # Update status more frequently for deep searches
                current_time = datetime.now()
                time_diff = (current_time - last_update_time).total_seconds()

                # Update status every 3 seconds or every 500 messages, whichever comes first
                if (deep_search or custom_query) and (time_diff > 3 or total_searched % 500 == 0):
                    elapsed = (current_time - start_time).total_seconds()
                    progress_percent = (channels_searched / total_channels) * 100

                    update_msg = (f"🔍 Searching... Checked {total_searched:,} messages "
                                  f"({channels_searched}/{total_channels} channels, {progress_percent:.1f}%) "
                                  f"in {elapsed:.1f}s... Found {len(found_messages)} matches so far.")

                    # Add cancellation hint
                    update_msg += "\n💡 Use `!search cancel` to stop this search."

                    await status_msg.edit(content=update_msg)
                    last_update_time = current_time

            except discord.Forbidden:
                # Skip channels where we don't have permissions
                continue

        # Calculate search time
        search_time = (datetime.now() - start_time).total_seconds()

        if not found_messages:
            await status_msg.edit(
                content=f"❌ No messages found from {user.name} containing '{keyword}'. Searched {total_searched:,} messages in {search_time:.1f}s.")
        else:
            # Format results for Discord message
            result = f"✅ Found {len(found_messages)} messages from {user.name} containing '{keyword}' (searched {total_searched:,} messages in {search_time:.1f}s):\n\n"

            for i, (msg, channel) in enumerate(found_messages, 1):
                # Format timestamp nicely
                timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S')

                # Format message content (truncate if too long)
                content = msg.content
                if len(content) > 500:
                    content = content[:497] + "..."

                result += f"{i}. **#{channel.name}** ({timestamp}):\n{content}\n\n"

                # Handle Discord message length limits
                if len(result) > 1800:
                    result = result[:1800] + "...\n(results truncated due to length)"
                    break

            await status_msg.edit(content=result)
            print(
                f"Searched {total_searched:,} messages in {ctx.guild.name} in {search_time:.1f}s. Found {len(found_messages)} matches.")

    finally:
        # Calculate search time
        search_time = (datetime.now() - start_time).total_seconds()

        # Update search stats
        search_stats["total_messages_searched"] += total_searched
        search_stats["search_time_total"] += search_time

        # Record if search was cancelled
        if search_cancelled:
            search_stats["cancelled_searches"] += 1

        # Set last search info
        search_stats["last_search"] = {
            "user": user.name,
            "keyword": keyword,
            "messages": total_searched,
            "time": search_time,
            "matches": len(found_messages),
            "guild": ctx.guild.name
        }

        # Update match counter
        search_stats["total_matches_found"] += len(found_messages)

        # Check if this is the largest search
        if total_searched > search_stats["largest_search"]["messages"]:
            search_stats["largest_search"] = {
                "messages": total_searched,
                "time": search_time,
                "keyword": keyword,
                "guild": ctx.guild.name
            }

        save_search_stats()

        # Always reset running state and cancellation flag when finished
        search_messages.is_running = False
        search_cancelled = False


# Handle cooldown error
@search_messages.error
async def search_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        remaining = int(error.retry_after)
        minutes = remaining // 60
        seconds = remaining % 60
        await ctx.send(f"⚠️ Command on cooldown! Try again in {minutes}m {seconds}s.")


STATS_FILE = "search_stats.json"


def load_search_stats():
    """Load search statistics from file if it exists"""
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r', encoding='utf-8') as f:
                loaded_stats = json.load(f)
                return loaded_stats
        else:
            # Return default stats structure if file doesn't exist
            return {
                "total_searches": 0,
                "total_messages_searched": 0,
                "total_matches_found": 0,
                "cancelled_searches": 0,
                "deep_searches": 0,
                "search_time_total": 0,
                "searches_by_guild": {},
                "searches_by_user": {},
                "last_search": None,
                "largest_search": {"messages": 0, "time": 0, "keyword": "", "guild": ""}
            }
    except Exception as e:
        print(f"Error loading search stats: {e}")
        # Return default stats structure on error
        return {
            "total_searches": 0,
            "total_messages_searched": 0,
            "total_matches_found": 0,
            "cancelled_searches": 0,
            "deep_searches": 0,
            "search_time_total": 0,
            "searches_by_guild": {},
            "searches_by_user": {},
            "last_search": None,
            "largest_search": {"messages": 0, "time": 0, "keyword": "", "guild": ""}
        }


# Global dictionaries for tracking search stats
search_stats = load_search_stats()


def save_search_stats():
    """Save current search statistics to file"""
    try:
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(search_stats, f, indent=2)
    except Exception as e:
        print(f"Error saving search stats: {e}")


@bot.command(name="searchstats")
async def search_stats_command(ctx):
    """Show statistics about searches performed"""
    if not is_admin(ctx):
        return await ctx.send("❌ You must be a server admin to use this.")

    global search_stats

    # No stats available
    if search_stats["total_searches"] == 0:
        return await ctx.send("ℹ️ No search statistics available yet.")

    # Calculate average time and messages
    avg_time = search_stats["search_time_total"] / search_stats["total_searches"]
    avg_messages = search_stats["total_messages_searched"] / search_stats["total_searches"]

    # Create embed with stats
    embed = discord.Embed(
        title="🔍 Search Statistics",
        color=0x3498db,
        description="Statistics about searches performed with this bot"
    )

    # General stats
    embed.add_field(
        name="General Stats",
        value=f"• Total searches: **{search_stats['total_searches']}**\n"
              f"• Messages searched: **{search_stats['total_messages_searched']:,}**\n"
              f"• Matches found: **{search_stats['total_matches_found']}**\n"
              f"• Deep searches: **{search_stats['deep_searches']}**\n"
              f"• Cancelled searches: **{search_stats['cancelled_searches']}**",
        inline=False
    )

    # Performance stats
    embed.add_field(
        name="Performance",
        value=f"• Average messages per search: **{avg_messages:,.1f}**\n"
              f"• Average search time: **{avg_time:.2f}s**\n"
              f"• Total search time: **{search_stats['search_time_total']:.2f}s**",
        inline=False
    )

    # Last search info
    if search_stats["last_search"]:
        last = search_stats["last_search"]
        embed.add_field(
            name="Last Search",
            value=f"• User: **{last['user']}**\n"
                  f"• Keyword: **{last['keyword']}**\n"
                  f"• Messages: **{last['messages']:,}**\n"
                  f"• Time: **{last['time']:.2f}s**\n"
                  f"• Matches: **{last['matches']}**\n"
                  f"• Guild: **{last['guild']}**",
            inline=False
        )

    # Largest search info
    if search_stats["largest_search"]["messages"] > 0:
        largest = search_stats["largest_search"]
        embed.add_field(
            name="Largest Search",
            value=f"• Messages: **{largest['messages']:,}**\n"
                  f"• Time: **{largest['time']:.2f}s**\n"
                  f"• Keyword: **{largest['keyword']}**\n"
                  f"• Guild: **{largest['guild']}**",
            inline=False
        )

    # Most frequent searchers
    if search_stats["searches_by_user"]:
        top_users = sorted(search_stats["searches_by_user"].items(), key=lambda x: x[1], reverse=True)[:5]
        users_text = "\n".join([f"• **{user}**: {count} searches" for user, count in top_users])
        embed.add_field(name="Top Searchers", value=users_text, inline=False)

    # Most searched servers
    if search_stats["searches_by_guild"]:
        top_guilds = sorted(search_stats["searches_by_guild"].items(), key=lambda x: x[1], reverse=True)[:5]
        guilds_text = "\n".join([f"• **{guild}**: {count} searches" for guild, count in top_guilds])
        embed.add_field(name="Most Searched Servers", value=guilds_text, inline=False)

    # Footer - update to show stats are persistent
    embed.set_footer(text="Stats persist across bot restarts")

    await ctx.send(embed=embed)

    # Save stats to ensure they're synced with file
    save_search_stats()


@bot.command(name="context")
async def get_context(ctx, message_id: int = None, lines: int = 5):
    """Get context around a specific message"""
    if not is_admin(ctx):
        return await ctx.send("❌ You must be a server admin to use this.")

    # Check for required message ID
    if message_id is None:
        return await ctx.send("⚠️ Usage: `!context message_id [lines=5]`\nYou must provide a message ID to get context.")

    # Validate lines parameter
    if lines < 1:
        lines = 1
    elif lines > 15:  # Limit to reasonable number
        lines = 15
        await ctx.send("⚠️ Maximum context limited to 15 messages.")

    # Status message
    status_msg = await ctx.send(f"🔍 Searching for message {message_id} and retrieving {lines} messages of context...")

    # Find the message across all channels
    target_message = None
    target_channel = None

    for channel in ctx.guild.text_channels:
        try:
            # Try to fetch the specific message
            target_message = await channel.fetch_message(message_id)
            if target_message:
                target_channel = channel
                break
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            # Message not in this channel or can't access
            continue

    if not target_message:
        return await status_msg.edit(content=f"❌ Message with ID {message_id} not found in any channel.")

    # Calculate how many messages to get before and after
    before_count = lines // 2
    after_count = lines - before_count

    # Get context messages
    context_messages = []

    # Get messages before target
    try:
        # Fix: Convert async generator to list manually instead of using flatten()
        before_msgs = []
        async for msg in target_channel.history(limit=before_count, before=target_message):
            before_msgs.append(msg)
        # Reverse order to show oldest first
        before_msgs.reverse()
        context_messages.extend(before_msgs)
    except discord.HTTPException:
        pass

    # Add target message
    context_messages.append(target_message)

    # Get messages after target
    try:
        # Fix: Convert async generator to list manually instead of using flatten()
        after_msgs = []
        async for msg in target_channel.history(limit=after_count, after=target_message):
            after_msgs.append(msg)
        context_messages.extend(after_msgs)
    except discord.HTTPException:
        pass

    # Create the embed for displaying context
    embed = discord.Embed(
        title=f"Message Context in #{target_channel.name}",
        color=0x3498db,
        description=f"Context around [message]({target_message.jump_url}) from {target_message.author.name}"
    )

    # Format the messages
    context_content = ""
    for i, msg in enumerate(context_messages):
        timestamp = msg.created_at.strftime('%H:%M:%S')
        is_target = msg.id == message_id

        # Format the message differently if it's the target message
        if is_target:
            author_part = f"**→ {msg.author.name}**"
        else:
            author_part = f"{msg.author.name}"

        # Truncate long messages
        content = msg.content if len(msg.content) <= 300 else f"{msg.content[:297]}..."

        # Add message to context string
        context_content += f"[{timestamp}] {author_part}: {content}\n"

        # Add attachments if any
        if msg.attachments:
            attachment_list = ", ".join([f"[{a.filename}]({a.url})" for a in msg.attachments])
            context_content += f"📎 {attachment_list}\n"

        # Add message separator
        context_content += "\n"

    # Add context to embed
    embed.description = f"Context around [message]({target_message.jump_url}) from {target_message.author.name}\n\n{context_content}"

    # Add footer with navigation help
    embed.set_footer(text=f"Use !context {message_id} [lines] to adjust context size")

    await status_msg.edit(content=None, embed=embed)

    # Add direct jump link as a separate message for easy clicking
    await ctx.send(f"🔗 **Direct link to message:** {target_message.jump_url}")


@bot.command(name="regex")
async def regex_search(ctx, *args):
    """Search for messages using regex patterns"""
    global search_cancelled, search_cooldowns

    if not is_admin(ctx):
        return await ctx.send("❌ You must be a server admin to use this.")

    # Parse arguments
    deep_search = False
    query_limit = 500  # Default limit
    custom_query = False
    include_channels = []  # Channels to specifically include
    exclude_channels = []  # Channels to exclude

    # Process arguments
    processed_args = []
    i = 0
    while i < len(args):
        # Check for deep search flag
        if args[i].lower() in ("--all", "-a", "--a"):
            deep_search = True
            query_limit = None  # Unlimited search
            i += 1
            continue

        # Check for custom query limit flag
        elif i + 1 < len(args) and args[i].lower() in ("--q", "--query"):
            try:
                limit_str = args[i + 1].lower()
                # Handle k/m suffixes (e.g., 100k = 100,000)
                if limit_str.endswith('k'):
                    query_limit = int(float(limit_str[:-1]) * 1000)
                elif limit_str.endswith('m'):
                    query_limit = int(float(limit_str[:-1]) * 1000000)
                else:
                    query_limit = int(limit_str)

                custom_query = True
                deep_search = query_limit > 1000  # Consider deep if over 1000 messages
                i += 2
                continue
            except (ValueError, IndexError):
                return await ctx.send("⚠️ Invalid query limit format. Example: `--q 10k` for 10,000 messages")

        # Check for include channels flag
        elif args[i].lower() in ("--in", "--channel"):
            if i + 1 >= len(args):
                return await ctx.send("⚠️ Please specify channel(s) after --in/--channel flag.")

            # Extract channel mentions or IDs
            channels_arg = args[i + 1]
            for channel_mention in channels_arg.split(','):
                channel_mention = channel_mention.strip()
                try:
                    if channel_mention.startswith("<#") and channel_mention.endswith(">"):
                        channel_id = int(channel_mention[2:-1])
                    else:
                        channel_id = int(channel_mention)

                    channel = ctx.guild.get_channel(channel_id)
                    if channel and isinstance(channel, discord.TextChannel):
                        include_channels.append(channel)
                except (ValueError, TypeError):
                    pass

            if not include_channels:
                return await ctx.send("⚠️ No valid channels found. Use #channel-mentions or channel IDs.")

            i += 2
            continue

        # Check for exclude channels flag
        elif args[i].lower() in ("--exclude", "--not"):
            if i + 1 >= len(args):
                return await ctx.send("⚠️ Please specify channel(s) after --exclude/--not flag.")

            # Extract channel mentions or IDs
            channels_arg = args[i + 1]
            for channel_mention in channels_arg.split(','):
                channel_mention = channel_mention.strip()
                try:
                    if channel_mention.startswith("<#") and channel_mention.endswith(">"):
                        channel_id = int(channel_mention[2:-1])
                    else:
                        channel_id = int(channel_mention)

                    channel = ctx.guild.get_channel(channel_id)
                    if channel and isinstance(channel, discord.TextChannel):
                        exclude_channels.append(channel)
                except (ValueError, TypeError):
                    pass

            if not exclude_channels:
                return await ctx.send("⚠️ No valid channels found to exclude. Use #channel-mentions or channel IDs.")

            i += 2
            continue

        # Keep other arguments
        processed_args.append(args[i])
        i += 1

    # Check for required user and pattern
    if len(processed_args) < 2:
        return await ctx.send("⚠️ Usage: `!regex @user pattern [options]`\nExample: `!regex @user \"\\b\\w+ing\\b\"`")

    # Extract user
    try:
        user_arg = processed_args[0]
        if user_arg.startswith("<@") and user_arg.endswith(">"):
            user_id = user_arg[2:-1]
            if user_id.startswith("!"):
                user_id = user_id[1:]
        else:
            user_id = user_arg

        user = await bot.fetch_user(int(user_id))

        # Rest of args is the pattern
        regex_pattern = " ".join(processed_args[1:])

    except Exception as e:
        return await ctx.send(f"⚠️ Error: {e}\nUse @mention or user ID.")

    # Compile regex pattern
    try:
        pattern = re.compile(regex_pattern, re.IGNORECASE)
    except re.error as e:
        return await ctx.send(f"⚠️ Invalid regex pattern: {e}")

    # Check cooldown for deep searches
    if deep_search or custom_query:
        guild_id = ctx.guild.id
        current_time = datetime.now()
        if guild_id in search_cooldowns:
            time_diff = (current_time - search_cooldowns[guild_id]).total_seconds()
            if time_diff < 600:  # 10 minutes cooldown
                minutes = int((600 - time_diff) // 60)
                seconds = int((600 - time_diff) % 60)
                return await ctx.send(f"⚠️ Deep search on cooldown! Try again in {minutes}m {seconds}s.")

    # Status message based on search type
    search_msg_prefix = ""
    if include_channels:
        channel_names = ", ".join([f"#{c.name}" for c in include_channels])
        search_msg_prefix = f"in {channel_names} "
    elif exclude_channels:
        channel_names = ", ".join([f"#{c.name}" for c in exclude_channels])
        search_msg_prefix = f"excluding {channel_names} "

    if deep_search:
        status_msg = await ctx.send(
            f"🔍 Deep regex searching {search_msg_prefix}for pattern `{regex_pattern}` in messages from {user.name}. This may take a while...")
        search_cooldowns[ctx.guild.id] = datetime.now()
    else:
        status_msg = await ctx.send(
            f"🔍 Regex searching {search_msg_prefix}for pattern `{regex_pattern}` in recent messages from {user.name}...")

    # Prepare search channels
    search_channels = []
    if include_channels:
        search_channels = include_channels
    else:
        search_channels = [c for c in ctx.guild.text_channels if c not in exclude_channels]

    total_channels = len(search_channels)

    found_messages = []
    total_searched = 0
    start_time = datetime.now()
    last_update_time = start_time
    channels_searched = 0

    # Search through channels
    for channel in search_channels:
        channels_searched += 1

        # Check if search was cancelled
        if search_cancelled:
            await status_msg.edit(
                content=f"🛑 Search cancelled after checking {total_searched:,} messages in {channels_searched}/{total_channels} channels.")
            return

        try:
            # Get message history with the specified limit
            async for msg in channel.history(limit=query_limit):
                total_searched += 1

                # Check if message is from the specified user
                if msg.author.id == user.id:
                    # Check for regex match in message content
                    if pattern.search(msg.content):
                        found_messages.append((msg, channel))

                # Break search if we've reached the limit of matches
                if len(found_messages) >= 15:
                    break

                # Update status more frequently for deep searches
                current_time = datetime.now()
                time_diff = (current_time - last_update_time).total_seconds()

                # Update status every 3 seconds or every 500 messages
                if (deep_search or custom_query) and (time_diff > 3 or total_searched % 500 == 0):
                    await status_msg.edit(
                        content=f"🔍 Regex searching... Checked {total_searched:,} messages in {channels_searched}/{total_channels} channels. Found {len(found_messages)} matches so far.")
                    last_update_time = current_time

        except discord.Forbidden:
            # Skip channels where we don't have permissions
            continue

    # Calculate search time
    search_time = (datetime.now() - start_time).total_seconds()

    if not found_messages:
        await status_msg.edit(
            content=f"❌ No regex matches found for pattern `{regex_pattern}` in messages from {user.name}. Searched {total_searched:,} messages in {search_time:.1f}s.")
    else:
        # Format results
        result = f"✅ Found {len(found_messages)} regex matches for pattern `{regex_pattern}` from {user.name} (searched {total_searched:,} messages in {search_time:.1f}s):\n\n"

        for i, (msg, channel) in enumerate(found_messages, 1):
            # Format timestamp
            timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S')

            # Format message content (truncate if too long)
            content = msg.content
            if len(content) > 500:
                content = content[:497] + "..."

            # Add message jump URL for easy navigation
            result += f"{i}. **#{channel.name}** ({timestamp}):\n{content}\n[Jump to message]({msg.jump_url})\n\n"

            # Handle Discord message length limits
            if len(result) > 1800:
                result = result[:1800] + "...\n(results truncated due to length)"
                break

        await status_msg.edit(content=result)

    # Update global search stats
    if 'search_stats' in globals():
        search_stats["total_searches"] += 1
        search_stats["total_messages_searched"] += total_searched
        search_stats["total_matches_found"] += len(found_messages)
        search_stats["search_time_total"] += search_time

        # Update guild stats
        guild_name = ctx.guild.name
        if guild_name not in search_stats["searches_by_guild"]:
            search_stats["searches_by_guild"][guild_name] = 0
        search_stats["searches_by_guild"][guild_name] += 1

        # Update user stats
        user_name = f"{ctx.author.name}"
        if user_name not in search_stats["searches_by_user"]:
            search_stats["searches_by_user"][user_name] = 0
        search_stats["searches_by_user"][user_name] += 1

        save_search_stats()


@bot.command(name="export")
async def export_results(ctx, *args):
    """Export search results to a file"""
    global search_cancelled, search_cooldowns

    if not is_admin(ctx):
        return await ctx.send("❌ You must be a server admin to use this.")

    # Parse arguments similar to search command
    deep_search = False
    query_limit = 500  # Default limit
    custom_query = False
    include_channels = []
    exclude_channels = []

    # Process arguments
    processed_args = []
    i = 0
    while i < len(args):
        # Handle deep search flag
        if args[i].lower() in ("--all", "-a", "--a"):
            deep_search = True
            query_limit = None
            i += 1
            continue

        # Handle custom query limit
        elif i + 1 < len(args) and args[i].lower() in ("--q", "--query"):
            try:
                limit_str = args[i + 1].lower()
                if limit_str.endswith('k'):
                    query_limit = int(float(limit_str[:-1]) * 1000)
                elif limit_str.endswith('m'):
                    query_limit = int(float(limit_str[:-1]) * 1000000)
                else:
                    query_limit = int(limit_str)

                custom_query = True
                deep_search = query_limit > 1000
                i += 2
                continue
            except (ValueError, IndexError):
                return await ctx.send("⚠️ Invalid query limit format. Example: `--q 10k` for 10,000 messages")

        # Handle include channels flag
        elif args[i].lower() in ("--in", "--channel"):
            if i + 1 >= len(args):
                return await ctx.send("⚠️ Please specify channel(s) after --in/--channel flag.")

            channels_arg = args[i + 1]
            for channel_mention in channels_arg.split(','):
                channel_mention = channel_mention.strip()
                try:
                    if channel_mention.startswith("<#") and channel_mention.endswith(">"):
                        channel_id = int(channel_mention[2:-1])
                    else:
                        channel_id = int(channel_mention)

                    channel = ctx.guild.get_channel(channel_id)
                    if channel and isinstance(channel, discord.TextChannel):
                        include_channels.append(channel)
                except (ValueError, TypeError):
                    pass

            if not include_channels:
                return await ctx.send("⚠️ No valid channels found. Use #channel-mentions or channel IDs.")

            i += 2
            continue

        # Handle exclude channels flag
        elif args[i].lower() in ("--exclude", "--not"):
            if i + 1 >= len(args):
                return await ctx.send("⚠️ Please specify channel(s) after --exclude/--not flag.")

            channels_arg = args[i + 1]
            for channel_mention in channels_arg.split(','):
                channel_mention = channel_mention.strip()
                try:
                    if channel_mention.startswith("<#") and channel_mention.endswith(">"):
                        channel_id = int(channel_mention[2:-1])
                    else:
                        channel_id = int(channel_mention)

                    channel = ctx.guild.get_channel(channel_id)
                    if channel and isinstance(channel, discord.TextChannel):
                        exclude_channels.append(channel)
                except (ValueError, TypeError):
                    pass

            if not exclude_channels:
                return await ctx.send("⚠️ No valid channels found to exclude. Use #channel-mentions or channel IDs.")

            i += 2
            continue

        # Keep other arguments
        processed_args.append(args[i])
        i += 1

    # First argument should be a user mention or ID
    if not processed_args:
        return await ctx.send(
            "⚠️ Usage: `!export @user keyword [--a/--all] [--q limit] [--in #channel1,#channel2] [--exclude #channel3]`")

    try:
        # Extract user from first argument
        user_arg = processed_args[0]
        if user_arg.startswith("<@") and user_arg.endswith(">"):
            user_id = user_arg[2:-1]
            if user_id.startswith("!"):
                user_id = user_id[1:]
        else:
            user_id = user_arg

        user = await bot.fetch_user(int(user_id))

        # Rest of args is the keyword
        if len(processed_args) > 1:
            keyword = " ".join(processed_args[1:])
        else:
            return await ctx.send("⚠️ Usage: `!export @user keyword [options]`")

    except Exception:
        return await ctx.send("⚠️ Invalid user format. Use @mention or user ID.")

    # Create exports directory if it doesn't exist
    exports_dir = "exports"
    os.makedirs(exports_dir, exist_ok=True)

    # Inform user that export is starting
    status_msg = await ctx.send(
        f"⏳ Starting export of messages from {user.name} containing `{keyword}`... This may take a while.")

    # Prepare search channels
    search_channels = []
    if include_channels:
        search_channels = include_channels
    else:
        search_channels = [c for c in ctx.guild.text_channels if c not in exclude_channels]

    total_channels = len(search_channels)

    # Generate unique filename with timestamp and sanitized keyword
    safe_keyword = "".join([c if c.isalnum() else "_" for c in keyword])[:20]  # Limit length
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{exports_dir}/search_{user.name}_{safe_keyword}_{timestamp}.txt"

    found_messages = []
    total_searched = 0
    start_time = datetime.now()

    # Open file for writing as we go (immediately write results rather than collecting all first)
    with open(filename, "w", encoding="utf-8") as f:
        # Write header with search parameters
        f.write(f"=== DISCORD MESSAGE SEARCH EXPORT ===\n")
        f.write(f"Search Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Server: {ctx.guild.name}\n")
        f.write(f"User: {user.name} (ID: {user.id})\n")
        f.write(f"Keyword: \"{keyword}\"\n")

        if include_channels:
            channel_names = ", ".join([f"#{c.name}" for c in include_channels])
            f.write(f"Searched in channels: {channel_names}\n")
        elif exclude_channels:
            channel_names = ", ".join([f"#{c.name}" for c in exclude_channels])
            f.write(f"Searched all channels except: {channel_names}\n")
        else:
            f.write(f"Searched all accessible channels\n")

        f.write(f"Search depth: {query_limit if query_limit else 'unlimited'} messages per channel\n")
        f.write("\n=== SEARCH RESULTS ===\n\n")

        # Search through the selected channels
        for idx, channel in enumerate(search_channels, 1):
            # Progress update every 5 channels
            if idx % 5 == 0:
                await status_msg.edit(
                    content=f"⏳ Export in progress... Searching channel {idx}/{total_channels} ({idx / total_channels * 100:.1f}%)")

            try:
                # Write channel header
                f.write(f"--- CHANNEL: #{channel.name} ---\n\n")

                # Get message history with the specified limit
                async for msg in channel.history(limit=query_limit):
                    total_searched += 1

                    # Skip bot messages
                    if msg.author.bot:
                        continue

                    # Check for the specific user
                    if msg.author.id != user.id:
                        continue

                    # Check keyword match
                    if keyword.lower() in msg.content.lower():
                        # Format timestamp nicely
                        timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S')

                        # Write to file
                        f.write(f"[{timestamp}] {msg.author.name}:\n")
                        f.write(f"{msg.content}\n")
                        if msg.attachments:
                            f.write(f"Attachments: {', '.join([a.url for a in msg.attachments])}\n")
                        f.write(f"Message link: https://discord.com/channels/{ctx.guild.id}/{channel.id}/{msg.id}\n\n")

                        # Track for stats
                        found_messages.append((msg, channel))

            except discord.Forbidden:
                f.write("Cannot access this channel (insufficient permissions)\n\n")
                continue

        # Write summary at the end
        search_time = (datetime.now() - start_time).total_seconds()
        f.write(f"\n=== SEARCH SUMMARY ===\n")
        f.write(f"Messages searched: {total_searched:,}\n")
        f.write(f"Matches found: {len(found_messages)}\n")
        f.write(f"Search time: {search_time:.2f} seconds\n")
        f.write(f"Export completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # Send the file to Discord
    await status_msg.edit(
        content=f"✅ Export complete! Found {len(found_messages)} matches in {total_searched:,} messages.")
    await ctx.send(f"📄 Here is your export file:", file=discord.File(filename))

    # Update search stats if we're tracking them
    if 'search_stats' in globals():
        search_stats["total_searches"] += 1
        search_stats["total_messages_searched"] += total_searched
        search_stats["total_matches_found"] += len(found_messages)
        search_stats["search_time_total"] += search_time

        # Update guild stats
        guild_name = ctx.guild.name
        if guild_name not in search_stats["searches_by_guild"]:
            search_stats["searches_by_guild"][guild_name] = 0
        search_stats["searches_by_guild"][guild_name] += 1

        # Update user stats
        user_name = f"{ctx.author.name}"
        if user_name not in search_stats["searches_by_user"]:
            search_stats["searches_by_user"][user_name] = 0
        search_stats["searches_by_user"][user_name] += 1

        save_search_stats()


@bot.command(name="help")
async def help_command(ctx):
    if not is_admin(ctx):
        return
    embed = discord.Embed(
        title="🛠️ Bot Commands",
        color=0x3498db,
        description="Available admin-only commands:"
    )
    embed.add_field(name="!setkeywords word1, word2...", value="Update search keywords", inline=False)
    embed.add_field(name="!toggleprints user/message", value="Toggle printed output", inline=False)
    embed.add_field(name="!showkeywords", value="Display current keywords", inline=False)
    embed.add_field(name="!scan --users/--messages/--all",
                    value="Manually scan server for matches (requires one option)", inline=False)
    embed.add_field(name="!search @user keyword [options]",
                    value="Search user messages with options:\n"
                          "• `--a/--all` for deep search\n"
                          "• `--q limit` for custom message limit (e.g. `--q 10k`)\n"
                          "• `--in #channel1,#channel2` to search only specific channels\n"
                          "• `--exclude #channel3,#channel4` to skip specific channels", inline=False)
    embed.add_field(name="!search cancel", value="Cancel a running search operation", inline=False)
    embed.add_field(name="!searchstats", value="Display statistics about searches performed", inline=False)
    embed.add_field(name="!regex @user pattern [options]",
                    value="Search using regex patterns with the same options as !search", inline=False)
    embed.add_field(name="!export @user keyword [options]",
                    value="Export search results to a text file with the same options as !search", inline=False)
    embed.add_field(name="!context message_id [lines=5]", value="Get conversation context around a specific message",
                    inline=False)
    embed.add_field(name="!autoscan on/off", value="Enable/disable periodic auto-scanning", inline=False)
    embed.add_field(name="!scaninterval <minutes>", value="Set auto-scan interval in minutes", inline=False)
    embed.add_field(name="!clearlogs today/all", value="Delete logs for today or all logs", inline=False)
    await ctx.send(embed=embed)


# --- Scheduled tasks ---
@tasks.loop(seconds=3600)  # Default interval
async def auto_scan():
    """Periodically scan all guilds for keyword matches"""
    print(f"🔄 Running scheduled auto-scan ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")

    # Force logging setup refresh to ensure we're using the current date/hour folder
    global msg_logger, user_logger, msg_log_path, user_log_path
    msg_logger, user_logger, msg_log_path, user_log_path = setup_logging()

    scan_count = 0
    message_count = 0

    for guild in bot.guilds:
        # Get members if needed
        if not guild.chunked:
            await guild.chunk()

        # Scan members
        for member in guild.members:
            name_fields = f"{member.name} {member.display_name}"
            if keyword_match(name_fields):
                entry = f"[AUTO-SCAN] {member} ({member.id}) in {guild.name}"
                user_logger.info(entry)
                scan_count += 1

        # Scan recent messages in text channels (if permissions allow)
        for channel in guild.text_channels:
            try:
                # Get last 100 messages per channel
                messages = [msg async for msg in channel.history(limit=100)]
                for msg in messages:
                    if not msg.author.bot and keyword_match(msg.content):
                        entry = f"[AUTO-SCAN] {msg.author} in #{msg.channel} ({msg.guild.name}) > {msg.content}"
                        msg_logger.info(entry)
                        message_count += 1
            except discord.Forbidden:
                # Skip channels where we don't have permissions
                continue

    # Calculate next scan time using the interval in seconds
    next_scan_time = datetime.now() + timedelta(seconds=auto_scan.seconds)
    next_scan_str = next_scan_time.strftime('%Y-%m-%d %H:%M:%S')

    print(f"✅ Auto-scan complete! Found {scan_count} matching members and {message_count} messages.")
    print(f"⏰ Next auto-scan scheduled for: {next_scan_str} (in {format_time_interval(auto_scan.seconds / 60)})")


@auto_scan.before_loop
async def before_auto_scan():
    """Wait for the bot to be ready before starting auto-scan"""
    await bot.wait_until_ready()


@bot.command(name="autoscan")
async def toggle_auto_scan(ctx, enabled: str = None):
    if not is_admin(ctx):
        return await ctx.send("❌ You must be a server admin to use this.")

    if enabled is None:
        status = "enabled" if CONFIG.get("auto_scan_enabled", False) else "disabled"
        interval = CONFIG.get("auto_scan_interval_minutes", 60)
        return await ctx.send(f"🔄 Auto-scan is {status} (interval: {format_time_interval(interval)})")

    if enabled.lower() in ("on", "true", "yes", "1"):
        CONFIG["auto_scan_enabled"] = True
        save_config()
        update_scheduled_tasks()
        interval = CONFIG.get("auto_scan_interval_minutes", 60)
        await ctx.send(f"✅ Auto-scan enabled (every {format_time_interval(interval)})")
    elif enabled.lower() in ("off", "false", "no", "0"):
        CONFIG["auto_scan_enabled"] = False
        save_config()
        update_scheduled_tasks()
        await ctx.send("❌ Auto-scan disabled")
    else:
        await ctx.send("⚠️ Use 'on' or 'off'")


@bot.command(name="scaninterval")
async def set_scan_interval(ctx, minutes: str):
    if not is_admin(ctx):
        return await ctx.send("❌ You must be a server admin to use this.")

    try:
        interval = float(minutes)

        # Check minimum value
        if interval < 0.5:
            return await ctx.send("⚠️ Interval must be at least 0.5 minutes (30 seconds)")

        # Store the interval in minutes
        CONFIG["auto_scan_interval_minutes"] = interval
        save_config()

        # Update the task
        update_scheduled_tasks()

        # Provide feedback with formatted time
        await ctx.send(f"✅ Auto-scan interval set to {format_time_interval(interval)}")

    except ValueError:
        await ctx.send("⚠️ Please provide a valid number for the interval")


@bot.command(name="clearlogs")
async def clear_logs(ctx, scope: str = "today"):
    """Clear logs based on scope (today/all)"""
    if not is_admin(ctx):
        return await ctx.send("❌ You must be a server admin to use this.")

    try:
        global msg_logger, user_logger, msg_log_path, user_log_path

        if scope.lower() == "today":
            # Get current date folder
            current_date = datetime.now().strftime('%Y-%m-%d')
            # Find all folders matching today's date
            today_folders = [folder for folder in os.listdir(LOGS_DIR)
                             if folder.startswith(current_date)]

            if not today_folders:
                return await ctx.send("ℹ️ No logs found for today.")

            count = 0
            for folder in today_folders:
                folder_path = os.path.join(LOGS_DIR, folder)
                if os.path.isdir(folder_path):
                    for file in os.listdir(folder_path):
                        os.remove(os.path.join(folder_path, file))
                        count += 1
                    os.rmdir(folder_path)

            # Refresh logging to ensure we're using a new folder
            msg_logger, user_logger, msg_log_path, user_log_path = setup_logging()

            await ctx.send(f"✅ Cleared {count} log files from today's folders.")

        elif scope.lower() == "all":
            # Confirm deletion with reaction
            confirm_msg = await ctx.send("⚠️ Are you sure you want to delete ALL logs? React with ✅ to confirm.")
            await confirm_msg.add_reaction("✅")

            def check(reaction, user):
                return user == ctx.author and str(reaction.emoji) == "✅" and reaction.message.id == confirm_msg.id

            try:
                # Wait for confirmation
                await bot.wait_for('reaction_add', timeout=30.0, check=check)

                # Delete all log folders
                count = 0
                for item in os.listdir(LOGS_DIR):
                    item_path = os.path.join(LOGS_DIR, item)
                    if os.path.isdir(item_path):
                        for file in os.listdir(item_path):
                            os.remove(os.path.join(item_path, file))
                            count += 1
                        os.rmdir(item_path)

                # Refresh logging
                msg_logger, user_logger, msg_log_path, user_log_path = setup_logging()

                await ctx.send(f"✅ Cleared {count} log files from all folders.")

            except asyncio.TimeoutError:
                await ctx.send("❌ Confirmation timed out. Logs were not deleted.")
                try:
                    await confirm_msg.delete()
                except:
                    pass

        else:
            await ctx.send("⚠️ Invalid option. Use 'today' or 'all'.")

    except Exception as e:
        await ctx.send(f"❌ Error clearing logs: {str(e)}")


try:
    bot.run(TOKEN)
except discord.LoginFailure:
    print("Error: Invalid token. Please check your .env file.")
except Exception as e:
    print(f"Error starting bot: {e}")
