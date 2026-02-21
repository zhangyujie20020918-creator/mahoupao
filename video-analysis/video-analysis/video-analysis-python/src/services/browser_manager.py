"""
浏览器管理器 - 保持浏览器实例在多次下载间复用
"""

import asyncio
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright


class BrowserManager:
    """
    全局浏览器管理器（单例模式）

    保持浏览器实例打开，供多次下载复用登录状态
    """

    _instance: Optional["BrowserManager"] = None
    _lock = asyncio.Lock()

    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._profile_dir: Optional[Path] = None
        self._chrome_path: Optional[str] = None

    @classmethod
    async def get_instance(cls) -> "BrowserManager":
        """获取单例实例"""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = BrowserManager()
        return cls._instance

    async def get_page(self, profile_dir: Path, chrome_path: Optional[str] = None) -> Page:
        """
        获取浏览器页面，如果不存在则创建

        Args:
            profile_dir: 用户数据目录
            chrome_path: Chrome 可执行文件路径

        Returns:
            Page: 浏览器页面
        """
        # 如果配置发生变化，关闭旧的浏览器
        if self._context and (self._profile_dir != profile_dir or self._chrome_path != chrome_path):
            await self.close()

        # 检查浏览器是否仍然有效（用户可能手动关闭了）
        if self._context is not None:
            try:
                # 尝试访问 pages 来检测连接是否有效
                _ = self._context.pages
            except Exception as e:
                print(f"[浏览器管理器] 检测到浏览器已断开: {e}")
                await self._cleanup()

        if self._context is None:
            await self._launch(profile_dir, chrome_path)

        # 确保页面可用
        if self._page is None or self._page.is_closed():
            if self._context.pages:
                self._page = self._context.pages[0]
            else:
                self._page = await self._context.new_page()

        return self._page

    async def _cleanup(self):
        """清理失效的浏览器资源（不尝试关闭，因为已断开）"""
        print(f"[浏览器管理器] 清理失效的浏览器资源...")
        self._context = None
        self._page = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    async def _launch(self, profile_dir: Path, chrome_path: Optional[str] = None):
        """启动浏览器"""
        self._profile_dir = profile_dir
        self._chrome_path = chrome_path

        self._playwright = await async_playwright().start()

        launch_options = {
            "user_data_dir": str(profile_dir),
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
            ],
            "viewport": {"width": 1280, "height": 800},
            "ignore_default_args": ["--enable-automation", "--no-sandbox"],
        }

        if chrome_path:
            launch_options["executable_path"] = chrome_path

        print(f"[浏览器管理器] 正在启动浏览器: {chrome_path or 'Playwright 内置'}")
        self._context = await self._playwright.chromium.launch_persistent_context(**launch_options)
        print(f"[浏览器管理器] 浏览器已启动")

        # 获取或创建页面
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = await self._context.new_page()

        # 注入反检测脚本
        await self._page.add_init_script("""
            // 隐藏 webdriver 标识
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            delete navigator.__proto__.webdriver;

            // 伪造插件
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                    { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                    { name: 'Native Client', filename: 'internal-nacl-plugin' }
                ]
            });

            // 语言设置
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });

            // Chrome 对象
            window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {} };

            // 伪造权限API
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );

            // 隐藏自动化特征
            Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 1 });
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
        """)

    async def close(self):
        """关闭浏览器"""
        print(f"[浏览器管理器] 正在关闭浏览器...")
        if self._context:
            await self._context.close()
            self._context = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self._page = None
        print(f"[浏览器管理器] 浏览器已关闭")

    @property
    def is_running(self) -> bool:
        """检查浏览器是否正在运行"""
        return self._context is not None

    def keep_alive(self):
        """标记浏览器应保持打开状态（仅日志提示）"""
        print(f"\n[浏览器管理器] 浏览器保持打开状态（登录状态将被保留）")
        print(f"[浏览器管理器] 下次下载将复用当前浏览器会话")


# 全局实例
_browser_manager: Optional[BrowserManager] = None


async def get_browser_manager() -> BrowserManager:
    """获取全局浏览器管理器"""
    global _browser_manager
    if _browser_manager is None:
        _browser_manager = await BrowserManager.get_instance()
    return _browser_manager
