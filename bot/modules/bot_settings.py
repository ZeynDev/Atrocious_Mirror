#!/usr/bin/env python3
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.filters import command, regex, create
from functools import partial
from asyncio import create_subprocess_exec, create_subprocess_shell, sleep, gather
from aiofiles.os import remove, rename, path as aiopath
from aiofiles import open as aiopen
from os import environ, getcwd
from dotenv import load_dotenv
from time import time
from io import BytesIO
from aioshutil import rmtree as aiormtree

from bot import config_dict, user_data, DATABASE_URL, MAX_SPLIT_SIZE, DRIVES_IDS, DRIVES_NAMES, INDEX_URLS, aria2, GLOBAL_EXTENSION_FILTER, status_reply_dict_lock, Interval, aria2_options, aria2c_global, IS_PREMIUM_USER, download_dict, qbit_options, get_client, LOGGER, bot, GLOBAL_BLACKLIST_FILE_KEYWORDS
from bot.helper.telegram_helper.message_utils import sendMessage, sendFile, editMessage, update_all_messages, deleteMessage
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.ext_utils.bot_utils import setInterval, sync_to_async, new_thread
from bot.helper.ext_utils.db_handler import DbManger
from bot.helper.ext_utils.task_manager import start_from_queued
from bot.helper.mirror_utils.rclone_utils.serve import rclone_serve_booter
from bot.modules.torrent_search import initiate_search_tools
from bot.modules.rss import addJob

START = 0
STATE = 'view'
handler_dict = {}
default_values = {'AUTO_DELETE_MESSAGE_DURATION': 30,
                  'DOWNLOAD_DIR': '/usr/src/app/downloads/',
                  'LEECH_SPLIT_SIZE': MAX_SPLIT_SIZE,
                  'RSS_DELAY': 600,
                  'STATUS_UPDATE_INTERVAL': 10,
                  'SEARCH_LIMIT': 0,
                  'UPSTREAM_BRANCH': 'master',
                  'DEFAULT_UPLOAD': 'gd'}


async def get_buttons(key=None, edit_type=None):
    buttons = ButtonMaker()
    if key is None:
        buttons.ibutton('Config Variables', "botset var")
        buttons.ibutton('Private Files', "botset private")
        buttons.ibutton('Qbit Settings', "botset qbit")
        buttons.ibutton('Aria2c Settings', "botset aria")
        buttons.ibutton('Close', "botset close")
        msg = 'Bot Settings:'
    elif key == 'var':
        for k in list(config_dict.keys())[START:10+START]:
            buttons.ibutton(k, f"botset editvar {k}")
        if STATE == 'view':
            buttons.ibutton('Edit', "botset edit var")
        else:
            buttons.ibutton('View', "botset view var")
        buttons.ibutton('Back', "botset back")
        buttons.ibutton('Close', "botset close")
        for x in range(0, len(config_dict), 10):
            buttons.ibutton(
                f'{int(x/10)}', f"botset start var {x}", position='footer')
        msg = f'Config Variables | Page: {int(START/10)} | State: {STATE}'
    elif key == 'private':
        buttons.ibutton('Back', "botset back")
        buttons.ibutton('Close', "botset close")
        msg = '''Send private file: config.env, token.pickle, rclone.conf, accounts.zip, list_drives.txt, cookies.txt, terabox.txt, .netrc or any other private file!
To delete private file send only the file name as text message.
Note: Changing .netrc will not take effect for aria2c until restart.
Timeout: 60 sec'''
    elif key == 'aria':
        for k in list(aria2_options.keys())[START:10+START]:
            buttons.ibutton(k, f"botset editaria {k}")
        if STATE == 'view':
            buttons.ibutton('Edit', "botset edit aria")
        else:
            buttons.ibutton('View', "botset view aria")
        buttons.ibutton('Add new key', "botset editaria newkey")
        buttons.ibutton('Back', "botset back")
        buttons.ibutton('Close', "botset close")
        for x in range(0, len(aria2_options), 10):
            buttons.ibutton(
                f'{int(x/10)}', f"botset start aria {x}", position='footer')
        msg = f'Aria2c Options | Page: {int(START/10)} | State: {STATE}'
    elif key == 'qbit':
        for k in list(qbit_options.keys())[START:10+START]:
            buttons.ibutton(k, f"botset editqbit {k}")
        if STATE == 'view':
            buttons.ibutton('Edit', "botset edit qbit")
        else:
            buttons.ibutton('View', "botset view qbit")
        buttons.ibutton('Back', "botset back")
        buttons.ibutton('Close', "botset close")
        for x in range(0, len(qbit_options), 10):
            buttons.ibutton(
                f'{int(x/10)}', f"botset start qbit {x}", position='footer')
        msg = f'Qbittorrent Options | Page: {int(START/10)} | State: {STATE}'
    elif edit_type == 'editvar':
        msg = ''
        buttons.ibutton('Back', "botset back var")
        if key not in ['TELEGRAM_HASH', 'TELEGRAM_API', 'OWNER_ID', 'BOT_TOKEN']:
            buttons.ibutton('Default', f"botset resetvar {key}")
        buttons.ibutton('Close', "botset close")
        if key in ['SUDO_USERS', 'CMD_SUFFIX', 'OWNER_ID', 'USER_SESSION_STRING', 'TELEGRAM_HASH',
                   'TELEGRAM_API', 'AUTHORIZED_CHATS', 'DATABASE_URL', 'BOT_TOKEN', 'DOWNLOAD_DIR']:
            msg += 'Restart required for this edit to take effect!\n\n'
        msg += f'Send a valid value for {key}. Timeout: 60 sec'
    elif edit_type == 'editaria':
        buttons.ibutton('Back', "botset back aria")
        if key != 'newkey':
            buttons.ibutton('Default', f"botset resetaria {key}")
            buttons.ibutton('Empty String', f"botset emptyaria {key}")
        buttons.ibutton('Close', "botset close")
        if key == 'newkey':
            msg = 'Send a key with value. Example: https-proxy-user:value'
        else:
            msg = f'Send a valid value for {key}. Timeout: 60 sec'
    elif edit_type == 'editqbit':
        buttons.ibutton('Back', "botset back qbit")
        buttons.ibutton('Empty String', f"botset emptyqbit {key}")
        buttons.ibutton('Close', "botset close")
        msg = f'Send a valid value for {key}. Timeout: 60 sec'
    button = buttons.build_menu(2) if key is None else buttons.build_menu(2)
    return msg, button


async def update_buttons(message, key=None, edit_type=None):
    msg, button = await get_buttons(key, edit_type)
    await editMessage(message, msg, button)


async def edit_variable(_, message, pre_message, key):
    handler_dict[message.chat.id] = False
    value = message.text
    if value.lower() == 'true':
        value = True
    elif value.lower() == 'false':
        value = False
        if key == 'INCOMPLETE_TASK_NOTIFIER' and DATABASE_URL:
            await DbManger().trunc_table('tasks')
    elif key == 'RSS_DELAY':
        value = int(value)
        addJob(value)
    elif key == 'DOWNLOAD_DIR':
        if not value.endswith('/'):
            value += '/'
    elif key in ['LEECH_DUMP_CHAT', 'RSS_CHAT']:
        if value.isdigit() or value.startswith('-'):
            value = int(value)
    elif key == 'STATUS_UPDATE_INTERVAL':
        value = int(value)
        if len(download_dict) != 0:
            async with status_reply_dict_lock:
                if Interval:
                    Interval[0].cancel()
                    Interval.clear()
                    Interval.append(setInterval(value, update_all_messages))
    elif key == 'TORRENT_TIMEOUT':
        value = int(value)
        downloads = await sync_to_async(aria2.get_downloads)
        for download in downloads:
            if not download.is_complete:
                try:
                    await sync_to_async(aria2.client.change_option, download.gid, {'bt-stop-timeout': f'{value}'})
                except Exception as e:
                    LOGGER.error(e)
        aria2_options['bt-stop-timeout'] = f'{value}'
    elif key == 'LEECH_SPLIT_SIZE':
        value = min(int(value), MAX_SPLIT_SIZE)
    elif key == 'BASE_URL_PORT':
        value = int(value)
        if config_dict['BASE_URL']:
            await (await create_subprocess_exec("pkill", "-9", "-f", "gunicorn")).wait()
            await create_subprocess_shell(f"gunicorn web.wserver:app --bind 0.0.0.0:{value} --worker-class gevent")
    elif key == 'EXTENSION_FILTER':
        fx = value.split()
        GLOBAL_EXTENSION_FILTER.clear()
        GLOBAL_EXTENSION_FILTER.extend(['aria2', '!qB'])
        for x in fx:
            x = x.lstrip('.')
            GLOBAL_EXTENSION_FILTER.append(x.strip().lower())
    elif key == 'GDRIVE_ID':
        if DRIVES_NAMES and DRIVES_NAMES[0] == 'Main':
            DRIVES_IDS[0] = value
        else:
            DRIVES_IDS.insert(0, value)
    elif key == 'INDEX_URL':
        if DRIVES_NAMES and DRIVES_NAMES[0] == 'Main':
            INDEX_URLS[0] = value
        else:
            INDEX_URLS.insert(0, value)
    elif value.isdigit():
        value = int(value)
    config_dict[key] = value
    await update_buttons(pre_message, 'var')
    await deleteMessage(message)
    if DATABASE_URL:
        await DbManger().update_config({key: value})
    if key in ['SEARCH_PLUGINS', 'SEARCH_API_LINK']:
        await initiate_search_tools()
    elif key in ['QUEUE_ALL', 'QUEUE_DOWNLOAD', 'QUEUE_UPLOAD']:
        await start_from_queued()
    elif key in ['RCLONE_SERVE_URL', 'RCLONE_SERVE_PORT', 'RCLONE_SERVE_USER', 'RCLONE_SERVE_PASS']:
        await rclone_serve_booter()


async def edit_aria(_, message, pre_message, key):
    handler_dict[message.chat.id] = False
    value = message.text
    if key == 'newkey':
        key, value = [x.strip() for x in value.split(':', 1)]
    elif value.lower() == 'true':
        value = "true"
    elif value.lower() == 'false':
        value = "false"
    if key in aria2c_global:
        await sync_to_async(aria2.set_global_options, {key: value})
    else:
        downloads = await sync_to_async(aria2.get_downloads)
        for download in downloads:
            if not download.is_complete:
                try:
                    await sync_to_async(aria2.client.change_option, download.gid, {key: value})
                except Exception as e:
                    LOGGER.error(e)
    aria2_options[key] = value
    await update_buttons(pre_message, 'aria')
    await deleteMessage(message)
    if DATABASE_URL:
        await DbManger().update_aria2(key, value)


async def edit_qbit(_, message, pre_message, key):
    handler_dict[message.chat.id] = False
    value = message.text
    if value.lower() == 'true':
        value = True
    elif value.lower() == 'false':
        value = False
    elif key == 'max_ratio':
        value = float(value)
    elif value.isdigit():
        value = int(value)
    await sync_to_async(get_client().app_set_preferences, {key: value})
    qbit_options[key] = value
    await update_buttons(pre_message, 'qbit')
    await deleteMessage(message)
    if DATABASE_URL:
        await DbManger().update_qbittorrent(key, value)


async def update_private_file(_, message, pre_message):
    handler_dict[message.chat.id] = False
    if not message.media and (file_name := message.text):
        fn = file_name.rsplit('.zip', 1)[0]
        if await aiopath.isfile(fn) and file_name != 'config.env':
            await remove(fn)
        if fn == 'accounts':
            if await aiopath.exists('accounts'):
                await aiormtree('accounts')
            if await aiopath.exists('rclone_sa'):
                await aiormtree('rclone_sa')
            config_dict['USE_SERVICE_ACCOUNTS'] = False
            if DATABASE_URL:
                await DbManger().update_config({'USE_SERVICE_ACCOUNTS': False})
        elif file_name in ['.netrc', 'netrc']:
            await (await create_subprocess_exec("touch", ".netrc")).wait()
            await (await create_subprocess_exec("chmod", "600", ".netrc")).wait()
            await (await create_subprocess_exec("cp", ".netrc", "/root/.netrc")).wait()
        await deleteMessage(message)
    elif doc := message.document:
        file_name = doc.file_name
        await message.download(file_name=f'{getcwd()}/{file_name}')
        if file_name == 'accounts.zip':
            if await aiopath.exists('accounts'):
                await aiormtree('accounts')
            if await aiopath.exists('rclone_sa'):
                await aiormtree('rclone_sa')
            await (await create_subprocess_exec("7z", "x", "-o.", "-aoa", "accounts.zip", "accounts/*.json")).wait()
            await (await create_subprocess_exec("chmod", "-R", "777", "accounts")).wait()
        elif file_name == 'list_drives.txt':
            DRIVES_IDS.clear()
            DRIVES_NAMES.clear()
            INDEX_URLS.clear()
            if GDRIVE_ID := config_dict['GDRIVE_ID']:
                DRIVES_NAMES.append("Main")
                DRIVES_IDS.append(GDRIVE_ID)
                INDEX_URLS.append(config_dict['INDEX_URL'])
            async with aiopen('list_drives.txt', 'r+') as f:
                lines = await f.readlines()
                for line in lines:
                    temp = line.strip().split()
                    DRIVES_IDS.append(temp[1])
                    DRIVES_NAMES.append(temp[0].replace("_", " "))
                    if len(temp) > 2:
                        INDEX_URLS.append(temp[2])
                    else:
                        INDEX_URLS.append('')
        elif file_name in ['.netrc', 'netrc']:
            if file_name == 'netrc':
                await rename('netrc', '.netrc')
                file_name = '.netrc'
            await (await create_subprocess_exec("chmod", "600", ".netrc")).wait()
            await (await create_subprocess_exec("cp", ".netrc", "/root/.netrc")).wait()
        elif file_name == 'config.env':
            load_dotenv('config.env', override=True)
            await load_config()
        if '@github.com' in config_dict['UPSTREAM_REPO']:
            buttons = ButtonMaker()
            msg = 'Push to UPSTREAM_REPO ?'
            buttons.ibutton('Yes!', f"botset push {file_name}")
            buttons.ibutton('No', "botset close")
            await sendMessage(message, msg, buttons.build_menu(2))
        else:
            await deleteMessage(message)
    if file_name == 'rclone.conf':
        await rclone_serve_booter()
    await update_buttons(pre_message)
    if DATABASE_URL:
        await DbManger().update_private_file(file_name)
    if await aiopath.exists('accounts.zip'):
        await remove('accounts.zip')


async def event_handler(client, query, pfunc, rfunc, document=False):
    chat_id = query.message.chat.id
    handler_dict[chat_id] = True
    start_time = time()

    async def event_filter(_, __, event):
        user = event.from_user or event.sender_chat
        return bool(user.id == query.from_user.id and event.chat.id == chat_id and (event.text or event.document and document))
    handler = client.add_handler(MessageHandler(
        pfunc, filters=create(event_filter)), group=-1)
    while handler_dict[chat_id]:
        await sleep(0.5)
        if time() - start_time > 60:
            handler_dict[chat_id] = False
            await rfunc()
    client.remove_handler(*handler)


@new_thread
async def edit_bot_settings(client, query):
    data = query.data.split()
    message = query.message
    if data[1] == 'close':
        handler_dict[message.chat.id] = False
        await query.answer()
        await deleteMessage(message.reply_to_message)
        await deleteMessage(message)
    elif data[1] == 'back':
        handler_dict[message.chat.id] = False
        await query.answer()
        key = data[2] if len(data) == 3 else None
        if key is None:
            globals()['START'] = 0
        await update_buttons(message, key)
    elif data[1] in ['var', 'aria', 'qbit']:
        await query.answer()
        await update_buttons(message, data[1])
    elif data[1] == 'resetvar':
        handler_dict[message.chat.id] = False
        await query.answer()
        value = ''
        if data[2] in default_values:
            value = default_values[data[2]]
            if data[2] == "STATUS_UPDATE_INTERVAL" and len(download_dict) != 0:
                async with status_reply_dict_lock:
                    if Interval:
                        Interval[0].cancel()
                        Interval.clear()
                        Interval.append(setInterval(
                            value, update_all_messages))
        elif data[2] == 'EXTENSION_FILTER':
            GLOBAL_EXTENSION_FILTER.clear()
            GLOBAL_EXTENSION_FILTER.extend(['aria2', '!qB'])
        elif data[2] == 'TORRENT_TIMEOUT':
            downloads = await sync_to_async(aria2.get_downloads)
            for download in downloads:
                if not download.is_complete:
                    try:
                        await sync_to_async(aria2.client.change_option, download.gid, {'bt-stop-timeout': '0'})
                    except Exception as e:
                        LOGGER.error(e)
            aria2_options['bt-stop-timeout'] = '0'
            if DATABASE_URL:
                await DbManger().update_aria2('bt-stop-timeout', '0')
        elif data[2] == 'BASE_URL':
            await (await create_subprocess_exec("pkill", "-9", "-f", "gunicorn")).wait()
        elif data[2] == 'BASE_URL_PORT':
            value = 80
            if config_dict['BASE_URL']:
                await (await create_subprocess_exec("pkill", "-9", "-f", "gunicorn")).wait()
                await create_subprocess_shell("gunicorn web.wserver:app --bind 0.0.0.0:80 --worker-class gevent")
        elif data[2] == 'GDRIVE_ID':
            if DRIVES_NAMES and DRIVES_NAMES[0] == 'Main':
                DRIVES_NAMES.pop(0)
                DRIVES_IDS.pop(0)
                INDEX_URLS.pop(0)
        elif data[2] == 'INDEX_URL':
            if DRIVES_NAMES and DRIVES_NAMES[0] == 'Main':
                INDEX_URLS[0] = ''
        elif data[2] == 'INCOMPLETE_TASK_NOTIFIER' and DATABASE_URL:
            await DbManger().trunc_table('tasks')
        config_dict[data[2]] = value
        await update_buttons(message, 'var')
        if DATABASE_URL:
            await DbManger().update_config({data[2]: value})
        if data[2] in ['SEARCH_PLUGINS', 'SEARCH_API_LINK']:
            await initiate_search_tools()
        elif data[2] in ['QUEUE_ALL', 'QUEUE_DOWNLOAD', 'QUEUE_UPLOAD']:
            await start_from_queued()
        elif data[2] in ['RCLONE_SERVE_URL', 'RCLONE_SERVE_PORT', 'RCLONE_SERVE_USER', 'RCLONE_SERVE_PASS']:
            await rclone_serve_booter()
    elif data[1] == 'resetaria':
        handler_dict[message.chat.id] = False
        aria2_defaults = await sync_to_async(aria2.client.get_global_option)
        if aria2_defaults[data[2]] == aria2_options[data[2]]:
            await query.answer('Value already same as you added in aria.sh!')
            return
        await query.answer()
        value = aria2_defaults[data[2]]
        aria2_options[data[2]] = value
        await update_buttons(message, 'aria')
        downloads = await sync_to_async(aria2.get_downloads)
        for download in downloads:
            if not download.is_complete:
                try:
                    await sync_to_async(aria2.client.change_option, download.gid, {data[2]: value})
                except Exception as e:
                    LOGGER.error(e)
        if DATABASE_URL:
            await DbManger().update_aria2(data[2], value)
    elif data[1] == 'emptyaria':
        handler_dict[message.chat.id] = False
        await query.answer()
        aria2_options[data[2]] = ''
        await update_buttons(message, 'aria')
        downloads = await sync_to_async(aria2.get_downloads)
        for download in downloads:
            if not download.is_complete:
                try:
                    await sync_to_async(aria2.client.change_option, download.gid, {data[2]: ''})
                except Exception as e:
                    LOGGER.error(e)
        if DATABASE_URL:
            await DbManger().update_aria2(data[2], '')
    elif data[1] == 'emptyqbit':
        handler_dict[message.chat.id] = False
        await query.answer()
        await sync_to_async(get_client().app_set_preferences, {data[2]: value})
        qbit_options[data[2]] = ''
        await update_buttons(message, 'qbit')
        if DATABASE_URL:
            await DbManger().update_qbittorrent(data[2], '')
    elif data[1] == 'private':
        handler_dict[message.chat.id] = False
        await query.answer()
        await update_buttons(message, data[1])
        pfunc = partial(update_private_file, pre_message=message)
        rfunc = partial(update_buttons, message)
        await event_handler(client, query, pfunc, rfunc, True)
    elif data[1] == 'editvar' and STATE == 'edit':
        handler_dict[message.chat.id] = False
        await query.answer()
        await update_buttons(message, data[2], data[1])
        pfunc = partial(edit_variable, pre_message=message, key=data[2])
        rfunc = partial(update_buttons, message, 'var')
        await event_handler(client, query, pfunc, rfunc)
    elif data[1] == 'editvar' and STATE == 'view':
        value = config_dict[data[2]]
        if len(str(value)) > 200:
            await query.answer()
            with BytesIO(str.encode(value)) as out_file:
                out_file.name = f"{data[2]}.txt"
                await sendFile(message, out_file)
            return
        elif value == '':
            value = None
        await query.answer(f'{value}', show_alert=True)
    elif data[1] == 'editaria' and (STATE == 'edit' or data[2] == 'newkey'):
        handler_dict[message.chat.id] = False
        await query.answer()
        await update_buttons(message, data[2], data[1])
        pfunc = partial(edit_aria, pre_message=message, key=data[2])
        rfunc = partial(update_buttons, message, 'aria')
        await event_handler(client, query, pfunc, rfunc)
    elif data[1] == 'editaria' and STATE == 'view':
        value = aria2_options[data[2]]
        if len(str(value)) > 200:
            await query.answer()
            with BytesIO(str.encode(value)) as out_file:
                out_file.name = f"{data[2]}.txt"
                await sendFile(message, out_file)
            return
        elif value == '':
            value = None
        await query.answer(f'{value}', show_alert=True)
    elif data[1] == 'editqbit' and STATE == 'edit':
        handler_dict[message.chat.id] = False
        await query.answer()
        await update_buttons(message, data[2], data[1])
        pfunc = partial(edit_qbit, pre_message=message, key=data[2])
        rfunc = partial(update_buttons, message, 'var')
        await event_handler(client, query, pfunc, rfunc)
    elif data[1] == 'editqbit' and STATE == 'view':
        value = qbit_options[data[2]]
        if len(str(value)) > 200:
            await query.answer()
            with BytesIO(str.encode(value)) as out_file:
                out_file.name = f"{data[2]}.txt"
                await sendFile(message, out_file)
            return
        elif value == '':
            value = None
        await query.answer(f'{value}', show_alert=True)
    elif data[1] == 'edit':
        await query.answer()
        globals()['STATE'] = 'edit'
        await update_buttons(message, data[2])
    elif data[1] == 'view':
        await query.answer()
        globals()['STATE'] = 'view'
        await update_buttons(message, data[2])
    elif data[1] == 'start':
        await query.answer()
        if START != int(data[3]):
            globals()['START'] = int(data[3])
            await update_buttons(message, data[2])
    elif data[1] == 'push':
        await query.answer()
        filename = data[2].rsplit('.zip', 1)[0]
        if await aiopath.exists(filename):
            await (await create_subprocess_shell(f"git add -f {filename} \
                                                   && git commit -sm botsettings -q \
                                                   && git push origin {config_dict['UPSTREAM_BRANCH']} -qf")).wait()
        else:
            await (await create_subprocess_shell(f"git rm -r --cached {filename} \
                                                   && git commit -sm botsettings -q \
                                                   && git push origin {config_dict['UPSTREAM_BRANCH']} -qf")).wait()
        await deleteMessage(message.reply_to_message)
        await deleteMessage(message)


async def bot_settings(_, message):
    handler_dict[message.chat.id] = False
    msg, button = await get_buttons()
    globals()['START'] = 0
    await sendMessage(message, msg, button, photo=True)


async def load_config():
    BOT_TOKEN = environ.get('BOT_TOKEN', '')
    if len(BOT_TOKEN) == 0:
        BOT_TOKEN = config_dict['BOT_TOKEN']

    TELEGRAM_API = environ.get('TELEGRAM_API', '')
    if len(TELEGRAM_API) == 0:
        TELEGRAM_API = config_dict['TELEGRAM_API']
    else:
        TELEGRAM_API = int(TELEGRAM_API)

    TELEGRAM_HASH = environ.get('TELEGRAM_HASH', '')
    if len(TELEGRAM_HASH) == 0:
        TELEGRAM_HASH = config_dict['TELEGRAM_HASH']

    OWNER_ID = environ.get('OWNER_ID', '')
    OWNER_ID = config_dict['OWNER_ID'] if len(OWNER_ID) == 0 else int(OWNER_ID)

    DATABASE_URL = environ.get('DATABASE_URL', '')
    if len(DATABASE_URL) == 0:
        DATABASE_URL = ''

    DOWNLOAD_DIR = environ.get('DOWNLOAD_DIR', '')
    if len(DOWNLOAD_DIR) == 0:
        DOWNLOAD_DIR = '/usr/src/app/downloads/'
    elif not DOWNLOAD_DIR.endswith("/"):
        DOWNLOAD_DIR = f'{DOWNLOAD_DIR}/'

    GDRIVE_ID = environ.get('GDRIVE_ID', '')
    if len(GDRIVE_ID) == 0:
        GDRIVE_ID = ''

    RCLONE_PATH = environ.get('RCLONE_PATH', '')
    if len(RCLONE_PATH) == 0:
        RCLONE_PATH = ''

    DEFAULT_UPLOAD = environ.get('DEFAULT_UPLOAD', '')
    if DEFAULT_UPLOAD != 'rc':
        DEFAULT_UPLOAD = 'gd'

    RCLONE_FLAGS = environ.get('RCLONE_FLAGS', '')
    if len(RCLONE_FLAGS) == 0:
        RCLONE_FLAGS = ''

    AUTHORIZED_CHATS = environ.get('AUTHORIZED_CHATS', '')
    if len(AUTHORIZED_CHATS) != 0:
        aid = AUTHORIZED_CHATS.split()
        for id_ in aid:
            user_data[int(id_.strip())] = {'is_auth': True}

    SUDO_USERS = environ.get('SUDO_USERS', '')
    if len(SUDO_USERS) != 0:
        aid = SUDO_USERS.split()
        for id_ in aid:
            user_data[int(id_.strip())] = {'is_sudo': True}

    EXTENSION_FILTER = environ.get('EXTENSION_FILTER', '')
    if len(EXTENSION_FILTER) > 0:
        fx = EXTENSION_FILTER.split()
        GLOBAL_EXTENSION_FILTER.clear()
        GLOBAL_EXTENSION_FILTER.extend(['aria2', '!qB'])
        for x in fx:
            if x.strip().startswith('.'):
                x = x.lstrip('.')
            GLOBAL_EXTENSION_FILTER.append(x.strip().lower())

    MEGA_EMAIL = environ.get('MEGA_EMAIL', '')
    MEGA_PASSWORD = environ.get('MEGA_PASSWORD', '')
    if len(MEGA_EMAIL) == 0 or len(MEGA_PASSWORD) == 0:
        MEGA_EMAIL = ''
        MEGA_PASSWORD = ''

    UPTOBOX_TOKEN = environ.get('UPTOBOX_TOKEN', '')
    if len(UPTOBOX_TOKEN) == 0:
        UPTOBOX_TOKEN = ''

    FILELION_API = environ.get('FILELION_API', '')
    if len(FILELION_API) == 0:
        FILELION_API = ''

    INDEX_URL = environ.get('INDEX_URL', '').rstrip("/")
    if len(INDEX_URL) == 0:
        INDEX_URL = ''

    SEARCH_API_LINK = environ.get('SEARCH_API_LINK', '').rstrip("/")
    if len(SEARCH_API_LINK) == 0:
        SEARCH_API_LINK = ''

    LEECH_FILENAME_PREFIX = environ.get('LEECH_FILENAME_PREFIX', '')
    if len(LEECH_FILENAME_PREFIX) == 0:
        LEECH_FILENAME_PREFIX = ''

    SEARCH_PLUGINS = environ.get('SEARCH_PLUGINS', '')
    if len(SEARCH_PLUGINS) == 0:
        SEARCH_PLUGINS = ''

    MAX_SPLIT_SIZE = 4194304000 if IS_PREMIUM_USER else 2097152000

    LEECH_SPLIT_SIZE = environ.get('LEECH_SPLIT_SIZE', '')
    if len(LEECH_SPLIT_SIZE) == 0 or int(LEECH_SPLIT_SIZE) > MAX_SPLIT_SIZE:
        LEECH_SPLIT_SIZE = MAX_SPLIT_SIZE
    else:
        LEECH_SPLIT_SIZE = int(LEECH_SPLIT_SIZE)

    STATUS_UPDATE_INTERVAL = environ.get('STATUS_UPDATE_INTERVAL', '')
    if len(STATUS_UPDATE_INTERVAL) == 0:
        STATUS_UPDATE_INTERVAL = 10
    else:
        STATUS_UPDATE_INTERVAL = int(STATUS_UPDATE_INTERVAL)
    if len(download_dict) != 0:
        async with status_reply_dict_lock:
            if Interval:
                Interval[0].cancel()
                Interval.clear()
                Interval.append(setInterval(
                    STATUS_UPDATE_INTERVAL, update_all_messages))

    AUTO_DELETE_MESSAGE_DURATION = environ.get(
        'AUTO_DELETE_MESSAGE_DURATION', '')
    if len(AUTO_DELETE_MESSAGE_DURATION) == 0:
        AUTO_DELETE_MESSAGE_DURATION = 30
    else:
        AUTO_DELETE_MESSAGE_DURATION = int(AUTO_DELETE_MESSAGE_DURATION)

    YT_DLP_OPTIONS = environ.get('YT_DLP_OPTIONS', '')
    if len(YT_DLP_OPTIONS) == 0:
        YT_DLP_OPTIONS = ''

    SEARCH_LIMIT = environ.get('SEARCH_LIMIT', '')
    SEARCH_LIMIT = 0 if len(SEARCH_LIMIT) == 0 else int(SEARCH_LIMIT)

    LEECH_DUMP_CHAT = environ.get('LEECH_DUMP_CHAT', '')
    LEECH_DUMP_CHAT = '' if len(LEECH_DUMP_CHAT) == 0 else LEECH_DUMP_CHAT
    if LEECH_DUMP_CHAT.isdigit() or LEECH_DUMP_CHAT.startswith('-'):
        LEECH_DUMP_CHAT = int(LEECH_DUMP_CHAT)

    STATUS_LIMIT = environ.get('STATUS_LIMIT', '')
    STATUS_LIMIT = 10 if len(STATUS_LIMIT) == 0 else int(STATUS_LIMIT)

    RSS_CHAT = environ.get('RSS_CHAT', '')
    RSS_CHAT = '' if len(RSS_CHAT) == 0 else RSS_CHAT
    if RSS_CHAT.isdigit() or RSS_CHAT.startswith('-'):
        RSS_CHAT = int(RSS_CHAT)

    RSS_DELAY = environ.get('RSS_DELAY', '')
    RSS_DELAY = 600 if len(RSS_DELAY) == 0 else int(RSS_DELAY)

    CMD_SUFFIX = environ.get('CMD_SUFFIX', '')

    USER_SESSION_STRING = environ.get('USER_SESSION_STRING', '')

    TORRENT_TIMEOUT = environ.get('TORRENT_TIMEOUT', '')
    downloads = aria2.get_downloads()
    if len(TORRENT_TIMEOUT) == 0:
        for download in downloads:
            if not download.is_complete:
                try:
                    await sync_to_async(aria2.client.change_option, download.gid, {'bt-stop-timeout': '0'})
                except Exception as e:
                    LOGGER.error(e)
        aria2_options['bt-stop-timeout'] = '0'
        if DATABASE_URL:
            await DbManger().update_aria2('bt-stop-timeout', '0')
        TORRENT_TIMEOUT = ''
    else:
        for download in downloads:
            if not download.is_complete:
                try:
                    await sync_to_async(aria2.client.change_option, download.gid, {'bt-stop-timeout': TORRENT_TIMEOUT})
                except Exception as e:
                    LOGGER.error(e)
        aria2_options['bt-stop-timeout'] = TORRENT_TIMEOUT
        if DATABASE_URL:
            await DbManger().update_aria2('bt-stop-timeout', TORRENT_TIMEOUT)
        TORRENT_TIMEOUT = int(TORRENT_TIMEOUT)

    QUEUE_ALL = environ.get('QUEUE_ALL', '')
    QUEUE_ALL = '' if len(QUEUE_ALL) == 0 else int(QUEUE_ALL)

    QUEUE_DOWNLOAD = environ.get('QUEUE_DOWNLOAD', '')
    QUEUE_DOWNLOAD = '' if len(QUEUE_DOWNLOAD) == 0 else int(QUEUE_DOWNLOAD)

    QUEUE_UPLOAD = environ.get('QUEUE_UPLOAD', '')
    QUEUE_UPLOAD = '' if len(QUEUE_UPLOAD) == 0 else int(QUEUE_UPLOAD)

    INCOMPLETE_TASK_NOTIFIER = environ.get('INCOMPLETE_TASK_NOTIFIER', '')
    INCOMPLETE_TASK_NOTIFIER = INCOMPLETE_TASK_NOTIFIER.lower() == 'true'
    if not INCOMPLETE_TASK_NOTIFIER and DATABASE_URL:
        await DbManger().trunc_table('tasks')

    STOP_DUPLICATE = environ.get('STOP_DUPLICATE', '')
    STOP_DUPLICATE = STOP_DUPLICATE.lower() == 'true'

    IS_TEAM_DRIVE = environ.get('IS_TEAM_DRIVE', '')
    IS_TEAM_DRIVE = IS_TEAM_DRIVE.lower() == 'true'

    USE_SERVICE_ACCOUNTS = environ.get('USE_SERVICE_ACCOUNTS', '')
    USE_SERVICE_ACCOUNTS = USE_SERVICE_ACCOUNTS.lower() == 'true'

    WEB_PINCODE = environ.get('WEB_PINCODE', '')
    WEB_PINCODE = WEB_PINCODE.lower() == 'true'

    AS_DOCUMENT = environ.get('AS_DOCUMENT', '')
    AS_DOCUMENT = AS_DOCUMENT.lower() == 'true'

    EQUAL_SPLITS = environ.get('EQUAL_SPLITS', '')
    EQUAL_SPLITS = EQUAL_SPLITS.lower() == 'true'

    MEDIA_GROUP = environ.get('MEDIA_GROUP', '')
    MEDIA_GROUP = MEDIA_GROUP.lower() == 'true'

    USER_LEECH = environ.get('USER_LEECH', '')
    USER_LEECH = USER_LEECH.lower() == 'true' and IS_PREMIUM_USER

    BASE_URL_PORT = environ.get('BASE_URL_PORT', '')
    BASE_URL_PORT = 80 if len(BASE_URL_PORT) == 0 else int(BASE_URL_PORT)

    RCLONE_SERVE_URL = environ.get('RCLONE_SERVE_URL', '')
    if len(RCLONE_SERVE_URL) == 0:
        RCLONE_SERVE_URL = ''

    RCLONE_SERVE_PORT = environ.get('RCLONE_SERVE_PORT', '')
    RCLONE_SERVE_PORT = 8080 if len(
        RCLONE_SERVE_PORT) == 0 else int(RCLONE_SERVE_PORT)

    RCLONE_SERVE_USER = environ.get('RCLONE_SERVE_USER', '')
    if len(RCLONE_SERVE_USER) == 0:
        RCLONE_SERVE_USER = ''

    RCLONE_SERVE_PASS = environ.get('RCLONE_SERVE_PASS', '')
    if len(RCLONE_SERVE_PASS) == 0:
        RCLONE_SERVE_PASS = ''

    await (await create_subprocess_exec("pkill", "-9", "-f", "gunicorn")).wait()
    BASE_URL = environ.get('BASE_URL', '').rstrip("/")
    if len(BASE_URL) == 0:
        BASE_URL = ''
    else:
        await create_subprocess_shell(f"gunicorn web.wserver:app --bind 0.0.0.0:{BASE_URL_PORT} --worker-class gevent")

    UPSTREAM_REPO = environ.get('UPSTREAM_REPO', '')
    if len(UPSTREAM_REPO) == 0:
        UPSTREAM_REPO = ''

    UPSTREAM_BRANCH = environ.get('UPSTREAM_BRANCH', '')
    if len(UPSTREAM_BRANCH) == 0:
        UPSTREAM_BRANCH = 'master'

    BLACKLIST_FILE_KEYWORDS = environ.get('BLACKLIST_FILE_KEYWORDS', '')
    if len(BLACKLIST_FILE_KEYWORDS) > 0:
        fx = BLACKLIST_FILE_KEYWORDS.split()
        for x in fx:
            x = x.lstrip('.')
            GLOBAL_BLACKLIST_FILE_KEYWORDS.append(x.strip().lower())

    BOT_MAX_TASKS = environ.get('BOT_MAX_TASKS', '')
    BOT_MAX_TASKS = int(BOT_MAX_TASKS) if BOT_MAX_TASKS.isdigit() else ''

    BOT_PM = environ.get('BOT_PM', '')
    BOT_PM = BOT_PM.lower() == 'true'

    CLONE_ENABLED = environ.get('CLONE_ENABLED', '')
    CLONE_ENABLED = CLONE_ENABLED.lower() == 'true'

    CLONE_LIMIT = environ.get('CLONE_LIMIT', '')
    CLONE_LIMIT = '' if len(CLONE_LIMIT) == 0 else float(CLONE_LIMIT)

    DELETE_LINKS = environ.get('DELETE_LINKS', '')
    DELETE_LINKS = DELETE_LINKS.lower() == 'true'

    DISABLE_DRIVE_LINK = environ.get('DISABLE_DRIVE_LINK', '')
    DISABLE_DRIVE_LINK = DISABLE_DRIVE_LINK.lower() == 'true'

    USER_TD_ENABLED = environ.get('USER_TD_ENABLED', '')
    USER_TD_ENABLED = USER_TD_ENABLED.lower() == 'true'

    FSUB_IDS = environ.get('FSUB_IDS', '')
    if len(FSUB_IDS) == 0:
        FSUB_IDS = ''

    GDRIVE_ENABLED = environ.get('GDRIVE_ENABLED', '')
    GDRIVE_ENABLED = GDRIVE_ENABLED.lower() == 'true'

    GDRIVE_LIMIT = environ.get('GDRIVE_LIMIT', '')
    GDRIVE_LIMIT = '' if len(GDRIVE_LIMIT) == 0 else float(GDRIVE_LIMIT)

    IMAGES = environ.get('IMAGES', '')
    IMAGES = (IMAGES.replace("'", '').replace('"', '').replace(
    '[', '').replace(']', '').replace(",", "")).split()

    LEECH_ENABLED = environ.get('LEECH_ENABLED', '')
    LEECH_ENABLED = LEECH_ENABLED.lower() == 'true'

    LEECH_LIMIT = environ.get('LEECH_LIMIT', '')
    LEECH_LIMIT = '' if len(LEECH_LIMIT) == 0 else float(LEECH_LIMIT)

    MEGA_ENABLED = environ.get('MEGA_ENABLED', '')
    MEGA_ENABLED = MEGA_ENABLED.lower() == 'true'

    MEGA_LIMIT = environ.get('MEGA_LIMIT', '')
    MEGA_LIMIT = '' if len(MEGA_LIMIT) == 0 else float(MEGA_LIMIT)

    MIRROR_ENABLED = environ.get('MIRROR_ENABLED', '')
    MIRROR_ENABLED = MIRROR_ENABLED.lower() == 'true'

    MIRROR_LIMIT = environ.get('MIRROR_LIMIT', '')
    MIRROR_LIMIT = '' if len(MIRROR_LIMIT) == 0 else float(MIRROR_LIMIT)

    MIRROR_LOG_CHAT = environ.get('MIRROR_LOG_CHAT', '')
    MIRROR_LOG_CHAT = '' if len(MIRROR_LOG_CHAT) == 0 else float(MIRROR_LOG_CHAT)

    PAID_SERVICE = environ.get('PAID_SERVICE', '')
    if len(PAID_SERVICE) == 0:
        PAID_SERVICE = ''

    SA_MAIL = environ.get('SA_MAIL', '')
    if len(SA_MAIL) == 0:
        SA_MAIL = ''
            
    SAFE_MODE = environ.get('SAFE_MODE', '')
    if len(SAFE_MODE) == 0:
        log_warning('SAFE_MODE Is Not Enabled')
        SAFE_MODE = ''
            
    SET_COMMANDS = environ.get('SET_COMMANDS', '')
    SET_COMMANDS = SET_COMMANDS.lower() == 'true'

    STATUS_HEADER = environ.get('STATUS_HEADER', '')
    if len(STATUS_HEADER) == 0:
        STATUS_HEADER = ''

    STORAGE_THRESHOLD = environ.get('STORAGE_THRESHOLD', '')
    STORAGE_THRESHOLD = '' if len(
    STORAGE_THRESHOLD) == 0 else float(STORAGE_THRESHOLD)

    THEME_ENABLED = environ.get('THEME_ENABLED', '')
    if len(THEME_ENABLED) == 0:
        THEME_ENABLED = ''
  
    TOKEN_TIMEOUT = environ.get('TOKEN_TIMEOUT', '')
    TOKEN_TIMEOUT = int(TOKEN_TIMEOUT) if TOKEN_TIMEOUT.isdigit() else ''

    TORRENT_ENABLED = environ.get('TORRENT_ENABLED', '')
    TORRENT_ENABLED = TORRENT_ENABLED.lower() == 'true'

    TORRENT_LIMIT = environ.get('TORRENT_LIMIT', '')
    TORRENT_LIMIT = '' if len(TORRENT_LIMIT) == 0 else float(TORRENT_LIMIT)

    USER_MAX_TASKS = environ.get('USER_MAX_TASKS', '')
    USER_MAX_TASKS = int(USER_MAX_TASKS) if USER_MAX_TASKS.isdigit() else ''

    YTDLP_ENABLED = environ.get('YTDLP_ENABLED', '')
    YTDLP_ENABLED = YTDLP_ENABLED.lower() == 'true'

    YTDLP_LIMIT = environ.get('YTDLP_LIMIT', '')
    YTDLP_LIMIT = '' if len(YTDLP_LIMIT) == 0 else float(YTDLP_LIMIT)

    DRIVES_IDS.clear()
    DRIVES_NAMES.clear()
    INDEX_URLS.clear()

    if GDRIVE_ID:
        DRIVES_NAMES.append("Main")
        DRIVES_IDS.append(GDRIVE_ID)
        INDEX_URLS.append(INDEX_URL)

    if await aiopath.exists('list_drives.txt'):
        async with aiopen('list_drives.txt', 'r+') as f:
            lines = await f.readlines()
            for line in lines:
                temp = line.strip().split()
                DRIVES_IDS.append(temp[1])
                DRIVES_NAMES.append(temp[0].replace("_", " "))
                if len(temp) > 2:
                    INDEX_URLS.append(temp[2])
                else:
                    INDEX_URLS.append('')

    if ospath.exists('shorteners.txt'):
        with open('shorteners.txt', 'r+') as f:
            lines = f.readlines()
            for line in lines:
                temp = line.strip().split()
                if len(temp) == 2:
                    shorteneres_list.append({'domain': temp[0],'api_key': temp[1]})
              
    config_dict.update({'AS_DOCUMENT': AS_DOCUMENT,
                        'AUTHORIZED_CHATS': AUTHORIZED_CHATS,
                        'AUTO_DELETE_MESSAGE_DURATION': AUTO_DELETE_MESSAGE_DURATION,
                        'BASE_URL': BASE_URL,
                        'BASE_URL_PORT': BASE_URL_PORT,
                        'BLACKLIST_FILE_KEYWORDS': BLACKLIST_FILE_KEYWORDS,
                        'BOT_MAX_TASKS': BOT_MAX_TASKS,
                        'BOT_PM': BOT_PM,
                        'BOT_TOKEN': BOT_TOKEN,
                        'CLONE_ENABLED': CLONE_ENABLED,
                        'CLONE_LIMIT': CLONE_LIMIT,
                        'CMD_SUFFIX': CMD_SUFFIX,
                        'DATABASE_URL': DATABASE_URL,
                        'DEFAULT_UPLOAD': DEFAULT_UPLOAD,
                        'DELETE_LINKS': DELETE_LINKS,
                        'DISABLE_DRIVE_LINK': DISABLE_DRIVE_LINK,
                        'DOWNLOAD_DIR': DOWNLOAD_DIR,
                        'EQUAL_SPLITS': EQUAL_SPLITS,
                        'EXTENSION_FILTER': EXTENSION_FILTER,
                        'FILELION_API': FILELION_API,
                        'FSUB_IDS': FSUB_IDS,
                        'GDRIVE_ENABLED': GDRIVE_ENABLED,
                        'GDRIVE_ID': GDRIVE_ID,
                        'GDRIVE_LIMIT': GDRIVE_LIMIT,
                        'IMAGES': IMAGES,
                        'INCOMPLETE_TASK_NOTIFIER': INCOMPLETE_TASK_NOTIFIER,
                        'INDEX_URL': INDEX_URL,
                        'IS_TEAM_DRIVE': IS_TEAM_DRIVE,
                        'LEECH_DUMP_CHAT': LEECH_DUMP_CHAT,
                        'LEECH_ENABLED': LEECH_ENABLED,
                        'LEECH_FILENAME_PREFIX': LEECH_FILENAME_PREFIX,
                        'LEECH_SPLIT_SIZE': LEECH_SPLIT_SIZE,
                        'MEDIA_GROUP': MEDIA_GROUP,
                        'MEGA_EMAIL': MEGA_EMAIL,
                        'MEGA_LIMIT': MEGA_LIMIT,
                        'MEGA_PASSWORD': MEGA_PASSWORD,
                        'MIRROR_ENABLED': MIRROR_ENABLED,
                        'MIRROR_LIMIT': MIRROR_LIMIT,
                        'MIRROR_LOG_CHAT': MIRROR_LOG_CHAT,
                        'OWNER_ID': OWNER_ID,
                        'PAID_SERVICE': PAID_SERVICE,
                        'QUEUE_ALL': QUEUE_ALL,
                        'QUEUE_DOWNLOAD': QUEUE_DOWNLOAD,
                        'QUEUE_UPLOAD': QUEUE_UPLOAD,
                        'RCLONE_FLAGS': RCLONE_FLAGS,
                        'RCLONE_PATH': RCLONE_PATH,
                        'RCLONE_SERVE_URL': RCLONE_SERVE_URL,
                        'RCLONE_SERVE_USER': RCLONE_SERVE_USER,
                        'RCLONE_SERVE_PASS': RCLONE_SERVE_PASS,
                        'RCLONE_SERVE_PORT': RCLONE_SERVE_PORT,
                        'RSS_CHAT': RSS_CHAT,
                        'RSS_DELAY': RSS_DELAY,
                        'SA_MAIL': SA_MAIL,
                        'SAFE_MODE': SAFE_MODE,
                        'SEARCH_API_LINK': SEARCH_API_LINK,
                        'SEARCH_LIMIT': SEARCH_LIMIT,
                        'SEARCH_PLUGINS': SEARCH_PLUGINS,
                        'SET_COMMANDS': SET_COMMANDS,
                        'STATUS_HEADER': STATUS_HEADER,
                        'STATUS_LIMIT': STATUS_LIMIT,
                        'STATUS_UPDATE_INTERVAL': STATUS_UPDATE_INTERVAL,
                        'STOP_DUPLICATE': STOP_DUPLICATE,
                        'STORAGE_THRESHOLD': STORAGE_THRESHOLD,
                        'SUDO_USERS': SUDO_USERS,
                        'TELEGRAM_API': TELEGRAM_API,
                        'TELEGRAM_HASH': TELEGRAM_HASH,
                        'THEME_ENABLED': THEME_ENABLED,
                        'TOKEN_TIMEOUT': TOKEN_TIMEOUT,
                        'TORRENT_ENABLED': TORRENT_ENABLED,
                        'TORRENT_LIMIT': TORRENT_LIMIT,
                        'TORRENT_TIMEOUT': TORRENT_TIMEOUT,
                        'USER_LEECH': USER_LEECH,
                        'USER_MAX_TASKS': USER_MAX_TASKS,
                        'UPSTREAM_REPO': UPSTREAM_REPO,
                        'UPSTREAM_BRANCH': UPSTREAM_BRANCH,
                        'UPTOBOX_TOKEN': UPTOBOX_TOKEN,
                        'USER_SESSION_STRING': USER_SESSION_STRING,
                        'USE_SERVICE_ACCOUNTS': USE_SERVICE_ACCOUNTS,
                        'WEB_PINCODE': WEB_PINCODE,
                        'YTDLP_ENABLED': YTDLP_ENABLED,
                        'YTDLP_LIMIT': YTDLP_LIMIT,
                        'YT_DLP_OPTIONS': YT_DLP_OPTIONS})

    if DATABASE_URL:
        await DbManger().update_config(config_dict)
    await gather(initiate_search_tools(), start_from_queued(), rclone_serve_booter())


bot.add_handler(MessageHandler(bot_settings, filters=command(
    BotCommands.BotSetCommand) & CustomFilters.sudo))
bot.add_handler(CallbackQueryHandler(edit_bot_settings,
                filters=regex("^botset") & CustomFilters.sudo))
