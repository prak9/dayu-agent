"""联网工具限制配置。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WebToolsConfig:
    """联网工具配置。

    Attributes:
        provider: provider 策略（auto/tavily/serper/duckduckgo）。
        request_timeout_seconds: HTTP 请求超时秒数。
        max_search_results: `search_web` 结果数量上限。
        fetch_truncate_chars: `fetch_web_page` 正文截断字符上限。
        allow_private_network_url: 是否允许访问内网/本地网络 URL。
        playwright_channel: 浏览器回退使用的 Chromium channel；空字符串表示不指定。
        playwright_storage_state_dir: 可选 Playwright storage state 目录；目录内按 host 自动查找 `<host>.json`。
    """

    provider: str = "auto"
    request_timeout_seconds: float = 12.0
    max_search_results: int = 20
    fetch_truncate_chars: int = 80000
    allow_private_network_url: bool = False
    playwright_channel: str = "chrome"
    playwright_storage_state_dir: str = "output/web_diagnostics/storage_states"
