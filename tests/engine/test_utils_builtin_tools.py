"""
测试工具函数模块

测试 utils_builtin_tools.py 中的工具函数：
- create_get_current_time_tool: 获取当前时间
- register_utils_builtin_tools: 工具注册
"""
import pytest
from unittest.mock import Mock
from datetime import datetime

from alpha.engine import register_utils_builtin_tools
from alpha.engine.tools.utils_tools import create_get_current_time_tool
from alpha.engine.tools import utils_tools
from zoneinfo import ZoneInfoNotFoundError


@pytest.mark.unit
class TestGetCurrentTimeTool:
    """测试 get_current_time 工具"""
    
    def test_get_current_time_default_timezone(self):
        """测试默认时区（Asia/Shanghai）"""
        _, get_current_time, _ = create_get_current_time_tool()
        result = get_current_time()
        
        # 验证返回格式
        assert "time" in result
        assert "timezone" in result
        assert "weekday" in result
        assert "iso" in result
        
        # 验证默认时区
        assert result["timezone"] == "Asia/Shanghai"
        
        # 验证数据类型
        assert isinstance(result["time"], str)
        assert isinstance(result["iso"], str)
        assert isinstance(result["weekday"], str)
    
    def test_get_current_time_custom_timezone(self):
        """测试自定义时区（仅支持 Asia/Shanghai）"""
        _, get_current_time, _ = create_get_current_time_tool()
        with pytest.raises(ValueError, match="仅支持 Asia/Shanghai"):
            get_current_time(timezone="America/New_York")
    
    def test_get_current_time_utc(self):
        """测试 UTC 时区"""
        _, get_current_time, _ = create_get_current_time_tool()
        with pytest.raises(ValueError, match="仅支持 Asia/Shanghai"):
            get_current_time(timezone="UTC")
    
    def test_get_current_time_return_format(self):
        """测试返回格式的完整性"""
        _, get_current_time, _ = create_get_current_time_tool()
        result = get_current_time()
        
        # 必须包含所有字段
        required_fields = ["time", "timezone", "weekday", "iso"]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"
        
        # time 应该包含年月日时分秒
        time_str = result["time"]
        assert "年" in time_str
        assert "月" in time_str
        assert "日" in time_str
        
        # weekday 应该是星期几
        weekday = result["weekday"]
        assert "星期" in weekday
    
    def test_get_current_time_weekday_format(self):
        """测试星期格式"""
        _, get_current_time, _ = create_get_current_time_tool()
        result = get_current_time()
        weekday = result["weekday"]
        
        # 应该是星期一到星期日之一
        valid_weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        assert weekday in valid_weekdays
    
    def test_get_current_time_iso_format(self):
        """测试 ISO 格式"""
        _, get_current_time, _ = create_get_current_time_tool()
        result = get_current_time()
        iso = result["iso"]
        
        # ISO 格式应该包含日期和时间
        assert "T" in iso  # ISO 8601 格式的日期时间分隔符
        
        # 验证可以解析回 datetime
        datetime.fromisoformat(iso)  # 如果格式错误会抛出异常

    def test_get_current_time_zoneinfo_not_found(self, monkeypatch):
        """测试 ZoneInfo 加载失败路径"""
        _, get_current_time, _ = create_get_current_time_tool()

        def raise_zoneinfo_error(_):
            raise ZoneInfoNotFoundError("Asia/Shanghai")

        monkeypatch.setattr(utils_tools, "ZoneInfo", raise_zoneinfo_error)

        with pytest.raises(ValueError, match="无法加载时区"):
            get_current_time()


@pytest.mark.unit
class TestRegisterUtilsBuiltinTools:
    """测试工具注册函数"""

    def test_register_utils_builtin_tools(self):
        """测试工具注册，应注册 get_current_time"""
        mock_registry = Mock()
        count = register_utils_builtin_tools(mock_registry)
        assert count == 1
        mock_registry.register.assert_called_once()
        tool_name = mock_registry.register.call_args[0][0]
        assert tool_name == "get_current_time"
