"""实际子进程的状态检查、预算和取消回收测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from alpha.contracts.cancellation import CancelledError, CancellationToken
from alpha.contracts.research_methods import ResearchMethodBundle
from alpha.process_liveness import is_pid_alive
from alpha.research.calculations import ResearchCalculationError, ResearchCalculationRejectedError, run_research_calculation
from alpha.research.methods.alpha_invest.__main__ import CalculationMethod
from alpha.research.methods.resources import read_packaged_method_files
from alpha.research.storage.methods import FsResearchMethodStore


def _controlled_bundle(tmp_path: Path, program: str) -> ResearchMethodBundle:
    """固定测试程序以注入进程行为。参数：目录、可信测试代码。返回：方法包。异常：存储错误。"""
    return FsResearchMethodStore(tmp_path / "methods").pin({
        "RUNTIME.md": b"test", "skills/invest/SKILL.md": b"test",
        "alpha_invest/__init__.py": b"", "alpha_invest/__main__.py": program.encode(),
    })


@pytest.mark.asyncio
async def test_real_validator_fail_report_is_rejected_despite_zero_exit(tmp_path: Path) -> None:
    """真实退出码零的 fail 报告不能算成功。参数：目录。返回：无。异常：断言失败。"""
    bundle = FsResearchMethodStore(tmp_path / "methods").pin(read_packaged_method_files())
    with pytest.raises(ResearchCalculationRejectedError) as error:
        await run_research_calculation(bundle, CalculationMethod.VALIDATE_DATA, {"metrics": []})
    assert error.value.report["status"] == "fail"
    result = await run_research_calculation(bundle, CalculationMethod.GF_DMA, {})
    assert result["aggregate_enabled"] is False and result["health_score"] is None


@pytest.mark.asyncio
async def test_fixed_pe_method_uses_pinned_code_and_stdin(tmp_path: Path) -> None:
    """固定算法接收显式数据而非任意命令。参数：目录。返回：无。异常：断言失败。"""
    store = FsResearchMethodStore(tmp_path / "methods")
    bundle = store.pin(read_packaged_method_files())
    result = await run_research_calculation(bundle, CalculationMethod.PE_IMPLIED_GROWTH, {
        "base_eps": 1, "years": 5, "cost_of_equity": 0.1, "cash_conversion": 1,
        "terminal_cash_conversion": 1, "terminal_growth": 0, "growth": 0,
    })
    assert result["status"] == "ok"
    assert store.load(bundle.method_hash) == bundle


@pytest.mark.asyncio
@pytest.mark.parametrize("program", ['print("not json")', 'print("[]")', 'import sys;sys.exit(2)'])
async def test_bad_process_results_fail(tmp_path: Path, program: str) -> None:
    """坏返回值和非零退出不能伪装研究结果。参数：目录、测试程序。返回：无。异常：断言失败。"""
    bundle = _controlled_bundle(tmp_path, program)
    with pytest.raises(ResearchCalculationError):
        await run_research_calculation(bundle, CalculationMethod.VALIDATE_DATA, {})


@pytest.mark.asyncio
async def test_timeout_kills_and_reaps_child(tmp_path: Path) -> None:
    """预算结束后子进程确实退出。参数：目录。返回：无。异常：断言失败。"""
    pid_file = tmp_path / "pid"
    bundle = _controlled_bundle(tmp_path, f"import os,time;from pathlib import Path;Path({str(pid_file)!r}).write_text(str(os.getpid()));time.sleep(60)")
    with pytest.raises(ResearchCalculationError, match="超时"):
        await run_research_calculation(bundle, CalculationMethod.VALIDATE_DATA, {}, timeout_seconds=0.5)
    assert pid_file.exists()
    assert not is_pid_alive(int(pid_file.read_text()))


@pytest.mark.asyncio
async def test_host_cancellation_kills_and_reaps_child(tmp_path: Path) -> None:
    """Host 令牌取消穿透到真实子进程。参数：目录。返回：无。异常：断言失败。"""
    pid_file = tmp_path / "pid"
    bundle = _controlled_bundle(tmp_path, f"import os,time;from pathlib import Path;Path({str(pid_file)!r}).write_text(str(os.getpid()));time.sleep(60)")
    token = CancellationToken()
    task = asyncio.create_task(run_research_calculation(bundle, CalculationMethod.VALIDATE_DATA, {}, cancellation_token=token))
    for _ in range(100):
        if pid_file.exists():
            break
        await asyncio.sleep(0.01)
    assert pid_file.exists()
    token.cancel()
    with pytest.raises(CancelledError):
        await asyncio.wait_for(task, timeout=3)
    assert not is_pid_alive(int(pid_file.read_text()))


@pytest.mark.asyncio
async def test_output_limit_stops_producer(tmp_path: Path) -> None:
    """输出过量时停止生成者，不无限缓冲。参数：目录。返回：无。异常：断言失败。"""
    bundle = _controlled_bundle(tmp_path, "import sys;sys.stdout.write('x'*(9*1024*1024));sys.stdout.flush()")
    with pytest.raises(ResearchCalculationError, match="输出超过"):
        await asyncio.wait_for(run_research_calculation(bundle, CalculationMethod.VALIDATE_DATA, {}), timeout=3)


@pytest.mark.asyncio
async def test_cancelled_before_start_and_invalid_budget_do_not_spawn(tmp_path: Path) -> None:
    """启动前的取消或非法预算无执行副作用。参数：目录。返回：无。异常：断言失败。"""
    bundle = _controlled_bundle(tmp_path, 'raise RuntimeError("should not execute")')
    token = CancellationToken()
    token.cancel()
    with pytest.raises(CancelledError):
        await run_research_calculation(bundle, CalculationMethod.VALIDATE_DATA, {}, cancellation_token=token)
    with pytest.raises(ValueError):
        await run_research_calculation(bundle, CalculationMethod.VALIDATE_DATA, {}, timeout_seconds=0)


class _GatedSpawner:
    """将真实进程创建与句柄交付分开，以复现启动中取消。"""

    def __init__(self) -> None:
        """准备门闩。参数：无。返回：无。异常：没有运行循环时 RuntimeError。"""
        self.original = asyncio.create_subprocess_exec
        self.created: asyncio.Future[asyncio.subprocess.Process] = asyncio.get_running_loop().create_future()
        self.release = asyncio.Event()

    async def __call__(self, *arguments: str, stdin: int, stdout: int, stderr: int) -> asyncio.subprocess.Process:
        """启动后暂停交付。参数：固定 argv 与管道。返回：真实进程。异常：启动错误或取消。"""
        process = await self.original(*arguments, stdin=stdin, stdout=stdout, stderr=stderr)
        self.created.set_result(process)
        await self.release.wait()
        return process


@pytest.mark.asyncio
async def test_task_cancellation_during_spawn_reaps_created_process(tmp_path: Path, mocker: MockerFixture) -> None:
    """进程已创建但尚未回传时取消也必须回收。参数：目录、mock。返回：无。异常：断言失败。"""
    bundle = _controlled_bundle(tmp_path, "import time;time.sleep(60)")
    spawner = _GatedSpawner()
    mocker.patch("alpha.research.calculations.asyncio.create_subprocess_exec", new=spawner)
    task = asyncio.create_task(run_research_calculation(bundle, CalculationMethod.VALIDATE_DATA, {}))
    process = await asyncio.wait_for(spawner.created, timeout=3)
    task.cancel()
    spawner.release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=3)
    assert process.returncode is not None and not is_pid_alive(process.pid)


@pytest.mark.asyncio
async def test_task_cancellation_after_start_reaps_process(tmp_path: Path) -> None:
    """外层任务取消与 Host 令牌取消具有同样的资源收尾。参数：目录。返回：无。异常：断言失败。"""
    pid_file = tmp_path / "pid"
    bundle = _controlled_bundle(tmp_path, f"import os,time;from pathlib import Path;Path({str(pid_file)!r}).write_text(str(os.getpid()));time.sleep(60)")
    task = asyncio.create_task(run_research_calculation(bundle, CalculationMethod.VALIDATE_DATA, {}))
    for _ in range(100):
        if pid_file.exists():
            break
        await asyncio.sleep(0.01)
    assert pid_file.exists()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=3)
    assert not is_pid_alive(int(pid_file.read_text()))
