"""Превью и тип сообщения консультации «Поможем выбрать»."""

from app.services import consult, media


def test_preview_from_text() -> None:
    assert consult.preview_text("Хочу красный чехол", None) == "Хочу красный чехол"
    long = "а" * 200
    out = consult.preview_text(long, None)
    assert out.endswith("…")
    assert len(out) == consult.PREVIEW_LEN


def test_preview_from_media() -> None:
    assert consult.preview_text("", [{"url": "/x", "type": "image"}]) == "Фото"
    assert consult.preview_text(None, [{"url": "/x", "type": "audio"}]) == "Голосовое"
    assert consult.preview_text("  ", [{"url": "/a"}, {"url": "/b"}]) == "2 вложения"
    assert consult.preview_text(None, None) == "Сообщение"


def test_message_kind() -> None:
    assert consult.message_kind("hi", None) == "text"
    assert consult.message_kind(None, [{"url": "/p", "type": "image"}]) == "image"
    assert consult.message_kind("cap", [{"url": "/a"}, {"url": "/b"}]) == "album"


def test_consult_kind_audio_and_image() -> None:
    assert media.consult_kind("image/jpeg", "a.jpg") == ("jpg", "image")
    assert media.consult_kind("audio/ogg", "voice.ogg") == ("ogg", "audio")
    assert media.consult_kind(None, "voice.ogg") == ("ogg", "audio")
    assert media.consult_kind(None, "scan.pdf") == ("pdf", "file")
    assert media.consult_kind("application/octet-stream", "x.bin") == ("bin", "file")
