#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Video Analysis Maker - 启动服务
"""

import uvicorn

if __name__ == "__main__":
    print("=" * 50)
    print("Video Analysis Maker API")
    print("服务地址: http://localhost:8002")
    print("=" * 50)

    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8002,
        reload=True,
        log_level="info"
    )
