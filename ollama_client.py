import requests
import json

def ask_llm(prompt, model="llama3:8b"):
    """
    Sends a prompt to the local Ollama server and returns the model's response.
    """
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "").strip()

    except Exception as e:
        return f"[Error contacting local LLM: {e}]"
