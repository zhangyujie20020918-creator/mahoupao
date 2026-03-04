"""
启动数据清洗服务
"""

import subprocess
import sys

PORT = 8001


def kill_existing_process():
    """杀掉占用端口的进程"""
    if sys.platform != "win32":
        return

    try:
        # 查找占用端口的进程
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
        )

        for line in result.stdout.split("\n"):
            if f":{PORT}" in line and "LISTENING" in line:
                parts = line.split()
                if len(parts) >= 5:
                    pid = parts[-1]
                    print(f"[启动] 发现端口 {PORT} 被进程 {pid} 占用，正在关闭...")
                    subprocess.run(
                        ["taskkill", "/PID", pid, "/F"],
                        capture_output=True,
                    )
                    print(f"[启动] 进程 {pid} 已关闭")
                    break
    except Exception as e:
        print(f"[启动] 检查端口时出错: {e}")


if __name__ == "__main__":
    # 先杀掉占用端口的旧进程
    kill_existing_process()

    import uvicorn
    from api import app

    print("=" * 60)
    print("数据清洗服务")
    print("=" * 60)
    print(f"API 地址: http://localhost:{PORT}")
    print(f"文档地址: http://localhost:{PORT}/docs")
    print("=" * 60)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        reload=False,
    )
