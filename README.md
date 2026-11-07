# botyaraMC 🎮

Лаунчер для своих + sync-сервер модов. Структура:

```
botyaraMC/
├─ server/                 <- запускается у тебя (Python-сервер с модами)
│  ├─ server.py            точка входа + HTTP
│  ├─ srv_config.py        config.txt (создаётся сам)
│  ├─ mods_index.py        индекс модов и SHA-256
│  ├─ discovery.py         UDP-автообнаружение
│  └─ mods/                сюда кидай .jar (создаётся сам)
└─ launcher/               <- раздаёшь друзьям
   ├─ main.py  ui.py  themes.py  config.py
   ├─ sync.py  mc.py  discovery.py
   └─ requirements.txt
```

## Сервер
```
cd server
python server.py
```
При первом запуске появятся `config.txt` и `mods/`. В `config.txt` задаёшь версию Minecraft,
загрузчик (fabric/forge/none) и `minecraft_server` = IP хоста в Radmin VPN.
Положил/удалил/заменил .jar в `mods/` — клиенты подхватят при следующем нажатии «ИГРАТЬ».
Порты: **TCP 25456** (моды) и **UDP 25457** (автообнаружение) — разреши в брандмауэре.

## Лаунчер
```
cd launcher
pip install -r requirements.txt
python main.py
```
Первый запуск: ник → тема (живой предпросмотр) → IP сервера (или «Найти автоматически»).
«Я хост» включается в ⚙ Настройках: добавляется папка модов Minecraft-сервера,
моды синкаются в неё и в твой `.minecraft/mods`. После смены модов хосту нужно перезапустить MC-сервер.

## Как это работает
- Моды ставятся только в `.minecraft/mods`; свои моды игроков лаунчер не трогает —
  удаляет только те, что поставил сам (список в `managed.json`).
- Каждый файл проверяется по SHA-256; имена с `../` и не-.jar отбрасываются.
- Если сервер недоступен — запуск идёт по последнему сохранённому манифесту.
- Логи: `launcher.log` и `game.log` лежат в папке настроек
  (`%APPDATA%/botyaraMC`, `~/.config/botyaraMC`, `~/Library/Application Support/botyaraMC`).
- Игра запускается offline (ник + стабильный offline-UUID), Minecraft-сервер должен быть с `online-mode=false`.
- Нужна Java для установки Forge; для Fabric и vanilla рантайм докачается сам.
