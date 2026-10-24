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
    "msg_006б": "Пришлите фото или файлы для кастом-чехла.",
    "msg_006б_done": "Готово. Теперь опишите пожелание текстом — или нажмите «Без описания».",
    "msg_006б_desc": "Опишите пожелание текстом — или нажмите «Без описания».",
    "msg_006б_summary": "Проверьте кастом-чехол:\nОписание: {desc}\nВложений: {files}",
    "msg_007а": "Чехол принят в работу. Оплатите полную стоимость по кнопке.",
    "msg_007б": "Чехол принят, ожидайте макет. Осталось внести предоплату.",
    "msg_007а_full": "Чехол принят в работу. Оплатите полную стоимость по кнопке.",
    "welcome_back": "С возвращением! Ваша скидка — {discount}%.",
    "msg_001_hint": (
        "Если что-то непонятно — нажмите в меню кнопку «Позвать человека»."
    ),
    "msg_cancel": "Заказ отменён из-за отсутствия оплаты.",
    "msg_help": (
        "Менеджер подключится в ближайшее время — пишите здесь. "
        "Можно текст, фото и голосовые.\n\n"
        "Оформление заказа можно продолжить кнопками выше."
    ),
    "msg_help_ack": "Передали ваше сообщение менеджеру — ответим здесь. "
    "Чтобы продолжить оформление, нажмите кнопку выше.",
    "msg_help_close": (
        "Диалог закрыт. Если понадобится помощь, напишите сюда или нажмите «Позвать человека»."
    ),
    "msg_offscript": (
        "Передали ваше сообщение менеджеру — ответим здесь. "
        "Чтобы продолжить оформление, нажмите кнопку выше."
    ),
}


class Texts:
    def __init__(self) -> None:
        self._messages: dict[str, str] = {}
        self._meta: dict[str, dict] = {}

    async def load(self) -> None:
        try:
            for m in await backend.get_messages():
                self._messages[m["code"]] = m["text"]
                self._meta[m["code"]] = m
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

    def meta(self, code: str) -> dict:
        """Полная запись bot_messages (media_format, media_url, file_id…)."""
        return dict(self._meta.get(code) or {})


texts = Texts()
