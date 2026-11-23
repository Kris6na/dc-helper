import html
import json
import os
import re
import time
from datetime import datetime
from html.parser import HTMLParser

import requests

TOKEN = os.environ.get("DISCORD_TOKEN", "")
# NEWS_CHANNEL_ID = "1132006965002903613"
NEWS_CHANNEL_ID = "1131913170282356746"
PING_ROLE_ID = "1574391373984047104"

API = "https://discord.com/api/v10"
SITE = "https://www-api.pandadagames.com/new/"
ORIGIN = "https://www.pandadagames.com"
ZH_LINK = ORIGIN + "/tc/news/"
EN_LINK = ORIGIN + "/en/news/"  # assumed from the tc pattern

CATEGORIES = {1: "Info | 新聞", 2: "Update | 公告", 3: "Event | 活動"}
SKIP_WORDS = ["占位"]
SKIP_CATEGORIES = set()  # use {2} to skip maintenance notices
MAX_PER_RUN = 3
MATCH_WINDOW = 3600  # seconds allowed between the zh and en versions
CHUNK = 1900
BANNER_FILE = "announcement.jpeg"

hdr = {"Authorization": f"Bot {TOKEN}"}


def site(path, lang, body):
    r = requests.post(
        SITE + path,
        json=body,
        headers={
            "lang": lang,
            "Origin": ORIGIN,
            "Referer": ORIGIN + "/",
            "User-Agent": "Mozilla/5.0 (compatible; EachClanNewsBot/1.0)",
        },
        timeout=30,
    )
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 100:
        raise SystemExit(f"Unexpected reply from site ({lang}, {path}): {d}")
    return d["data"]


def fetch(lang):
    data = site("lists", lang, {"cate_id": 0, "page": 1, "rows": 10})
    return [
        a for a in data["lists"]
        if not any(w in a["title"] for w in SKIP_WORDS)
        and a["cate_id"] not in SKIP_CATEGORIES
    ]


def when(a):
    return datetime.strptime(a["display_time"], "%Y-%m-%d %H:%M")


def pair(zh_list, en_pool):
    out = []
    for zh in zh_list:
        best, gap = None, MATCH_WINDOW + 1
        for en in en_pool:
            if en["cate_id"] != zh["cate_id"]:
                continue
            g = abs((when(en) - when(zh)).total_seconds())
            if g < gap:
                best, gap = en, g
        if best and gap <= MATCH_WINDOW:
            en_pool.remove(best)
            out.append((zh, best))
        else:
            out.append((zh, None))
    return out


def discord(method, path, **kw):
    for _ in range(3):
        r = requests.request(method, API + path, headers=hdr, timeout=30, **kw)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 1)) + 0.5)
            continue
        if not r.ok:
            raise RuntimeError(f"Discord {r.status_code}: {r.text[:300]}")
        return r.json()
    raise RuntimeError("Rate limited too long")


def already_posted():
    msgs = discord("GET", f"/channels/{NEWS_CHANNEL_ID}/messages", params={"limit": 100})
    seen = set()
    for m in msgs:
        for e in m.get("embeds", []):
            text = (e.get("url") or "") + "\n" + (e.get("description") or "")
            for lid in re.findall(r"/tc/news/([0-9a-f]+)", text):
                seen.add(lid)
    return seen


class Text(HTMLParser):
    BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "tr", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "br":
            self.out.append("\n")
        elif tag in self.BLOCK:
            if self.out and not self.out[-1].endswith("\n"):
                self.out.append("\n")
        elif tag == "li":
            if self.out and not self.out[-1].endswith("\n"):
                self.out.append("\n")
            self.out.append("• ")
        elif tag in ("b", "strong"):
            self.out.append("**")
        elif tag == "a":
            href = a.get("href")
            self.hrefs.append(href)
            if href:
                self.out.append("[")
        elif tag == "img":
            src = a.get("src") or ""
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = ORIGIN + src
            if src.startswith("http"):
                self.out.append("\n" + src + "\n")

    def handle_endtag(self, tag):
        if tag in self.BLOCK:
            self.out.append("\n")
        elif tag in ("b", "strong"):
            self.out.append("**")
        elif tag == "a" and self.hrefs:
            href = self.hrefs.pop()
            if href:
                self.out.append(f"]({href})")

    def handle_data(self, data):
        self.out.append(re.sub(r"([\\*_~`|])", r"\\\1", data))


def to_text(raw):
    p = Text()
    p.feed(html.unescape(raw or ""))
    t = "".join(p.out).replace("\xa0", " ")
    t = re.sub(r"\*\*\s*\*\*", "", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"(?m)^([#>])", r"\\\1", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def chunks(text):
    out, cur = [], ""
    for line in text.split("\n"):
        while len(line) > CHUNK:
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:CHUNK])
            line = line[CHUNK:]
        if len(cur) + len(line) + 1 > CHUNK:
            out.append(cur)
            cur = line
        else:
            cur = cur + "\n" + line if cur else line
    if cur.strip():
        out.append(cur)
    return [c for c in out if c.strip()]


def send_text(channel_id, text):
    for c in chunks(text):
        discord("POST", f"/channels/{channel_id}/messages",
                json={"content": c, "allowed_mentions": {"parse": []}})
        time.sleep(1)


if __name__ == "__main__":
    zh_list = fetch("t_chinese")
    en_pool = fetch("english")
    pairs = pair(zh_list, en_pool)

    seen = already_posted()
    new = [(z, e) for z, e in pairs if z["lid"] not in seen]
    new = new[:1] if not seen else new[:MAX_PER_RUN]  # first run: newest only

    banner_bytes = None
    if os.path.isfile(BANNER_FILE):
        with open(BANNER_FILE, "rb") as f:
            banner_bytes = f.read()

    for zh, en in reversed(new):  # oldest first
        cat = CATEGORIES.get(zh["cate_id"], "Announcement | 公告")
        display_time = en["display_time"] if en else zh["display_time"]

        link_lines = []
        if en:
            link_lines.append(f"🇬🇧 [{en['title']}]({EN_LINK}{en['lid']})")
        link_lines.append(f"🇹🇼 [{zh['title']}]({ZH_LINK}{zh['lid']})")

        sections = [
            f"📅 {display_time}",
            "\n".join(link_lines),
            "👇 Full text in the thread | 完整內容請見討論串",
        ]
        embed = {
            "title": f"📢 {cat}",
            "description": "\n\n".join(sections),
            "color": 16716947,
            "footer": {"text": "Source: pandadagames.com"},
        }

        payload = {
            "content": f"<@&{PING_ROLE_ID}>",
            "embeds": [embed],
            "allowed_mentions": {"parse": [], "roles": [PING_ROLE_ID]},
        }
        if banner_bytes:
            embed["image"] = {"url": f"attachment://{BANNER_FILE}"}
            msg = discord(
                "POST",
                f"/channels/{NEWS_CHANNEL_ID}/messages",
                data={"payload_json": json.dumps(payload)},
                files={"files[0]": (BANNER_FILE, banner_bytes, "image/jpeg")},
            )
        else:
            msg = discord("POST", f"/channels/{NEWS_CHANNEL_ID}/messages", json=payload)

        print("Posted", zh["lid"], "| EN:", en["title"] if en else "none", "| ZH:", zh["title"])
        try:
            thread_name = (en["title"] if en else zh["title"])[:90]
            thread = discord(
                "POST", f"/channels/{NEWS_CHANNEL_ID}/messages/{msg['id']}/threads",
                json={"name": thread_name, "auto_archive_duration": 1440})
            if en:
                en_body = site("detail", "english", {"lid": en["lid"]}).get("content")
                send_text(thread["id"], "**English**\n\n" + to_text(en_body))
            zh_body = site("detail", "t_chinese", {"lid": zh["lid"]}).get("content")
            send_text(thread["id"], "**繁體中文**\n\n" + to_text(zh_body))
        except Exception as e:
            print("Thread step failed:", e)

    print("Done. New articles:", len(new))
