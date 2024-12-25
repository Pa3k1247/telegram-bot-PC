import asyncio
import os
import socket
import logging
from aiogram import F
import json
import webbrowser
from wakeonlan import send_magic_packet
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import subprocess
import psutil  # Для получения MAC-адреса
import socket
import shutil
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters import Command
from pynvml import (
    nvmlInit, nvmlDeviceGetCount, nvmlDeviceGetHandleByIndex,
    nvmlDeviceGetName, nvmlDeviceGetMemoryInfo, nvmlDeviceGetTemperature,
    nvmlShutdown, NVML_TEMPERATURE_GPU
)
from fastapi import FastAPI, Request
from googlesearch import search
from contextvars import ContextVar
from pathlib import Path
class UserState(StatesGroup):
    waiting_for_app = State()
    waiting_for_site = State()
    waiting_for_mac = State()
from dotenv import load_dotenv


def is_executable(file_path):
    return os.path.isfile(file_path) and file_path.endswith('.exe')

app = FastAPI()

load_dotenv()
AUTHORIZED_USERS = set()
CACHE_FILE = "cache.json"

bot = Bot(os.getenv('TOKEN'))
dp = Dispatcher()

waiting_for_site = {}
waiting_for_pid = {}

STATE_WAITING_FOR_SITE = "waiting_for_site"
STATE_WAITING_FOR_APP = "waiting_for_app"



logging.basicConfig(level=logging.INFO)

# Глобальный кэш для хранения путей
game_paths = {}
user_data = {}  # Глобальный словарь для хранения состояния пользователей


user_states = {}

STATE_WAITING_FOR_APP = "waiting_for_app"
STATE_WAITING_FOR_SITE = "waiting_for_site"


SITES_SYNONYMS = {
    "youtube": ["youtube", "ютуб", "youtub", "ютюб"],
    "google": ["google", "гугл", "гоугл"],
    "facebook": ["facebook", "фейсбук"],
    "instagram": ["instagram", "инстаграм", "инста"],
    # Добавьте другие сайты по аналогии
}


# Обработчик команды /start
def is_valid_mac_address(mac_address: str) -> bool:
    # Заменяем дефисы на двоеточия
    mac_address = mac_address.replace("-", ":")
    
    # Проверяем, что MAC-адрес состоит из 17 символов и 5 двоеточий
    if len(mac_address) == 17 and mac_address.count(":") == 5:
        parts = mac_address.split(":")
        # Проверяем, что каждый компонент является двухсимвольным шестнадцатеричным числом
        for part in parts:
            if len(part) != 2 or not all(c in '0123456789ABCDEFabcdef' for c in part):
                return False
        return True
    return False


# Обработчик команды /start


# Обработчик команды /register
@dp.message(Command("register"))
async def cmd_register(message: types.Message, state: FSMContext):
    await message.answer("Введите MAC-адрес вашего ПК:")
    await state.set_state(UserState.waiting_for_mac)

# Обработчик ввода MAC-адреса
@dp.message(UserState.waiting_for_mac)
async def handle_mac_address(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    mac_address = message.text.strip()

    # Проверка на корректность MAC-адреса
    if is_valid_mac_address(mac_address):
        # Сохраняем MAC-адрес
        user_data[user_id] = {
            'mac_address': mac_address,
            'pc_name': f"ПК пользователя {user_id}",
        }
        await message.answer(f"Ваш ПК с MAC-адресом {mac_address} успешно зарегистрирован!")
        await state.clear()
    else:
        await message.answer("Неверный формат MAC-адреса. Пожалуйста, убедитесь, что он имеет формат XX:XX:XX:XX:XX:XX.")


def get_mac_address():
    try:
        for interface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == psutil.AF_LINK:  # Проверяем MAC-адрес
                    if "Ethernet" in interface or "Wi-Fi" in interface:  # Фильтруем активные интерфейсы
                        return addr.address
    except Exception as e:
        print(f"[ERROR] Ошибка при получении MAC-адреса: {e}")
    return None


def load_cache():
    global game_paths
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as file:
            try:
                game_paths = json.load(file)
                print("[LOG] Кэш загружен:", game_paths)
            except json.JSONDecodeError:
                print("[ERROR] Ошибка при чтении кэша. Файл поврежден.")
                game_paths = {}
    else:
        print("[ERROR] Файл кэша не найден.")

# Сохраняем кэш в файл
def save_cache():
    global game_paths
    with open(CACHE_FILE, 'w') as file:
        json.dump(game_paths, file, indent=4)
        print("[LOG] Кэш сохранён:", game_paths)

def search_in_start_menu(app_name):
    """
    Поиск приложения в меню «Пуск» с учетом части названия.
    """
    # Папки, где хранятся ярлыки из меню «Пуск»
    start_menu_dirs = [
        Path(r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs"),
        Path(os.getenv('APPDATA')) / r"Microsoft\Windows\Start Menu\Programs"
    ]
    
    app_name = app_name.lower()
    for directory in start_menu_dirs:
        for root, _, files in os.walk(directory):
            for file in files:
                if app_name in file.lower() and file.endswith('.lnk'):
                    app_path = os.path.join(root, file)
                    game_paths[app_name] = app_path  # Кэшируем путь
                    return app_path
    return None

def search_file_on_disks(target_substring):
    target_substring = target_substring.lower()
    extensions = ['.exe', '.bat', '.cmd', '.lnk']  # Поддерживаемые расширения
    for disk in "CDEFG":  # Перебор дисков
        drive = f"{disk}:/"
        if os.path.exists(drive):
            print(f"[DEBUG] Поиск на диске {drive}...")
            try:
                for root, _, files in os.walk(drive, topdown=True):
                    for file in files:
                        # Ищем частичное совпадение
                        if target_substring in file.lower() and os.path.splitext(file)[1].lower() in extensions:
                            app_path = os.path.join(root, file)
                            game_paths[target_substring] = app_path  # Кэшируем путь
                            return app_path
            except PermissionError:
                print(f"[WARNING] Нет доступа к диску {disk}")
    return None

def find_and_open_application(app_name):
    """
    Функция для поиска и запуска приложения.
    Сначала ищет в кэше, затем в меню «Пуск», используя частичное совпадение.
    """
    app_name = app_name.strip().lower()

    # Сначала проверим, есть ли приложение в кэше
    if app_name in game_paths:
        app_path = game_paths[app_name]
        print(f"[DEBUG] Приложение найдено в кэше: {app_path}")
        try:
            subprocess.Popen(['cmd', '/c', 'start', '', app_path], shell=True)  # Открываем ярлык
            return f"🎮 Приложение '{app_name}' запущено!"
        except Exception as e:
            return f"❌ Ошибка при запуске приложения из кэша: {e}"

    # Если не найдено в кэше, ищем в меню «Пуск»
    print(f"[DEBUG] Приложение '{app_name}' не найдено в кэше. Поиск в меню Пуск...")
    app_path = search_in_start_menu(app_name)
    
    if app_path:
        try:
            print(f"[DEBUG] Запуск приложения из меню Пуск: {app_path}")
            subprocess.Popen(['cmd', '/c', 'start', '', app_path], shell=True)  # Открываем ярлык
            save_cache()  # Сохраняем кэш после успешного запуска
            return f"🎮 Приложение '{app_name}' найдено в меню Пуск и запущено!"
        except Exception as e:
            return f"❌ Ошибка при запуске приложения из меню Пуск: {e}"

    # Если не нашли в меню «Пуск», ищем на диске
    print(f"[DEBUG] Приложение '{app_name}' не найдено в меню Пуск. Поиск на дисках...")
    app_path = search_file_on_disks(app_name)
    
    if app_path:
        try:
            print(f"[DEBUG] Запуск приложения с диска: {app_path}")
            subprocess.Popen(app_path, shell=True)  # Запуск найденного файла
            save_cache()  # Сохраняем кэш после успешного запуска
            return f"🎮 Приложение '{app_name}' найдено на диске и запущено!"
        except Exception as e:
            return f"❌ Ошибка при запуске приложения с диска: {e}"

    # Если нигде не нашли
    return f"❌ Приложение '{app_name}' не найдено."




def kill_process_by_pid(pid):
    try:
        process = psutil.Process(pid)
        process_name = process.name()
        process.terminate()
        return f"✅ Процесс {process_name} (PID: {pid}) успешно завершён."
    except psutil.NoSuchProcess:
        return f"❌ Процесс с PID {pid} не найден."
    except psutil.AccessDenied:
        return f"❌ Нет прав на завершение процесса с PID {pid}."
    except Exception as e:
        return f"❌ Ошибка при завершении процесса: {e}"

def get_running_exe_processes():
    try:
        exe_processes = []
        for process in psutil.process_iter(attrs=['pid', 'name', 'exe']):
            try:
                process_info = process.info
                if process_info['exe'] and process_info['exe'].endswith('.exe'):
                    exe_processes.append(f"{process_info['name']} (PID: {process_info['pid']})")
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue

        if exe_processes:
            return (
                "⚙️ <b>Список запущенных .exe процессов:</b>\n" +
                "\n".join(f"• {proc}" for proc in exe_processes[:50])
            )
        else:
            return "❌ В данный момент нет запущенных .exe процессов."
    except Exception as e:
        return f"❌ Ошибка при получении списка процессов: {e}"

# Обработчики команд

async def cmd_kill_process(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_data:
        await message.answer(
            "❓ Напишите PID процесса, который вы хотите завершить.\n"
            "Чтобы узнать список процессов, используйте команду /processes.",
            parse_mode="Markdown"
        )
        waiting_for_pid[user_id] = True
    else:
        await message.answer("⛔ У вас нет прав для выполнения этой команды.", parse_mode="Markdown")

async def handle_kill_pid(message: types.Message):
    user_id = message.from_user.id
    if user_id in waiting_for_pid and waiting_for_pid[user_id]:
        pid_text = message.text.strip()

        try:
            pid = int(pid_text)
            result = kill_process_by_pid(pid)
            await message.answer(result, parse_mode="Markdown")
        except ValueError:
            await message.answer("❌ Введите корректный PID (целое число).", parse_mode="Markdown")
        waiting_for_pid[user_id] = False
    else:
        await message.answer("Я вас не понял. Используйте команды из списка.", parse_mode="Markdown")

async def cmd_processes(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_data:
        processes_list = get_running_exe_processes()
        await message.answer(processes_list, parse_mode="HTML")
    else:
        await message.answer("⛔ У вас нет прав для выполнения этой команды.", parse_mode="Markdown")


def get_pc_status():
    try:
        # Получение информации о ЦП
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_temp = "не удалось определить"

        # Попытка получить температуру процессора
        try:
            sensors = psutil.sensors_temperatures()
            if not sensors:
                cpu_temp = "не поддерживается системой"
            else:
                for name, entries in sensors.items():
                    for entry in entries:
                        if "cpu" in name.lower() or "coretemp" in name.lower():
                            cpu_temp = entry.current  # Берем первое подходящее значение
                            break
        except Exception:
            cpu_temp = "не удалось определить"

        # Получение информации о памяти
        memory = psutil.virtual_memory()
        memory_usage = memory.percent

        # Получение информации о дисках
        disk_usage = shutil.disk_usage('/')
        disk_free_percent = (disk_usage.free / disk_usage.total) * 100

        # Проверка сети
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=2)  # Проверка доступности Google DNS
            network_status = "🟢 Интернет доступен"
        except OSError:
            network_status = "🔴 Нет подключения к интернету"

        # Получение информации о видеокарте
        gpu_status = []
        try:
            nvmlInit()
            gpu_count = nvmlDeviceGetCount()
            for i in range(gpu_count):
                handle = nvmlDeviceGetHandleByIndex(i)
                name = nvmlDeviceGetName(handle)  # Убираем .decode('utf-8')
                memory_info = nvmlDeviceGetMemoryInfo(handle)
                memory_total = memory_info.total // (1024 ** 2)  # в МБ
                memory_used = memory_info.used // (1024 ** 2)  # в МБ
                temperature = nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU)

                gpu_status.append(
                    f"🎮 GPU {i}: {name}\n"
                    f"   • Память: {memory_used}MB / {memory_total}MB\n"
                    f"   • Температура: {temperature}°C"
                )
            nvmlShutdown()
        except Exception as e:
            gpu_status.append(f"❌ Ошибка получения данных GPU: {e}")

        # Формирование ответа
        status_message = (
            "🖥️ <b>Состояние ПК</b>\n"
            f"• 🔋 Загруженность процессора: {cpu_percent}%\n"
            f"• 🌡️ Температура процессора: {cpu_temp}°C\n"
            f"• 💾 Использование памяти: {memory_usage}%\n"
            f"• 📂 Свободное место на диске: {disk_free_percent:.2f}%\n"
            f"• 🌐 Сеть: {network_status}\n\n"
            + "\n\n".join(gpu_status)
        )
        return status_message
    except Exception as e:
        return f"❌ Ошибка при получении состояния ПК: {e}"

async def cmd_status(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_data:
        pc_status = get_pc_status()
        await message.answer(pc_status, parse_mode="HTML")
    else:
        await message.answer("⛔ У вас нет прав для выполнения этой команды.", parse_mode="Markdown")

async def send_welcome(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_data:
        # Если MAC-адрес не зарегистрирован, запросим его
        await message.answer("🔧 <b>Добро пожаловать!</b>\nЯ бот для управления вашим ПК. Пожалуйста, зарегистрируйте MAC-адрес вашего ПК с помощью команды /register.")
        return
    else:
        
        await message.answer(
            "🔧 <b>Добро пожаловать!</b>\n"
            "Я бот для управления компьютером. Вот что я умею:\n\n"
            "🖥️ <b>Команды управления ПК:</b>\n"
            "• 🟢 <b>/wake</b> — Включить ПК (Wake-on-LAN).\n"
            "• 🔴 <b>/shutdown</b> — Выключить ПК.\n"
            "• 🛠️ <b>/status</b> — Проверить состояние компьютера (процессор, память, сеть).\n\n"
            "📂 <b>Работа с файлами и приложениями:</b>\n"
            "• 🛑 <b>/close</b> — закрыть приложение.\n"
            "• 💻 <b>/open_app</b> — Открыть приложение.\n"
            "• 🌐 <b>/open_site</b> — Открыть сайт.\n"
            "• 📂 <b>/files</b> — Управление файлами (просмотр, копирование, удаление).\n\n"
            "⚙️ <b>Процессы:</b>\n"
            "• 🛠️ <b>/processes</b> — Показать список запущенных .exe процессов.\n\n"
            "• 🛑 <b>/kill_process</b> — введи пид.\n\n"
            "ℹ️ <b>Прочее:</b>\n"
            "• ℹ️ <b>/help</b> — Получить справку по командам.\n\n"
            "🔐 <b>Ваш ID добавлен автоматически.</b>\n"
            "Для вопросов и предложений обращайтесь к администратору.",
            parse_mode="HTML"
        )


async def cmd_wake(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_data:
        try:
            mac_address = get_mac_address()
            if mac_address:
                send_magic_packet(mac_address)
                await message.answer(f"🟢 *Магический пакет отправлен!*\nMAC-адрес: {mac_address}", parse_mode="Markdown")
            else:
                await message.answer("❌ Не удалось найти MAC-адрес.", parse_mode="Markdown")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}", parse_mode="Markdown")
    else:
        await message.answer("⛔ У вас нет прав для выполнения этой команды.", parse_mode="Markdown")

async def cmd_shutdown(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_data:
        try:
            subprocess.run(["shutdown", "/s", "/f", "/t", "0"])  # Команда для выключения компьютера
            await message.answer("🔴 Компьютер выключается...", parse_mode="Markdown")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}", parse_mode="Markdown")
    else:
        await message.answer("⛔ У вас нет прав для выполнения этой команды.", parse_mode="Markdown")


# Обработчик команды /open_app
@dp.message(Command("open_app"))
async def cmd_open_app(message: types.Message, state: FSMContext):
    await message.answer("Напишите название программы, которую хотите открыть:")
    await state.set_state(UserState.waiting_for_app)

@dp.message(UserState.waiting_for_app)
async def handle_app_name(message: types.Message, state: FSMContext):
    app_name = message.text.strip().lower()
    result = find_and_open_application(app_name)
    await message.answer(result)
    await state.clear()

def normalize_site_name(site_name):
    """
    Нормализует название сайта, превращая его в нижний регистр.
    """
    site_name = site_name.strip().lower()
    for key, synonyms in SITES_SYNONYMS.items():
        if site_name in synonyms:
            return key
    return site_name  # Если не нашли, возвращаем как есть



@dp.message(Command("open_site"))
async def open_site_command_handler(message: types.Message, state: FSMContext):
    await message.answer("Введите сайт, который вы хотите найти и открыть:")
    await state.set_state(UserState.waiting_for_site)

# Обработчик сообщений для ввода сайта
@dp.message(UserState.waiting_for_site)
async def handle_site_name(message: types.Message, state: FSMContext):
    user_input = message.text.strip().lower()
    
    # Нормализуем ввод пользователя
    site_name = normalize_site_name(user_input)
    
    # Выполняем поиск в Google
    search_query = f"{site_name}"
    try:
        # Получаем список URL-ов по запросу
        search_results = list(search(search_query, num_results=5))  # Мы можем ограничить количество результатов
        
        if search_results:
            # Открываем первый сайт из результатов
            url = search_results[0]
            webbrowser.open(url)  # Открываем сайт в браузере
            await message.answer(f"Открываю первый сайт по запросу '{site_name}': {url}")
        else:
            await message.answer(f"Не удалось найти сайты по запросу '{site_name}'.")
    except Exception as e:
        await message.answer(f"Ошибка при выполнении поиска: {e}")
    
    # Очищаем состояние после завершения
    await state.clear()


async def close_app_command(message: types.Message):
    user_states[message.from_user.id] = "awaiting_app_name"
    await bot.send_message(message.chat.id, "Какое приложение вы хотите закрыть?")


async def process_app_name(message: types.Message):
    if user_states.get(message.from_user.id) == "awaiting_app_name":
        app_name = message.text.strip().lower()
        user_states[message.from_user.id] = None  # Сбрасываем состояние
        closed_processes = []

        for process in psutil.process_iter(['name', 'pid']):
            try:
                if app_name in process.info['name'].lower():
                    os.kill(process.pid, 9)
                    closed_processes.append(process.info['name'])
            except Exception as e:
                await bot.send_message(message.chat.id, f"Не удалось закрыть процесс {process.info['name']}: {e}")

        if closed_processes:
            closed_list = "\n".join(closed_processes)
            await bot.send_message(
                message.chat.id,
                f"Успешно закрыты процессы, связанные с '{app_name}'"
            )
        else:
            await bot.send_message(message.chat.id, f"Не найдено приложений, связанных с '{app_name}'.")


# Обработчик команды отмены
async def cancel_command(message: types.Message):
    if user_states.get(message.from_user.id):
        user_states[message.from_user.id] = None
        await bot.send_message(message.chat.id, "Действие отменено.")
    else:
        await bot.send_message(message.chat.id, "Нечего отменять.")



def register_handlers(dp: Dispatcher):
    register_commands(dp) 
    register_message_handlers(dp) 

def register_commands(dp: Dispatcher):
    dp.message.register(send_welcome, Command("start"))
    dp.message.register(cmd_wake, Command("wake"))
    dp.message.register(cmd_shutdown, Command("shutdown"))
    dp.message.register(cmd_open_app, Command("open_app"))
    dp.message.register(cmd_processes, Command("processes"))
    dp.message.register(cmd_kill_process, Command("kill_process"))
    dp.message.register(open_site_command_handler, Command("open_site"))
    dp.message.register(cmd_status, Command('status'))
    dp.message.register(close_app_command, Command('close'))
    dp.message.register(cancel_command, Command('cancel'))


def register_message_handlers(dp: Dispatcher):
    dp.message.register(handle_app_name, F.text & F.state(STATE_WAITING_FOR_APP))  
    dp.message.register(handle_site_name, F.text & F.state(STATE_WAITING_FOR_SITE))
    dp.message.register(process_app_name)


async def main():
    load_cache()
    print("[LOG] Бот запущен и готов к работе.")
    register_handlers(dp) 
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("[LOG] Бот выключен.")