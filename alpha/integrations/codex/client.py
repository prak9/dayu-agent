"""Host 所持有的本地 Codex JSON-RPC 进程；取消后回收进程组。"""

import asyncio
import json
import os
from pathlib import Path
import signal
from typing import cast

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.cancellation import CancellationToken

_LINE_LIMIT_BYTES = 8 * 1024 * 1024
_CANCEL_POLL_SECONDS = 0.1
_CLOSE_GRACE_SECONDS = 2.0


def require_map(value: JsonValue) -> dict[str, JsonValue]:
    """核验协议对象。参数：JSON。返回：映射。异常：格式错误。"""
    if not isinstance(value, dict):
        raise ValueError("Codex app-server 响应必须是 JSON 对象")
    return value


def require_text(value: JsonValue) -> str:
    """核验身份或正文。参数：值。返回：字符串。异常：格式错误。"""
    if not isinstance(value, str):
        raise ValueError("Codex app-server 字符串字段非法")
    return value


class CodexRpcClient:
    """一个独立 app-server 进程，保留 Codex 自己的登录与配置管理。"""

    def __init__(self, executable: str, cwd: Path, token: CancellationToken) -> None:
        """记录进程规格。参数：可执行文件、工作区、Host 令牌。返回：无。异常：无。"""
        self._executable = executable
        self._cwd = cwd
        self._token = token
        self._process: asyncio.subprocess.Process | None = None
        self._sequence = 0
        self._notifications: list[dict[str, JsonValue]] = []

    async def start(self) -> None:
        """启动并协商动态工具。参数：无。返回：无。异常：启动、协议或取消错误。"""
        self._token.raise_if_cancelled()
        startup = asyncio.create_task(asyncio.create_subprocess_exec(
            self._executable, "app-server", "--stdio", cwd=self._cwd,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=_LINE_LIMIT_BYTES, start_new_session=os.name != "nt"))
        try:
            self._process = await asyncio.shield(startup)
        except asyncio.CancelledError:
            self._process = await startup
            await self.close()
            raise
        await self.request("initialize", {"clientInfo": {"name": "alpha", "version": "0.1.4"},
            "capabilities": {"experimentalApi": True}})
        await self.send({"method": "initialized", "params": {}})

    async def send(self, message: dict[str, JsonValue]) -> None:
        """发送一条协议消息。参数：强类型 JSON。返回：无。异常：进程退出或传输错误。"""
        process = self._process
        if process is None or process.stdin is None:
            raise RuntimeError("Codex app-server 尚未启动")
        process.stdin.write(json.dumps(message, ensure_ascii=False, allow_nan=False).encode() + b"\n")
        await process.stdin.drain()

    async def _read(self) -> dict[str, JsonValue]:
        """有界读取并周期检查取消。参数：无。返回：消息。异常：取消、EOF 或协议损坏。"""
        process = self._process
        if process is None or process.stdout is None:
            raise RuntimeError("Codex app-server 尚未启动")
        while True:
            self._token.raise_if_cancelled()
            try:
                line = await asyncio.wait_for(process.stdout.readline(), _CANCEL_POLL_SECONDS)
            except asyncio.TimeoutError:
                continue
            if not line:
                raise RuntimeError("Codex app-server 意外退出")
            try:
                return require_map(cast(JsonValue, json.loads(line)))
            except (ValueError, UnicodeError):
                raise ValueError("Codex app-server 返回非法协议消息") from None

    async def receive(self) -> dict[str, JsonValue]:
        """先消费请求期间缓存的通知。参数：无。返回：消息。异常：协议或取消错误。"""
        self._token.raise_if_cancelled()
        return self._notifications.pop(0) if self._notifications else await self._read()

    async def request(self, method: str, parameters: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """发送客户端请求并保留交错通知。参数：方法、参数。返回：结果。异常：远端明确错误或取消。"""
        self._sequence += 1
        identifier = self._sequence
        await self.send({"id": identifier, "method": method, "params": parameters})
        while True:
            message = await self._read()
            if message.get("id") != identifier or "method" in message:
                self._notifications.append(message)
                continue
            if "error" in message:
                # 不回传原始错误正文，配置错误可能携带凭据或认证请求地址。
                error = require_map(message["error"])
                raise RuntimeError(f"Codex app-server {method} 失败，code={error.get('code')}")
            return require_map(message.get("result"))

    async def close(self) -> None:
        """终止本次进程及其子进程，等待实际退出。参数：无。返回：无。异常：操作系统回收错误。"""
        process, self._process = self._process, None
        self._notifications.clear()
        if process is None:
            return
        if process.returncode is None:
            try:
                if os.name == "nt":
                    process.terminate()
                else:
                    os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.communicate(), _CLOSE_GRACE_SECONDS)
            except asyncio.TimeoutError:
                try:
                    if os.name == "nt":
                        process.kill()
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.communicate()
        else:
            await process.wait()
