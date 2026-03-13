"""LLM interface for MLX server.

Provides a simple client wrapper to query a local MLX chat/completions server
with proper payloads and connection testing.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import time
import requests


@dataclass
class MLXConfig:
	base_url: str = "http://localhost:8080/v1"
	model: str = "mlx-community/Qwen2.5-Coder-14B-Instruct-4bit"
	max_tokens: int = 65536
	temperature: float = 0.1
	timeout: float = 120.0


class MLXClient:
	"""Thin client for MLX chat/completions API."""

	def __init__(self, config: Optional[MLXConfig] = None):
		self.config = config or MLXConfig()

	def test_connection(self) -> bool:
		try:
			resp = requests.get(f"{self.config.base_url}/models", timeout=10)
			return resp.status_code == 200
		except Exception:
			return False

	def call(self, prompt: str, system_prompt: Optional[str] = None) -> str:
		messages: List[Dict[str, str]] = []
		if system_prompt:
			messages.append({"role": "system", "content": system_prompt})
		messages.append({"role": "user", "content": prompt})

		payload: Dict[str, Any] = {
			"model": self.config.model,
			"messages": messages,
			"max_tokens": self.config.max_tokens,
			"temperature": self.config.temperature,
			"stream": False,
		}

		try:
			start = time.time()
			resp = requests.post(
				f"{self.config.base_url}/chat/completions",
				json=payload,
				timeout=self.config.timeout,
			)
			elapsed = time.time() - start
			if resp.status_code == 200:
				data = resp.json()
				content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
				return content.strip()
			else:
				return f"Error: {resp.status_code} - {resp.text[:120]}"
		except requests.exceptions.Timeout:
			return "Error: Request timeout"
		except Exception as e:
			return f"Error: {str(e)}"

