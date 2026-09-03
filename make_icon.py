"""把 INFINITY 无穷符号图标转成 Windows 多尺寸 .ico，供窗口 / Nuitka / 安装包使用。"""
import os
import shutil

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "web", "infinity-icon.png")
ICO = os.path.join(HERE, "icon.ico")
FAV = os.path.join(HERE, "web", "favicon.ico")

img = Image.open(SRC).convert("RGBA")
sizes = [(16, 16), (32, 32), (48, 48), (256, 256)]
img.save(ICO, sizes=sizes)
shutil.copyfile(ICO, FAV)
print("icon.ico created from", SRC)
print("web/favicon.ico copied")
