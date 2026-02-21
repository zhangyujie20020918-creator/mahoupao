"""
API服务器启动脚本
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import uvicorn

# 确保工作目录为项目根目录
PROJECT_ROOT = Path(__file__).parent.resolve()
os.chdir(PROJECT_ROOT)


def check_port(host: str, port: int) -> bool:
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect((host, port))
            return True  # 端口被占用
        except (ConnectionRefusedError, socket.timeout, OSError):
            return False  # 端口可用


def kill_process_on_port(port: int) -> bool:
    """终止占用指定端口的进程"""
    try:
        # Windows: 查找占用端口的进程
        result = subprocess.run(
            f"netstat -ano | findstr :{port}",
            shell=True,
            capture_output=True,
            text=True,
        )

        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    pid = parts[-1]
                    subprocess.run(f"taskkill /PID {pid} /F", shell=True, capture_output=True)
                    print(f"已停止旧服务进程 (PID: {pid})")
                    return True
        return False
    except Exception as e:
        print(f"停止进程失败: {e}")
        return False


def main():
    host = "0.0.0.0"
    port = 8000

    if check_port("127.0.0.1", port):
        print(f"检测到端口 {port} 被占用，正在停止旧服务...")
        kill_process_on_port(port)
        time.sleep(1)  # 等待端口释放

    print(f"启动服务器 http://{host}:{port}")
    uvicorn.run(
        "src.api.app:app",
        host=host,
        port=port,
        reload=False,  # 禁用热重载以避免子进程环境问题
    )


if __name__ == "__main__":
    main()
