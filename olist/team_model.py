"""OpenAI-compatible transport that preserves Gemini's tool-call signatures."""
import json
from dataclasses import dataclass, replace

import httpx


@dataclass
class TeamModel:
    provider: object
    timeout: float
    tools: list | None = None

    def bind_tools(self, tools, **kwargs):
        from langchain_core.utils.function_calling import convert_to_openai_tool
        return replace(self, tools=[convert_to_openai_tool(t) for t in tools])

    async def ainvoke(self, messages):
        from langchain_core.messages import AIMessage
        wire = []
        for message in messages:
            if message.type == "ai" and "wire_message" in message.additional_kwargs:
                # Keep opaque extra_content.google.thought_signature exactly as received.
                # https://ai.google.dev/gemini-api/docs/thought-signatures
                wire.append(message.additional_kwargs["wire_message"])
                continue
            item = {"role": {"human": "user", "ai": "assistant"}.get(message.type, message.type),
                    "content": message.content}
            if message.type == "tool":
                item["tool_call_id"] = message.tool_call_id
            wire.append(item)
        payload = {"model": self.provider.model, "messages": wire, "temperature": 0,
                   "max_tokens": 1800, "stream": False}
        if self.tools:
            payload.update(tools=self.tools, parallel_tool_calls=False)
        base = self.provider.base + "/v1" if self.provider.name == "ollama" else self.provider.base
        headers = {"Authorization": "Bearer " + (self.provider.key or "ollama")}
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=self.provider.name != "ollama") as client:
            if self.provider.name == "ollama" and not self.tools:
                response = await client.post(self.provider.base + "/api/chat", json={
                    "model": self.provider.model, "messages": wire, "think": False, "stream": False,
                    "options": {"temperature": 0, "num_predict": 256, "num_ctx": 4096}})
            else:
                response = await client.post(base + "/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        if self.provider.name == "ollama" and not self.tools:
            data = {"choices": [{"message": data["message"]}], "usage": {
                "prompt_tokens": data.get("prompt_eval_count", 0), "completion_tokens": data.get("eval_count", 0),
                "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0)}}
        raw = data["choices"][0]["message"]
        saved = {k: raw[k] for k in ("role", "content", "tool_calls") if k in raw}
        calls = [{"id": call["id"], "name": call["function"]["name"],
                  "args": json.loads(call["function"]["arguments"]), "type": "tool_call"}
                 for call in raw.get("tool_calls", [])]
        usage = data.get("usage") or {}
        return AIMessage(content=raw.get("content") or "", tool_calls=calls,
                         additional_kwargs={"wire_message": saved},
                         usage_metadata={"input_tokens": usage.get("prompt_tokens", 0),
                                         "output_tokens": usage.get("completion_tokens", 0),
                                         "total_tokens": usage.get("total_tokens", 0)})
