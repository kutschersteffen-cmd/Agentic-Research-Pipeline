import base64
import hashlib

from langchain_core.messages import AIMessage
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

    async def fake_call(bound, messages):
        sent.append(messages[1].content)
        return AIMessage(content="", tool_calls=[{"name": "emit_result", "args": {"ok": True}, "id": "t"}])

    monkeypatch.setattr(client, "_call_with_backoff", fake_call)
    await client.complete_structured(system="s", prompt="p", output_model=_Out, images=[b"img"])
    await client.complete_structured(system="s", prompt="p", output_model=_Out, images=[b"other"])  # different image: no cache hit
    assert len(sent) == 2
    assert sent[0] == [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(b"img").decode()}},
        {"type": "text", "text": "p"},
    ]
