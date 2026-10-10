import base64
import hashlib

from anthropic.types import Message, ToolUseBlock, Usage
from pydantic import BaseModel

from arp.llm.cache import DiskLLMCache
from arp.llm.langchain_client import LangChainAnthropicClient

_KEY = dict(model="m", system="s", prompt="p", schema_name="X", schema_json={}, temperature=0.0)


def test_image_hash_changes_cache_key():
    a, b = hashlib.sha256(b"a").hexdigest(), hashlib.sha256(b"b").hexdigest()
    assert DiskLLMCache.make_key(**_KEY, image_hashes=[a]) != DiskLLMCache.make_key(**_KEY, image_hashes=[b])
    assert DiskLLMCache.make_key(**_KEY, image_hashes=None) == DiskLLMCache.make_key(**_KEY)


class _Out(BaseModel):
    ok: bool


async def test_images_go_before_text_as_base64_png_blocks(tmp_path, monkeypatch):
    client = LangChainAnthropicClient(api_key="k", model="m", cache_dir=tmp_path)
    sent = []

    async def fake_create(**kwargs):
        sent.append(kwargs["messages"][0]["content"])
        return Message(
            id="m", type="message", role="assistant", model="m", stop_reason="tool_use", stop_sequence=None,
            content=[ToolUseBlock(type="tool_use", id="t", name="emit_result", input={"ok": True})],
            usage=Usage(input_tokens=1, output_tokens=1),
        )

    monkeypatch.setattr(client._client.messages, "create", fake_create)
    await client.complete_structured(system="s", prompt="p", output_model=_Out, images=[b"img"])
    await client.complete_structured(system="s", prompt="p", output_model=_Out, images=[b"other"])  # different image: no cache hit
    assert len(sent) == 2
    assert sent[0] == [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(b"img").decode()}},
        {"type": "text", "text": "p"},
    ]
