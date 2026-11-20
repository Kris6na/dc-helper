import os
import requests

TOKEN = os.environ["DISCORD_TOKEN"]

GUILD_ID = "1101855542093303928"
CHANNEL_ID = "1131913170282356746"
PENDING_ROLE = "1572890292300808222"
MEMBER_ROLE = "1111997634174001212"
MOD_ROLE = "1223308581827383466"

API = "https://discord.com/api/v10"
headers = {"Authorization": f"Bot {TOKEN}"}

waiting = []
after = "0"

while True:
    r = requests.get(
        f"{API}/guilds/{GUILD_ID}/members",
        headers=headers,
        params={"limit": 1000, "after": after},
        timeout=30,
    )
    r.raise_for_status()
    batch = r.json()
    if not batch:
        break
    for m in batch:
        roles = m["roles"]
        if PENDING_ROLE in roles and MEMBER_ROLE not in roles:
            waiting.append(m["user"]["id"])
    after = batch[-1]["user"]["id"]
    if len(batch) < 1000:
        break

if waiting:
    users = " ".join(f"<@{uid}>" for uid in waiting)
    content = f"<@&{MOD_ROLE}> A user has requested member access: {users}"
    if len(content) > 1900:
        content = (
            f"<@&{MOD_ROLE}> {len(waiting)} users have requested member access. "
            "Check the Member Pending list."
        )
    requests.post(
        f"{API}/channels/{CHANNEL_ID}/messages",
        headers=headers,
        json={"content": content, "allowed_mentions": {"roles": [MOD_ROLE]}},
        timeout=30,
    ).raise_for_status()
