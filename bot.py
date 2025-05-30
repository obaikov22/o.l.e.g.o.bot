import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer
import socket
import asyncio
import os
import sys

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

active_tickets = {}
ticket_locks = {}
ticket_message_ids = set()

def is_admin():
    async def predicate(interaction: discord.Interaction):
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        synced = await tree.sync()
        print(f"🔄 Slash-команды синхронизированы ({len(synced)})")
    except Exception as e:
        print(f"❌ Ошибка синхронизации: {e}")

# DM логирование
@bot.event
async def on_message(message):
    if message.guild is None and not message.author.bot:
        log_channel_id = os.getenv("DM_LOG_CHANNEL_ID")
        if log_channel_id:
            log_channel = bot.get_channel(int(log_channel_id))
            if log_channel:
                embed = discord.Embed(
                    title="📨 Личное сообщение боту",
                    description=message.content,
                    color=discord.Color.blurple()
                )
                embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
                await log_channel.send(embed=embed)
    await bot.process_commands(message)

class AdminPanel(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SendMessageButton())
        self.add_item(SendDMButton())
        self.add_item(CreateTicketButton())

class SendMessageButton(Button):
    def __init__(self):
        super().__init__(label="📣 Отправить сообщение", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SendMessageModal())

class SendDMButton(Button):
    def __init__(self):
        super().__init__(label="💌 Отправить в ЛС", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SendDMModal())

class CreateTicketButton(Button):
    def __init__(self):
        super().__init__(label="🎫 Создать тикет", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CreateTicketModal())

class SendMessageModal(Modal, title="📣 Отправка сообщения"):
    channel = TextInput(label="Название или ID канала", placeholder="#общий")
    content = TextInput(label="Сообщение", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            channel = discord.utils.get(interaction.guild.text_channels, name=self.channel.value.strip('#'))                       or interaction.guild.get_channel(int(self.channel.value))
            await channel.send(self.content.value)
            await interaction.response.send_message("✅ Сообщение отправлено.", ephemeral=True)
        except:
            await interaction.response.send_message("❌ Не удалось отправить сообщение.", ephemeral=True)

class SendDMModal(Modal, title="💌 Отправка ЛС"):
    user_id = TextInput(label="ID пользователя")
    content = TextInput(label="Сообщение", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user = await bot.fetch_user(int(self.user_id.value))
            await user.send(self.content.value)
            await interaction.response.send_message("✅ ЛС отправлено.", ephemeral=True)
        except:
            await interaction.response.send_message("❌ Не удалось отправить ЛС.", ephemeral=True)

class CreateTicketModal(Modal, title="🎫 Создание тикета"):
    issue = TextInput(label="Опишите проблему", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        user = interaction.user
        guild = interaction.guild

        if user.id in active_tickets:
            await interaction.response.send_message("❗ У вас уже есть открытый тикет.", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        category_id = os.getenv("TICKET_CATEGORY_ID")
        category = guild.get_channel(int(category_id)) if category_id else None

        ticket_channel = await guild.create_text_channel(
            name=f"ticket-{user.name}-{user.discriminator}",
            overwrites=overwrites,
            topic=self.issue.value,
            category=category
        )

        active_tickets[user.id] = ticket_channel.id
        await ticket_channel.send(f"{user.mention}, ваш тикет создан! Напишите, в чём проблема.")
        await interaction.response.send_message("📩 Тикет создан.", ephemeral=True)

@tree.command(name="admin_panel", description="Открыть панель управления")
@is_admin()
async def admin_panel(interaction: discord.Interaction):
    await interaction.response.send_message("🔧 Панель администратора", view=AdminPanel(), ephemeral=True)

@tree.command(name="setup_ticket_message", description="Создать сообщение с тикет-реакцией")
@is_admin()
async def setup_ticket_message(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    message = await interaction.channel.send("Нажмите 🎫, чтобы создать тикет.")
    await message.add_reaction("🎫")
    ticket_message_ids.add(message.id)
    await interaction.followup.send("✅ Сообщение с реакцией создано.", ephemeral=True)

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id or str(payload.emoji) != "🎫":
        return

    if payload.message_id not in ticket_message_ids:
        return

    guild = bot.get_guild(payload.guild_id)
    user = guild.get_member(payload.user_id)
    if not user or user.bot:
        return

    if user.id not in ticket_locks:
        ticket_locks[user.id] = asyncio.Lock()

    async with ticket_locks[user.id]:
        if user.id in active_tickets:
            return

        active_tickets[user.id] = -1

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        category_id = os.getenv("TICKET_CATEGORY_ID")
        category = guild.get_channel(int(category_id)) if category_id else None

        ticket_channel = await guild.create_text_channel(
            name=f"ticket-{user.name}-{user.discriminator}",
            overwrites=overwrites,
            topic=f"Тикет от {user.name}",
            category=category
        )

        active_tickets[user.id] = ticket_channel.id
        await ticket_channel.send(f"{user.mention}, ваш тикет создан! Напишите, в чём проблема.")

@tree.command(name="close_ticket", description="Закрыть тикет")
@is_admin()
async def close_ticket(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    for user_id, ch_id in list(active_tickets.items()):
        if ch_id == interaction.channel.id:
            del active_tickets[user_id]
            break

    await interaction.followup.send("Тикет будет закрыт через 5 секунд...", ephemeral=True)
    await asyncio.sleep(5)
    await interaction.channel.delete()

@tree.command(name="send_message_with_file", description="Отправить сообщение с медиа в канал")
@is_admin()
@app_commands.describe(channel="Канал для отправки", content="Текст сообщения", file="Файл или изображение")
async def send_message_with_file(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    content: str,
    file: discord.Attachment
):
    try:
        await channel.send(content, file=await file.to_file())
        await interaction.response.send_message("✅ Сообщение с медиа отправлено!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Ошибка отправки: {e}", ephemeral=True)

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Pong")

def run_http_server():
    port = int(os.environ.get("PORT", 10000))  # Render автоматически назначает PORT
    server = HTTPServer(("", port), PingHandler)
    print(f"🌐 HTTP-сервер запущен на порту {port}")
    server.serve_forever()

Thread(target=run_http_server, daemon=True).start()


bot.run(os.getenv("DISCORD_TOKEN"))

import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Pong")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    server.serve_forever()

threading.Thread(target=run_web_server).start()