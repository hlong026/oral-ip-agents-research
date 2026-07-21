"""
SAU 配置适配层
- 替代 social-auto-upload 的 conf.py，从项目 dynamic_config / settings 读取
- 在 import SAU uploader 之前，将本模块注入 sys.modules["conf"]
"""

import sys
from pathlib import Path

from app.core.config import get_settings

settings = get_settings()

# SAU 需要的核心配置
BASE_DIR = Path(__file__).parent.parent.parent.parent.parent / "vendor" / "social-auto-upload"
XHS_SERVER = "http://127.0.0.1:11901"
LOCAL_CHROME_PATH = ""  # 留空使用 patchright 自带 chromium
LOCAL_CHROME_HEADLESS = settings.publish_browser_headless
DEBUG_MODE = settings.app_env == "dev"
YT_PROXY = None


def install_conf_module() -> None:
    """将本模块注册为 sys.modules['conf']，使 SAU 代码 `from conf import ...` 正常工作"""
    import types

    conf_mod = types.ModuleType("conf")
    conf_mod.BASE_DIR = BASE_DIR  # type: ignore[attr-defined]
    conf_mod.XHS_SERVER = XHS_SERVER  # type: ignore[attr-defined]
    conf_mod.LOCAL_CHROME_PATH = LOCAL_CHROME_PATH  # type: ignore[attr-defined]
    conf_mod.LOCAL_CHROME_HEADLESS = LOCAL_CHROME_HEADLESS  # type: ignore[attr-defined]
    conf_mod.DEBUG_MODE = DEBUG_MODE  # type: ignore[attr-defined]
    conf_mod.YT_PROXY = YT_PROXY  # type: ignore[attr-defined]
    sys.modules["conf"] = conf_mod


def ensure_sau_path() -> None:
    """确保 SAU vendor 目录在 sys.path 中，使 uploader/utils 可被 import"""
    sau_root = str(BASE_DIR)
    if sau_root not in sys.path:
        sys.path.insert(0, sau_root)


def setup_sau() -> None:
    """一次性初始化 SAU 环境（在 app 启动时调用）"""
    ensure_sau_path()
    install_conf_module()
