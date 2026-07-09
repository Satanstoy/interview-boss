from app.agents.chat.stop_policy import detect_closing_signal


def test_detect_closing_signal_time_almost_up():
    """候选人说'时间差不多了'应被检测为收尾信号。"""
    assert detect_closing_signal("今天聊得挺深入的，时间差不多了。感谢您的时间！") is True


def test_detect_closing_signal_thank_you():
    """候选人说'感谢您的时间'应被检测为收尾信号。"""
    assert detect_closing_signal("感谢面试官的时间") is True


def test_detect_closing_signal_not_triggered():
    """正常回答不应被检测为收尾信号。"""
    assert detect_closing_signal("我用 Redis 做缓存，MySQL 做持久化") is False
