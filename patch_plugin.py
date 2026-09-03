"""为 Nuitka 的 pywebview 插件补上 webview.platforms.win32。

Nuitka 的 pywebview 插件（截至 4.1.3）在 Windows 白名单里漏了 pywebview 6.2.x 新增的
webview.platforms.win32 辅助子模块，导致打包后 winforms 后端因缺该模块而无法启动。
本脚本幂等地把它加进插件白名单，供打包前调用。
"""

import importlib.util
import pathlib

spec = importlib.util.find_spec("nuitka")
if not spec or not spec.submodule_search_locations:
    raise SystemExit("未找到 nuitka，请先 pip install -r requirements.txt")

plugin = pathlib.Path(spec.submodule_search_locations[0]) / "plugins" / "standard" / "PywebViewPlugin.py"
text = plugin.read_text(encoding="utf-8")

if "webview.platforms.win32" in text:
    print("插件已包含 win32，无需修补")
else:
    patched = text.replace(
        '"webview.platforms.cef",',
        '"webview.platforms.cef",\n                    "webview.platforms.win32",',
        1,
    )
    if patched == text:
        raise SystemExit("未能定位插件白名单，Nuitka 版本可能已变，请手动检查 PywebViewPlugin.py")
    plugin.write_text(patched, encoding="utf-8")
    print("已修补：", plugin)
