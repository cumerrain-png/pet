from __future__ import annotations

from typing import Any

from openai import OpenAI


def make_client(cfg: dict[str, Any]) -> OpenAI:
    llm = cfg["llm"]
    return OpenAI(
        base_url=llm["base_url"].rstrip("/"),
        api_key=llm.get("api_key") or "sk-local",
        timeout=float(llm.get("timeout_seconds") or 120),
    )


def chat(cfg: dict[str, Any], messages: list[dict[str, str]]) -> str:
    llm = cfg["llm"]
    client = make_client(cfg)
    resp = client.chat.completions.create(
        model=llm["model"],
        messages=messages,
        temperature=float(llm.get("temperature") or 0.7),
    )
    content = resp.choices[0].message.content
    if not content:
        raise RuntimeError("模型返回空内容")
    return content.strip()