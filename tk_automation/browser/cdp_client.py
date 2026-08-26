from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import time
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


class CDPError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChromeTarget:
    target_id: str
    title: str
    url: str
    target_type: str
    web_socket_url: str


def list_chrome_targets(host: str = "127.0.0.1", port: int = 9333, timeout: int = 5) -> list[ChromeTarget]:
    with urllib.request.urlopen(f"http://{host}:{port}/json", timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    targets: list[ChromeTarget] = []
    for item in data:
        web_socket_url = item.get("webSocketDebuggerUrl")
        if not web_socket_url:
            continue
        targets.append(
            ChromeTarget(
                target_id=str(item.get("id") or ""),
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                target_type=str(item.get("type") or ""),
                web_socket_url=str(web_socket_url),
            )
        )
    return targets


def select_page_target(targets: list[ChromeTarget], url_contains: str = "") -> ChromeTarget:
    pages = [target for target in targets if target.target_type == "page"]
    if url_contains:
        lowered = url_contains.lower()
        for target in pages:
            if lowered in target.url.lower():
                return target
    for target in pages:
        if "tiktok" in target.url.lower():
            return target
    if pages:
        return pages[0]
    raise CDPError("No Chrome page target found. Start Chrome with --remote-debugging-port first.")


class SimpleWebSocket:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock

    @classmethod
    def connect(cls, ws_url: str, timeout: int = 10) -> "SimpleWebSocket":
        parsed = urlparse(ws_url)
        if parsed.scheme != "ws":
            raise CDPError(f"Unsupported DevTools websocket URL: {ws_url}")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = "\r\n".join(
            [
                f"GET {path} HTTP/1.1",
                f"Host: {host}:{port}",
                "Upgrade: websocket",
                "Connection: Upgrade",
                f"Sec-WebSocket-Key: {key}",
                "Sec-WebSocket-Version: 13",
                "",
                "",
            ]
        )
        sock.sendall(request.encode("ascii"))
        response = cls._recv_http_response(sock)
        if " 101 " not in response.split("\r\n", 1)[0]:
            sock.close()
            raise CDPError(f"Chrome DevTools websocket handshake failed: {response.splitlines()[0]}")
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        if accept not in response:
            sock.close()
            raise CDPError("Chrome DevTools websocket handshake returned an invalid accept key.")
        return cls(sock)

    @staticmethod
    def _recv_http_response(sock: socket.socket) -> str:
        chunks: list[bytes] = []
        while b"\r\n\r\n" not in b"".join(chunks):
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode("iso-8859-1", errors="replace")

    def close(self) -> None:
        try:
            self._send_frame(0x8, b"")
        finally:
            self.sock.close()

    def send_text(self, text: str) -> None:
        self._send_frame(0x1, text.encode("utf-8"))

    def recv_text(self) -> str:
        chunks: list[bytes] = []
        while True:
            fin, opcode, payload = self._recv_frame()
            if opcode == 0x8:
                raise CDPError("Chrome DevTools websocket closed.")
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x1, 0x0):
                chunks.append(payload)
                if fin:
                    return b"".join(chunks).decode("utf-8")

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        first = 0x80 | opcode
        mask = os.urandom(4)
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", first, 0x80 | length)
        elif length < 65536:
            header = struct.pack("!BBH", first, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", first, 0x80 | 127, length)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def _recv_frame(self) -> tuple[bool, int, bytes]:
        header = self._recv_exact(2)
        first, second = header[0], header[1]
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length) if length else b""
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return fin, opcode, payload

    def _recv_exact(self, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise CDPError("Chrome DevTools websocket disconnected.")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


class CDPClient:
    def __init__(self, websocket: SimpleWebSocket) -> None:
        self.websocket = websocket
        self._next_id = 0

    @classmethod
    def connect_to_page(
        cls,
        host: str = "127.0.0.1",
        port: int = 9333,
        url_contains: str = "",
        timeout: int = 10,
    ) -> "CDPClient":
        target = select_page_target(list_chrome_targets(host=host, port=port, timeout=timeout), url_contains=url_contains)
        websocket = SimpleWebSocket.connect(target.web_socket_url, timeout=timeout)
        return cls(websocket)

    def close(self) -> None:
        self.websocket.close()

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
        self._next_id += 1
        message_id = self._next_id
        payload = {"id": message_id, "method": method, "params": params or {}}
        self.websocket.send_text(json.dumps(payload, ensure_ascii=False))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for CDP response to {method}.")
            self.websocket.sock.settimeout(remaining)
            message = json.loads(self.websocket.recv_text())
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise CDPError(json.dumps(message["error"], ensure_ascii=False))
            return message.get("result", {})

    def next_message(self, timeout: int = 30) -> dict[str, Any]:
        self.websocket.sock.settimeout(timeout)
        try:
            return json.loads(self.websocket.recv_text())
        except socket.timeout as exc:
            raise TimeoutError("Timed out waiting for Chrome DevTools event.") from exc

    def evaluate(self, expression: str, timeout: int = 30) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
                "userGesture": True,
            },
            timeout=timeout,
        )
        if "exceptionDetails" in result:
            raise CDPError(json.dumps(result["exceptionDetails"], ensure_ascii=False))
        remote_object = result.get("result") or {}
        if remote_object.get("subtype") == "error":
            raise CDPError(str(remote_object.get("description") or remote_object.get("value")))
        return remote_object.get("value")
