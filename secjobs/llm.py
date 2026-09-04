"""Minimal Ollama chat client. Everything stays on localhost."""
import requests


class Ollama:
    def __init__(self, host: str, model: str, temperature: float = 0.3, num_ctx: int = 16384):
        self.host, self.model = host.rstrip("/"), model
        self.options = {"temperature": temperature, "num_ctx": num_ctx}

    def check(self) -> None:
        try:
            tags = requests.get(f"{self.host}/api/tags", timeout=5).json()
        except Exception as e:
            raise SystemExit(f"Ollama not reachable at {self.host}: {e}\nStart it with `ollama serve`.")
        names = [m["name"] for m in tags.get("models", [])]
        if not any(n == self.model or n.split(":")[0] == self.model.split(":")[0] for n in names):
            raise SystemExit(f"Model '{self.model}' not pulled. Run: ollama pull {self.model}")

    def chat(self, system: str, user: str) -> str:
        r = requests.post(f"{self.host}/api/chat", json={
            "model": self.model,
            "stream": False,
            "options": self.options,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }, timeout=600)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
