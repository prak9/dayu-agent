"""
Log 日志系统测试

测试重点：
- 日志级别设置
- 各级别日志输出
- 堆栈跟踪
- 基于 logging 模块的实现
"""
import io
import logging

import pytest

import alpha.log as alpha_log_module
from alpha.log import Log, LogLevel


class TestLogLevelSetting:
    """测试日志级别设置"""
    
    def test_set_level_debug(self):
        """测试设置 DEBUG 级别"""
        Log.set_level(LogLevel.DEBUG)
        assert logging.getLogger().level == LogLevel.DEBUG.value
    
    def test_set_level_info(self):
        """测试设置 INFO 级别"""
        Log.set_level(LogLevel.INFO)
        assert logging.getLogger().level == LogLevel.INFO.value
    
    def test_set_level_warn(self):
        """测试设置 WARN 级别"""
        Log.set_level(LogLevel.WARN)
        assert logging.getLogger().level == LogLevel.WARN.value
    
    def test_set_level_error(self):
        """测试设置 ERROR 级别"""
        Log.set_level(LogLevel.ERROR)
        assert logging.getLogger().level == LogLevel.ERROR.value
    
    def test_set_level_verbose(self):
        """测试设置 VERBOSE 级别"""
        Log.set_level(LogLevel.VERBOSE)
        assert logging.getLogger().level == LogLevel.VERBOSE.value


class TestLogOutput:
    """测试日志输出"""
    
    def test_debug_output(self, caplog):
        """测试 DEBUG 日志输出"""
        Log.set_level(LogLevel.DEBUG)
        
        with caplog.at_level(logging.DEBUG):
            Log.debug("Debug message", module="test")
            
            assert len(caplog.records) > 0
            assert any("Debug message" in record.message for record in caplog.records)
            assert any(record.levelname == "DEBUG" for record in caplog.records)
    
    def test_info_output(self, caplog):
        """测试 INFO 日志输出"""
        Log.set_level(LogLevel.INFO)
        
        with caplog.at_level(logging.INFO):
            Log.info("Info message", module="test")
            
            assert len(caplog.records) > 0
            assert any("Info message" in record.message for record in caplog.records)
            assert any(record.levelname == "INFO" for record in caplog.records)
    
    def test_warn_output(self, caplog):
        """测试 WARN 日志输出"""
        Log.set_level(LogLevel.WARN)
        
        with caplog.at_level(logging.WARNING):
            Log.warn("Warning message", module="test")
            
            assert len(caplog.records) > 0
            assert any("Warning message" in record.message for record in caplog.records)
            assert any(record.levelname == "WARNING" for record in caplog.records)

    def test_warning_alias_output(self, caplog):
        """测试 warning 别名输出"""
        Log.set_level(LogLevel.WARN)

        with caplog.at_level(logging.WARNING):
            Log.warning("Warning alias", module="test")

            assert len(caplog.records) > 0
            assert any("Warning alias" in record.message for record in caplog.records)
            assert any(record.levelname == "WARNING" for record in caplog.records)
    
    def test_error_output(self, caplog):
        """测试 ERROR 日志输出"""
        Log.set_level(LogLevel.ERROR)
        
        with caplog.at_level(logging.ERROR):
            Log.error("Error message", module="test")
            
            assert len(caplog.records) > 0
            assert any("Error message" in record.message for record in caplog.records)
            assert any(record.levelname == "ERROR" for record in caplog.records)
    
    def test_verbose_output(self, caplog):
        """测试 VERBOSE 日志输出"""
        Log.set_level(LogLevel.VERBOSE)
        
        with caplog.at_level(LogLevel.VERBOSE.value):
            Log.verbose("Verbose message", module="test")
            
            assert len(caplog.records) > 0
            assert any("Verbose message" in record.message for record in caplog.records)
            assert any(record.levelname == "VERBOSE" for record in caplog.records)

    def test_default_handlers_route_non_error_to_stdout_and_error_only_to_stderr(self) -> None:
        """测试默认 handler 会把非 error 日志写到 stdout，并让 error 只写入 stderr。

        Args:
            无。

        Returns:
            无。

        Raises:
            无。
        """

        logger = logging.getLogger("test_stream_routing")
        original_handlers = list(logger.handlers)
        original_level = logger.level
        original_propagate = logger.propagate
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()

        try:
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
            logger.setLevel(logging.DEBUG)
            logger.propagate = False
            logger.addHandler(
                alpha_log_module._build_stream_handler(
                    stream=stdout_buffer,
                    max_level=alpha_log_module._STDOUT_MAX_LEVEL,
                )
            )
            logger.addHandler(alpha_log_module._build_stream_handler(stream=stderr_buffer, min_level=logging.ERROR))

            logger.info("Info to stdout")
            logger.warning("Warn to stdout")
            logger.error("Error to stderr")

            assert "Info to stdout" in stdout_buffer.getvalue()
            assert "Warn to stdout" in stdout_buffer.getvalue()
            assert "Error to stderr" not in stdout_buffer.getvalue()
            assert "Warn to stdout" not in stderr_buffer.getvalue()
            assert "Error to stderr" in stderr_buffer.getvalue()
        finally:
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
            for handler in original_handlers:
                logger.addHandler(handler)
            logger.setLevel(original_level)
            logger.propagate = original_propagate


class TestLogLevelFiltering:
    """测试日志级别过滤"""
    
    def test_debug_level_shows_all(self, caplog):
        """测试 DEBUG 级别显示所有日志"""
        Log.set_level(LogLevel.DEBUG)
        
        with caplog.at_level(logging.DEBUG):
            Log.debug("Debug", module="test")
            Log.verbose("Verbose", module="test")
            Log.info("Info", module="test")
            
            messages = [record.message for record in caplog.records]
            assert "Debug" in messages
            assert "Verbose" in messages
            assert "Info" in messages
    
    def test_info_level_hides_debug(self, caplog):
        """测试 INFO 级别隐藏 DEBUG 和 VERBOSE"""
        Log.set_level(LogLevel.INFO)
        
        with caplog.at_level(logging.INFO):  # caplog 只捕获 INFO 及以上
            Log.debug("Debug", module="test")
            Log.verbose("Verbose", module="test")
            Log.info("Info", module="test")
            
            messages = [record.message for record in caplog.records]
            # DEBUG 和 VERBOSE 不应该被记录
            assert "Debug" not in messages
            assert "Verbose" not in messages
            assert "Info" in messages
    
    def test_warn_level_hides_debug_info(self, caplog):
        """测试 WARN 级别隐藏 DEBUG、VERBOSE 和 INFO"""
        Log.set_level(LogLevel.WARN)
        
        with caplog.at_level(logging.WARNING):  # caplog 只捕获 WARNING 及以上
            Log.debug("Debug", module="test")
            Log.info("Info", module="test")
            Log.warn("Warning", module="test")
            
            messages = [record.message for record in caplog.records]
            # DEBUG 和 INFO 不应该被记录
            assert "Debug" not in messages
            assert "Info" not in messages
            assert "Warning" in messages
    
    def test_error_level_shows_only_errors(self, caplog):
        """测试 ERROR 级别仅显示错误"""
        Log.set_level(LogLevel.ERROR)
        
        with caplog.at_level(logging.ERROR):  # caplog 只捕获 ERROR 及以上
            Log.debug("Debug", module="test")
            Log.info("Info", module="test")
            Log.warn("Warning", module="test")
            Log.error("Error", module="test")
            
            messages = [record.message for record in caplog.records]
            # 只有 ERROR 应该被记录
            assert "Debug" not in messages
            assert "Info" not in messages
            assert "Warning" not in messages
            assert "Error" in messages


class TestLogFormatting:
    """测试日志格式化"""
    
    def test_log_includes_module_name(self, caplog):
        """测试日志包含模块名"""
        Log.set_level(LogLevel.INFO)
        
        with caplog.at_level(logging.INFO):
            Log.info("Test", module="test_module")
            
            assert len(caplog.records) > 0
            assert any(record.name == "test_module" for record in caplog.records)
    
    def test_log_format_structure(self, caplog):
        """测试日志格式结构"""
        Log.set_level(LogLevel.INFO)
        
        with caplog.at_level(logging.INFO):
            Log.info("Test message", module="test")
            
            assert len(caplog.records) > 0
            record = caplog.records[0]
            assert record.levelname == "INFO"
            assert record.message == "Test message"
            assert record.name == "test"


class TestLogStackTrace:
    """测试堆栈跟踪"""
    
    def test_error_with_exception(self, caplog):
        """测试记录异常信息"""
        Log.set_level(LogLevel.ERROR)
        
        try:
            raise ValueError("Test error")
        except ValueError:
            with caplog.at_level(logging.ERROR):
                Log.error("Error occurred", exc_info=True, module="test")
                
                assert len(caplog.records) > 0
                record = caplog.records[0]
                assert "Error occurred" in record.message
                assert record.exc_info is not None
                assert record.exc_info[0] == ValueError
    
    def test_error_without_exc_info(self, caplog):
        """测试不带异常堆栈的错误"""
        Log.set_level(LogLevel.ERROR)
        
        with caplog.at_level(logging.ERROR):
            Log.error("Simple error", module="test")
            
            assert len(caplog.records) > 0
            record = caplog.records[0]
            assert "Simple error" in record.message
            # exc_info 可能是 False 或 None，都表示没有异常信息
            assert record.exc_info in (None, False)


class TestLogEdgeCases:
    """测试边缘情况"""
    
    def test_log_empty_message(self, caplog):
        """测试空消息"""
        Log.set_level(LogLevel.INFO)
        
        with caplog.at_level(logging.INFO):
            Log.info("", module="test")
            
            assert len(caplog.records) > 0
            assert caplog.records[0].message == ""
    
    def test_log_unicode_characters(self, caplog):
        """测试 Unicode 字符"""
        Log.set_level(LogLevel.INFO)
        
        with caplog.at_level(logging.INFO):
            Log.info("中文日志 🎉 Émojis", module="test")
            
            assert len(caplog.records) > 0
            message = caplog.records[0].message
            assert "中文日志" in message
            assert "🎉" in message
            assert "Émojis" in message
    
    def test_log_very_long_message(self, caplog):
        """测试非常长的消息"""
        Log.set_level(LogLevel.INFO)
        
        long_message = "A" * 10000
        
        with caplog.at_level(logging.INFO):
            Log.info(long_message, module="test")
            
            assert len(caplog.records) > 0
            assert caplog.records[0].message == long_message
    
    def test_log_with_newlines(self, caplog):
        """测试包含换行符的消息"""
        Log.set_level(LogLevel.INFO)
        
        with caplog.at_level(logging.INFO):
            Log.info("Line 1\nLine 2\nLine 3", module="test")
            
            assert len(caplog.records) > 0
            message = caplog.records[0].message
            assert "Line 1" in message
            assert "Line 2" in message
            assert "Line 3" in message


class TestLogThreadSafety:
    """测试线程安全（可选）"""
    
    @pytest.mark.skip(reason="Thread safety test - enable if needed")
    def test_concurrent_logging(self):
        """测试并发日志（需要时启用）
        
        logging 模块本身是线程安全的，因此基于 logging 的 Log 也是线程安全的。
        """
        import threading
        
        Log.set_level(LogLevel.INFO)
        
        def log_worker(worker_id):
            for i in range(100):
                Log.info(f"Worker {worker_id}: Message {i}", module="test")
        
        threads = [threading.Thread(target=log_worker, args=(i,)) for i in range(10)]
        
        for thread in threads:
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # 如果没有崩溃，则线程安全


class TestLogModule:
    """测试模块参数功能"""
    
    def test_different_modules(self, caplog):
        """测试不同模块的日志记录"""
        Log.set_level(LogLevel.INFO)
        
        with caplog.at_level(logging.INFO):
            Log.info("Message from module A", module="moduleA")
            Log.info("Message from module B", module="moduleB")
            
            assert len(caplog.records) >= 2
            
            module_a_records = [r for r in caplog.records if r.name == "moduleA"]
            module_b_records = [r for r in caplog.records if r.name == "moduleB"]
            
            assert len(module_a_records) > 0
            assert len(module_b_records) > 0
            assert "Message from module A" in module_a_records[0].message
            assert "Message from module B" in module_b_records[0].message
    
    def test_default_module(self, caplog):
        """测试默认模块名"""
        Log.set_level(LogLevel.INFO)
        
        with caplog.at_level(logging.INFO):
            Log.info("Test with default module")
            
            assert len(caplog.records) > 0
            # 默认模块名是 "APP"
            assert any(record.name == "APP" for record in caplog.records)
