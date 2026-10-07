#!/usr/bin/env python3
# Бот-адмінка магазину: приймає APK в Telegram, кладе в GitHub Release
# і дописує запис в apps.json. Працює на Python 3.8 + requests.
import base64
import datetime
import json
import os
import re
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))
BOT = CFG["bot_token"]
GH = CFG["github_token"]
ADMIN = int(CFG["admin_id"])
OWNER = CFG.get("owner", "Volodapatik")
REPO = CFG.get("repo", "Cherkasy-1-2-Download")
BRANCH = CFG.get("branch", "main")

TG = "https://api.telegram.org/bot" + BOT
TGFILE = "https://api.telegram.org/file/bot" + BOT
API = "https://api.github.com/repos/%s/%s" % (OWNER, REPO)
GHH = {"Authorization": "Bearer " + GH, "Accept": "application/vnd.github+json"}
MAX_TG = 20 * 1024 * 1024
state = {}

HELP = ("Команди:\n/add - додати або оновити додаток\n/list - список\n"
        "/delete id - видалити зі списку\n/cancel - скасувати")

TR = {"а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e",
      "є": "ye", "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "yi", "й": "y",
      "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
      "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
      "ш": "sh", "щ": "shch", "ю": "yu", "я": "ya", "ы": "y", "э": "e"}


def slug(name):
    s = "".join(TR.get(c, c) for c in name.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "app-%d" % int(time.time())


def send(chat, text):
    try:
        requests.post(TG + "/sendMessage", json={"chat_id": chat, "text": text},
                      timeout=30)
    except Exception as e:
        print("send error:", e)


def update_catalog(entry=None, delete_id=None):
    r = requests.get(API + "/contents/apps.json", headers=GHH,
                     params={"ref": BRANCH}, timeout=30)
    r.raise_for_status()
    j = r.json()
    data = json.loads(base64.b64decode(j["content"]).decode("utf-8"))
    apps = data.get("apps", [])
    if delete_id:
        apps = [a for a in apps if a.get("id") != delete_id]
    if entry:
        old = next((a for a in apps if a.get("id") == entry["id"]), None)
        if old:
            entry["icon"] = old.get("icon", entry["icon"])
            entry["category"] = old.get("category", entry["category"])
            apps = [entry if a.get("id") == entry["id"] else a for a in apps]
        else:
            apps.append(entry)
    data["apps"] = apps
    body = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    p = requests.put(API + "/contents/apps.json", headers=GHH, timeout=30, json={
        "message": "Оновлення каталогу через бота",
        "content": base64.b64encode(body.encode("utf-8")).decode(),
        "sha": j["sha"], "branch": BRANCH})
    p.raise_for_status()
    return apps


def upload_apk(st, app_id):
    info = requests.get(TG + "/getFile", params={"file_id": st["file_id"]},
                        timeout=30).json()
    path = info["result"]["file_path"]
    data = requests.get(TGFILE + "/" + path, timeout=300).content
    tag = "%s-%s" % (app_id, st["version"])
    fname = "%s-%s.apk" % (app_id, st["version"])
    rel = requests.post(API + "/releases", headers=GHH, timeout=60, json={
        "tag_name": tag, "name": "%s %s" % (st["name"], st["version"]),
        "target_commitish": BRANCH})
    if rel.status_code == 422:  # такий реліз уже є
        rel = requests.get(API + "/releases/tags/" + tag, headers=GHH, timeout=30)
    rel.raise_for_status()
    r = rel.json()
    up = r["upload_url"].split("{")[0]
    hdr = dict(GHH)
    hdr["Content-Type"] = "application/vnd.android.package-archive"
    a = requests.post(up, params={"name": fname}, headers=hdr, data=data,
                      timeout=900)
    a.raise_for_status()
    return a.json()["browser_download_url"], r["html_url"]


def publish(chat, st):
    send(chat, "Завантажую, зачекай хвилинку...")
    try:
        app_id = slug(st["name"])
        if "file_id" in st:
            apk_url, rel_url = upload_apk(st, app_id)
        else:
            apk_url, rel_url = st["url"], st["url"]
        entry = {
            "id": app_id, "name": st["name"],
            "shortDescription": st["desc"], "description": st["desc"],
            "icon": "📱", "category": "Корисні", "version": st["version"],
            "apkUrl": apk_url, "releasesUrl": rel_url,
            "updated": datetime.date.today().isoformat()}
        update_catalog(entry=entry)
        send(chat, "✅ Додано в магазин: %s\nНа сайті з'явиться за 1-2 хв." % st["name"])
    except Exception as e:
        send(chat, "❌ Помилка: %s\nЯкщо це оновлення тієї ж версії, змін версію." % e)


def handle(m):
    chat = m["chat"]["id"]
    if m.get("from", {}).get("id") != ADMIN:
        return
    text = (m.get("text") or "").strip()
    st = state.get(chat)

    if text == "/cancel":
        state.pop(chat, None)
        send(chat, "Скасовано.")
    elif text in ("/start", "/help"):
        send(chat, HELP)
    elif text == "/list":
        try:
            r = requests.get(API + "/contents/apps.json", headers=GHH,
                             params={"ref": BRANCH}, timeout=30).json()
            apps = json.loads(base64.b64decode(r["content"]).decode("utf-8"))["apps"]
            send(chat, "\n".join("%s - %s (%s)" % (a["id"], a["name"], a.get("version", "?"))
                                 for a in apps) or "Порожньо")
        except Exception as e:
            send(chat, "Помилка: %s" % e)
    elif text.startswith("/delete"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send(chat, "Напиши так: /delete id (id дивись в /list)")
            return
        try:
            update_catalog(delete_id=parts[1].strip())
            send(chat, "Видалено зі списку (файл у Releases лишається).")
        except Exception as e:
            send(chat, "Помилка: %s" % e)
    elif text == "/add":
        state[chat] = {"step": "apk"}
        send(chat, "Надішли APK файлом (до 20 МБ) або пряме посилання на APK.")
    elif not st:
        send(chat, HELP)
    elif st["step"] == "apk":
        doc = m.get("document")
        if doc:
            if doc.get("file_size", 0) > MAX_TG:
                send(chat, "Файл більше 20 МБ, Telegram не віддасть його боту. "
                           "Завантаж APK у GitHub Releases і надішли мені пряме посилання.")
                return
            st["file_id"] = doc["file_id"]
        elif text.startswith("http"):
            st["url"] = text
        else:
            send(chat, "Потрібен APK файлом або посилання, що починається з http.")
            return
        st["step"] = "name"
        send(chat, "Назва додатку? (Для оновлення напиши ту саму назву)")
    elif st["step"] == "name" and text:
        st["name"] = text
        st["step"] = "desc"
        send(chat, "Короткий опис?")
    elif st["step"] == "desc" and text:
        st["desc"] = text
        st["step"] = "version"
        send(chat, "Версія? (наприклад 1.0)")
    elif st["step"] == "version" and text:
        st["version"] = re.sub(r"[^0-9A-Za-z._-]", "", text) or "1.0"
        state.pop(chat, None)
        publish(chat, st)


def main():
    offset = None
    print("Бот запущено")
    while True:
        try:
            r = requests.get(TG + "/getUpdates", timeout=40,
                             params={"timeout": 30, "offset": offset}).json()
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                if "message" in u:
                    try:
                        handle(u["message"])
                    except Exception as e:
                        print("handle error:", e)
        except Exception as e:
            print("poll error:", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
