from types import SimpleNamespace

from ashare.ai.client import extract_chat_content


def test_extract_prefers_content():
    assert extract_chat_content({"content": '{"ok": true}', "reasoning": "think"}) == '{"ok": true}'


def test_extract_falls_back_to_reasoning_when_content_empty():
    msg = {"content": "", "reasoning_content": '{"beneficiaries": []}'}
    assert extract_chat_content(msg) == '{"beneficiaries": []}'


def test_extract_from_sdk_message_extra():
    msg = SimpleNamespace(content="", reasoning_content=None, model_extra={"reasoning": '{"a": 1}'})
    assert extract_chat_content(msg) == '{"a": 1}'
