"""Đường dẫn gốc của ứng dụng.

Tách riêng để các module con của package ``bot`` dùng chung mà không phải
import ``bot/__init__.py`` (tránh import vòng).
"""

from __future__ import annotations

import os
import sys

# Console Windows có thể dùng cp1252 khi stdout bị redirect; log tiếng Việt
# không được phép làm sập tiến trình.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# PyInstaller --onefile giải nén code vào thư mục tạm. Dữ liệu chạy (profile,
# cookie, export, log) phải nằm cạnh file exe thì mới còn sau khi thoát.
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = BASE_DIR
