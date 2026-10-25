"""在隔离子进程执行已固定 invest 计算，落实工具预算、取消与输出状态检查。"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from functools import partial
from typing import Callable, cast

from alpha.contracts.cancellation import CancellationToken
from alpha.contracts.research_methods import ResearchMethodBundle
from alpha.research.methods.alpha_invest.__main__ import CalculationMethod
from alpha.research.methods.alpha_invest.json_values import JsonMap, JsonValue, require_map

_DEFAULT_TIMEOUT_SECONDS = 30.0
_MAX_OUTPUT_BYTES = 8 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_ERROR_SUMMARY_CHARS = 2000
_ISOLATED_BOOTSTRAP = (
    "import runpy,sys;sys.path.insert(0,sys.argv[1]);sys.argv=sys.argv[2:];"
    "runpy.run_module('alpha_invest',run_name='__main__')"
)


class ResearchCalculationError(RuntimeError):
    """计算执行失败、超限或输出格式非法。"""


class ResearchCalculationRejectedError(ResearchCalculationError):
    """计算生成了失败报告；保留结构化问题，不能仅凭退出码标成功。"""

    def __init__(self, report: JsonMap) -> None:
        """保存报告。参数：report 计算输出。返回：无。异常：无。"""
        super().__init__(f"invest 计算未通过：{report.get('status')}")
        self.report = report


@dataclass(frozen=True)
class _ProcessOutput:
    """已收敛子进程的完整、有界标准输出。"""

    stdout: bytes
    stderr: bytes
    returncode: int


def _kill_process(process: asyncio.subprocess.Process) -> None:
    """终止本次计算子进程。参数：process 进程。返回：无。异常：系统错误传播。"""
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass


def _request_kill(loop: asyncio.AbstractEventLoop, process: asyncio.subprocess.Process) -> None:
    """从 Host 取消线程投递终止。参数：loop 事件循环、process 子进程。返回：无。异常：循环关闭时 RuntimeError。"""
    loop.call_soon_threadsafe(_kill_process, process)


async def _read_bounded(reader: asyncio.StreamReader) -> bytes:
    """读取有界输出。参数：reader 标准流。返回：完整字节。异常：超限时 ResearchCalculationError。"""
    chunks: list[bytes] = []
    size = 0
    while chunk := await reader.read(_READ_CHUNK_BYTES):
        size += len(chunk)
        if size > _MAX_OUTPUT_BYTES:
            raise ResearchCalculationError("invest 计算输出超过 8 MiB 限制")
        chunks.append(chunk)
    return b"".join(chunks)


async def _write_input(writer: asyncio.StreamWriter, data: bytes) -> None:
    """写入 JSON 并关闭 stdin。参数：writer 标准输入、data 内容。返回：无。异常：管道错误。"""
    try:
        writer.write(data)
        await writer.drain()
    finally:
        writer.close()


async def _discard_output(reader: asyncio.StreamReader | None) -> None:
    """丢弃终止进程的残余输出。参数：reader 标准流。返回：无。异常：管道读取错误。"""
    if reader is not None:
        while await reader.read(_READ_CHUNK_BYTES):
            pass


async def _reap_process(process: asyncio.subprocess.Process) -> None:
    """终止并排空管道后回收。参数：process 进程。返回：无。异常：系统或管道错误。"""
    _kill_process(process)
    if process.stdin is not None:
        process.stdin.close()
    # asyncio 的退出等待还依赖管道断开；超限读者已取消，必须继续排空暂停的缓冲区。
    await asyncio.gather(_discard_output(process.stdout), _discard_output(process.stderr), process.wait())


async def _collect(process: asyncio.subprocess.Process, data: bytes) -> _ProcessOutput:
    """同时读写管道以避免互相阻塞。参数：进程、JSON。返回：收敛结果。异常：管道或输出超限。"""
    if process.stdin is None or process.stdout is None or process.stderr is None:
        raise ResearchCalculationError("计算子进程缺少标准管道")
    tasks = (
        asyncio.create_task(_write_input(process.stdin, data)),
        asyncio.create_task(_read_bounded(process.stdout)),
        asyncio.create_task(_read_bounded(process.stderr)),
        asyncio.create_task(process.wait()),
    )
    try:
        _, stdout, stderr, returncode = await asyncio.gather(*tasks)
        return _ProcessOutput(stdout, stderr, returncode)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _spawn(arguments: list[str]) -> asyncio.subprocess.Process:
    """启动进程并封住启动中取消窗口。参数：固定参数数组。返回：进程。异常：启动错误或任务取消。"""
    task = asyncio.create_task(asyncio.create_subprocess_exec(
        *arguments, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    ))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        process = await task
        await _reap_process(process)
        raise


async def run_research_calculation(
    bundle: ResearchMethodBundle, method: CalculationMethod, data: JsonMap, *,
    timeout_seconds: float | None = None, cancellation_token: CancellationToken | None = None,
) -> JsonMap:
    """执行固定方法。参数：方法包、方法、输入、预算及取消令牌。返回：通过状态检查的 JSON。异常：取消、超时或计算失败。"""
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    timeout = _DEFAULT_TIMEOUT_SECONDS if timeout_seconds is None else min(timeout_seconds, _DEFAULT_TIMEOUT_SECONDS)
    if timeout <= 0:
        raise ValueError("计算预算必须大于零")
    encoded = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
    process: asyncio.subprocess.Process | None = None
    unregister: Callable[[], None] | None = None
    try:
        async with asyncio.timeout(timeout):
            process = await _spawn([sys.executable, "-B", "-I", "-c", _ISOLATED_BOOTSTRAP,
                                    str(bundle.root), "alpha_invest", method.value, "-"])
            if cancellation_token is not None:
                unregister = cancellation_token.on_cancel(partial(_request_kill, asyncio.get_running_loop(), process))
            output = await _collect(process, encoded)
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
    except TimeoutError as exc:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        raise ResearchCalculationError("invest 计算超时") from exc
    except (BrokenPipeError, ConnectionResetError) as exc:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        raise ResearchCalculationError("invest 计算输入管道提前关闭") from exc
    except Exception:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        raise
    finally:
        if unregister is not None:
            unregister()
        if process is not None:
            await _reap_process(process)
    if output.returncode != 0:
        detail = output.stderr.decode("utf-8", errors="replace")[:_ERROR_SUMMARY_CHARS]
        raise ResearchCalculationError(f"invest 计算退出码 {output.returncode}：{detail}")
    try:
        result = require_map(cast(JsonValue, json.loads(output.stdout.decode("utf-8"))))
    except (ValueError, UnicodeError) as exc:
        raise ResearchCalculationError("invest 计算未返回有效 JSON 对象") from exc
    if "status" in result and result["status"] not in ("pass", "ok"):
        raise ResearchCalculationRejectedError(result)
    return result
