import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
import asyncio
import sys
import os

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

active_tickets = {}  # user_id: channel_id

# 🔒 Проверка: только администраторы
def is_admin():
    async def predicate(interaction: discord.Interaction):
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        await tree.sync()
        print("🔄 Слеш-команды синхронизированы.")
    except Exception as e:
        print(f"❌ Ошибка синхронизации: {e}")

# 📤 Панель администратора
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
    channel = TextInput(label="Название или ID канала (#имя или ID)", placeholder="#общий")
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
            topic=f"Тикет от {user.name}",
            category=category
        )

        active_tickets[user.id] = ticket_channel.id
        await ticket_channel.send(f"{user.mention}, ваш тикет создан! Опишите вашу проблему.")
        await interaction.response.send_message(f"📩 Тикет создан: {ticket_channel.mention}", ephemeral=True)

# 📥 Команда: панель администратора
@tree.command(name="admin_panel", description="Открыть панель управления")
@is_admin()
async def admin_panel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send("🔧 Панель администратора", view=AdminPanel(), ephemeral=True)

# 🧷 Команда: разместить сообщение с реакцией
@tree.command(name="setup_ticket_message", description="Разместить сообщение с тикет-реакцией")
@is_admin()
async def setup_ticket_message(interaction: discord.Interaction):
    message = await interaction.channel.send("Нажмите 🎫, чтобы создать тикет.")
    await message.add_reaction("🎫")
    await interaction.response.send_message("✅ Готово. Сообщение размещено.", ephemeral=True)

# 🎫 Обработка реакции
@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id or str(payload.emoji) != "🎫":
        return

    guild = bot.get_guild(payload.guild_id)
    user = guild.get_member(payload.user_id)

    if not user or user.bot:
        return

    if user.id in active_tickets:
        try:
            await user.send("❗ У вас уже есть открытый тикет.")
        except:
            pass
        return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }

    ticket_channel = await guild.create_text_channel(
        name=f"ticket-{user.name}-{user.discriminator}",
        overwrites=overwrites,
        topic=f"Тикет от {user.name}"
    )

    active_tickets[user.id] = ticket_channel.id
    await ticket_channel.send(f"{user.mention}, ваш тикет создан! Напишите, в чём проблема.")
    try:
        await user.send(f"📩 Ваш тикет создан: {ticket_channel.mention}")
    except:
        pass

# ❌ Команда: закрыть тикет
@tree.command(name="close_ticket", description="Закрыть текущий тикет")
@is_admin()
async def close_ticket(interaction: discord.Interaction):
    channel = interaction.channel
    for user_id, ch_id in list(active_tickets.items()):
        if ch_id == channel.id:
            del active_tickets[user_id]
            break

    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send("Тикет будет закрыт через 5 секунд...", ephemeral=True)
    await asyncio.sleep(5)
    await channel.delete()

# 🪟 Fix для Windows (aiodns)
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 🔑 Запуск
bot.run(os.getenv("DISCORD_TOKEN"))
