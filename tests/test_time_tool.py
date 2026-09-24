"""时间工具测试。

这个工具的输出是用户最容易当场核验对错的——
历史上它把容器内的 UTC 时间当成北京时间返回，慢了 8 个小时，
而容器里一切"看起来正常"，只有用户会发现问题。
所以这里锁两件事：输出格式稳定、时区按配置生效。
"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from agent.tools import TIMEZONE_NAME, get_current_time


def test_output_format_is_stable():
    """正则格式的答案判定依赖这个格式，变了会悄悄破坏评测判定。"""
    out = get_current_time.invoke({})
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", out)


def test_time_matches_configured_timezone():
    """核心回归：必须按 TIMEZONE 配置的时区返回，而不是容器/系统的 UTC。"""
    out = get_current_time.invoke({})
    parsed = datetime.strptime(out, "%Y-%m-%d %H:%M:%S")
    expected = datetime.now(ZoneInfo(TIMEZONE_NAME)).replace(tzinfo=None)
    assert abs((parsed - expected).total_seconds()) < 5


def test_default_timezone_is_beijing():
    """容器默认 UTC 是这个 bug 的根源，把默认值锁在测试里防止被改掉。"""
    assert TIMEZONE_NAME == "Asia/Shanghai"
