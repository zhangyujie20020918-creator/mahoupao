#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Voice Cloning API - 启动服务
"""

import uvicorn
import config

if __name__ == "__main__":
    print("=" * 50)
    print("Video Analysis Voice Cloning API")
    print(f"服务地址: http://localhost:{config.API_PORT}")
    print(f"GPU: {config.GPU_NAME if config.GPU_AVAILABLE else 'Not Available (CPU mode)'}")
    print("=" * 50)

    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=config.API_PORT,
        reload=True,
        log_level="info",
    )
