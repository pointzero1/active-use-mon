"""Work-area geometry: correct logical work rect from Win32 physical insets.

Regression for the HiDPI nesting bug: Qt's QScreen.availableGeometry() does not
divide the taskbar inset origin by the device-pixel-ratio on scaled displays, so
the widget nested with a gap (top taskbar) or hung off-screen (bottom taskbar).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRect

from widget import logical_work_area


def test_top_taskbar_hidpi_keeps_workarea_inside_screen():
    # Real captured values: 2880x1800 panel @ 200%, taskbar at top 80 phys px.
    full = QRect(0, 0, 1440, 900)
    mon_phys = (0, 0, 2880, 1800)
    work_phys = (0, 80, 2880, 1800)
    wa = logical_work_area(full, mon_phys, work_phys, 2.0)
    assert wa == QRect(0, 40, 1440, 860)
    # The whole point: the work area must stay within the physical screen.
    assert wa.bottom() <= full.bottom()


def test_bottom_taskbar_normal_dpi():
    full = QRect(0, 0, 1920, 1080)
    mon_phys = (0, 0, 1920, 1080)
    work_phys = (0, 0, 1920, 1032)  # 48px taskbar at bottom
    wa = logical_work_area(full, mon_phys, work_phys, 1.0)
    assert wa == QRect(0, 0, 1920, 1032)


def test_left_taskbar_hidpi():
    full = QRect(0, 0, 1280, 800)
    mon_phys = (0, 0, 2560, 1600)
    work_phys = (120, 0, 2560, 1600)  # 120px taskbar on the left, phys
    wa = logical_work_area(full, mon_phys, work_phys, 2.0)
    assert wa == QRect(60, 0, 1220, 800)


def test_no_taskbar_inset_returns_full():
    full = QRect(0, 0, 1440, 900)
    mon_phys = (0, 0, 2880, 1800)
    work_phys = (0, 0, 2880, 1800)
    wa = logical_work_area(full, mon_phys, work_phys, 2.0)
    assert wa == full
