"""时间处理工具"""

from datetime import datetime, date


def now() -> datetime:
    """获取当前时间"""
    return datetime.now()


def today_str() -> str:
    """获取今天的日期字符串 YYYY-MM-DD"""
    return date.today().isoformat()


def parse_date(date_str: str) -> date:
    """解析日期字符串"""
    return date.fromisoformat(date_str)


def format_datetime(dt: datetime) -> str:
    """格式化 datetime 为 ISO 字符串"""
    return dt.isoformat()


def hours_since(dt: datetime) -> float:
    """计算距离给定时间过去了多少小时"""
    return (datetime.now() - dt).total_seconds() / 3600
