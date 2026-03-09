#!/usr/bin/env python3
"""Tiny reverse proxy that rewrites model names for OpenCode.

OpenCode's agents use hardcoded model names (e.g. gpt-5.2-chat-latest)
that aren't available on the FABRIC AI server. This proxy intercepts
requests to the OpenAI-compatible API and rewrites any unknown model
name to the configured default before forwarding to the real server.

Supports both regular and streaming (SSE) responses.

Usage:
    model_proxy.py <port> <target_url> <default_model> <allowed_model,...>

Example:
    model_proxy.py 9199 https://ai.fabric-testbed.net/v1 qwen3-coder-30b qwen3-coder-30b,gpt-oss-20b
"""

import http.server
import json
import ssl
import sys
import urllib.request

PORT = int(sys.argv[1])
TARGET_URL = sys.argv[2].rstrip("/")
DEFAULT_MODEL = sys.argv[3]
ALLOWED_MODELS = set(sys.argv[4].split(",")) if len(sys.argv) > 4 else set()


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    """Forward requests to TARGET_URL, rewriting model names."""

    def _forward(self, method: str):
        # Read request body
        length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(length) if length else b""

        # Detect streaming request
        is_stream = False

        # Rewrite model name in JSON body
        if body_bytes:
            try:
                body = json.loads(body_bytes)
                is_stream = body.get("stream", False)
                if "model" in body:
                    original = body["model"]
                    # Strip provider prefix (openai/model -> model)
                    bare = original.split("/", 1)[-1] if "/" in original else original
                    if bare not in ALLOWED_MODELS and original not in ALLOWED_MODELS:
                        body["model"] = DEFAULT_MODEL
                body_bytes = json.dumps(body).encode()
            except (json.JSONDecodeError, KeyError):
                pass

        # Build target URL
        url = f"{TARGET_URL}{self.path}"

        # Forward headers (except Host)
        headers = {}
        for key, val in self.headers.items():
            if key.lower() not in ("host", "content-length"):
                headers[key] = val
        headers["Content-Length"] = str(len(body_bytes))

        req = urllib.request.Request(
            url, data=body_bytes if method == "POST" else None,
            headers=headers, method=method,
        )

        ctx = ssl.create_default_context()
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED

        try:
            resp = urllib.request.urlopen(req, context=ctx, timeout=300)
            self.send_response(resp.status)

            if is_stream:
                # Streaming: forward headers then relay chunks
                for key, val in resp.getheaders():
                    if key.lower() not in ("transfer-encoding", "content-length"):
                        self.send_header(key, val)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()

                while True:
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    self.wfile.write(b"%x\r\n%b\r\n" % (len(chunk), chunk))
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            else:
                # Non-streaming: buffer full response
                resp_body = resp.read()
                for key, val in resp.getheaders():
                    if key.lower() not in ("transfer-encoding",):
                        self.send_header(key, val)
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)

            resp.close()

        except urllib.error.HTTPError as e:
            resp_body = e.read()
            self.send_response(e.code)
            for key, val in e.headers.items():
                if key.lower() not in ("transfer-encoding",):
                    self.send_header(key, val)
            self.send_header("Content-Length", str(len(resp_body)))
            self.end_headers()
            self.wfile.write(resp_body)
        except Exception as e:
            error = json.dumps({"error": {"message": str(e)}}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(error)))
            self.end_headers()
            self.wfile.write(error)

    def do_GET(self):
        self._forward("GET")

    def do_POST(self):
        self._forward("POST")

    def log_message(self, format, *args):
        pass  # Suppress request logging


if __name__ == "__main__":
    server = http.server.HTTPServer(("127.0.0.1", PORT), ProxyHandler)
    print(f"Model proxy on :{PORT} -> {TARGET_URL} (default: {DEFAULT_MODEL})", flush=True)
    server.serve_forever()
