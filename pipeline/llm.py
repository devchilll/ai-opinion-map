"""Pluggable LLM backend. Local by default.

The extraction step needs a model that can do three things: spot passages where
someone states a position, pull the exact sentence, and score it against a
rubric. That is extraction and classification, not open-ended reasoning, so a
local 8B model is a reasonable fit -- and the verbatim validator downstream is
what makes it safe: a hallucinated quote cannot pass a substring check against
the source document, so the failure mode is a dropped claim, not a fabricated one.

Backends: ollama (default, local), openai-compatible (llama-server, mlx_lm,
LM Studio), anthropic. Set AIOM_LLM_BACKEND / AIOM_LLM_MODEL to switch.
"""
from __future__ import annotations

import json
import os
import re

import httpx

BACKEND = os.environ.get("AIOM_LLM_BACKEND", "ollama")
MODEL = os.environ.get("AIOM_LLM_MODEL", "gemma4:latest")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OPENAI_BASE = os.environ.get("AIOM_OPENAI_BASE", "http://127.0.0.1:8080/v1")
TIMEOUT = float(os.environ.get("AIOM_LLM_TIMEOUT", "180"))

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def complete(prompt: str, *, temperature: float = 0.0, max_tokens: int = 1600) -> str:
    if BACKEND == "ollama":
        r = httpx.post(f"{OLLAMA_HOST}/api/generate", timeout=TIMEOUT, json={
            "model": MODEL, "prompt": prompt, "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        })
        r.raise_for_status()
        return r.json()["response"]

    if BACKEND == "openai":
        r = httpx.post(f"{OPENAI_BASE}/chat/completions", timeout=TIMEOUT, json={
            "model": MODEL, "temperature": temperature, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }, headers={"Authorization": f"Bearer {os.environ.get('AIOM_OPENAI_KEY', 'local')}"})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    if BACKEND == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY unset; use AIOM_LLM_BACKEND=ollama")
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=TIMEOUT, json={
            "model": MODEL, "max_tokens": max_tokens, "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }, headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
        r.raise_for_status()
        return r.json()["content"][0]["text"]

    raise ValueError(f"unknown backend {BACKEND!r}")


def parse_json(text: str) -> list | dict | None:
    """Models wrap JSON in prose and fences. Recover it without being clever."""
    m = _JSON_BLOCK.search(text)
    if m:
        text = m.group(1)
    text = text.strip()
    for opener, closer in (("[", "]"), ("{", "}")):
        i, j = text.find(opener), text.rfind(closer)
        if i != -1 and j > i:
            try:
                return json.loads(text[i:j + 1])
            except json.JSONDecodeError:
                continue
    return None


def describe() -> str:
    return f"{BACKEND}:{MODEL}"
