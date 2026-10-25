"""
异常模块测试 - 覆盖所有异常类型

测试覆盖：
1. EngineError 基类
2. ConfigError - 配置错误
3. ToolNotFoundError - 工具不存在
4. ToolExecutionError - 工具执行失败
5. ToolArgumentError - 工具参数错误
6. FileAccessError - 文件访问错误
"""

import pytest

from alpha.engine.exceptions import (
    EngineError,
    ConfigError,
    ToolError,
    ToolNotFoundError,
    ToolExecutionError,
    ToolArgumentError,
    FileAccessError,
)


class TestEngineError:
    """测试 EngineError 基类"""
    
    def test_engine_error_basic(self):
        """测试基础异常创建"""
        error = EngineError("test error")
        assert str(error) == "test error"
        assert isinstance(error, Exception)
    
    def test_engine_error_empty(self):
        """测试空异常"""
        error = EngineError()
        assert isinstance(error, Exception)
    
    def test_engine_error_inheritance(self):
        """测试异常继承关系"""
        error = EngineError("test")
        assert isinstance(error, Exception)
        assert isinstance(error, EngineError)


class TestToolError:
    """测试 ToolError 基类"""
    
    def test_tool_error_basic(self):
        """测试工具错误基类"""
        error = ToolError("tool error")
        assert str(error) == "tool error"
        assert isinstance(error, EngineError)
        assert isinstance(error, Exception)


class TestConfigError:
    """测试 ConfigError - 配置错误"""
    
    def test_config_error_minimal(self):
        """测试最小配置错误（无参数）"""
        error = ConfigError()
        assert str(error) == "配置错误"
        assert error.config_name is None
        assert error.config_file is None
        assert error.details == ""
    
    def test_config_error_with_name(self):
        """测试带配置名称的错误"""
        error = ConfigError(config_name="deepseek_chat")
        assert "deepseek_chat" in str(error)
        assert error.config_name == "deepseek_chat"
    
    def test_config_error_with_file(self):
        """测试带配置文件的错误"""
        error = ConfigError(config_file="llm_models.json")
        assert "llm_models.json" in str(error)
        assert error.config_file == "llm_models.json"
    
    def test_config_error_with_details(self):
        """测试带详细信息的错误"""
        error = ConfigError(details="API key 未设置")
        assert "API key 未设置" in str(error)
        assert error.details == "API key 未设置"
    
    def test_config_error_full(self):
        """测试完整配置错误（所有参数）"""
        error = ConfigError(
            config_name="deepseek_chat",
            config_file="llm_models.json",
            details="API key 未设置"
        )
        message = str(error)
        assert "deepseek_chat" in message
        assert "llm_models.json" in message
        assert "API key 未设置" in message
    
    def test_config_error_inheritance(self):
        """测试继承关系"""
        error = ConfigError()
        assert isinstance(error, EngineError)
        assert isinstance(error, Exception)


class TestToolNotFoundError:
    """测试 ToolNotFoundError - 工具不存在"""
    
    def test_tool_not_found_minimal(self):
        """测试最小工具不存在错误（仅工具名）"""
        error = ToolNotFoundError("unknown_tool")
        assert "unknown_tool" in str(error)
        assert error.tool_name == "unknown_tool"
        assert error.available_tools is None
    
    def test_tool_not_found_with_available_tools(self):
        """测试带可用工具列表的错误"""
        available = ["read_file", "search_files", "list_files"]
        error = ToolNotFoundError("unknown_tool", available)
        message = str(error)
        assert "unknown_tool" in message
        assert "read_file" in message
        assert "search_files" in message
        assert "list_files" in message
        assert error.available_tools == available
    
    def test_tool_not_found_empty_available(self):
        """测试空的可用工具列表"""
        error = ToolNotFoundError("unknown_tool", [])
        # 空列表不应该在消息中
        assert "unknown_tool" in str(error)
        assert error.available_tools == []
    
    def test_tool_not_found_inheritance(self):
        """测试继承关系"""
        error = ToolNotFoundError("test_tool")
        assert isinstance(error, ToolError)
        assert isinstance(error, EngineError)


class TestToolExecutionError:
    """测试 ToolExecutionError - 工具执行失败"""
    
    def test_tool_execution_error_minimal(self):
        """测试最小工具执行错误（仅工具名）"""
        error = ToolExecutionError("read_file")
        assert "read_file" in str(error)
        assert "execution failed" in str(error)
        assert error.tool_name == "read_file"
        assert error.tool_args is None
        assert error.original_error is None
    
    def test_tool_execution_error_with_args(self):
        """测试带参数的执行错误"""
        args = {"file_path": "test.txt", "start_line": 1}
        error = ToolExecutionError("read_file", args)
        assert error.tool_args == args
    
    def test_tool_execution_error_with_original_error(self):
        """测试带原始异常的执行错误"""
        original = ValueError("file not found")
        error = ToolExecutionError("read_file", original_error=original)
        message = str(error)
        assert "read_file" in message
        assert "file not found" in message
        assert error.original_error == original
    
    def test_tool_execution_error_full(self):
        """测试完整执行错误（所有参数）"""
        args = {"file_path": "test.txt"}
        original = IOError("Permission denied")
        error = ToolExecutionError("read_file", args, original)
        
        assert error.tool_name == "read_file"
        assert error.tool_args == args
        assert error.original_error == original
        assert "Permission denied" in str(error)
    
    def test_tool_execution_error_inheritance(self):
        """测试继承关系"""
        error = ToolExecutionError("test_tool")
        assert isinstance(error, ToolError)
        assert isinstance(error, EngineError)


class TestToolArgumentError:
    """测试 ToolArgumentError - 工具参数错误"""
    
    def test_tool_argument_error_minimal(self):
        """测试最小参数错误（仅工具名）"""
        error = ToolArgumentError("read_file")
        assert "read_file" in str(error)
        assert "argument error" in str(error)
        assert error.tool_name == "read_file"
        assert error.arg_name is None
        assert error.arg_value is None
        assert error.details == ""
    
    def test_tool_argument_error_with_arg_name(self):
        """测试带参数名的错误"""
        error = ToolArgumentError("read_file", arg_name="start_line")
        message = str(error)
        assert "read_file" in message
        assert "start_line" in message
        assert error.arg_name == "start_line"
    
    def test_tool_argument_error_with_arg_value(self):
        """测试带参数值的错误"""
        error = ToolArgumentError("read_file", arg_name="start_line", arg_value=-1)
        message = str(error)
        assert "start_line" in message
        assert "-1" in message
        assert error.arg_value == -1
    
    def test_tool_argument_error_with_details(self):
        """测试带详细信息的错误"""
        error = ToolArgumentError("read_file", details="必须 >= 1")
        message = str(error)
        assert "必须 >= 1" in message
        assert error.details == "必须 >= 1"
    
    def test_tool_argument_error_full(self):
        """测试完整参数错误（所有参数）"""
        error = ToolArgumentError(
            tool_name="read_file",
            arg_name="start_line",
            arg_value=-1,
            details="必须 >= 1"
        )
        message = str(error)
        assert "read_file" in message
        assert "start_line" in message
        assert "-1" in message
        assert "必须 >= 1" in message
    
    def test_tool_argument_error_with_none_value(self):
        """测试参数值为 None 的情况"""
        error = ToolArgumentError("read_file", arg_name="cursor", arg_value=None)
        message = str(error)
        assert "read_file" in message
        assert "cursor" in message
        # None 值不应该显示在消息中
        assert error.arg_value is None
    
    def test_tool_argument_error_inheritance(self):
        """测试继承关系"""
        error = ToolArgumentError("test_tool")
        assert isinstance(error, ToolError)
        assert isinstance(error, EngineError)


class TestFileAccessError:
    """测试 FileAccessError - 文件访问错误"""
    
    def test_file_access_error_minimal(self):
        """测试最小文件访问错误（无参数）"""
        error = FileAccessError()
        assert "File access denied" in str(error)
        assert error.directory is None
        assert error.filename is None
        assert error.reason == ""
    
    def test_file_access_error_with_directory(self):
        """测试带目录的错误"""
        error = FileAccessError(directory="data")
        message = str(error)
        assert "File access denied" in message
        assert "data" in message
        assert error.directory == "data"
    
    def test_file_access_error_with_filename(self):
        """测试带文件名的错误"""
        error = FileAccessError(filename="secret.txt")
        message = str(error)
        assert "File access denied" in message
        assert "secret.txt" in message
        assert error.filename == "secret.txt"
    
    def test_file_access_error_with_directory_and_filename(self):
        """测试带目录和文件名的错误"""
        error = FileAccessError(directory="data", filename="secret.txt")
        message = str(error)
        assert "File access denied" in message
        assert "data/secret.txt" in message
    
    def test_file_access_error_with_reason(self):
        """测试带拒绝原因的错误"""
        error = FileAccessError(reason="not in whitelist")
        message = str(error)
        assert "File access denied" in message
        assert "not in whitelist" in message
        assert error.reason == "not in whitelist"
    
    def test_file_access_error_full(self):
        """测试完整文件访问错误（所有参数）"""
        error = FileAccessError(
            directory="data",
            filename="secret.txt",
            reason="not in whitelist"
        )
        message = str(error)
        assert "File access denied" in message
        assert "data/secret.txt" in message
        assert "not in whitelist" in message
    
    def test_file_access_error_inheritance(self):
        """测试继承关系"""
        error = FileAccessError()
        assert isinstance(error, ToolError)
        assert isinstance(error, EngineError)


class TestExceptionCatching:
    """测试异常捕获场景"""
    
    def test_catch_engine_error_catches_all(self):
        """测试 EngineError 可以捕获所有子异常"""
        exceptions = [
            ConfigError("test"),
            ToolNotFoundError("test"),
            ToolExecutionError("test"),
            ToolArgumentError("test"),
            FileAccessError()
        ]
        
        for exc in exceptions:
            try:
                raise exc
            except EngineError:
                pass  # 应该能捕获
            else:
                pytest.fail(f"Failed to catch {type(exc).__name__} with EngineError")
    
    def test_catch_tool_error_catches_tool_exceptions(self):
        """测试 ToolError 可以捕获所有工具相关异常"""
        tool_exceptions = [
            ToolNotFoundError("test"),
            ToolExecutionError("test"),
            ToolArgumentError("test"),
            FileAccessError()
        ]
        
        for exc in tool_exceptions:
            try:
                raise exc
            except ToolError:
                pass  # 应该能捕获
            else:
                pytest.fail(f"Failed to catch {type(exc).__name__} with ToolError")
    
    def test_config_error_not_caught_by_tool_error(self):
        """测试 ConfigError 不会被 ToolError 捕获"""
        with pytest.raises(ConfigError):
            try:
                raise ConfigError("test")
            except ToolError:
                pytest.fail("ConfigError should not be caught by ToolError")
            except ConfigError:
                raise  # 正确的捕获路径


class TestExceptionAttributes:
    """测试异常属性访问"""
    
    def test_config_error_attributes(self):
        """测试 ConfigError 属性"""
        error = ConfigError("name", "file.json", "details")
        assert hasattr(error, 'config_name')
        assert hasattr(error, 'config_file')
        assert hasattr(error, 'details')
    
    def test_tool_not_found_error_attributes(self):
        """测试 ToolNotFoundError 属性"""
        error = ToolNotFoundError("tool", ["a", "b"])
        assert hasattr(error, 'tool_name')
        assert hasattr(error, 'available_tools')
    
    def test_tool_execution_error_attributes(self):
        """测试 ToolExecutionError 属性"""
        error = ToolExecutionError("tool", {"arg": 1}, ValueError("test"))
        assert hasattr(error, 'tool_name')
        assert hasattr(error, 'tool_args')
        assert hasattr(error, 'original_error')
    
    def test_tool_argument_error_attributes(self):
        """测试 ToolArgumentError 属性"""
        error = ToolArgumentError("tool", "arg", 123, "details")
        assert hasattr(error, 'tool_name')
        assert hasattr(error, 'arg_name')
        assert hasattr(error, 'arg_value')
        assert hasattr(error, 'details')
    
    def test_file_access_error_attributes(self):
        """测试 FileAccessError 属性"""
        error = FileAccessError("dir", "file.txt", "reason")
        assert hasattr(error, 'directory')
        assert hasattr(error, 'filename')
        assert hasattr(error, 'reason')
