"""Bot API delivery. The reader account never sends messages on your behalf."""

from .http import APIError, post_json
from .rules import (
    LOUD_MAX_PRICE_USD,
    LOUD_MAX_WALK_MINUTES,
    MAX_BUILDING_AGE_YEARS,
    QUIET_MAX_PRICE_USD,
    QUIET_MAX_WALK_MINUTES,
)


BUTTON_COMMANDS = {
    "📊 Состояние": "/status",
    "📋 Правила": "/rules",
    "⏸ Пауза": "/pause",
    "▶️ Возобновить": "/resume",
}

CONTROL_KEYBOARD = {
    "keyboard": [["📊 Состояние", "📋 Правила"], ["⏸ Пауза", "▶️ Возобновить"]],
    "resize_keyboard": True,
    "is_persistent": True,
    "one_time_keyboard": False,
    "input_field_placeholder": "Выберите действие или введите команду",
}


class BotAPI:
    def __init__(self, token: str, chat_id: int):
        self._base = f"https://api.telegram.org/bot{token}/"
        self.chat_id = chat_id

    async def call(self, method: str, **parameters):
        response = await post_json(self._base + method, parameters, service="Telegram")
        if not response.get("ok"):
            raise APIError("Telegram", int(response.get("error_code", 0)),
                           int(response.get("parameters", {}).get("retry_after", 0)))
        return response["result"]

    async def message(self, text: str, *, silent: bool = True):
        return await self.call("sendMessage", chat_id=self.chat_id, text=text[:4000],
                               disable_notification=silent,
                               link_preview_options={"is_disabled": True},
                               reply_markup=CONTROL_KEYBOARD)

    async def forward(self, channel: str, message_ids: list[int]) -> bool:
        try:
            result = await self.call("forwardMessages", chat_id=self.chat_id,
                                     from_chat_id="@" + channel,
                                     message_ids=sorted(message_ids), disable_notification=True)
            return len(result) == len(message_ids)
        except APIError as exc:
            if exc.status in (400, 403):
                # Bot membership / protected content can prevent forwarding.
                # The already delivered summary includes the original link.
                return False
            raise


RULES_TEXT = (
    "Ищу долгосрочную аренду целой квартиры.\n"
    f"Дом сдан не более {MAX_BUILDING_AGE_YEARS} лет назад, от 2 комнат, от 40 м² — обязательно.\n"
    f"Сразу со звуком: до ${LOUD_MAX_PRICE_USD}, пешком до офиса ≤{LOUD_MAX_WALK_MINUTES} минут.\n"
    f"Тихо: максимум одно отклонение — до ${QUIET_MAX_PRICE_USD} ИЛИ до {QUIET_MAX_WALK_MINUTES} минут.\n"
    "Также тихо: 1–2 неизвестных параметра, если остальные строго подходят.\n"
    "Пн–Пт до 16:50: тихие объявления накапливаются к 16:50; после — сразу.\n"
    "Сб–Вс: тихие сразу. Часовой пояс — Ташкент.\n"
    "Коммунальные платежи, залог, комиссия не входят в лимит аренды.\n"
    "Громкость и режим «Не беспокоить» задаются на вашем телефоне."
)


async def handle_update(update: dict, bot: BotAPI, store) -> None:
    message = update.get("message", {})
    if (message.get("chat", {}).get("type") != "private"
            or message.get("chat", {}).get("id") != bot.chat_id
            or message.get("from", {}).get("id") != bot.chat_id):
        return
    text = message.get("text", "").strip()
    command = BUTTON_COMMANDS.get(text)
    if command is None:
        command = text.split(maxsplit=1)[0].split("@")[0].lower() if text else ""
    if command in ("/start", "/help", "/menu"):
        answer = ("Управляйте ботом кнопками под строкой ввода.\n"
                  "/menu — показать кнопки\n/status — состояние\n"
                  "/rules — правила\n/pause — приостановить отправку\n/resume — возобновить\n"
                  "Пауза сохраняет очередь. Чтение канала продолжится.")
    elif command == "/rules":
        answer = RULES_TEXT
    elif command == "/pause":
        store.set_meta("paused", "true")
        answer = "Отправка приостановлена. Объявления продолжают попадать в очередь."
    elif command == "/resume":
        store.set_meta("paused", "false")
        answer = "Отправка возобновлена. Перед отправкой очередь будет проверена заново."
    elif command == "/status":
        counts = store.counts()
        answer = (f"Отправка: {'пауза' if store.get_meta('paused') == 'true' else 'включена'}\n"
                  f"В очереди: {counts['pending']}\nОтправлено: {counts['sent']}\n"
                  f"Отсеяно: {counts['rejected']}\n"
                  f"Последнее чтение канала (UTC): {store.get_meta('last_poll', 'ещё не было')}\n"
                  f"Последний сбой: {store.get_meta('last_error', 'нет')}\n"
                  "Состояние маршрутов и недостающие параметры указаны в карточках.")
    else:
        return
    await bot.message(answer)
