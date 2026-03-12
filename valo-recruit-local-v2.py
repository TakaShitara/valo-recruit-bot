import discord
from discord.ext import commands
import asyncio
import time
import os

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise ValueError("DISCORD_TOKEN is not set")
    
GUILD_ID = 348675685138563072  # ←あなたのサーバーID
RECRUIT_CHANNEL_ID = 1005814134165753959 # 本番-募集ちゃんねる
# RECRUIT_CHANNEL_ID = 1473361908479426661 # 検証-ちゃんねる
MENTION_ROLE_ID = 1046317949847351316
# CLOSE_STICKER_ID = 1360608121189302463

# STICKERS = {
#     1: 1360655163165249646,
#     2: 1360646951963459664,
#     3: 1360644614096158941,
#     4: 1360644772229939390
# }

PROGRESS_IMAGES = {
    1: "https://takashitara.github.io/valorant-recruit-images-for-discord-bot-/at1.png",
    2: "https://takashitara.github.io/valorant-recruit-images-for-discord-bot-/at2.png",
    3: "https://takashitara.github.io/valorant-recruit-images-for-discord-bot-/at3.png",
    4: "https://takashitara.github.io/valorant-recruit-images-for-discord-bot-/at4.png",
    "CLOSED": "https://takashitara.github.io/valorant-recruit-images-for-discord-bot-/close.png"
}


AUTO_CLOSE_SECONDS = 6 * 60 * 60

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

recruits = {}


# =========================
# タイトル入力モーダル
# =========================
class TitleModal(discord.ui.Modal):
    def __init__(self, max_members):
        super().__init__(title="募集タイトル（任意）")
        self.max_members = max_members

        self.title_input = discord.ui.TextInput(
            label="募集タイトル（未入力可）",
            placeholder="例：アンレート / フルパ / 23時まで",
            required=False,
            max_length=50
        )
        self.add_item(self.title_input)

    async def on_submit(self, interaction: discord.Interaction):

        await interaction.response.defer()  # ← これ追加

        title = self.title_input.value.strip()
        if not title:
            title = "パーティ募集"

        await create_recruit(interaction, title, self.max_members)



# =========================
# LATER時間選択
# =========================
class LaterSelect(discord.ui.Select):
    def __init__(self, recruit_view):
        options = [
            discord.SelectOption(label=t)
            for t in ["21:30", "22:00", "22:30", "23:00", "23:30", "00:00"]
        ]
        super().__init__(
            placeholder="参加可能時間を選択",
            min_values=1,
            max_values=1,
            options=options
        )
        self.recruit_view = recruit_view

    async def callback(self, interaction: discord.Interaction):
        recruit = self.recruit_view.get_recruit()

        recruit["members"][interaction.user.id] = {
            "type": "LATER",
            "note": self.values[0]
        }

        await interaction.response.defer(ephemeral=True)
        await self.recruit_view.refresh()


class LaterView(discord.ui.View):
    def __init__(self, recruit_view):
        super().__init__(timeout=60)
        self.add_item(LaterSelect(recruit_view))


# =========================
# 募集View
# =========================
class RecruitView(discord.ui.View):
    def __init__(self, message_id):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.add_buttons()

    def add_buttons(self):
        self.add_item(self.NowButton())
        self.add_item(self.LaterButton())
        self.add_item(self.WaitButton())
        self.add_item(self.CancelButton())
        self.add_item(self.CloseButton())
        self.add_item(self.DeclineButton())

    def get_recruit(self):
        return recruits.get(self.message_id)

    def count_now(self, recruit):
        return len([m for m in recruit["members"].values() if m["type"] == "NOW"])

    async def refresh(self):
        recruit = self.get_recruit()
        if not recruit:
            return

        now_count = self.count_now(recruit)
        embed = build_embed(recruit, now_count)

        channel = bot.get_channel(RECRUIT_CHANNEL_ID)
        msg = await channel.fetch_message(self.message_id)

        for item in self.children:
            if recruit["status"] == "募集中":
                if item.custom_id == "wait":
                    item.disabled = True
                else:
                    item.disabled = False
            else:
                if item.custom_id in ["wait", "decline"]:
                    item.disabled = False
                else:
                    item.disabled = True

        await msg.edit(embed=embed, view=self)

    async def auto_close(self):
        await asyncio.sleep(AUTO_CLOSE_SECONDS)
        recruit = self.get_recruit()
        if recruit and recruit["status"] == "募集中":
            recruit["status"] = "タイムアウトでクローズ"
            await self.refresh()

            # channel = bot.get_channel(RECRUIT_CHANNEL_ID)
            # sticker = discord.Object(id=CLOSE_STICKER_ID)
            # await channel.send(stickers=[sticker])

    # ===== BUTTONS =====

    class DeclineButton(discord.ui.Button):
        def __init__(self):
            super().__init__(
                label="今日は無理",
                style=discord.ButtonStyle.secondary,
                custom_id="decline"
            )

        async def callback(self, interaction: discord.Interaction):
            view = self.view
            recruit = view.get_recruit()

            if interaction.user.id == recruit["owner"]:
                return await interaction.response.send_message(
                    "募集主は利用できません", ephemeral=True
                )

            recruit["members"][interaction.user.id] = {
                "type": "DECLINE",
                "note": None
            }

            await interaction.response.defer()
            await view.refresh()

    class NowButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="今すぐ参加", style=discord.ButtonStyle.green, custom_id="now")

        async def callback(self, interaction: discord.Interaction):
            view = self.view
            recruit = view.get_recruit()

            if interaction.user.id == recruit["owner"]:
                return await interaction.response.send_message(
                    "募集主は「今すぐ参加」ボタンを利用できません", ephemeral=True
                )

            if recruit["status"] != "募集中":
                return await interaction.response.send_message("受付終了", ephemeral=True)

            # 既存状態を上書き
            recruit["members"][interaction.user.id] = {
                "type": "NOW",
                "note": None
            }

            if view.count_now(recruit) >= recruit["max"]:
                recruit["status"] = "満員でクローズ"
            
                # 〆ステッカー送信
                # channel = interaction.guild.get_channel(RECRUIT_CHANNEL_ID)
                # sticker = discord.Object(id=CLOSE_STICKER_ID)

                # message = await channel.send(
                    # content=role_mention,
                    # embed=embed,
                    # allowed_mentions=discord.AllowedMentions(roles=True)
                # )
            await interaction.response.defer()
            await view.refresh()

    class LaterButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="あとから参加", style=discord.ButtonStyle.blurple, custom_id="later")

        async def callback(self, interaction: discord.Interaction):
            view = self.view
            recruit = view.get_recruit()

            if self.view.get_recruit()["status"] != "募集中":
                return await interaction.response.send_message("受付終了", ephemeral=True)
            
            if interaction.user.id == recruit["owner"]:
                return await interaction.response.send_message(
                    "募集主は「あとから参加」ボタンを利用できません", ephemeral=True
                )

            await interaction.response.send_message(
                "参加時間を選択してください",
                view=LaterView(self.view),
                ephemeral=True
            )

    class WaitButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="キャンセル待ち", style=discord.ButtonStyle.gray, custom_id="wait")

        async def callback(self, interaction: discord.Interaction):
            view = self.view
            recruit = view.get_recruit()

            if interaction.user.id == recruit["owner"]:
                return await interaction.response.send_message(
                "募集主は「キャンセル待ち」ボタンを利用できません", ephemeral=True
                )

            if recruit["status"] == "募集中":
                return await interaction.response.send_message("まだ満員ではありません", ephemeral=True)

            recruit["members"][interaction.user.id] = {"type": "WAIT", "note": None}

            await interaction.response.defer()
            await self.view.refresh()

    class CancelButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="参加取消", style=discord.ButtonStyle.red, custom_id="cancel")

        async def callback(self, interaction: discord.Interaction):
            view = self.view
            recruit = view.get_recruit()

            if interaction.user.id == recruit["owner"]:
                return await interaction.response.send_message(
                    "募集主は「参加取消」ボタンを利用できません", ephemeral=True
                )

            member = recruit["members"].get(interaction.user.id)

            if not member:
                return await interaction.response.send_message(
                    "参加状態ではありません", ephemeral=True
                )

            recruit["members"].pop(interaction.user.id)

            await interaction.response.defer()
            await view.refresh()
        
    class CloseButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="締め切る", style=discord.ButtonStyle.danger, custom_id="close")

        async def callback(self, interaction: discord.Interaction):
            view = self.view
            recruit = view.get_recruit()

            if interaction.user.id != recruit["owner"]:
                return await interaction.response.send_message("主催者のみ可能", ephemeral=True)

            recruit["status"] = "募集主による手動クローズ"

            await interaction.response.defer()
            await self.view.refresh()

            # 〆ステッカー送信
            # channel = interaction.guild.get_channel(RECRUIT_CHANNEL_ID)
            # sticker = discord.Object(id=CLOSE_STICKER_ID)

            # message = await channel.send(
                # content=role_mention,
                # embed=embed,
                # allowed_mentions=discord.AllowedMentions(roles=True)
            # )

def build_embed(recruit, now_count):

    embed = discord.Embed(title=f"🎮 {recruit['title']}")

    embed.add_field(name="募集主", value=f"<@{recruit['owner']}>", inline=False)
    embed.add_field(name="定員", value=f"{now_count}/{recruit['max']}", inline=False)

    now_list = []
    later_list = []
    wait_list = []
    decline_list = []

    for uid, data in recruit["members"].items():
        mention = f"<@{uid}>"

        if data["type"] == "NOW":
            now_list.append(mention)

        elif data["type"] == "LATER":
            later_list.append(f"{mention}（{data['note']}）")

        elif data["type"] == "WAIT":
            wait_list.append(mention)

        elif data["type"] == "DECLINE":
            decline_list.append(mention)

    embed.add_field(
        name="🟢 今すぐ参加",
        value="\n".join(now_list) if now_list else "なし",
        inline=False
    )

    embed.add_field(
        name="🔵 あとから参加",
        value="\n".join(later_list) if later_list else "なし",
        inline=False
    )

    embed.add_field(
        name="🟡 キャンセル待ち",
        value="\n".join(wait_list) if wait_list else "なし",
        inline=False
    )

    embed.add_field(
        name="状態", 
        value=recruit["status"], 
        inline=False
    )

    embed.add_field(
        name="⚫ 今日は無理",
        value="\n".join(decline_list) if decline_list else "なし",
        inline=False
    )

    # 🔥 ここが追加部分（画像切替）
    remaining = recruit["max"] - now_count

    if recruit["status"] == "募集中" and remaining > 0:
        image_url = PROGRESS_IMAGES.get(remaining)
        if image_url:
            embed.set_image(
                url=f"{image_url}?v={int(time.time())}"
            )
    else:
        embed.set_image(
            url=f"{PROGRESS_IMAGES['CLOSED']}?v={int(time.time())}"
        )

    return embed

async def create_recruit(interaction, title, max_members):
    channel = bot.get_channel(RECRUIT_CHANNEL_ID)

    recruit_data = {
        "title": title,
        "max": max_members,
        "members": {},
        "owner": interaction.user.id,
        "status": "募集中"
    }

    embed = build_embed(recruit_data, 0)

    role_mention = f"<@&{MENTION_ROLE_ID}>"
    # sticker_id = STICKERS.get(max_members)
    # sticker = discord.Object(id=sticker_id) if sticker_id else None

    message = await channel.send(
        content=role_mention,
        embed=embed,
        allowed_mentions=discord.AllowedMentions(roles=True)
    )
    recruits[message.id] = recruit_data

    view = RecruitView(message.id)
    await message.edit(view=view)

    asyncio.create_task(view.auto_close())


# ===== ギルドコマンド =====
@bot.tree.command(
    name="setup_panel",
    description="募集作成パネルを設置",
    guild=discord.Object(id=GUILD_ID)
)
async def setup_panel(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🎮 パーティ募集作成\nタイトルは任意入力です。\n人数を選択してください。",
        view=CreateView()
    )


class CreateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="@1", style=discord.ButtonStyle.primary)
    async def one(self, interaction, button):
        await interaction.response.send_modal(TitleModal(1))

    @discord.ui.button(label="@2", style=discord.ButtonStyle.primary)
    async def two(self, interaction, button):
        await interaction.response.send_modal(TitleModal(2))

    @discord.ui.button(label="@3", style=discord.ButtonStyle.primary)
    async def three(self, interaction, button):
        await interaction.response.send_modal(TitleModal(3))

    @discord.ui.button(label="@4", style=discord.ButtonStyle.primary)
    async def four(self, interaction, button):
        await interaction.response.send_modal(TitleModal(4))

@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    await bot.tree.sync(guild=guild)
    print("Bot Ready (Guild Synced)")


bot.run(TOKEN)
