"""真实管道子进程上的 Codex 协议、交错通知与取消回收测试。"""

import asyncio
from collections.abc import Iterator
from pathlib import Path
import sys
import tempfile

import pytest

from alpha.contracts.cancellation import CancellationToken, CancelledError
from alpha.integrations.codex.client import CodexRpcClient

_SERVER = r'''
import json,sys,time,signal
for line in sys.stdin:
    message=json.loads(line)
    if 'id' not in message:
        continue
    method=message['method']
    if method=='initialize':
        print(json.dumps({'method':'test/notice','params':{}}),flush=True)
    if method=='error':
        print(json.dumps({'id':message['id'],'error':{'code':-1,'message':'must-not-leak-secret'}}),flush=True)
    elif method=='bad':
        print('not-json',flush=True)
    elif method=='eof':
        sys.exit(0)
    elif method=='hang':
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        while True: time.sleep(1)
    else:
        print(json.dumps({'id':message['id'],'result':{'accepted':True}}),flush=True)
'''


@pytest.fixture
def executable() -> Iterator[Path]:
    """生成只在 workspace/tmp 存在的测试可执行文件。参数：无。返回：脚本。异常：I/O 错误。"""
    root = Path("workspace/tmp")
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fake-codex-", dir=root.resolve()) as directory:
        path = Path(directory) / "codex"
        path.write_text(f"#!{sys.executable}\n" + _SERVER)
        path.chmod(0o700)
        yield path


@pytest.mark.asyncio
async def test_real_rpc_preserves_interleaving_and_redacts_remote_errors(executable: Path, tmp_path: Path) -> None:
    """通知不丢，错误只显示代码，重复关闭安全。参数：程序、目录。返回：无。异常：断言失败。"""
    client = CodexRpcClient(str(executable), tmp_path, CancellationToken())
    with pytest.raises(RuntimeError):
        await client.send({})
    await client.start()
    assert (await client.receive())["method"] == "test/notice"
    assert await client.request("probe", {}) == {"accepted": True}
    with pytest.raises(RuntimeError) as error:
        await client.request("error", {})
    assert "must-not-leak-secret" not in str(error.value)
    await client.close()
    await client.close()


@pytest.mark.parametrize("method,error_type", [("bad", ValueError), ("eof", RuntimeError)])
@pytest.mark.asyncio
async def test_invalid_protocol_and_eof_are_explicit(executable: Path, tmp_path: Path, method: str, error_type: type[Exception]) -> None:
    """损坏和退出不伪装完成。参数：程序、目录、方法、异常类型。返回：无。异常：断言失败。"""
    client = CodexRpcClient(str(executable), tmp_path, CancellationToken())
    try:
        await client.start()
        with pytest.raises(error_type):
            await client.request(method, {})
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_cancel_during_read_kills_uncooperative_process(executable: Path, tmp_path: Path) -> None:
    """管道无输出也响应 Host 取消，忽略 TERM 的进程最终被回收。参数：程序、目录。返回：无。异常：断言失败。"""
    token = CancellationToken()
    client = CodexRpcClient(str(executable), tmp_path, token)
    await client.start()
    process = client._process
    assert process is not None
    asyncio.get_running_loop().call_later(0.05, token.cancel)
    with pytest.raises(CancelledError):
        await client.request("hang", {})
    await client.close()
    assert process.returncode is not None and client._process is None
