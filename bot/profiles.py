"""Singleton quản lý profile/cookie trong phạm vi một process."""

from __future__ import annotations

import threading

from services.profile_manager import ProfileManager

from .paths import APP_DIR

_DEFAULT_PROFILE_MANAGER = None
_DEFAULT_PROFILE_MANAGER_LOCK = threading.Lock()


def get_profile_manager() -> ProfileManager:
    """Trả về ProfileManager dùng chung cho cả process."""
    global _DEFAULT_PROFILE_MANAGER
    with _DEFAULT_PROFILE_MANAGER_LOCK:
        if _DEFAULT_PROFILE_MANAGER is None:
            _DEFAULT_PROFILE_MANAGER = ProfileManager(APP_DIR)
        return _DEFAULT_PROFILE_MANAGER
