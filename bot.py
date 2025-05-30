import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
import asyncio
import os
import sys

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

active_tickets = {}  # user_id: channel_id
ticket_locks = {}    # user_id: Lock
ticket_message_ids = set()  # message IDs для реакции 🎫

# 🔐 Проверка на админа
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

# 🎛️ Панель администратора
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

# 🧾 Модалки
class SendMessageModal(Modal, title="📣 Отправка сообщения"):
    channel = TextInput(label="Название или ID канала", placeholder="#общий")
    content = TextInput(label="Сообщение", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            channel = discord.utils.get(interaction.guild.text_channels, name=self.channel.value.strip('#')) \
                      or interaction.guild.get_channel(int(self.channel.value))
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
        await interaction.response.send_message(f"📩 Тикет создан: {ticket_channel.mention}", ephemeral=True)

# 📥 Команда: панель админа
@tree.command(name="admin_panel", description="Открыть панель управления")
@is_admin()
async def admin_panel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send("🔧 Панель администратора", view=AdminPanel(), ephemeral=True)

# 📌 Команда: сообщение с реакцией 🎫
@tree.command(name="setup_ticket_message", description="Создать сообщение с тикет-реакцией")
@is_admin()
async def setup_ticket_message(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    message = await interaction.channel.send("Нажмите 🎫, чтобы создать тикет.")
    await message.add_reaction("🎫")
    ticket_message_ids.add(message.id)
    await interaction.followup.send("✅ Сообщение с реакцией создано.", ephemeral=True)

# 🎫 Реакция на тикет
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
            try:
                await user.send("❗ У вас уже есть открытый тикет.")
            except:
                pass
            return

        active_tickets[user.id] = -1  # Защита

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
        try:
            await user.send(f"📩 Ваш тикет создан: {ticket_channel.mention}")
        except:
            pass

# ❌ Закрытие тикета
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

# 🪟 Windows Fix
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 🔑 Запуск
bot.run(os.getenv("DISCORD_TOKEN"))
