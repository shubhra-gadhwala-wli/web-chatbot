"""A minimal, real, locally-served OpenAI-compatible `/v1/chat/completions`
endpoint used by the end-to-end test.

This is a stand-in for the developer's configured local LLM server (llama.cpp,
Ollama, vLLM, ...). It is a real HTTP server spoken to over the real client
code path -- the retrieval, embedding, index and citation verification under
test are never mocked. Its "model" simply answers by quoting the first source
it was given and citing that source's handle, which is exactly what a grounded
model is instructed to do.
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HANDLE_RE = re.compile(r"\[\[(S-[A-Za-z0-9_-]{6,32})\]\]")


class _Handler(BaseHTTPRequestHandler):
    behaviour = "grounded"

    def log_message(self, *_a):
        pass

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        prompt = payload["messages"][-1]["content"]
        handles = HANDLE_RE.findall(prompt)
        sources = prompt.split("SOURCES", 1)[-1]
        if self.behaviour == "forge":
            content = "Here is a confident answer. [[S-forgedxyz12]]"
        elif not handles:
            content = "NO_ANSWER"
        else:
            first_block = sources.split(f"[[{handles[0]}]]", 1)[1].split("\n\n", 1)[0].strip()
            sentence = first_block.split("\n")[0][:400]
            content = f"{sentence} [[{handles[0]}]]"
        body = json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]})
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body.encode())


class LocalOpenAIServer:
    def __init__(self, behaviour: str = "grounded"):
        handler = type("H", (_Handler,), {"behaviour": behaviour})
        self.httpd = HTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        return False
