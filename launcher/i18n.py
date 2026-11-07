"""Двуязычная локализация клиента (RU / EN), строгая валидация ника и приветствия по времени суток."""
from datetime import datetime
import random
import re

NICK_STRICT_RE = re.compile(r"\A[A-Za-z0-9_]{3,16}\Z")

# Приветствия по времени суток в духе botyaranewtab (без привязки к Minecraft).
# Часть фраз использует {name}, часть самодостаточна — как в botyaranewtab!
GREETINGS_BY_TIME = {
    "ru": {
        "morning": [
            "Доброе утро, {name}!",
            "Утречко, {name} ☀️",
            "С добрым утром!",
            "Подъём, {name}!",
            "Новый день — новые свершения!",
            "Ранняя пташка, {name}?",
            "Утро начинается с тебя!",
            "Проснулся? Красавчик!",
            "Солнышко встало, и ты тоже!",
            "Время кофе, {name} ☕",
            "Бодрого утра, {name}!",
            "Утро доброе, день будет лучше!",
            "Сегодня будет отличный день!",
            "Кто рано встаёт… привет, {name}!",
            "Утренний {name} — лучший {name}!",
            "Свежее утро, свежие идеи, {name}!",
            "Доброе утро! Заряжаемся хорошим настроением ✨",
            "Чай или кофе сегодня, {name}? ☕",
            "Пусть это утро будет лёгким, {name}!",
            "Привет, {name}! Как спалось?",
            "Утренний вайб на максимум 🌤",
            "Начинаем день красиво, {name}!",
            "Потягушки сделаны, {name}?",
            "Доброе утречко! Всё получится 💪",
            "Лучи добра с самого утра, {name} ☀️",
            "Отличного старта дня, {name}!",
            "Утро обещает быть классным!",
            "С новым днём, {name}! Рад тебя видеть",
            "Завтрак уже был, {name}? 🥐",
            "Бодрости и крутого настроения, {name}!",
        ],
        "afternoon": [
            "Добрый день, {name}!",
            "Привет, {name}! 👋",
            "Как дела, {name}?",
            "День в разгаре!",
            "Продолжай в том же духе!",
            "Хороший день, {name}?",
            "Дневной {name} жжёт!",
            "Так держать, {name}!",
            "Полдень. Время великих дел!",
            "Привет! Как настроение?",
            "Ты молодец, {name}!",
            "Дневная смена, {name}!",
            "Уже половина дня — ты справляешься!",
            "Рад тебя видеть, {name}! ✨",
            "Как проходит твой день, {name}?",
            "Самое время немного передохнуть, {name} 😎",
            "Отличного тебе дня, {name}!",
            "Привет-привет, {name}!",
            "Пусть остаток дня пройдёт кайфово!",
            "Дневные вайбы ✨",
            "Заглянул перевести дух, {name}?",
            "Легенда на месте — привет, {name}! 🔥",
            "Хорошего настроения, {name}!",
            "Йоу, {name}! Рад видеть 👋",
            "Обед уже был, {name}? 🍲",
            "Всё идёт по плану, {name}!",
            "Секунда отдыха никому не помешает 😉",
            "Лови плюс к настроению, {name}!",
            "Отличный темп сегодня, {name}!",
            "С возвращением, {name}!",
        ],
        "evening": [
            "Добрый вечер, {name}!",
            "Вечер добрый! 🌆",
            "Как прошёл день, {name}?",
            "Время отдыхать!",
            "Вечерний {name} в деле!",
            "Расслабься, ты заслужил!",
            "Уютного вечера, {name}!",
            "Вечерние вайбы 🌙",
            "Закат. Красиво, правда?",
            "Отличный был день, {name}?",
            "Скоро ночь, но ты ещё здесь!",
            "Вечерок, {name} 🌅",
            "Вечер — лучшее время!",
            "Самое время выдохнуть и чиллить, {name} ☕",
            "Тёплого вечера, {name}! ✨",
            "Дела позади — теперь время для себя!",
            "Привет, {name}! Хорошего вечера",
            "Режим вечернего уюта включён 🛋",
            "Надеюсь, день порадовал тебя, {name}!",
            "Чай налит, вечер свободен, {name}?",
            "Приятного вечера в хорошей компании!",
            "Золотой час, {name} 🌅",
            "Никакой спешки — просто хороший вечер!",
            "С возвращением, {name}! Отдыхаем?",
            "Вечер обещает быть ламповым ✨",
            "Устраивайся поудобнее, {name}!",
            "Отличного отдыха после длинного дня, {name}!",
            "Вечерний чилл начинается прямо сейчас 🎧",
            "Как насчёт отличного вечера, {name}?",
            "Спокойного и приятного вечера!",
        ],
        "night": [
            "Привет, полуночник! 🦉",
            "Не спится, {name}?",
            "Ночная смена?",
            "Ночь — время гениев!",
            "Звёзды вышли, {name} ✨",
            "Тише… все спят!",
            "Полуночные приключения!",
            "Мир спит, а {name} нет!",
            "Ночной {name} — особенный!",
            "Кому нужен сон?",
            "3 часа ночи, {name}? Серьёзно?",
            "Ночной режим активирован 🌙",
            "Привет, ночная душа!",
            "Тёмная тема для тёмного времени",
            "Сова? Жаворонок? Нет — {name}!",
            "Ночная тишина и уют, {name} 🌌",
            "Все спят, а у нас тут своя атмосфера!",
            "Опять засиделся допоздна, {name}? 😄",
            "Доброй ночи, {name}!",
            "Самые ламповые посиделки — ночью ✨",
            "Ночной вайб ни с чем не спутать 🌙",
            "Клуб полуночников приветствует тебя, {name}!",
            "За окном темно, зато тут уютно!",
            "Сон подождёт, да, {name}? 😉",
            "Ночной дозор на связи, {name}!",
            "Тихая ночь и отличное настроение 🌠",
            "Полуночный чай уже готов, {name}? ☕",
            "Луна светит специально для {name} 🌕",
            "Ночное время — самое спокойное!",
            "Привет совам от сов, {name}! 🦉",
        ],
    },
    "en": {
        "morning": [
            "Good morning, {name}",
            "Morning, {name} ☀️",
            "Rise and shine!",
            "Top of the morning!",
            "Hey early bird!",
            "Wakey wakey, {name}!",
            "A brand new day, {name}",
            "Morning sunshine!",
            "Hello, beautiful morning!",
            "Ready to conquer the day?",
            "Fresh start, {name}!",
            "The world awaits, {name}",
            "Good morning, superstar!",
            "Up and at 'em!",
            "Dawn patrol, {name}!",
            "Coffee time, {name} ☕",
            "Hope you slept well, {name}!",
            "Morning vibes on point 🌤",
            "Today is going to be awesome, {name}!",
            "Bright and early, {name}!",
            "Tea or coffee this morning, {name}? ☕",
            "Wishing you an easy morning, {name}!",
            "New day, new energy ✨",
            "Good morning! Glad to see you, {name}",
            "Have a fantastic start to your day!",
            "Morning {name} is the best {name}!",
            "Grab some breakfast and let's roll, {name} 🥐",
            "Sending good morning vibes your way ☀️",
            "Fresh air, fresh start, {name}!",
            "Look who's up early — hey, {name}!",
        ],
        "afternoon": [
            "Good afternoon, {name}",
            "Afternoon, {name}",
            "Hey there!",
            "How's your day going?",
            "Halfway through the day!",
            "Keep it up, {name}!",
            "Hope your day is great!",
            "Productive afternoon, {name}?",
            "Still crushing it?",
            "Hello, {name}! 👋",
            "What's cooking, {name}?",
            "Afternoon vibes ✨",
            "You're doing great!",
            "Great to see you, {name}!",
            "Time for a well-deserved break, {name} 😎",
            "Hey {name}, how's it going?",
            "Hope the afternoon treats you well!",
            "Welcome back, {name}!",
            "Midday check-in — all good, {name}?",
            "Keep that good energy rolling, {name}!",
            "Nice to have you here, {name} ✨",
            "Taking a quick breather, {name}?",
            "Yo, {name}! Good to see you 👋",
            "The day is in full swing!",
            "You've got this, {name} 💪",
            "Wishing you an awesome afternoon!",
            "Smooth sailing today, {name}?",
            "Afternoon legend {name} has arrived 🔥",
            "Already had lunch, {name}? 🍲",
            "Good vibes all afternoon!",
        ],
        "evening": [
            "Good evening, {name}",
            "Evening, {name} 🌆",
            "Winding down?",
            "How was your day, {name}?",
            "Relax, you've earned it!",
            "Evening vibes 🌙",
            "Time to chill, {name}",
            "Hello, {name}! Nice evening",
            "Sunset mode activated",
            "Almost done for today!",
            "Take it easy, {name}",
            "Enjoy your evening!",
            "Golden hour, {name} 🌅",
            "Cozy evening ahead, {name} ✨",
            "Time to kick back and unwind!",
            "Hope today was kind to you, {name}",
            "Evening {name} is in the house!",
            "No rush — just good evening vibes ☕",
            "Make yourself comfortable, {name}!",
            "Long day behind you — enjoy the rest!",
            "Cozy mode: engaged 🛋",
            "Welcome back, {name}! Ready to relax?",
            "Nothing beats a chill evening 🎧",
            "Tea brewed, evening free, {name}?",
            "Have a warm and peaceful evening!",
            "Evening chill starts right now ✨",
            "Glad you dropped by tonight, {name}!",
            "Kick your feet up, {name}!",
            "Sunset looks great today, doesn't it?",
            "Wishing you a cozy night in, {name}!",
        ],
        "night": [
            "Hello, night owl 🦉",
            "Burning the midnight oil?",
            "Late night, {name}?",
            "The night is young!",
            "Can't sleep, {name}?",
            "Night shift vibes",
            "Stars are out, {name} ✨",
            "Shh… it's quiet hours",
            "Midnight adventures!",
            "The world sleeps, but not {name}!",
            "Nocturnally yours 🌙",
            "Who needs sleep anyway?",
            "3 AM thoughts, {name}?",
            "Hello darkness, my old friend",
            "Night mode: activated",
            "Staying up late again, {name}? 😄",
            "Peaceful late-night vibes 🌌",
            "Nighttime is when the best ideas happen!",
            "Welcome to the midnight club, {name}!",
            "Dark outside, cozy right here ✨",
            "Sleep can wait, right, {name}? 😉",
            "Late-night {name} is built different!",
            "Quiet night, great mood 🌠",
            "Midnight tea ready, {name}? ☕",
            "Moon's out just for {name} tonight 🌕",
            "Fellow night owl spotted — hey, {name}! 🦉",
            "Everything feels calmer at night",
            "Good night — or good late evening, {name}!",
            "Night watch reporting in, {name}!",
            "Pure late-night chill 🌙",
        ],
    },
}


def get_time_period(hour=None):
    """Возвращает период суток по часу (как в botyaranewtab)."""
    if hour is None:
        hour = datetime.now().hour
    hour = int(hour) % 24
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def format_greeting_template(template, name=""):
    clean_name = (name or "").strip()
    if clean_name:
        res = template.replace("{name}", clean_name).replace("{nick}", clean_name)
    else:
        res = (
            template
            .replace(", {name}", "")
            .replace(" {name}", "")
            .replace("{name}", "")
            .replace(", {nick}", "")
            .replace(" {nick}", "")
            .replace("{nick}", "")
        )
    return re.sub(r"\s{2,}", " ", res).strip()


def random_greeting(nick="", lang="ru", prev=None, hour=None):
    """Выбирает случайное приветствие под текущее время суток и язык, не повторяя prev."""
    lg = "en" if lang == "en" else "ru"
    period = get_time_period(hour)
    pool = GREETINGS_BY_TIME[lg].get(period, GREETINGS_BY_TIME[lg]["afternoon"])
    rendered = [format_greeting_template(tpl, nick) for tpl in pool]
    if prev and len(rendered) > 1:
        candidates = [g for g in rendered if g != prev]
        if candidates:
            return random.choice(candidates)
    return random.choice(rendered)


def validate_nickname(nick, lang="ru"):
    """
    Строгая проверка ника:
    3–16 символов, только a-z, A-Z, 0-9 и _. Пробелы, дефисы, точки и прочие символы запрещены.
    Возвращает (is_valid: bool, message: str).
    """
    en = (lang == "en")
    if not isinstance(nick, str) or nick == "":
        return False, (
            "3–16 chars: only a-z, A-Z, 0-9 and _ (no spaces, hyphens or dots)"
            if en else
            "3–16 символов: только a-z, A-Z, 0-9 и _ (пробелы, дефисы и точки запрещены)"
        )
    if " " in nick or "\t" in nick:
        return False, (
            "Spaces are not allowed — use underscore (_) instead"
            if en else
            "Пробелы запрещены — используй подчёркивание (_)"
        )
    if "-" in nick or "." in nick:
        return False, (
            "Hyphens (-) and dots (.) are forbidden — only a-z, A-Z, 0-9 and _"
            if en else
            "Дефисы (-) и точки (.) запрещены — только a-z, A-Z, 0-9 и _"
        )
    if re.search(r"[^A-Za-z0-9_]", nick):
        return False, (
            "Only Latin letters (a-z, A-Z), digits (0-9) and _ are allowed"
            if en else
            "Разрешены только английские буквы (a-z, A-Z), цифры (0-9) и _"
        )
    if len(nick) < 3 or len(nick) > 16:
        return False, (
            f"Nickname must be 3 to 16 characters long (currently {len(nick)})"
            if en else
            f"Ник должен быть от 3 до 16 символов (сейчас: {len(nick)})"
        )
    if not NICK_STRICT_RE.fullmatch(nick):
        return False, (
            "Invalid nickname format" if en else "Некорректный формат ника"
        )
    return True, ("✓ Great nickname!" if en else "✓ Отличный ник!")


TEXTS = {
    "ru": {
        # Мастер первого запуска (4 шага)
        "wizard_step": "Шаг {step} из {total}",
        "btn_back": "← Назад",
        "btn_next": "Дальше →",
        "btn_finish": "Готово 🚀",
        "btn_save_anyway": "Сохранить так 💾",
        "wiz_lang_title": "Выбери язык / Choose language 🌐",
        "wiz_lang_sub": "Язык интерфейса всегда можно переключить позже в ⚙ Настройках.",
        "wiz_nick_title": "Привет! Добро пожаловать в botyaraMC 👋",
        "wiz_nick_sub": "Как тебя зовут в игре? Придумай свой ник 😎",
        "wiz_nick_placeholder": "Например, Steve_228",
        "wiz_nick_hint": "3–16 символов: только a-z, A-Z, 0-9 и _ (пробелы и спецсимволы запрещены)",
        "wiz_theme_title": "Выбери тему оформления 🎨",
        "wiz_theme_sub": "Всё вокруг перекрашивается прямо сейчас — это живой предпросмотр.",
        "wiz_srv_title": "Где живёт сервер синхронизации? 🌐",
        "wiz_srv_sub": "Впиши IP хоста (например в Radmin VPN) или нажми «Найти автоматически».",
        "wiz_find_auto": "🔍 Найти автоматически",
        "wiz_searching": "Ищем сервер в сети… 🔍",
        "wiz_found": "Нашли сервер: {host} 🎉",
        "wiz_not_found": "Не нашли 😕 Включён Radmin VPN? Можно вписать IP вручную.",
        "wiz_bad_addr": "Не похоже на адрес 🤔 Пример: 26.12.34.56",
        "wiz_checking": "Проверяем связь с сервером… ⏳",
        "wiz_offline_warn": "Сервер не отвечает 😕 Проверь IP и VPN. Можно сохранить как есть и поправить позже.",

        # Главное окно
        "top_settings": "⚙ Настройки",
        "top_folders": "📂 Папки ▾",
        "top_log": "📄 Лог",
        "host_badge": "👑 режим хоста",
        "auto_ram_tag": "Авто-RAM",
        "ram_tag": "RAM",
        "mb_unit": "МБ",
        "play_btn": "▶  ИГРАТЬ",
        "play_btn_dl": "▶  ИГРАТЬ  •  Скачать {size}",
        "play_btn_update": "▶  ИГРАТЬ  •  Обновить файлы",
        "play_btn_swap": "▶  ИГРАТЬ  •  Переключить сборку",
        "play_btn_running": "🎮  ИГРА ЗАПУЩЕНА",
        "no_server_selected": "Сервер не выбран",
        "status_no_server": "Сервер не выбран — добавь его в ⚙ Настройках",
        "mc_ping_online": "🟢 Онлайн: {on}/{mx}  •  {ms} мс",
        "mc_ping_offline": "⚪ Minecraft-сервер сейчас офлайн",
        "badge_mods": "модов: {n}",
        "badge_rp": "РП: {n}",
        "badge_hidden": "🕵 скрыты",

        # Статусы синхронизации и запуска
        "status_refreshing": "Обновляем данные с сервера… 🔄",
        "status_need_dl": "Нужно докачать {size} (модов: {mods}, ресурспаков: {rp}) 📦",
        "status_up_to_date": "Все моды и ресурспаки уже скачаны ✨",
        "status_offline_cache": "Сервер сейчас не в сети — запуск пойдёт из локального кэша 📡",
        "status_connecting": "Подключаемся к серверу… 🔌",
        "status_unreachable": "Сервер недоступен 😕 Проверь Radmin VPN и список серверов в настройках.",
        "status_downloading": "Скачиваем {size}… 📥",
        "downloading_live": "Скачиваем файлы: {got} / {total} 📥",
        "status_checking_mods": "Проверяем моды и ресурспаки… ✨",
        "status_preparing_mc": "Подготавливаем Minecraft {ver} ({loader})… ☕",
        "status_launching": "Запускаем игру и ждём окно… 🚀",
        "status_game_ready": "Игра запущена! Удачного геймплея 🎮",
        "status_game_closed": "Игра закрыта. Заходи ещё! 😊",
        "status_crash_prefix": "Упс: {title}",
        "status_launch_err": "Ошибка запуска: {err} 😕 (подробности в launcher.log)",

        # Диалог папок
        "folders_title": "📂 Быстрое открытие папок",
        "folders_heading": "📂 Какую папку открыть?",
        "folders_sub": "Нажми мышкой или клавишу 1–7 на клавиатуре",
        "folder_mc": "📁  Папка сборки ({name})",
        "folder_mods": "🧩  mods — активные моды текущего сервера",
        "folder_rp": "🎨  resourcepacks — ресурспаки",
        "folder_screens": "📸  screenshots — твои скриншоты",
        "folder_crashes": "💥  crash-reports — отчёты о сбоях",
        "folder_cfg": "🛠  Конфиг и логи botyaraMC",
        "folder_srv_mods": "👑  Моды твоего Minecraft-сервера",
        "folders_close": "Закрыть (Esc)",

        # Диалог горячих клавиш
        "hk_title": "⌨ Горячие клавиши",
        "hk_heading": "⌨ Горячие клавиши botyaraMC",
        "hk_ok": "Понятно 👍",
        "hk_play": "Запустить игру (на главном экране)",
        "hk_random_greet": "Сменить приветствие на случайное",
        "hk_refresh": "Перепроверить сервер и размер загрузки",
        "hk_folders": "Быстрое открытие папок (сборка, mods, screenshots…)",
        "hk_log": "Открыть полный лог последнего запуска (game.log)",
        "hk_settings": "Открыть ⚙ Настройки",
        "hk_esc": "Закрыть диалог или выйти из Настроек",
        "hk_f1": "Показать эту подсказку",

        # Краш-репорт и просмотр лога
        "log_empty_yet": "(Логов пока нет — запусти игру хотя бы раз!)",
        "crash_win_title": "💥 Игра крашнулась!",
        "crash_heading": "💥 Упс, игра крашнулась!",
        "crash_exit_code": "Код выхода: {code}",
        "crash_tech_reason": "Техническая причина:",
        "crash_suspects": "Подозрительные моды / файлы:",
        "crash_what_to_do": "Что можно сделать:",
        "crash_view_full": "📄 Посмотреть полный лог",
        "crash_restart": "🔄 Перезапуск",
        "crash_close": "Закрыть",
        "log_win_title": "Полный лог — botyaraMC",
        "log_default_hdr": "📄 Полный лог игры",
        "log_lines": "{n} строк",
        "log_empty": "(Пусто)",
        "log_open_browser": "Открыть в браузере 🌐",
        "log_copied": "Полный лог скопирован в буфер обмена 📋",
        "log_sharing": "Отправляем… ⏳",
        "log_uploading": "Загружаем лог на https://mclo.gs… 🌐",
        "log_share_btn": "🔗 Поделиться (mclo.gs)",
        "log_copy_btn": "📋 Скопировать",
        "log_close_btn": "✖ Закрыть",
        "log_shared_ok": "Ссылка скопирована: {url} 🎉",
        "log_shared_err": "Не вышло отправить: {err}",

        # Редактор JVM-пресетов
        "pe_title": "⚙ Редактор JVM-пресетов",
        "pe_heading": "⚙ JVM-пресеты",
        "pe_sub": "Выбери готовый пресет для редактирования или создай собственный набор флагов.",
        "pe_new_placeholder": "Имя нового пресета…",
        "pe_create_btn": "+ Создать",
        "pe_modified": " (изменён тобой)",
        "pe_enter_name": "Введи название для нового пресета 🙂",
        "pe_created": "Создан пресет «{name}» ✨",
        "pe_reset_ok": "Пресет «{name}» сброшен к заводским флагам ↺",
        "pe_deleted": "Пресет «{name}» удалён 🗑",
        "pe_reset_btn": "↺ Сбросить / Удалить",
        "pe_apply_btn": "Применить ✓",
        "pe_cancel_btn": "Отмена",

        # Диалог добавления нового сервера
        "add_srv_win_title": "Добавить сервер",
        "add_srv_heading": "🌐 Добавить новый сервер",
        "add_srv_sub": "Введи IP или домен сервера синхронизации (например в Radmin VPN) или найди автоматически:",
        "add_srv_name_ph": "Название (необязательно — подтянется с сервера)",
        "add_srv_confirm": "Добавить ✓",

        # Диалог переименования папки сборки сервера
        "ren_win_title": "Папка сборки сервера",
        "ren_heading": "📁 Переименовать папку сборки",
        "ren_sub": "Укажи имя папки внутри .minecraft/home/ (все моды, миры и настройки переедут сами):",
        "ren_ph": "Например, Моя сборка 1.20",
        "ren_confirm": "Сохранить ✓",
        "ren_err_bad": "Недопустимое имя папки (избегай / \\ : * ? \" < > | и точек на конце)",
        "ren_err_exists": "Непустая папка с таким именем уже занята другой сборкой!",
        "ren_err_io": "Не удалось переименовать папку на диске (проверь, закрыта ли игра)",

        # Настройки (с автосохранением!)
        "st_title": "⚙ Настройки",
        "st_autosave_hint": "Изменения сохраняются автоматически",
        "st_saved_ok": "✓ Все изменения сохранены",
        "st_close": "✕ Закрыть",
        "st_sec_profile": "👤 Язык, профиль и серверы синхронизации",
        "st_lang": "Язык / Language",
        "st_nick": "Игровой ник",
        "st_theme": "Тема оформления",
        "st_active_server": "Выбранный сервер",
        "st_srv_add": "+ Добавить…",
        "st_srv_remove": "🗑 Удалить",
        "st_srv_addr": "Адрес сервера",
        "st_find_btn": "🔍 Найти",
        "st_srv_folder": "Папка этой сборки",
        "st_srv_folder_rename": "✏ Переименовать",
        "st_srv_folder_reset": "↺ Авто",
        "st_srv_folder_root": ".minecraft (общая)",
        "st_host_mode": "Режим хоста",
        "st_host_switch": "я хост! 👑 (дублировать моды в папку сервера)",
        "st_srv_mods_dir": "Папка модов сервера",
        "st_srv_mods_ph": "путь к папке mods у Minecraft-сервера",
        "st_browse": "Обзор…",
        "st_sec_java": "☕ Память (RAM), Java и JVM-аргументы",
        "st_autoram": "Авто-RAM",
        "st_autoram_switch": "Автоподбор по системе ({rec} МБ из {total} МБ ОЗУ)",
        "st_manual_ram": "Память вручную",
        "st_java_mode": "Режим Java",
        "java_mode_auto": "Авто (рекомендуется)",
        "java_mode_manual": "Вручную",
        "st_java_detected": "Найденные Java",
        "java_detect_placeholder": "Нажми «Найти Java»…",
        "st_detect_java_btn": "🔄 Найти Java",
        "st_java_path": "Путь к Java",
        "st_java_path_ph": "путь к bin/java (или оставь Авто)",
        "java_auto_hint": "Авторежим сам выберет подходящую системную Java или докачает рантайм Mojang.",
        "java_manual_empty": "Укажи путь к java или выбери установку из списка выше",
        "java_probe_ok": "✓ Найдена {label}",
        "java_probe_bad": "✗ Не удалось запустить java -version по этому пути",
        "java_scanning": "Ищем установленные Java в системе… 🔍",
        "java_none_found": "Системная Java не найдена (скачается сама)",
        "java_none_hint": "Системная Java не найдена — в Авто-режиме лаунчер сам скачает её от Mojang.",
        "java_found_summary": "Найдено Java: {n} шт. • лучшая: {best}",
        "st_jvm_preset": "JVM-пресет",
        "st_edit_presets": "✏ Редактировать пресеты…",
        "st_extra_jvm": "Доп. параметры JVM",
        "st_extra_jvm_ph": "Дописать к пресету, например: -Dfile.encoding=UTF-8",
        "st_sec_window": "🖥 Папки версий, окно игры и поведение",
        "st_mc_dir": "Папка .minecraft",
        "st_isolation": "Разделение версий",
        "iso_none": "Без отдельных папок (.minecraft)",
        "iso_family": "Отдельная папка для семейства (home/Fabric-1.16)",
        "iso_version": "Отдельная папка для версии (home/Fabric 1.16.5)",
        "st_on_launch": "При запуске игры",
        "launch_keep": "Оставлять лаунчер открытым",
        "launch_minimize": "Сворачивать окно",
        "launch_hide": "Скрывать до выхода из игры",
        "st_server_bg": "Фон от сервера",
        "st_server_bg_switch": "Показывать кастомный фон сервера (если задан хостом)",
        "st_win_mode": "Режим окна игры",
        "win_default": "Обычное окно",
        "win_fullscreen": "Полный экран",
        "win_custom": "Свой размер",
        "st_win_size": "Размер окна (Ш × В)",
        "st_timeout": "Таймаут запуска",
        "st_timeout_hint": "сек  (0 — отключить контроль зависания старта)",
        "st_sec_linux": "🐧 Linux: оптимизация и оверлей",
        "st_gamemode": "Feral GameMode",
        "st_gamemode_on": "Запускать игру через gamemoderun (установлен ✓)",
        "st_gamemode_off": "gamemoderun не установлен (пакет gamemode)",
        "st_mangohud": "MangoHud",
        "st_mangohud_on": "Включить FPS-оверлей mangohud (установлен ✓)",
        "st_mangohud_off": "mangohud не установлен (пакет mangohud)",
        "st_sec_account": "🚪 Выход из аккаунта и удаление конфигов",
        "st_signout_desc": (
            "Полностью удалить конфиги и серверы botyaraMC из системной папки настроек "
            "(~/.config/botyaraMC или %APPDATA%\\botyaraMC) и вернуться к мастеру первого запуска "
            "(папка .minecraft, моды и миры не трогаются):"
        ),
        "st_signout_btn": "🚪 Выйти из botyaraMC и удалить серверы",
        "st_signout_confirm_title": "Выйти и удалить конфиги botyaraMC?",
        "st_signout_confirm_body": (
            "Твой профиль, список серверов и вся папка конфигов botyaraMC "
            "(~/.config/botyaraMC / %APPDATA%\\botyaraMC) будут полностью удалены, "
            "после чего откроется мастер первого запуска.\n\n"
            "Сами файлы Minecraft, моды, миры и скриншоты останутся нетронутыми."
        ),
        "st_signout_yes": "Выйти и удалить",
        "st_signout_no": "Отмена",
        "st_err_addr": "Адрес сервера не похож на IP или домен (пример: 26.12.34.56 или play.host.ru)",
        "st_err_host_dir": "Для режима хоста укажи существующую папку модов сервера",
        "st_err_host_dup": "Эта папка уже закреплена за сервером «{srv}»! Укажи уникальную папку для каждого сервера.",
        "st_err_host_sync_own": "Это раздающая папка самого sync-сервера! Укажи папку mods именно у Minecraft-сервера.",
        "st_err_ram": "Память (RAM) должна быть числом в мегабайтах (например 4096)",
        "st_err_java": "Укажи рабочий путь к Java или переключи режим на «Авто»",
        "st_err_res": "Ширина и высота окна должны быть числами (например 1920 и 1080)",
        "st_err_timeout": "Таймаут запуска должен быть числом секунд (0 или больше)",
    },
    "en": {
        # Setup Wizard (4 steps)
        "wizard_step": "Step {step} of {total}",
        "btn_back": "← Back",
        "btn_next": "Next →",
        "btn_finish": "Finish 🚀",
        "btn_save_anyway": "Save anyway 💾",
        "wiz_lang_title": "Choose language / Выбери язык 🌐",
        "wiz_lang_sub": "You can switch the interface language anytime in ⚙ Settings.",
        "wiz_nick_title": "Welcome to botyaraMC! 👋",
        "wiz_nick_sub": "What should we call you in-game? Pick your nickname 😎",
        "wiz_nick_placeholder": "For example, Steve_228",
        "wiz_nick_hint": "3–16 chars: only a-z, A-Z, 0-9 and _ (no spaces or special characters)",
        "wiz_theme_title": "Choose a color theme 🎨",
        "wiz_theme_sub": "Everything around recolors right now — live preview!",
        "wiz_srv_title": "Where is your sync server? 🌐",
        "wiz_srv_sub": "Enter the host IP (e.g. Radmin VPN) or click 'Auto-Find'.",
        "wiz_find_auto": "🔍 Auto-Find",
        "wiz_searching": "Searching for server on LAN / VPN… 🔍",
        "wiz_found": "Found server: {host} 🎉",
        "wiz_not_found": "No server found 😕 Is Radmin VPN active? You can type the IP manually.",
        "wiz_bad_addr": "Doesn't look like a valid address 🤔 Example: 26.12.34.56",
        "wiz_checking": "Checking connection to server… ⏳",
        "wiz_offline_warn": "Server didn't respond 😕 Check IP & VPN. You can save anyway and edit later.",

        # Main screen
        "top_settings": "⚙ Settings",
        "top_folders": "📂 Folders ▾",
        "top_log": "📄 Log",
        "host_badge": "👑 host mode",
        "auto_ram_tag": "Auto-RAM",
        "ram_tag": "RAM",
        "mb_unit": "MB",
        "play_btn": "▶  PLAY",
        "play_btn_dl": "▶  PLAY  •  Download {size}",
        "play_btn_update": "▶  PLAY  •  Update files",
        "play_btn_swap": "▶  PLAY  •  Switch pack",
        "play_btn_running": "🎮  GAME RUNNING",
        "no_server_selected": "No server selected",
        "status_no_server": "No server selected — add one in ⚙ Settings",
        "mc_ping_online": "🟢 Online: {on}/{mx}  •  {ms} ms",
        "mc_ping_offline": "⚪ Minecraft server is currently offline",
        "badge_mods": "mods: {n}",
        "badge_rp": "RP: {n}",
        "badge_hidden": "🕵 cloaked",

        # Sync & launch statuses
        "status_refreshing": "Refreshing server manifest… 🔄",
        "status_need_dl": "Need to download {size} (mods: {mods}, resourcepacks: {rp}) 📦",
        "status_up_to_date": "All mods and resourcepacks are up to date ✨",
        "status_offline_cache": "Server is offline — launch will use local cached manifest 📡",
        "status_connecting": "Connecting to sync server… 🔌",
        "status_unreachable": "Sync server unreachable 😕 Check Radmin VPN and your server list in Settings.",
        "status_downloading": "Downloading {size}… 📥",
        "downloading_live": "Downloading files: {got} / {total} 📥",
        "status_checking_mods": "Verifying mods & resourcepacks… ✨",
        "status_preparing_mc": "Preparing Minecraft {ver} ({loader})… ☕",
        "status_launching": "Starting Minecraft & waiting for window… 🚀",
        "status_game_ready": "Minecraft is running! Have fun 🎮",
        "status_game_closed": "Minecraft closed. See you next time! 😊",
        "status_crash_prefix": "Oops: {title}",
        "status_launch_err": "Launch error: {err} 😕 (see launcher.log for details)",

        # Folders dialog
        "folders_title": "📂 Quick Folder Opener",
        "folders_heading": "📂 Which folder do you want to open?",
        "folders_sub": "Click an item or press keys 1–7 on your keyboard",
        "folder_mc": "📁  Instance folder ({name})",
        "folder_mods": "🧩  mods — active mods for current server",
        "folder_rp": "🎨  resourcepacks — resourcepacks",
        "folder_screens": "📸  screenshots — your screenshots",
        "folder_crashes": "💥  crash-reports — crash reports",
        "folder_cfg": "🛠  botyaraMC config & logs",
        "folder_srv_mods": "👑  Your Minecraft server mods folder",
        "folders_close": "Close (Esc)",

        # Hotkeys dialog
        "hk_title": "⌨ Keyboard Shortcuts",
        "hk_heading": "⌨ botyaraMC Keyboard Shortcuts",
        "hk_ok": "Got it 👍",
        "hk_play": "Launch Minecraft (on main screen)",
        "hk_random_greet": "Randomize greeting",
        "hk_refresh": "Refresh server manifest & download size",
        "hk_folders": "Open quick folder selector (instance, mods, screenshots…)",
        "hk_log": "Open latest game log viewer (game.log)",
        "hk_settings": "Open ⚙ Settings",
        "hk_esc": "Close active dialog or leave Settings",
        "hk_f1": "Show this shortcuts cheat sheet",

        # Crash report & log viewer
        "log_empty_yet": "(No logs yet — launch the game at least once!)",
        "crash_win_title": "💥 Game Crashed!",
        "crash_heading": "💥 Oops, Minecraft crashed!",
        "crash_exit_code": "Exit code: {code}",
        "crash_tech_reason": "Technical cause:",
        "crash_suspects": "Suspected mods / files:",
        "crash_what_to_do": "Suggested fixes:",
        "crash_view_full": "📄 View Full Log",
        "crash_restart": "🔄 Retry launch",
        "crash_close": "Close",
        "log_win_title": "Full Log — botyaraMC",
        "log_default_hdr": "📄 Full Game Log",
        "log_lines": "{n} lines",
        "log_empty": "(Empty)",
        "log_open_browser": "Open in browser 🌐",
        "log_copied": "Full log copied to clipboard 📋",
        "log_sharing": "Uploading… ⏳",
        "log_uploading": "Uploading log to https://mclo.gs… 🌐",
        "log_share_btn": "🔗 Share (mclo.gs)",
        "log_copy_btn": "📋 Copy",
        "log_close_btn": "✖ Close",
        "log_shared_ok": "Link copied: {url} 🎉",
        "log_shared_err": "Upload failed: {err}",

        # JVM Presets editor
        "pe_title": "⚙ JVM Presets Editor",
        "pe_heading": "⚙ JVM Presets",
        "pe_sub": "Choose a preset to edit or create your own custom JVM flag profile.",
        "pe_new_placeholder": "New preset name…",
        "pe_create_btn": "+ Create",
        "pe_modified": " (modified by you)",
        "pe_enter_name": "Enter a name for the new preset 🙂",
        "pe_created": "Created preset '{name}' ✨",
        "pe_reset_ok": "Preset '{name}' reset to factory defaults ↺",
        "pe_deleted": "Preset '{name}' deleted 🗑",
        "pe_reset_btn": "↺ Reset / Delete",
        "pe_apply_btn": "Apply ✓",
        "pe_cancel_btn": "Cancel",

        # Add Server dialog
        "add_srv_win_title": "Add Server",
        "add_srv_heading": "🌐 Add a Sync Server",
        "add_srv_sub": "Enter the sync server IP or domain (e.g. Radmin VPN) or auto-discover on LAN:",
        "add_srv_name_ph": "Display name (optional — fetched from server)",
        "add_srv_confirm": "Add server ✓",

        # Rename Server Pack Folder dialog
        "ren_win_title": "Server Pack Folder",
        "ren_heading": "📁 Rename Pack Folder",
        "ren_sub": "Enter a folder name inside .minecraft/home/ (mods, worlds & settings move automatically):",
        "ren_ph": "For example, My Modpack 1.20",
        "ren_confirm": "Save ✓",
        "ren_err_bad": "Invalid folder name (avoid / \\ : * ? \" < > | and trailing dots)",
        "ren_err_exists": "A non-empty folder with this name already belongs to another pack!",
        "ren_err_io": "Could not rename folder on disk (make sure Minecraft is closed)",

        # Settings (Auto-saved!)
        "st_title": "⚙ Settings",
        "st_autosave_hint": "Changes are saved automatically",
        "st_saved_ok": "✓ All changes saved",
        "st_close": "✕ Close",
        "st_sec_profile": "👤 Language, Profile & Sync Servers",
        "st_lang": "Language / Язык",
        "st_nick": "Nickname",
        "st_theme": "Color theme",
        "st_active_server": "Selected server",
        "st_srv_add": "+ Add…",
        "st_srv_remove": "🗑 Remove",
        "st_srv_addr": "Server address",
        "st_find_btn": "🔍 Find",
        "st_srv_folder": "Pack folder",
        "st_srv_folder_rename": "✏ Rename",
        "st_srv_folder_reset": "↺ Auto",
        "st_srv_folder_root": ".minecraft (shared)",
        "st_host_mode": "Host mode",
        "st_host_switch": "I'm the host! 👑 (mirror mods to MC server folder)",
        "st_srv_mods_dir": "Server mods folder",
        "st_srv_mods_ph": "path to your Minecraft server's mods/ folder",
        "st_browse": "Browse…",
        "st_sec_java": "☕ Memory (RAM), Java & JVM Arguments",
        "st_autoram": "Auto-RAM",
        "st_autoram_switch": "Auto-calculate for system ({rec} MB of {total} MB RAM)",
        "st_manual_ram": "Manual RAM",
        "st_java_mode": "Java mode",
        "java_mode_auto": "Auto (recommended)",
        "java_mode_manual": "Manual",
        "st_java_detected": "Detected Java",
        "java_detect_placeholder": "Click 'Detect Java'…",
        "st_detect_java_btn": "🔄 Detect Java",
        "st_java_path": "Java path",
        "st_java_path_ph": "path to bin/java (or leave on Auto)",
        "java_auto_hint": "Auto mode selects a matching local Java or downloads Mojang Runtime automatically.",
        "java_manual_empty": "Enter path to java binary or pick one from Detected Java above",
        "java_probe_ok": "✓ Found {label}",
        "java_probe_bad": "✗ Could not run java -version at this path",
        "java_scanning": "Scanning installed Java runtimes… 🔍",
        "java_none_found": "No system Java found (will auto-download)",
        "java_none_hint": "No system Java found — Auto mode will download Mojang Runtime automatically.",
        "java_found_summary": "Detected Java: {n} found • best: {best}",
        "st_jvm_preset": "JVM preset",
        "st_edit_presets": "✏ Edit presets…",
        "st_extra_jvm": "Extra JVM flags",
        "st_extra_jvm_ph": "Appended to preset, e.g.: -Dfile.encoding=UTF-8",
        "st_sec_window": "🖥 Version Folders, Game Window & Behavior",
        "st_mc_dir": ".minecraft folder",
        "st_isolation": "Version folders",
        "iso_none": "No separate folders (.minecraft)",
        "iso_family": "Separate folder per family (home/Fabric-1.16)",
        "iso_version": "Separate folder per version (home/Fabric 1.16.5)",
        "st_on_launch": "When game starts",
        "launch_keep": "Keep launcher open",
        "launch_minimize": "Minimize window",
        "launch_hide": "Hide until game closes",
        "st_server_bg": "Server background",
        "st_server_bg_switch": "Display custom background from server (if set by host)",
        "st_win_mode": "Game window mode",
        "win_default": "Default window",
        "win_fullscreen": "Fullscreen",
        "win_custom": "Custom size",
        "st_win_size": "Window size (W × H)",
        "st_timeout": "Launch timeout",
        "st_timeout_hint": "sec  (0 — disable startup freeze watchdog)",
        "st_sec_linux": "🐧 Linux: Performance & Overlay",
        "st_gamemode": "Feral GameMode",
        "st_gamemode_on": "Launch via gamemoderun (installed ✓)",
        "st_gamemode_off": "gamemoderun not found (install 'gamemode' package)",
        "st_mangohud": "MangoHud",
        "st_mangohud_on": "Enable mangohud FPS overlay (installed ✓)",
        "st_mangohud_off": "mangohud not found (install 'mangohud' package)",
        "st_sec_account": "🚪 Sign Out & Delete Configs",
        "st_signout_desc": (
            "Completely delete botyaraMC configs and saved servers from your system config folder "
            "(~/.config/botyaraMC or %APPDATA%\\botyaraMC) and return to the setup wizard "
            "(.minecraft, mods, and worlds are untouched):"
        ),
        "st_signout_btn": "🚪 Sign out of botyaraMC & remove servers",
        "st_signout_confirm_title": "Sign out & delete botyaraMC configs?",
        "st_signout_confirm_body": (
            "Your profile, saved servers, and the entire botyaraMC config directory "
            "(~/.config/botyaraMC / %APPDATA%\\botyaraMC) will be deleted, "
            "and the setup wizard will open.\n\n"
            "Your Minecraft files, mods, worlds, and screenshots remain untouched."
        ),
        "st_signout_yes": "Sign out & delete",
        "st_signout_no": "Cancel",
        "st_err_addr": "Server address doesn't look like a valid IP or domain (example: 26.12.34.56 or play.host.net)",
        "st_err_host_dir": "For Host Mode, select an existing Minecraft server mods folder",
        "st_err_host_dup": "This folder is already assigned to server '{srv}'! Use a unique folder per server.",
        "st_err_host_sync_own": "That's the sync-server's own folder! Select your Minecraft server's mods/ folder instead.",
        "st_err_ram": "Memory (RAM) must be a number in MB (e.g. 4096)",
        "st_err_java": "Provide a working Java binary path or switch Java mode to 'Auto'",
        "st_err_res": "Window width and height must be numbers (e.g. 1920 and 1080)",
        "st_err_timeout": "Launch timeout must be a number of seconds (0 or greater)",
    },
}


def tr(lang, key, **kwargs):
    lg = lang if lang in TEXTS else "ru"
    template = TEXTS[lg].get(key) or TEXTS["ru"].get(key, key)
    return template.format(**kwargs) if kwargs else template
