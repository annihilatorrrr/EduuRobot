# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2022 Amano Team

import asyncio
import html
import io
import os
import re
import sys
import time
import traceback
from contextlib import redirect_stdout
from sqlite3 import IntegrityError, OperationalError
from typing import Union

import humanfriendly
import speedtest
from meval import meval
from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.errors import RPCError
from pyrogram.types import Message

from eduu.config import DATABASE_PATH
from eduu.database import db, dbc
from eduu.utils import set_restarted, sudofilter
from eduu.utils.localization import use_chat_lang

prefix: Union[list, str] = "!"


@Client.on_message(filters.command("sudos", prefix) & sudofilter)
async def sudos(c: Client, m: Message):
    await m.reply_text("Test")


@Client.on_message(filters.command("cmd", prefix) & sudofilter)
@use_chat_lang()
async def run_cmd(c: Client, m: Message, strings):
    cmd = m.text.split(maxsplit=1)[1]
    if re.match("(?i)poweroff|halt|shutdown|reboot", cmd):
        res = strings("forbidden_command")
    else:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        res = (
            "<b>Output:</b>\n<code>{}</code>".format(
                html.escape(stdout.decode().strip())
            )
            if stdout
            else ""
        ) + (
            "\n<b>Errors:</b>\n<code>{}</code>".format(
                html.escape(stderr.decode().strip())
            )
            if stderr
            else ""
        )
    await m.reply_text(res)


@Client.on_message(filters.command("upgrade", prefix) & sudofilter)
@use_chat_lang()
async def upgrade(c: Client, m: Message, strings):
    sm = await m.reply_text("Upgrading sources...")
    proc = await asyncio.create_subprocess_shell(
        "git pull --no-edit",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout = (await proc.communicate())[0]
    if proc.returncode == 0:
        if "Already up to date." in stdout.decode():
            await sm.edit_text("There's nothing to upgrade.")
        else:
            await sm.edit_text(strings("restarting"))
            set_restarted(sm.chat.id, sm.id)
            db.commit()
            args = [sys.executable, "-m", "eduu"]
            os.execv(sys.executable, args)  # skipcq: BAN-B606
    else:
        await sm.edit_text(
            f"Upgrade failed (process exited with {proc.returncode}):\n{stdout.decode()}"
        )
        proc = await asyncio.create_subprocess_shell("git merge --abort")
        await proc.communicate()


@Client.on_message(filters.command("eval", prefix) & sudofilter)
async def evals(c: Client, m: Message):
    text = m.text.split(maxsplit=1)[1]
    try:
        res = await meval(text, globals(), **locals())
    except:  # skipcq
        ev = traceback.format_exc()
        await m.reply_text(f"<code>{html.escape(ev)}</code>")
    else:
        try:
            await m.reply_text(f"<code>{html.escape(str(res))}</code>")
        except Exception as e:  # skipcq
            await m.reply_text(str(e))


@Client.on_message(filters.command("exec", prefix) & sudofilter)
async def execs(c: Client, m: Message):
    strio = io.StringIO()
    code = m.text.split(maxsplit=1)[1]
    exec(
        "async def __ex(c, m): " + " ".join("\n " + l for l in code.split("\n"))
    )  # skipcq: PYL-W0122
    with redirect_stdout(strio):
        try:
            await locals()["__ex"](c, m)
        except:  # skipcq
            return await m.reply_text(html.escape(traceback.format_exc()))

    if strio.getvalue().strip():
        out = f"<code>{html.escape(strio.getvalue())}</code>"
    else:
        out = "Command executed."
    await m.reply_text(out)


@Client.on_message(filters.command("speedtest", prefix) & sudofilter)
@use_chat_lang()
async def test_speed(c: Client, m: Message, strings):
    string = strings("speedtest")
    sent = await m.reply_text(string.format(host="", ping="", download="", upload=""))
    s = speedtest.Speedtest()
    bs = s.get_best_server()
    await sent.edit_text(
        string.format(
            host=bs["sponsor"], ping=int(bs["latency"]), download="", upload=""
        )
    )
    dl = round(s.download() / 1024 / 1024, 2)
    await sent.edit_text(
        string.format(
            host=bs["sponsor"], ping=int(bs["latency"]), download=dl, upload=""
        )
    )
    ul = round(s.upload() / 1024 / 1024, 2)
    await sent.edit_text(
        string.format(
            host=bs["sponsor"], ping=int(bs["latency"]), download=dl, upload=ul
        )
    )


@Client.on_message(filters.command("sql", prefix) & sudofilter)
async def execsql(c: Client, m: Message):
    command = m.text.split(maxsplit=1)[1]

    try:
        ex = dbc.execute(command)
    except (IntegrityError, OperationalError) as e:
        return await m.reply_text(
            f"SQL executed with an error: {e.__class__.__name__}: {e}"
        )

    ret = ex.fetchall()
    db.commit()

    if ret:
        res = "|".join([name[0] for name in ex.description]) + "\n"
        res += "\n".join(
            ["|".join(str(s) for i, s in enumerate(items)) for items in ret]
        )
        if len(res) > 3500:
            bio = io.BytesIO()
            bio.name = "output.txt"

            bio.write(res.encode())

            await m.reply_document(bio)
        else:
            await m.reply_text(f"<code>{res}</code>")
    else:
        await m.reply_text("SQL executed successfully and without any return.")


@Client.on_message(filters.command("restart", prefix) & sudofilter)
@use_chat_lang()
async def restart(c: Client, m: Message, strings):
    sent = await m.reply_text(strings("restarting"))
    set_restarted(sent.chat.id, sent.id)
    db.commit()
    args = [sys.executable, "-m", "eduu"]
    os.execv(sys.executable, args)  # skipcq: BAN-B606


@Client.on_message(filters.command("leave", prefix) & sudofilter)
async def leave_chat(c: Client, m: Message):
    if len(m.command) == 1:
        try:
            await m.chat.leave()
        except RPCError as e:
            print(e)
    else:
        chat_id = m.text.split(maxsplit=1)[1]
        try:
            await c.leave_chat(int(chat_id))
        except RPCError as e:
            print(e)


@Client.on_message(filters.command(["bot_stats", "stats"], prefix) & sudofilter)
async def getbotstats(c: Client, m: Message):
    users_count = dbc.execute("select count() from users")
    users_count = users_count.fetchone()[0]
    groups_count = dbc.execute("select count() from groups")
    groups_count = groups_count.fetchone()[0]
    filters_count = dbc.execute("select count() from filters")
    filters_count = filters_count.fetchone()[0]
    notes_count = dbc.execute("select count() from notes")
    notes_count = notes_count.fetchone()[0]
    bot_uptime = round(time.time() - c.start_time)
    bot_uptime = humanfriendly.format_timespan(bot_uptime)

    await m.reply_text(
        "<b>Bot statistics:</b>\n\n"
        f"<b>Users:</b> {users_count}\n"
        f"<b>Groups:</b> {groups_count}\n"
        f"<b>Filters:</b> {filters_count}\n"
        f"<b>Notes:</b> {notes_count}\n\n"
        f"<b>Uptime:</b> {bot_uptime}"
    )


@Client.on_message(filters.command("del", prefix) & sudofilter)
async def del_message(c: Client, m: Message):
    try:
        await c.delete_messages(m.chat.id, m.reply_to_message.id)
    except RPCError as e:
        print(e)
    try:
        await c.delete_messages(m.chat.id, m.id)
    except RPCError as e:
        print(e)


@Client.on_message(
    filters.command("backup", prefix)
    & sudofilter
    & ~filters.forwarded
    & ~filters.group
    & ~filters.via_bot
)
async def backupcmd(c: Client, m: Message):
    await m.reply_document(DATABASE_PATH)


@Client.on_message(filters.command("upload", prefix) & sudofilter)
async def uploadfile(c: Client, m: Message):
    if not m.reply_to_message:
        await m.reply_text("You must reply to a file to upload.")

    sent = await m.reply_to_message.reply_text("Uploading file...")
    file_path = await m.reply_to_message.download(
        m.command[1] if len(m.command) > 1 else ""
    )
    await sent.edit_text(f"File successfully saved to {file_path}.")


@Client.on_message(filters.command("doc", prefix) & sudofilter)
async def downloadfile(c: Client, m: Message):
    if len(m.text.split()) > 1:
        await m.reply_document(m.command[1])
    else:
        await m.reply_text("You must specify the document path.")


@Client.on_message(filters.command("chat", prefix) & sudofilter)
async def getchatcmd(c: Client, m: Message):
    if len(m.text.split()) > 1:
        targetchat = await c.get_chat(m.command[1])
        if targetchat.type != ChatType.PRIVATE:
            await m.reply_text(
                f"<b>Title:</b> {targetchat.title}\n<b>Username:</b> {targetchat.username}\n<b>Members:</b> {targetchat.members_count}"
            )
        else:
            await m.reply_text("This is a private Chat.")
    else:
        await m.reply_text("You must specify the Chat.")
