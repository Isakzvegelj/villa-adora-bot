import asyncio
import discord
import subprocess
import os
import time
import json
from datetime import datetime

# Paths
CLAW_DIR = "/Users/isakzvegelj/clawd"
INBOX_PATH = os.path.join(CLAW_DIR, "INBOX.md")
STATUS_PATH = os.path.join(CLAW_DIR, "STATUS.md")
DROP_DIR = os.path.join(CLAW_DIR, "drop")
CONFIG_PATH = os.path.join(CLAW_DIR, "ralph_config.json")
OPENCODE_BIN = "/Users/isakzvegelj/.opencode/bin/opencode"

# State
START_TIME = datetime.now()
IS_PROCESSING = False

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
    return {"discord_token": "", "channel_id": "", "whatsapp_phone": "+38640943220"}

def save_config(config_data):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(config_data, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")

def get_sys_info():
    try:
        load = os.getloadavg()[0]
        return f"CPU Load: {load:.2f}"
    except:
        return "CPU Load: Unknown"

class RalphBot(discord.Client):
    def __init__(self, bot_config, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot_config = bot_config
        self.bg_task = None

    async def setup_hook(self) -> None:
        self.bg_task = self.loop.create_task(self.monitor_loop())

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')
        cid = self.bot_config.get("channel_id")
        if cid:
            channel = self.get_channel(int(cid))
            if channel:
                await channel.send("🤖 **Ralph is online.** System re-aligned for Discord communication. Type `!help` for instructions.")
        else:
            print("Warning: No Channel ID set. Use !setchannel in a channel to bind Ralph.")

    async def on_message(self, message):
        if message.author == self.user:
            return

        content = message.content.strip()
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_bound_channel = str(message.channel.id) == self.bot_config.get("channel_id")

        # Basic Command Handling
        if content.startswith('!setchannel'):
            self.bot_config["channel_id"] = str(message.channel.id)
            save_config(self.bot_config)
            await message.channel.send(f"✅ Ralph is now bound to this channel (ID: {message.channel.id})")
            return

        # Restrict other commands and direct chat to bound channel or DMs
        if not (is_dm or is_bound_channel):
            return

        if content.startswith('!status') or content.startswith('!check'):
            await self.send_status(message.channel)

        elif content.startswith('!queue') or content.startswith('!inbox'):
            await self.send_queue(message.channel)

        elif content.startswith('!reset '):
            target = content[7:].strip().lower()
            if target == "clawd":
                await message.channel.send("♻️ Resetting Clawd service...")
                try:
                    subprocess.run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.clawdbot.gateway"], check=True)
                    await message.channel.send("✅ Clawd service reset triggered.")
                except Exception as e:
                    await message.channel.send(f"❌ Failed to reset Clawd: {e}")
            elif target == "ralph":
                await message.channel.send("♻️ Resetting Ralph service... I will be back in a few seconds.")
                os._exit(0)
            else:
                await message.channel.send(f"❓ Unknown target: `{target}`. Try `clawd` or `ralph`.")

        elif content.startswith('!setkey '):
            parts = content[8:].split(None, 1)
            if len(parts) == 2:
                key_name, key_val = parts
                if "api_keys" not in self.bot_config:
                    self.bot_config["api_keys"] = {}
                self.bot_config["api_keys"][key_name.upper()] = key_val
                save_config(self.bot_config)
                try:
                    await message.delete()
                    await message.channel.send(f"✅ Key `{key_name.upper()}` updated and command message deleted for security.")
                except:
                    await message.channel.send(f"✅ Key `{key_name.upper()}` updated. (Note: Could not auto-delete your message!)")
            else:
                await message.channel.send("❌ Usage: `!setkey <NAME> <VALUE>`")

        elif content.startswith('!listkeys'):
            keys = self.bot_config.get("api_keys", {}).keys()
            if keys:
                await message.channel.send(f"🔑 **Stored Keys:**\\n" + "\\n".join([f"- `{k}`" for k in keys]))
            else:
                await message.channel.send("Empty 🔑 keychain.")

        elif content.startswith('!model'):
            parts = content[7:].strip().split()
            if not parts:
                # Show current model
                current_model = self.bot_config.get("model", "default")
                await message.channel.send(f"🤖 **Current Model:** `{current_model}`\\n\\nUse `!model \u003cprovider/model\u003e` to change (e.g., `!model anthropic/claude-sonnet-4`).")
            else:
                # Set new model
                new_model = parts[0]
                self.bot_config["model"] = new_model
                save_config(self.bot_config)
                await message.channel.send(f"✅ **Model switched to:** `{new_model}`")


        elif content.startswith('!resume'):
            self.bot_config["api_error_paused"] = False
            save_config(self.bot_config)
            await message.channel.send("🚀 **System Resumed.** Next pulse will proceed as scheduled.")

        elif content.startswith('!task '):
            await self.add_task(message, content[6:].strip())

        elif content.startswith('!pulse'):
            await message.channel.send("⚡ Triggering manual pulse...")
            await self.trigger_heartbeat("Manual pulse requested")

        elif content.startswith('!help'):
            await self.send_help(message.channel)

        # Natural Language Handling (Chatting with Ralph/Clawd)
        elif not content.startswith('!'):
            lower_content = content.lower()
            
            if "ralph" in lower_content:
                identity = "Ralph"
                personality = "the system daemon (efficient, robotic, technical)"
            else:
                identity = "Clawd"
                personality = "an AI Familiar (warm, precise, curious lobster 🦞)"

            prompt = (
                f"You are {identity}, {personality}. The user ({message.author.name}) is talking to you. "
                f"Message: \"{content}\". "
                "Respond naturally. If they gave you a task, you MUST append it to /Users/isakzvegelj/clawd/INBOX.md using your tools and confirm to the user. "
                "If they are just chatting, respond as your personality."
            )
            await self.run_agent(message.channel, prompt, is_chat=True)

    async def add_task(self, message, task_content):
        if not task_content:
            return
        with open(INBOX_PATH, "a") as f:
            f.write(f"\n- [ ] {task_content} (Requested via Discord: {message.author.name})")
        await message.channel.send(f"📥 **Added to Clawd's queue:** `{task_content}`")
        await self.trigger_heartbeat(f"Direct Discord message: {task_content}")

    async def send_help(self, channel):
        embed = discord.Embed(title="🤖 Ralph & Clawd: Integration Guide", color=0x3498db)
        embed.description = "I am Ralph, your autonomous background daemon. I work with **Pi (Clawd)** to keep your projects moving 24/7."
        
        embed.add_field(name="💬 Natural Language", value=(
            "You can talk to us just like a friend!\n"
            "• Just send any message to chat with **Clawd**.\n"
            "• Mention **Ralph** to talk to the system daemon.\n"
            "• Tasks you give in chat are automatically queued."
        ), inline=False)

        embed.add_field(name="🎮 Core Commands", value=(
            "`!status` - View current focus, uptime, and system load.\\n"
            "`!queue` / `!inbox` - View the detailed task queue from INBOX.md.\\n"
            "`!pulse` - Force an immediate project check.\\n"
            "`!model [provider/model]` - View or switch AI model.\\n"
            "`!reset [clawd/ralph]` - Restart the specified service.\\n"
            "`!setkey [NAME] [VAL]` - Update API keys.\\n"
            "`!help` - Show this guide."
        ), inline=False)
        
        embed.add_field(name="🚀 How to Take Advantage", value=(
            "**1. Conversational Tasks:** Just say \"Clawd, please finish the breakfast app.\"\n"
            "**2. System Queries:** Ask \"Ralph, how is the system load?\"\n"
            "**3. 24/7 Autonomy:** We work while you sleep."
        ), inline=False)
        
        await channel.send(embed=embed)

    async def send_status(self, channel):
        uptime = str(datetime.now() - START_TIME).split('.')[0]
        status_text = "Processing ⚙️" if IS_PROCESSING else "Idle 🟢"
        embed = discord.Embed(title="Ralph Status Report", color=0x00ff00 if not IS_PROCESSING else 0xffff00)
        embed.add_field(name="Status", value=status_text, inline=True)
        embed.add_field(name="Uptime", value=uptime, inline=True)
        embed.add_field(name="System", value=get_sys_info(), inline=True)
        
        active_tasks = []
        if os.path.exists(INBOX_PATH):
            with open(INBOX_PATH, "r") as f:
                lines = f.readlines()
                active_tasks = [l.strip().replace("- [ ] ", "").strip() for l in lines if "- [ ]" in l]
        
        task_list = "\n".join([f"• {t}" for t in active_tasks[:10]]) if active_tasks else "No pending tasks"
        embed.add_field(name=f"Current Queue ({len(active_tasks)})", value=task_list, inline=False)
        await channel.send(embed=embed)

    async def send_queue(self, channel):
        goals = []
        queue = []
        if os.path.exists(INBOX_PATH):
            with open(INBOX_PATH, "r") as f:
                lines = f.readlines()
                # Parse high level goals and current queue
                current_section = None
                for line in lines:
                    if "## 🚀 HIGH LEVEL GOALS" in line:
                        current_section = "goals"
                    elif "## 📝 CURRENT QUEUE" in line:
                        current_section = "queue"
                    elif "## ✅ COMPLETED" in line:
                        current_section = "completed"
                    
                    if line.strip().startswith("- [ ]"):
                        task = line.strip().replace("- [ ] ", "").strip()
                        if current_section == "goals":
                            goals.append(task)
                        elif current_section == "queue":
                            queue.append(task)
        
        embed = discord.Embed(title="📋 Current Task Queue", color=0x3498db)
        
        if goals:
            embed.add_field(name="🚀 High Level Goals", value="\n".join([f"• {g}" for g in goals]), inline=False)
        
        if queue:
            # Discord has a limit of 1024 characters per field, so we might need to truncate
            task_text = ""
            for i, t in enumerate(queue):
                line = f"{i+1}. {t}\n"
                if len(task_text) + len(line) < 1000:
                    task_text += line
                else:
                    task_text += f"... and {len(queue) - i} more."
                    break
            embed.add_field(name="📝 Active Tasks", value=task_text or "No active tasks", inline=False)
        
        if not goals and not queue:
            embed.description = "The queue is currently empty! 🏖️"
            
        await channel.send(embed=embed)

    async def run_agent(self, channel, prompt, is_chat=False):
        global IS_PROCESSING
        if IS_PROCESSING:
            if is_chat and channel:
                await channel.send("⌛ I'm currently busy with another task. Please wait a moment...")
            return

        # Check if we are in a "paused" state due to API error
        if self.bot_config.get("api_error_paused", False):
            if channel:
                await channel.send("⚠️ **System Paused:** System is paused due to a previous API error. Use `!resume` after fixing the key.")
            return

        IS_PROCESSING = True
        
        # Determine if we should show typing
        typing_ctx = channel.typing() if is_chat and channel else None

        try:
            if typing_ctx:
                await typing_ctx.__aenter__()

            if channel and not is_chat:
                await channel.send("⚡ **Pulse Triggered...**")

            # Prepare environment with stored API keys
            env = os.environ.copy()
            api_keys = self.bot_config.get("api_keys", {})
            env.update(api_keys)

            # Log the command for debugging
            print(f"[DEBUG] Running: {OPENCODE_BIN} run \"{prompt[:100]}...\"")
            print(f"[DEBUG] Working directory: {CLAW_DIR}")

            # Build command with optional model parameter
            cmd_args = [OPENCODE_BIN, "run"]
            
            # Add model if specified in config
            model = self.bot_config.get("model")
            if model:
                cmd_args.extend(["--model", model])
                print(f"[DEBUG] Using model: {model}")
            
            cmd_args.append(prompt)

            process = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=CLAW_DIR
            )
            stdout, stderr = await process.communicate()
            
            out_str = stdout.decode()
            err_str = stderr.decode()
            combined_output = out_str + "\n" + err_str

            # Error detection (401, API Errors)
            error_detected = False
            if any(indicator in combined_output for indicator in ["401", "Unauthorized", "Invalid API Key", "api_key_invalid"]):
                error_detected = True
                self.bot_config["api_error_paused"] = True
                save_config(self.bot_config)
                if channel:
                    await channel.send("🛑 **API Authentication Error Detected (401)!**\nSystem has been paused. Use `!setkey <NAME> <VALUE>` to update your key, then `!resume`.")

            if channel:
                output = out_str.strip() or err_str.strip()
                if output:
                    if len(output) > 1900:
                        output = output[:1900] + "..."
                    
                    if is_chat:
                        await channel.send(output)
                    else:
                        await channel.send(f"✅ **Clawd Response:**\n```\n{output}\n```")
                elif not error_detected and not is_chat:
                    await channel.send("✅ Pulse complete. No output reported.")
            
        except Exception as e:
            if channel:
                await channel.send(f"❌ **Error during execution:** {str(e)}")
        finally:
            if typing_ctx:
                await typing_ctx.__aexit__(None, None, None)
            IS_PROCESSING = False

    async def trigger_heartbeat(self, reason):
        prompt = (
            f"Heartbeat Triggered: {reason}. "
            "Examine INBOX.md. Process the queue. Break down large projects into small actionable tasks. "
            "Execute the top actionable task and mark as [x]. Provide a summary."
        )
        cid = self.bot_config.get("channel_id")
        channel = self.get_channel(int(cid)) if cid else None
        await self.run_agent(channel, prompt, is_chat=False)


    async def monitor_loop(self):
        await self.wait_until_ready()
        last_heartbeat = time.time()
        self.update_status_file("Daemon started")
        while not self.is_closed():
            if self.check_drop_folder():
                await self.trigger_heartbeat("New files detected in drop folder")
                last_heartbeat = time.time()
            
            if time.time() - last_heartbeat > 1800:
                await self.trigger_heartbeat("Scheduled periodic check")
                last_heartbeat = time.time()

            self.update_status_file("Monitoring")
            await asyncio.sleep(60)

    def update_status_file(self, last_event):
        uptime = str(datetime.now() - START_TIME).split('.')[0]
        active_tasks = []
        goals = []
        if os.path.exists(INBOX_PATH):
            try:
                with open(INBOX_PATH, "r") as f:
                    lines = f.readlines()
                    current_section = None
                    for line in lines:
                        if "## 🚀 HIGH LEVEL GOALS" in line:
                            current_section = "goals"
                        elif "## 📝 CURRENT QUEUE" in line:
                            current_section = "queue"
                        
                        if line.strip().startswith("- [ ]"):
                            task = line.strip().replace("- [ ] ", "").strip()
                            if current_section == "goals":
                                goals.append(task)
                            elif current_section == "queue":
                                active_tasks.append(task)
            except Exception as e:
                print(f"Error reading inbox for status update: {e}")
        
        status = "Processing ⚙️" if IS_PROCESSING else "Idle 🟢"
        
        content = f"""# RALPH STATUS REPORT
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

- **Uptime:** {uptime}
- **Status:** {status}
- **Queue Depth:** {len(active_tasks)} tasks
- **Current Top Tasks:**
"""
        for t in active_tasks[:5]:
            content += f"  - {t}\n"
        
        if goals:
            content += "- **High Level Goals:**\n"
            for g in goals[:3]:
                content += f"  - {g}\n"
                
        content += f"""- **Last Event:** {last_event}
- **System:** {get_sys_info()}

---
*This file is updated automatically by the Ralph Daemon.*
"""
        try:
            with open(STATUS_PATH, "w") as f:
                f.write(content)
        except Exception as e:
            print(f"Error writing status file: {e}")

    def check_drop_folder(self):
        if not os.path.exists(DROP_DIR):
            os.makedirs(DROP_DIR)
        files = [f for f in os.listdir(DROP_DIR) if f != "processed" and not f.startswith(".")]
        if files:
            with open(INBOX_PATH, "a") as f:
                for file in files:
                    f.write(f"\n- [ ] New incoming task from drop: {file}")
                    processed_dir = os.path.join(DROP_DIR, "processed")
                    os.makedirs(processed_dir, exist_ok=True)
                    os.rename(os.path.join(DROP_DIR, file), os.path.join(processed_dir, file))
            return True
        return False

if __name__ == "__main__":
    current_config = load_config()
    if not current_config["discord_token"] or "HERE" in current_config["discord_token"]:
        print("CRITICAL: Update ralph_config.json with your new Discord token.")
    else:
        intents = discord.Intents.default()
        intents.message_content = True
        client = RalphBot(current_config, intents=intents)
        client.run(current_config["discord_token"])
