"""
自定义异常模块 - 适配异步 Streaming 架构

设计原则：
1. 异步 + Streaming 架构中，大部分错误通过 error_event 传递（不中断流）
2. 只保留必须立即中断执行的异常（配置错误、API 错误、工具安全错误）
3. 符合 Python 异常层次结构

使用场景：
- 配置加载失败 → ConfigError（抛出异常）
    - API/CLI 调用失败 → error_event 或通用 EngineError
- 工具安全检查失败 → Tool 系列异常（抛出异常）
- 迭代次数过多、超时等 → error_event（不抛异常，继续流式传递）
"""

from typing import Any, Optional


class EngineError(Exception):
    """
    Engine 包基础异常
    
    所有 Engine 包的异常都继承自此类，便于统一捕获。
    """
    pass


class ConfigError(EngineError):
    """
    配置错误（必须立即中断）
    
    当配置文件格式错误、必需字段缺失、环境变量未设置时抛出。
    这类错误无法恢复，必须立即中断执行。
    
    Attributes:
        config_name: 配置名称
        config_file: 配置文件路径
        details: 详细错误信息
    
    Example:
        >>> raise ConfigError("deepseek_chat", "llm_models.json", "API key 未设置")
    """
    
    def __init__(
        self,
        config_name: Optional[str] = None,
        config_file: Optional[str] = None,
        details: str = "",
    ) -> None:
        """初始化配置异常。

        Args:
            config_name: 配置名称。
            config_file: 配置文件路径。
            details: 详细错误信息。

        Returns:
            无。

        Raises:
            无。
        """

        self.config_name = config_name
        self.config_file = config_file
        self.details = details

        # 按“配置名 -> 文件 -> 详情”拼接异常消息，便于终端快速定位问题来源。
        message_parts = []
        if config_name:
            message_parts.append(f"配置 '{config_name}'")
        if config_file:
            message_parts.append(f"文件 '{config_file}'")
        if details:
            message_parts.append(f": {details}")
        
        message = " ".join(message_parts) if message_parts else "配置错误"
        super().__init__(message)


class ToolError(EngineError):
    """
    工具错误基类（安全相关，必须中断）
    
    所有工具相关的错误都继承自此类。
    工具错误通常涉及安全问题（路径遍历、权限等），必须立即中断。
    """
    pass


class ToolNotFoundError(ToolError):
    """
    工具不存在错误
    
    当尝试调用未注册的工具时抛出。
    
    Attributes:
        tool_name: 工具名称
        available_tools: 可用工具列表
    
    Example:
        >>> raise ToolNotFoundError("unknown_tool", ["read_file", "search_files"])
    """
    
    def __init__(self, tool_name: str, available_tools: Optional[list[str]] = None) -> None:
        """初始化工具不存在异常。

        Args:
            tool_name: 调用方请求的工具名称。
            available_tools: 可用工具列表。

        Returns:
            无。

        Raises:
            无。
        """

        self.tool_name = tool_name
        self.available_tools = available_tools

        message = f"工具 '{tool_name}' 不存在"
        if available_tools:
            message += f"。可用工具: {', '.join(available_tools)}"
        
        super().__init__(message)


class ToolExecutionError(ToolError):
    """
    工具执行错误
    
    当工具执行过程中发生错误时抛出（通常会被捕获并转换为 error_event）。
    
    Attributes:
        tool_name: 工具名称
        tool_args: 工具参数
        original_error: 原始异常对象
    
    Example:
        >>> try:
        ...     result = tool_func(**tool_args)
        ... except Exception as e:
        ...     raise ToolExecutionError("read_file", tool_args, e) from e
    """
    
    def __init__(
        self,
        tool_name: str,
        tool_args: Optional[dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ) -> None:
        """初始化工具执行异常。

        Args:
            tool_name: 工具名称。
            tool_args: 工具参数字典。
            original_error: 原始异常对象。

        Returns:
            无。

        Raises:
            无。
        """

        self.tool_name = tool_name
        self.tool_args = tool_args
        self.original_error = original_error

        message = f"Tool '{tool_name}' execution failed"
        if original_error:
            message += f": {str(original_error)}"
        
        super().__init__(message)


class ToolArgumentError(ToolError):
    """
    工具参数错误（参数验证失败）
    
    当工具参数格式错误、缺少必需参数、参数值无效时抛出。
    
    Attributes:
        tool_name: 工具名称
        arg_name: 参数名称
        arg_value: 参数值
        details: 详细错误信息
    
    Example:
        >>> raise ToolArgumentError("read_file", "start_line", -1, "必须 >= 1")
    """
    
    def __init__(
        self,
        tool_name: str,
        arg_name: Optional[str] = None,
        arg_value: Optional[Any] = None,
        details: str = "",
    ) -> None:
        """初始化工具参数异常。

        Args:
            tool_name: 工具名称。
            arg_name: 参数名称。
            arg_value: 参数值。
            details: 详细错误信息。

        Returns:
            无。

        Raises:
            无。
        """

        self.tool_name = tool_name
        self.arg_name = arg_name
        self.arg_value = arg_value
        self.details = details

        # 优先拼出“工具 + 参数 + 参数值 + 详细说明”，增强排障可读性。
        message = f"Tool '{tool_name}' argument error"
        if arg_name:
            message += f", argument '{arg_name}'"
            if arg_value is not None:
                message += f" = {arg_value}"
        if details:
            message += f": {details}"
        
        super().__init__(message)


class FileAccessError(ToolError):
    """
    文件访问错误（安全相关，必须中断）
    
    当文件访问被拒绝、文件不存在、路径不安全时抛出。
    这是安全检查失败，必须立即中断。
    
    Attributes:
        directory: 目录名称
        filename: 文件名
        reason: 拒绝原因
    
    Example:
        >>> raise FileAccessError("data", "secret.txt", "文件不在白名单中")
    """
    
    def __init__(
        self,
        directory: Optional[str] = None,
        filename: Optional[str] = None,
        reason: str = "",
    ) -> None:
        """初始化文件访问异常。

        Args:
            directory: 目录名称。
            filename: 文件名。
            reason: 拒绝原因。

        Returns:
            无。

        Raises:
            无。
        """

        self.directory = directory
        self.filename = filename
        self.reason = reason

        # 消息结构保持固定前缀，后续按可用上下文补齐目录、文件与拒绝原因。
        message_parts = ["File access denied"]
        if directory and filename:
            message_parts.append(f": {directory}/{filename}")
        elif directory:
            message_parts.append(f": directory '{directory}'")
        elif filename:
            message_parts.append(f": file '{filename}'")
        
        if reason:
            message_parts.append(f" ({reason})")
        
        super().__init__(" ".join(message_parts))
