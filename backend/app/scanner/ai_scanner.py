import logging
from textwrap import shorten
from typing import Dict, List

import httpx

from ..config import get_settings

settings = get_settings()
logger = logging.getLogger("dristi-scan")


def _build_prompt(file_name: str, content: str) -> str:
    snippet = content[:4000]
    return (
        "You are a senior application security engineer. "
        "Review the following source code for vulnerabilities. "
        "List concrete vulnerabilities with severity (Critical/High/Medium/Low), explain why, "
        "and give one remediation step per finding. "
        f"File: {file_name}\n\n"
        "Code:\n"
        f"{snippet}\n"
    )


async def analyze_with_ai(file_name: str, content: str) -> List[Dict]:
    """
    Best-effort AI analysis via local Ollama; returns list of vulnerability-like dicts.
    """
    ollama_url = str(settings.ollama_url).rstrip("/")
    payload = {"model": "codellama", "prompt": _build_prompt(file_name, content), "stream": False}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{ollama_url}/api/generate", json=payload)
            resp.raise_for_status()
            text = resp.json().get("response", "") or resp.text
    except Exception as exc:
        logger.warning("AI scan skipped: %s", exc)
        return []

    # Treat the whole response as a single insight entry; downstream consumers can render it.
    cleaned = shorten(text.strip(), width=2000, placeholder=" ...")
    return [
        {
            "name": "AI Security Review",
            "severity": "Medium",
            "file_name": file_name,
            "line_number": None,
            "description": cleaned,
            "remediation": "See AI recommendations above; validate manually.",
            "cwe_reference": None,
            "code_snippet": None,
            "category": "AI Analysis",
        }
    ]
