"""`alpha.contracts` 包级导出测试。"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_contracts_getattr_lazily_loads_and_caches_exports(monkeypatch: pytest.MonkeyPatch) -> None:
    """包级导出应按需加载并缓存到模块全局。"""

    import alpha.contracts as contracts
    from alpha.contracts.run import RunState

    monkeypatch.delitem(contracts.__dict__, "RunState", raising=False)

    loaded = contracts.__getattr__("RunState")

    assert loaded is RunState
    assert contracts.RunState is RunState


@pytest.mark.unit
def test_contracts_getattr_rejects_unknown_export() -> None:
    """未知导出名应抛出 `AttributeError`。"""

    import alpha.contracts as contracts

    with pytest.raises(AttributeError):
        contracts.__getattr__("NotExistingExport")


@pytest.mark.unit
def test_contracts_dir_contains_public_exports() -> None:
    """`__dir__()` 应包含 `__all__` 中的公共导出。"""

    import alpha.contracts as contracts

    exported_names = set(contracts.__all__)
    visible_names = set(contracts.__dir__())

    assert exported_names <= visible_names
    assert "__all__" in visible_names