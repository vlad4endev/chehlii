"""Блок оплаты для сообщений бота: текст карточки + кнопки на каждый шлюз.

Ссылки в текст не вставляем — они уходят в кнопки. Иначе мессенджер рисует превью
страницы шлюза («auth.robokassa.ru — Index - MerchantNew»), и сообщение выглядит
мусорно. Backend отдаёт по ссылке на каждый настроенный шлюз (см. LinkOut.options):
если настроены оба — клиент выбирает способ сам, кнопкой.

Модуль общий для TG и MAX: блок должен быть одинаковым в обоих каналах.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from bots.core.backend import backend

# Названия шлюзов клиенту: в подписи кнопки (когда способов несколько) и в тексте
# (когда способ один — кнопка тогда говорит про сумму, а не про шлюз).
_PROVIDER_BTN = {"robokassa": "Картой (Robokassa)", "yandex_pay": "Яндекс Пэй"}
_PROVIDER_RU = {"robokassa": "картой", "yandex_pay": "через Яндекс Пэй"}

_LABEL_RU = {
    "prepayment": "Предоплата",
    "postpayment": "Остаток к оплате",
    "delivery": "Доставка",
}
_TAIL_RU = {
    "prepayment": "Заказ уйдёт в работу сразу после оплаты.",
    "postpayment": "Отправим заказ сразу после оплаты.",
    "delivery": "Курьера вызовем сразу после оплаты.",
}


@dataclass(frozen=True)
class PayButton:
    label: str
    url: str


@dataclass(frozen=True)
class PayBlock:
    text: str
    buttons: list[PayButton]  # пусто → оплата не настроена, показываем только текст


def _rub(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def render(
    *,
    amount: float,
    options: Sequence[dict] = (),
    kind: str = "prepayment",
    percent: float = 0,
) -> PayBlock:
    label = _LABEL_RU.get(kind, "К оплате")
    if kind == "prepayment" and percent:
        label = f"{label} {int(percent)}%"

    if len(options) > 1:
        how = "Выберите способ оплаты."
        buttons = [
            PayButton(f"💳 {_PROVIDER_BTN.get(o['provider'], 'Оплатить')}", o["url"])
            for o in options
        ]
    else:
        provider = options[0]["provider"] if options else "robokassa"
        how = f"Оплата {_PROVIDER_RU.get(provider, 'картой')} на защищённой странице шлюза."
        buttons = [PayButton(f"💳 Оплатить {_rub(amount)} ₽", o["url"]) for o in options]

    return PayBlock(
        text=f"💳 {label} — {_rub(amount)} ₽\n{how} {_TAIL_RU.get(kind, '')}".strip(),
        buttons=buttons,
    )


async def block(order_id: int, kind: str = "prepayment") -> PayBlock:
    """Карточка оплаты по заказу. Если шлюзы не настроены — текст-фолбэк без кнопок."""
    try:
        p = await backend.payment_link(order_id, kind)
    except Exception:
        return PayBlock("Ссылка на оплату придёт следующим сообщением.", [])
    options = list(p.get("options") or [])
    if not options and p.get("url"):
        options = [{"provider": "robokassa", "url": p["url"]}]
    return render(
        amount=p["amount"],
        options=options,
        kind=kind,
        percent=p.get("percent", 0),
    )


if __name__ == "__main__":
    rk = {"provider": "robokassa", "url": "https://rk"}
    yp = {"provider": "yandex_pay", "url": "https://yp"}

    one = render(amount=12.0, options=[yp], percent=50)
    assert "Предоплата 50% — 12 ₽" in one.text, one.text
    assert "через Яндекс Пэй" in one.text, one.text
    assert "https://yp" not in one.text, one.text
    assert [b.label for b in one.buttons] == ["💳 Оплатить 12 ₽"], one.buttons

    two = render(amount=12.0, options=[rk, yp], percent=50)
    assert "Выберите способ оплаты" in two.text, two.text
    assert [b.label for b in two.buttons] == ["💳 Картой (Robokassa)", "💳 Яндекс Пэй"], two.buttons
    assert [b.url for b in two.buttons] == ["https://rk", "https://yp"], two.buttons

    none = render(amount=1234.4, kind="postpayment")
    assert not none.buttons
    assert "Остаток к оплате — 1 234 ₽" in none.text, none.text
    print("ok")
