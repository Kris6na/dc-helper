import os
import re
from datetime import datetime, timedelta, timezone

import requests

TOKEN = os.environ["DISCORD_TOKEN"]

GUILD_ID = "1101855542093303928"
CHANNEL_ID = "1131913170282356746"
PENDING_ROLE = "1572890292300808222"
MEMBER_ROLE = "1111997634174001212"
PING_ROLES = ["1223308581827383466", "1111997909362278482"]
COOLDOWN = timedelta(hours=3)
MAX_PER_MESSAGE = 40

API = "https://discord.com/api/v10"
headers = {"Authorization": f"Bot {TOKEN}"}


def get(path, **params):
    r = requests.get(f"{API}{path}", headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


bot_id = get("/users/@me")["id"]


def recently_pinged():
    cutoff = datetime.now(timezone.utc) - COOLDOWN
    pinged = set()
    before = None
    while True:
        params = {"limit": 100}
        if before:
            params["before"] = before
        msgs = get(f"/channels/{CHANNEL_ID}/messages", **params)
        if not msgs:
            return pinged
        for m in msgs:
            if datetime.fromisoformat(m["timestamp"]) < cutoff:
                return pinged
            if m["author"]["id"] == bot_id:
                pinged.update(re.findall(r"<@!?(\d+)>", m["content"]))
        before = msgs[-1]["id"]


waiting = []
after = "0"
while True:
    batch = get(f"/guilds/{GUILD_ID}/members", limit=1000, after=after)
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
    already = recently_pinged()
    to_ping = [uid for uid in waiting if uid not in already][:MAX_PER_MESSAGE]
    if to_ping:
        roles_text = " ".join(f"<@&{rid}>" for rid in PING_ROLES)
        users_text = " ".join(f"<@{uid}>" for uid in to_ping)
        content = f"{roles_text} A user has requested member access: {users_text}"
        requests.post(
            f"{API}/channels/{CHANNEL_ID}/messages",
            headers=headers,
            json={"content": content, "allowed_mentions": {"roles": PING_ROLES}},
            timeout=30,
        ).raise_for_status()
