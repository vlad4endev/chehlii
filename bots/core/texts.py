"""Тексты сообщений бота: подгружаются из backend (редактируются в AdminUI).

Есть безопасные дефолты на случай, если сообщение ещё не заведено. Плейсхолдеры
формата {name} подставляются через .format().
"""

from __future__ import annotations

from bots.core.backend import backend

DEFAULTS: dict[str, str] = {
    "msg_001": "Привет! Это бот для заказа индивидуальных чехлов.",
    "msg_002": "Поделитесь контактом, чтобы продолжить.",
    "msg_003": "Готово! Выберите раздел в меню.",
    "msg_005аб": "Подтвердите заказ: {type}, {model}, цена {price} ₽.",
    "msg_006а": "Напишите имя или букву для чехла.",
    "msg_006б": "Пришлите фото/файлы и опишите пожелание.",
    "msg_007а": "Чехол принят в работу. Осталось внести предоплату.",
    "msg_007б": "Чехол принят, ожидайте макет. Осталось внести предоплату.",
    "welcome_back": "С возвращением! Ваша скидка — {discount}%.",
}


class Texts:
    def __init__(self) -> None:
        self._messages: dict[str, str] = {}

    async def load(self) -> None:
        try:
            for m in await backend.get_messages():
                self._messages[m["code"]] = m["text"]
        except Exception:
            # backend недоступен на старте — работаем на дефолтах
            pass

    def get(self, code: str, **fmt) -> str:
        template = self._messages.get(code) or DEFAULTS.get(code, "")
        if not fmt:
            return template
        try:
            return template.format(**fmt)
        except (KeyError, IndexError, ValueError):
            return template


texts = Texts()
