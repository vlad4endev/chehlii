"""Превью, сценарии и закрытие консультации «Сообщения»."""

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


def test_fsm_state_for_guide_scenarios() -> None:
    assert consult.fsm_state_for("msg_002") == "waiting_contact"
    assert consult.fsm_state_for("msg_003") == "clear"
    assert consult.fsm_state_for("msg_006а") == "waiting_name"
    assert consult.fsm_state_for("msg_006б") == "waiting_materials"
    assert consult.fsm_state_for("msg_help") == "consulting"
    assert consult.fsm_state_for("msg_help_close") == "clear"
    assert consult.fsm_state_for("msg_007а") is None
    assert "msg_006а" in consult.NEEDS_ORDER
    assert "msg_003" not in consult.NEEDS_ORDER


def test_scenario_meta_roundtrip() -> None:
    """Мета сценария без url остаётся в media для истории."""
    meta = [{"type": "scenario", "code": "msg_006а", "state": "waiting_name"}]
    # message_kind без url → text; явный kind=scenario задаётся в send_scenario
    assert consult.message_kind("Напишите имя", meta) == "text"
