#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Video Analysis Soul - 启动服务
"""

import os
import signal
import socket
import subprocess
import sys

import uvicorn

PORT = 8004


def kill_port(port):
    """杀掉占用指定端口的进程"""
    # 先检测端口是否被占用
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", port)) != 0:
            return  # 端口空闲

    print(f"端口 {port} 被占用，正在释放...")

    if sys.platform == "win32":
        # Windows: netstat 找 PID，taskkill 杀掉
        try:
            out = subprocess.check_output(
                f"netstat -ano | findstr :{port}",
                shell=True, text=True,
            )
            pids = set()
            for line in out.strip().splitlines():
                parts = line.split()
                if "LISTENING" in parts:
                    pids.add(int(parts[-1]))
            for pid in pids:
                if pid == os.getpid():
                    continue
                print(f"  杀掉进程 PID={pid}")
                subprocess.run(
                    f"taskkill /F /PID {pid}",
                    shell=True, capture_output=True,
                )
        except subprocess.CalledProcessError:
            pass
    else:
        # Linux/Mac: lsof 找 PID，kill 杀掉
        try:
            out = subprocess.check_output(
                f"lsof -ti :{port}", shell=True, text=True,
            )
            for pid_str in out.strip().splitlines():
                pid = int(pid_str)
                if pid == os.getpid():
                    continue
                print(f"  杀掉进程 PID={pid}")
                os.kill(pid, signal.SIGKILL)
        except subprocess.CalledProcessError:
            pass

    print(f"端口 {port} 已释放")


if __name__ == "__main__":
    kill_port(PORT)

    print("=" * 50)
    print("Video Analysis Soul API")
    print(f"服务地址: http://localhost:{PORT}")
    print("=" * 50)

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        reload=True,
        log_level="info",
    )
