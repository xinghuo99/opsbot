import os
import sys
import logging

# 必须在导入任何 PyQt5 模块之前设置！
os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"

from PyQt5.QtWidgets import QApplication, QWidget, QHBoxLayout, QLineEdit, QPushButton, QLabel, QFileDialog, QMenu, QAction, QShortcut, QFontComboBox, QComboBox, QInputDialog
from PyQt5.QtCore import pyqtSignal, Qt, QRect, QPoint, QRectF, QTimer, QObject
from PyQt5.QtGui import QPixmap, QScreen, QPainter, QPen, QCursor, QColor, QPolygon, QBrush, QFont, QKeySequence, QIcon, QImage
from PyQt5 import QtCore, QtGui, QtWidgets
from datetime import datetime
import subprocess
import tempfile
import wave
import struct
import threading
import shutil


import ctypes
from ctypes import wintypes

# 配置日志
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# 启用高DPI支持（必须在 QApplication 创建之前设置）
if hasattr(Qt, 'AA_EnableHighDpiScaling'):
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

# 全局快捷键常量
MOD_ALT = 0x0001
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
VK_1 = 0x31
VK_2 = 0x32
VK_3 = 0x33
VK_A = 0x41
VK_S = 0x53
VK_Q = 0x51
VK_W = 0x57
HK_SCREENSHOT = 1
HK_PASTE = 2
HK_CANCEL_SCREENSHOT = 3
HK_DOODLE = 4
HK_DOODLE_END = 5
HK_DOODLE_UNDO = 6
HK_DOODLE_REDO = 7

# 当前活跃的截图窗口引用，用于全局快捷键取消截图
_active_screenshot_window = None
# 当前活跃的涂鸦窗口引用，用于全局快捷键结束涂鸦
_active_doodle_window = None
# 独立函数创建的钉图窗口列表，防止被垃圾回收
_standalone_pinned_windows = []


class _ImageSavedEmitter(QObject):
    """全局信号：截图或涂鸦图片保存后触发，传出保存的图片路径"""
    image_saved = pyqtSignal(str)


_image_saved_emitter = _ImageSavedEmitter()


def _save_and_emit(pixmap):
    """保存 pixmap 到 ./xiaohua/images/image_<timestamp>.png 并通过信号发出路径"""
    save_dir = os.path.join(os.getcwd(), 'xiaohua', 'images')
    os.makedirs(save_dir, exist_ok=True)
    filename = f"image_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
    path = os.path.join(save_dir, filename)
    pixmap.save(path, 'PNG')
    _image_saved_emitter.image_saved.emit(path)
    return path


def _copy_pixmap_rect(pixmap, rect):
    """
    从带有 devicePixelRatio 的 QPixmap 中正确复制子区域。
    
    PyQt5 中 QPixmap.copy(QRect) 在高 DPI 模式下可能不正确处理 devicePixelRatio，
    导致复制的物理像素区域与逻辑坐标不匹配。本函数通过 QImage 中转来避免此问题。
    """
    dpr = pixmap.devicePixelRatio()
    if abs(dpr - 1.0) < 0.01:
        return pixmap.copy(rect)
    qimg = pixmap.toImage()
    phys_rect = QRect(int(rect.x() * dpr), int(rect.y() * dpr),
                      int(rect.width() * dpr), int(rect.height() * dpr))
    cropped = qimg.copy(phys_rect)
    result = QPixmap.fromImage(cropped)
    result.setDevicePixelRatio(dpr)
    return result


def _capture_current_screen():
    """
    捕获当前鼠标所在屏幕的截图，返回 QPixmap。
    
    使用 QScreen.grabWindow(0) 捕获单个屏幕，pixmap 自动携带正确的 devicePixelRatio。
    窗口只需覆盖该屏幕即可，不再跨屏拼接。
    """
    screen = QApplication.screenAt(QCursor.pos())
    if screen is None:
        screen = QApplication.primaryScreen()
    pixmap = screen.grabWindow(0)
    logging.info(f"当前屏幕截图: geom={screen.geometry().x()},{screen.geometry().y()} "
                 f"{screen.geometry().width()}x{screen.geometry().height()}, "
                 f"physical={pixmap.width()}x{pixmap.height()}, DPR={pixmap.devicePixelRatio()}")
    return pixmap


def capture_screenshot():
    """
    独立的截图函数，与主窗口无关，可在任意地方调用。
    仅捕获当前鼠标所在屏幕，窗口覆盖该屏幕。
    返回截取的区域图片 QPixmap，如果取消则返回 None。
    """
    from PyQt5.QtCore import QEventLoop
    
    # 确定当前鼠标所在屏幕
    screen = QApplication.screenAt(QCursor.pos())
    if screen is None:
        screen = QApplication.primaryScreen()
    screen_geom = screen.geometry()
    
    # 捕获当前屏幕截图
    combined = _capture_current_screen()
    
    result = {'pixmap': None}
    loop = QEventLoop()
    
    window = ScreenshotWindow(combined)
    
    def on_taken(pixmap):
        global _active_screenshot_window
        _active_screenshot_window = None
        result['pixmap'] = pixmap
        loop.quit()
    
    def on_canceled():
        global _active_screenshot_window
        _active_screenshot_window = None
        result['pixmap'] = None
        loop.quit()
    
    def on_pinned(pixmap, pos):
        global _active_screenshot_window, _standalone_pinned_windows
        _active_screenshot_window = None
        pinned = PinnedWindow(pixmap, pos)
        pinned.show()
        _standalone_pinned_windows.append(pinned)
        result['pixmap'] = None
        loop.quit()
    
    window.screenshot_taken.connect(on_taken)
    window.screenshot_canceled.connect(on_canceled)
    window.screenshot_pinned.connect(on_pinned)
    # 窗口仅覆盖当前屏幕
    window.setGeometry(screen_geom)
    
    global _active_screenshot_window
    _active_screenshot_window = window
    window.show()
    window.raise_()
    window.activateWindow()
    
    loop.exec_()
    pix = result['pixmap']
    if pix is not None:
        _save_and_emit(pix)
    return pix


def start_doodle(pixmap):
    """
    独立的涂鸦函数，与主窗口无关，可在任意地方调用。
    传入原始图片 QPixmap，返回涂鸦后的图片 QPixmap。
    窗口仅覆盖当前鼠标所在屏幕。
    """
    from PyQt5.QtCore import QEventLoop
    
    result = {'pixmap': None}
    loop = QEventLoop()
    
    window = DoodleWindow(pixmap)
    
    def on_finished(doodled):
        global _active_doodle_window
        _active_doodle_window = None
        result['pixmap'] = doodled
        loop.quit()
    
    window.doodle_finished.connect(on_finished)
    
    # 确定当前鼠标所在屏幕，窗口仅覆盖该屏幕
    screen = QApplication.screenAt(QCursor.pos())
    if screen is None:
        screen = QApplication.primaryScreen()
    screen_geom = screen.geometry()
    window.setGeometry(screen_geom)
    
    global _active_doodle_window
    _active_doodle_window = window
    window.show()
    window.raise_()
    window.activateWindow()
    window.toolbar.show_at_mouse_screen()
    
    loop.exec_()
    pix = result['pixmap']
    if pix is not None:
        _save_and_emit(pix)
    return pix


class HotkeyManager(QWidget):
    """不可见的全局快捷键管理器，替代原 PicBot 窗口"""
    
    def __init__(self):
        super().__init__()
        self._hotkeys_registered = False
        self._last_captured = None
        # 全局屏幕监控：检测鼠标是否移到其他屏幕，自动关旧流程开新流程
        self._screen_monitor_timer = QTimer(self)
        self._screen_monitor_timer.timeout.connect(self._on_screen_monitor)
        self._active_screen = None  # 当前活跃窗口（截图/涂鸦）所在的屏幕
    
    def register_hotkeys(self):
        """注册全局快捷键"""
        if self._hotkeys_registered:
            return
        try:
            hwnd = int(self.winId())
            if hwnd == 0:
                logging.warning("窗口句柄无效，无法注册全局快捷键")
                return
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            flags = MOD_ALT | MOD_NOREPEAT
            hotkeys = [
                (HK_SCREENSHOT, VK_1, "ALT+1"),
                (HK_PASTE, VK_2, "ALT+2"),
                (HK_CANCEL_SCREENSHOT, VK_3, "ALT+3"),
                (HK_DOODLE, VK_Q, "ALT+Q"),
                (HK_DOODLE_END, VK_W, "ALT+W"),
                (HK_DOODLE_UNDO, VK_A, "ALT+A"),
                (HK_DOODLE_REDO, VK_S, "ALT+S"),
            ]
            failed = []
            for hk_id, vk, name in hotkeys:
                if not user32.RegisterHotKey(hwnd, hk_id, flags, vk):
                    err = kernel32.GetLastError()
                    failed.append(f"{name}(错误码{err})")
                else:
                    logging.info(f"全局快捷键 {name} 注册成功")
            if failed:
                logging.warning(f"全局快捷键注册失败: {', '.join(failed)}")
            else:
                logging.info("全部全局快捷键注册成功")
            self._hotkeys_registered = True
        except Exception as e:
            logging.warning(f"注册全局快捷键异常: {e}")
    
    def unregister_hotkeys(self):
        """注销全局快捷键"""
        if not self._hotkeys_registered:
            return
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            for hk_id in [HK_SCREENSHOT, HK_PASTE, HK_CANCEL_SCREENSHOT, HK_DOODLE, HK_DOODLE_END, HK_DOODLE_UNDO, HK_DOODLE_REDO]:
                user32.UnregisterHotKey(hwnd, hk_id)
            self._hotkeys_registered = False
        except Exception:
            pass
    
    def nativeEvent(self, eventType, message):
        """处理 Windows 原生事件，捕获全局快捷键"""
        if eventType == b"windows_generic_MSG":
            class MSG(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND),
                    ("message", wintypes.UINT),
                    ("wParam", wintypes.WPARAM),
                    ("lParam", wintypes.LPARAM),
                    ("time", wintypes.DWORD),
                    ("pt_x", wintypes.LONG),
                    ("pt_y", wintypes.LONG),
                ]
            msg = ctypes.cast(ctypes.c_void_p(int(message)), ctypes.POINTER(MSG))
            if msg.contents.message == WM_HOTKEY:
                hotkey_id = msg.contents.wParam
                logging.info(f"收到全局快捷键事件: id={hotkey_id}")
                QTimer.singleShot(0, lambda hid=hotkey_id: self._on_hotkey(hid))
                return True, 0
        return False, 0
    
    def _on_hotkey(self, hotkey_id):
        """处理全局快捷键事件"""
        logging.info(f"处理全局快捷键: id={hotkey_id}")
        if hotkey_id == HK_SCREENSHOT:
            self._hotkey_screenshot()
        elif hotkey_id == HK_PASTE:
            self._hotkey_paste()
        elif hotkey_id == HK_CANCEL_SCREENSHOT:
            self._hotkey_cancel_screenshot()
        elif hotkey_id == HK_DOODLE:
            self._hotkey_doodle()
        elif hotkey_id == HK_DOODLE_END:
            self._hotkey_doodle_end()
        elif hotkey_id == HK_DOODLE_UNDO:
            self._hotkey_doodle_undo()
        elif hotkey_id == HK_DOODLE_REDO:
            self._hotkey_doodle_redo()
    
    def _on_screen_monitor(self):
        """全局屏幕监控：鼠标移到新屏幕→关旧窗口→开新流程"""
        global _active_screenshot_window, _active_doodle_window
        
        mouse_screen = QApplication.screenAt(QCursor.pos())
        if not mouse_screen or mouse_screen == self._active_screen:
            return
        
        # 截图窗口：仅在未开始选区时切换
        if _active_screenshot_window and _active_screenshot_window.isVisible():
            if _active_screenshot_window.start_pos is not None:
                return
            _active_screenshot_window.on_cancel()  # 取消旧截图，触发 loop.quit()
            self._active_screen = mouse_screen
            QTimer.singleShot(0, self._hotkey_screenshot)  # 下一事件循环开新截图
            return
        
        # 涂鸦窗口：仅在未开始绘制时切换
        if _active_doodle_window and _active_doodle_window.isVisible():
            if _active_doodle_window.drawing:
                return
            doodle_win = _active_doodle_window  # 保存引用，避免 emit 后全局变量被清空
            doodle_win.doodle_finished.emit(doodle_win.canvas)
            doodle_win.close()
            self._active_screen = mouse_screen
            QTimer.singleShot(0, self._hotkey_doodle)  # 下一事件循环开新涂鸦
            return
        
        # 无活跃窗口，停止监控
        self._screen_monitor_timer.stop()
    
    def _hotkey_screenshot(self):
        """ALT+1: 截图"""
        self._active_screen = QApplication.screenAt(QCursor.pos())
        self._screen_monitor_timer.start(150)
        capture_screenshot()
        self._screen_monitor_timer.stop()
    
    def _hotkey_paste(self):
        """ALT+2: 从剪贴板获取图片"""
        clipboard = QApplication.clipboard()
        pixmap = clipboard.pixmap()
        if pixmap and not pixmap.isNull():
            self._last_captured = pixmap
    
    def _hotkey_cancel_screenshot(self):
        """ALT+3: 取消/退出截图，并关闭所有钉图窗口"""
        global _active_screenshot_window, _standalone_pinned_windows
        if _active_screenshot_window and _active_screenshot_window.isVisible():
            _active_screenshot_window.close()
            _active_screenshot_window = None
        for w in _standalone_pinned_windows:
            if w is not None and w.isVisible():
                w.close()
        _standalone_pinned_windows.clear()
    
    def _hotkey_doodle(self):
        """ALT+Q: 开始涂鸦"""
        global _active_doodle_window
        # 已经有涂鸦窗口在运行，忽略重复触发
        if _active_doodle_window and _active_doodle_window.isVisible():
            return
        self._active_screen = QApplication.screenAt(QCursor.pos())
        self._screen_monitor_timer.start(150)
        combined = _capture_current_screen()
        start_doodle(combined)
        self._screen_monitor_timer.stop()
    
    def _hotkey_doodle_end(self):
        """ALT+W: 结束涂鸦"""
        global _active_doodle_window
        if _active_doodle_window and _active_doodle_window.isVisible():
            _active_doodle_window.close()
    
    def _hotkey_doodle_undo(self):
        """ALT+A: 涂鸦撤销"""
        global _active_doodle_window, _active_screenshot_window
        if _active_doodle_window and _active_doodle_window.isVisible():
            _active_doodle_window.undo()
            return
        if _active_screenshot_window and _active_screenshot_window.isVisible() and _active_screenshot_window.is_screenshot_doodle:
            _active_screenshot_window.undo()
    
    def _hotkey_doodle_redo(self):
        """ALT+S: 涂鸦重做"""
        global _active_doodle_window, _active_screenshot_window
        if _active_doodle_window and _active_doodle_window.isVisible():
            _active_doodle_window.redo()
            return
        if _active_screenshot_window and _active_screenshot_window.isVisible() and _active_screenshot_window.is_screenshot_doodle:
            _active_screenshot_window.redo()
    
    def closeEvent(self, event):
        self.unregister_hotkeys()
        event.accept()


class PinnedWindow(QWidget):
    def __init__(self, pixmap, pos=None):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        
        self.original_pixmap = pixmap
        self.pixmap = pixmap
        self.drag_offset = None
        
        # 使用 pixmap 原始尺寸，不做 DPI 缩放，避免跨屏 setGeometry 冲突
        #self.resize(pixmap.width(), pixmap.height())
        dpr = pixmap.devicePixelRatio()
        self.resize(int(pixmap.width() / dpr), int(pixmap.height() / dpr))
        
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        
        if pos is not None:
            self.move(pos)
        else:
            screen_geo = QApplication.primaryScreen().geometry()
            x = (screen_geo.width() - pixmap.width()) // 2
            y = (screen_geo.height() - pixmap.height()) // 2
            self.move(x, y)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        painter.drawPixmap(self.rect(), self.original_pixmap)
        
        red = QColor(255, 0, 0)
        for i in range(3):
            glow_color = QColor(255, 0, 0, 80 - i * 20)
            pen = QPen(glow_color, (3 - i) * 2 + 2)
            painter.setPen(pen)
            painter.drawRect(QRect(i, i, self.width() - i * 2 - 1, self.height() - i * 2 - 1))
        
        pen = QPen(red, 2)
        painter.setPen(pen)
        painter.drawRect(QRect(2, 2, self.width() - 5, self.height() - 5))
        
        painter.end()
    
    def show_context_menu(self, pos):
        menu = QMenu(self)
        close_action = menu.addAction('关闭')
        close_action.triggered.connect(self.close)
        menu.exec_(self.mapToGlobal(pos))
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_offset = event.pos()
    
    def mouseMoveEvent(self, event):
        if self.drag_offset is not None:
            new_pos = event.globalPos() - self.drag_offset
            # 限制在当前鼠标所在屏幕内
            screen = QApplication.screenAt(event.globalPos())
            if screen:
                geo = screen.geometry()
                x = max(geo.x(), min(new_pos.x(), geo.x() + geo.width() - self.width()))
                y = max(geo.y(), min(new_pos.y(), geo.y() + geo.height() - self.height()))
                self.move(x, y)
            else:
                self.move(new_pos)
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_offset = None
    
    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            factor = 1.1
        else:
            factor = 0.9
        new_w = int(self.width() * factor)
        new_h = int(self.height() * factor)
        # 限制最小/最大尺寸，基于原始图片尺寸
        orig_w = self.original_pixmap.width()
        orig_h = self.original_pixmap.height()
        min_w = max(10, int(orig_w * 0.05))
        min_h = max(10, int(orig_h * 0.05))
        max_w = max(min_w + 1, int(orig_w * 5.0))
        max_h = max(min_h + 1, int(orig_h * 5.0))
        new_w = max(min_w, min(new_w, max_w))
        new_h = max(min_h, min(new_h, max_h))
        self.resize(new_w, new_h)


class RecordingBorder(QWidget):
    """录制区域红色边框指示窗口（透明背景+红色边框+四角手柄）"""
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, event):
        painter = QPainter(self)
        # 红色边框
        painter.setPen(QPen(QColor(255, 0, 0), 2))
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)
        # 四角手柄
        r = 8
        painter.setBrush(QColor(255, 0, 0))
        for pt in [QPoint(0, 0), QPoint(self.width() - 1, 0),
                    QPoint(0, self.height() - 1), QPoint(self.width() - 1, self.height() - 1)]:
            painter.drawEllipse(pt, r, r)


class ScreenshotWindow(QWidget):
    screenshot_taken = pyqtSignal(QPixmap)
    screenshot_canceled = pyqtSignal()
    screenshot_pinned = pyqtSignal(QPixmap, QPoint)
    
    def __init__(self, screenshot):
        super().__init__()
        self.screenshot = screenshot
        self.start_pos = None
        self.end_pos = None
        self.cropped_pixmap = None
        self.is_text_editing = False
        self.text_input = None
        self.text_input_pos = None
        self.cropped_pixmap_original = None
        self.is_screenshot_doodle = False
        self.doodle_last_pos = None
        self.doodle_window = None
        self.is_dragging = False
        self.drag_offset = None
        self.history = []
        self.future = []
        self.max_history = 50
        self.edit_layer = None
        self.text_font = QFont('Microsoft YaHei')
        self.text_font.setPixelSize(20)
        self.text_font.setBold(True)
        self.text_color = QColor(Qt.red)
        self.text_size = 20
        self._style_btn_active = False
        self._finalizing = False
        self.is_resizing = False
        self.resize_corner = None
        self.resize_opposite = None
        
        # 录像相关状态
        self.is_recording_mode = False
        self.is_recording = False
        self.is_recording_paused = False
        self.record_video_enabled = True
        self.record_mic_enabled = True
        self.record_speaker_enabled = True
        self.recording_frames = []  # BGR numpy 数组列表
        self.recording_timer = None
        self.recording_start_time = None
        self.audio_thread = None
        self.audio_frames = []
        self.py_audio = None
        self._recording_float = None  # 录制时浮动控制窗口
        self._recording_border = None  # 录制区域红色边框窗口
        self._recording_indicator_timer = None  # 指示灯动画定时器
        self._recording_indicator_bright = False  # 指示灯亮/暗状态
        
        self.setMouseTracking(True)
        self.initUI()
    
    def initUI(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setStyleSheet("background-color: transparent;")
        #self.setStyleSheet("background-color: rgba(0, 0, 0, 0.3);")
        
        # 设置红色十字光标
        crosshair_pixmap = QPixmap(32, 32)
        crosshair_pixmap.fill(Qt.transparent)
        ch_painter = QPainter(crosshair_pixmap)
        ch_painter.setPen(QPen(QColor(255, 0, 0), 2))
        ch_painter.drawLine(16, 0, 16, 32)
        ch_painter.drawLine(0, 16, 32, 16)
        ch_painter.end()
        self.crosshair_cursor = QCursor(crosshair_pixmap, 16, 16)
        self.setCursor(self.crosshair_cursor)

        
        self.cancel_btn = QPushButton('取消', self)
        self.cancel_btn.setStyleSheet("background-color: gray; color: white; border: none; padding: 8px 16px; font-size: 14px;")
        self.cancel_btn.clicked.connect(self.on_cancel)
        self.cancel_btn.setCursor(Qt.ArrowCursor)
        self.cancel_btn.move(10, 10)
        self.cancel_btn.show()
        
        self.copy_btn = QPushButton('复制', self)
        self.copy_btn.setStyleSheet("background-color: blue; color: white; border: none; padding: 8px 16px; font-size: 14px;")
        self.copy_btn.clicked.connect(self.on_copy)
        self.copy_btn.hide()
        
        self.add_btn = QPushButton('给小华', self)
        self.add_btn.setStyleSheet("background-color: green; color: white; border: none; padding: 8px 16px; font-size: 14px;")
        self.add_btn.clicked.connect(self.on_add)
        self.add_btn.hide()
        
        self.text_edit_btn = QPushButton('文本', self)
        self.text_edit_btn.setStyleSheet("background-color: #4169E1; color: white; border: none; padding: 8px 16px; font-size: 14px;")
        self.text_edit_btn.clicked.connect(self.on_edit_text)
        self.text_edit_btn.hide()
        
        self.doodle_btn = QPushButton('涂鸦', self)
        self.doodle_btn.setStyleSheet("background-color: purple; color: white; border: none; padding: 8px 16px; font-size: 14px;")
        self.doodle_btn.clicked.connect(self.on_doodle)
        self.doodle_btn.hide()
        
        # 截图内涂鸦颜色下拉框
        self._doodle_colors = [
            ('大红', '#FF0000'), ('赤', '#E60000'), ('橙', '#FF7F00'), ('黄', '#FFFF00'),
            ('绿', '#00FF00'), ('青', '#00FFFF'), ('蓝', '#0000FF'), ('紫', '#8B00FF'),
            ('黑', '#000000'), ('白', '#FFFFFF'), ('粉红', '#FFC0CB'), ('砖红', '#B22222'),
            ('酒红', '#8B0000'), ('浅绿', '#90EE90'), ('浅蓝', '#ADD8E6'),
        ]
        self.doodle_color_combo = QComboBox(self)
        self.doodle_color_combo.setStyleSheet(
            "QComboBox { background-color: #333; color: white; border: 1px solid #555; "
            "padding: 4px 8px; font-size: 12px; min-width: 70px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background-color: #333; color: white; selection-background-color: #555; }"
        )
        for name, hex_color in self._doodle_colors:
            pixmap = QPixmap(16, 16)
            pixmap.fill(QColor(hex_color))
            self.doodle_color_combo.addItem(QIcon(pixmap), name)
        self.doodle_color_combo.setCurrentIndex(0)
        self.doodle_color_combo.currentIndexChanged.connect(self._on_doodle_color_changed)
        self.doodle_color_combo.hide()
        
        # 截图内涂鸦线条粗细下拉框
        self.doodle_width_combo = QComboBox(self)
        self.doodle_width_combo.setStyleSheet(
            "QComboBox { background-color: #333; color: white; border: 1px solid #555; "
            "padding: 4px 8px; font-size: 12px; min-width: 55px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background-color: #333; color: white; selection-background-color: #555; }"
        )
        self.doodle_width_combo.addItems([str(i) for i in range(1, 21)])
        self.doodle_width_combo.setCurrentIndex(4)  # 默认 5
        self.doodle_width_combo.currentIndexChanged.connect(self._on_doodle_width_changed)
        self.doodle_width_combo.hide()
        
        self._doodle_pen_color = QColor('#FF0000')
        self._doodle_pen_width = 5
        
        self.save_btn = QPushButton('保存', self)
        self.save_btn.setStyleSheet("background-color: orange; color: white; border: none; padding: 8px 16px; font-size: 14px;")
        self.save_btn.clicked.connect(self.on_save)
        self.save_btn.hide()
        
        self.undo_btn = QPushButton('后退', self)
        self.undo_btn.setStyleSheet("background-color: #555555; color: white; border: none; padding: 8px 16px; font-size: 14px;")
        self.undo_btn.clicked.connect(self.undo)
        self.undo_btn.hide()
        
        self.redo_btn = QPushButton('前进', self)
        self.redo_btn.setStyleSheet("background-color: #555555; color: white; border: none; padding: 8px 16px; font-size: 14px;")
        self.redo_btn.clicked.connect(self.redo)
        self.redo_btn.hide()
        
        self.pin_btn = QPushButton('钉图', self)
        self.pin_btn.setStyleSheet("background-color: #8B008B; color: white; border: none; padding: 8px 16px; font-size: 14px;")
        self.pin_btn.clicked.connect(self.on_pin)
        self.pin_btn.hide()
        
        # 录像按钮（紫色，钉图后面）
        self.record_btn = QPushButton('录像', self)
        self.record_btn.setStyleSheet("background-color: #8B008B; color: white; border: none; padding: 8px 16px; font-size: 14px;")
        self.record_btn.clicked.connect(self.on_record)
        self.record_btn.hide()
        
        self.end_edit_btn = QPushButton('结束编辑', self)
        self.end_edit_btn.setStyleSheet("background-color: #4169E1; color: white; border: none; padding: 8px 16px; font-size: 14px;")
        self.end_edit_btn.clicked.connect(self.on_end_edit)
        self.end_edit_btn.hide()
        
        self.font_btn = QFontComboBox(self)
        self.font_btn.setStyleSheet("background-color: #2E8B57; color: white; border: none; padding: 4px 8px; font-size: 12px;")
        self.font_btn.currentFontChanged.connect(self.on_font_changed)
        self.font_btn.activated.connect(self._on_style_btn_pressed)
        self.font_btn.hide()
        
        # 预设颜色列表: (名称, 颜色值)
        self._preset_colors = [
            ('赤', '#FF0000'), ('橙', '#FF7F00'), ('黄', '#FFFF00'),
            ('绿', '#00FF00'), ('青', '#00FFFF'), ('蓝', '#0000FF'),
            ('紫', '#8B00FF'), ('粉', '#FFC0CB'), ('黑', '#000000'),
            ('白', '#FFFFFF'), ('酒红', '#8B0000'), ('砖红', '#B22222'),
        ]
        
        self.color_btn = QComboBox(self)
        self.color_btn.setStyleSheet("background-color: #CD853F; color: white; border: none; padding: 4px 8px; font-size: 12px;")
        for name, hex_color in self._preset_colors:
            pixmap = QPixmap(16, 16)
            pixmap.fill(QColor(hex_color))
            self.color_btn.addItem(QIcon(pixmap), name)
        self.color_btn.activated.connect(self._on_style_btn_pressed)
        self.color_btn.currentTextChanged.connect(self.on_color_changed)
        self.color_btn.hide()
        
        self.size_btn = QComboBox(self)
        self.size_btn.setStyleSheet("background-color: #8B4513; color: white; border: none; padding: 4px 8px; font-size: 12px;")
        self.size_btn.addItems(['8', '10', '12', '14', '16', '18', '20', '24', '28', '32', '36', '48', '64', '72'])
        self.size_btn.setCurrentText('20')
        self.size_btn.currentTextChanged.connect(self.on_size_changed)
        self.size_btn.activated.connect(self._on_style_btn_pressed)
        self.size_btn.hide()
        
        self.text_input = QLineEdit(self)
        self.text_input.setStyleSheet("background: transparent; border: 2px solid #4169E1; color: red; font-size: 20px; font-weight: bold; font-family: Microsoft YaHei;")
        self.text_input.setFixedSize(300, 40)
        self.text_input.hide()
        self.text_input.returnPressed.connect(self.on_text_input_finished)
        self.text_input.installEventFilter(self)
        self.text_input.textChanged.connect(self.on_text_input_changed)
        
        # ===== 录像模式按钮（8个，初始隐藏）=====
        rec_btn_style = "border: none; padding: 8px 16px; font-size: 14px; color: white;"
        
        # ①取消按钮（浅蓝色）
        self.rec_cancel_btn = QPushButton('取消', self)
        self.rec_cancel_btn.setStyleSheet(rec_btn_style + "background-color: #4682B4;")
        self.rec_cancel_btn.clicked.connect(self.on_recording_cancel)
        self.rec_cancel_btn.hide()

        # 关闭按钮（银色）
        self.rec_close_btn = QPushButton('关闭', self)
        self.rec_close_btn.setStyleSheet(rec_btn_style + "background-color: #C0C0C0; color: #333;")
        self.rec_close_btn.clicked.connect(self.close)
        self.rec_close_btn.hide()
        
        # ②保存按钮（橙色）
        self.rec_save_btn = QPushButton('保存', self)
        self.rec_save_btn.setStyleSheet(rec_btn_style + "background-color: #CD7F32;")
        self.rec_save_btn.clicked.connect(self.on_recording_save)
        self.rec_save_btn.hide()
        
        # ③结束按钮（默认灰色）
        self.rec_stop_btn = QPushButton('结束', self)
        self.rec_stop_btn.setStyleSheet(rec_btn_style + "background-color: #555555;")
        self.rec_stop_btn.clicked.connect(self.on_recording_stop)
        self.rec_stop_btn.hide()
        
        # ④开始/暂停按钮（默认浅黄色，文本"开始"）
        self.rec_start_pause_btn = QPushButton('开始', self)
        self.rec_start_pause_btn.setStyleSheet(rec_btn_style + "background-color: #DAA520;")
        self.rec_start_pause_btn.clicked.connect(self.on_recording_start_pause)
        self.rec_start_pause_btn.hide()

        # 录制指示灯按钮（默认灰色+黑色圆点）
        self.rec_indicator_btn = QPushButton('●', self)
        self.rec_indicator_btn.setFixedWidth(36)
        self.rec_indicator_btn.setStyleSheet(
            "border: none; padding: 4px; font-size: 18px; color: #333; background-color: #555555;")
        self.rec_indicator_btn.hide()
        
        # ⑤视频按钮（绿色，默认开启）
        self.rec_video_btn = QPushButton('视频', self)
        self.rec_video_btn.setStyleSheet(rec_btn_style + "background-color: #228B22;")
        self.rec_video_btn.clicked.connect(self.on_toggle_video)
        self.rec_video_btn.hide()
        
        # ⑥话筒按钮（蓝色，默认开启）
        self.rec_mic_btn = QPushButton('话筒', self)
        self.rec_mic_btn.setStyleSheet(rec_btn_style + "background-color: #4169E1;")
        self.rec_mic_btn.clicked.connect(self.on_toggle_mic)
        self.rec_mic_btn.hide()
        
        # ⑦喇叭按钮（浅红色，默认开启）
        self.rec_speaker_btn = QPushButton('喇叭', self)
        self.rec_speaker_btn.setStyleSheet(rec_btn_style + "background-color: #CD5C5C;")
        self.rec_speaker_btn.clicked.connect(self.on_toggle_speaker)
        self.rec_speaker_btn.hide()
        
        self.shortcut_paste = QShortcut(QKeySequence('Alt+2'), self)
        self.shortcut_paste.activated.connect(self.on_add)
    
    def show_preview(self, cropped_pixmap, reset_edit_layer=True):
        self.cropped_pixmap = cropped_pixmap
        if reset_edit_layer:
            edit_img = QImage(cropped_pixmap.width(), cropped_pixmap.height(), QImage.Format_ARGB32)
            edit_img.fill(Qt.transparent)
            self.edit_layer = QPixmap.fromImage(edit_img)
            if cropped_pixmap.devicePixelRatio() > 1.0:
                self.edit_layer.setDevicePixelRatio(cropped_pixmap.devicePixelRatio())
        
        select_rect = self.get_rect()
        btn_y = select_rect.bottom() + 10
        btn_width = 80
        btn_height = 36
        spacing = 5
        
        row1_count = 7
        total_width = btn_width * row1_count + spacing * (row1_count - 1)
        start_x = select_rect.center().x() - total_width // 2
        
        if btn_y + btn_height * 2 + spacing > self.height():
            btn_y = select_rect.top() - btn_height * 2 - spacing - 10
        
        self.cancel_btn.setGeometry(start_x, btn_y, btn_width, btn_height)
        self.copy_btn.setGeometry(start_x + (btn_width + spacing), btn_y, btn_width, btn_height)
        self.text_edit_btn.setGeometry(start_x + (btn_width + spacing) * 2, btn_y, btn_width, btn_height)
        self.doodle_btn.setGeometry(start_x + (btn_width + spacing) * 3, btn_y, btn_width, btn_height)
        self.save_btn.setGeometry(start_x + (btn_width + spacing) * 4, btn_y, btn_width, btn_height)
        self.add_btn.setGeometry(start_x + (btn_width + spacing) * 5, btn_y, btn_width, btn_height)
        self.undo_btn.setGeometry(start_x + (btn_width + spacing) * 6, btn_y, btn_width, btn_height)
        
        row2_y = btn_y + btn_height + spacing
        self.redo_btn.setGeometry(start_x, row2_y, btn_width * 2 + spacing, btn_height)
        redo_width = btn_width * 2 + spacing
        self.pin_btn.setGeometry(start_x + redo_width + spacing, row2_y, btn_width, btn_height)
        self.record_btn.setGeometry(start_x + redo_width + spacing + btn_width + spacing, row2_y, btn_width, btn_height)
        
        self.cancel_btn.show()
        self.copy_btn.show()
        self.text_edit_btn.show()
        self.doodle_btn.show()
        self.save_btn.show()
        self.add_btn.show()
        self.undo_btn.show()
        self.redo_btn.show()
        self.pin_btn.show()
        self.record_btn.show()
        
        self._update_undo_redo_buttons()
        self.update()
    
    def hide_buttons(self):
        self.cancel_btn.hide()
        self.copy_btn.hide()
        self.text_edit_btn.hide()
        self.doodle_btn.hide()
        self.save_btn.hide()
        self.add_btn.hide()
        self.undo_btn.hide()
        self.redo_btn.hide()
        self.pin_btn.hide()
        self.record_btn.hide()
        self.end_edit_btn.hide()
        self.doodle_color_combo.hide()
        self.doodle_width_combo.hide()
        self.rec_cancel_btn.hide()
        self.rec_save_btn.hide()
        self.rec_stop_btn.hide()
        self.rec_start_pause_btn.hide()
        self.rec_video_btn.hide()
        self.rec_mic_btn.hide()
        self.rec_speaker_btn.hide()
    
    def show_buttons(self):
        self.cancel_btn.show()
        self.copy_btn.show()
        self.text_edit_btn.show()
        self.doodle_btn.show()
        self.doodle_btn.setText('涂鸦')
        self.save_btn.show()
        self.add_btn.show()
        self.undo_btn.show()
        self.redo_btn.show()
        self.pin_btn.show()
        self.record_btn.show()
        self.end_edit_btn.hide()
        self.doodle_color_combo.hide()
        self.doodle_width_combo.hide()
    
    def on_cancel(self):
        self.screenshot_canceled.emit()
        self.close()
    
    def on_copy(self):
        clipboard = QApplication.clipboard()
        clipboard.setPixmap(self.cropped_pixmap)
        self.screenshot_taken.emit(self.cropped_pixmap)
        self.close()
    
    def on_add(self):
        self.screenshot_taken.emit(self.cropped_pixmap)
        self.close()
    
    def on_save(self):
        file_path, _ = QFileDialog.getSaveFileName(self, '保存图片', '', 'PNG (*.png);;JPEG (*.jpg);;BMP (*.bmp)')
        if file_path:
            self.cropped_pixmap.save(file_path)
    
    def on_pin(self):
        if self.cropped_pixmap:
            select_rect = self.get_rect()
            pos = self.mapToGlobal(QPoint(select_rect.x(), select_rect.y()))
            self.screenshot_pinned.emit(self.cropped_pixmap.copy(), pos)
            self.close()
    
    # ===== 录像功能 =====
    def on_record(self):
        """进入录像模式：隐藏普通按钮，显示录像按钮"""
        self.is_recording_mode = True
        self.is_recording = False
        self.is_recording_paused = False
        self.recording_frames = []
        self.audio_frames = []
        # 隐藏普通按钮
        self.cancel_btn.hide()
        self.copy_btn.hide()
        self.text_edit_btn.hide()
        self.doodle_btn.hide()
        self.save_btn.hide()
        self.add_btn.hide()
        self.undo_btn.hide()
        self.redo_btn.hide()
        self.pin_btn.hide()
        self.record_btn.hide()
        self.end_edit_btn.hide()
        self.doodle_color_combo.hide()
        self.doodle_width_combo.hide()
        # 显示录像按钮，布局为一行（取消 关闭 保存 结束 开始 指示灯 视频 话筒 喇叭）
        select_rect = self.get_rect()
        btn_y = select_rect.bottom() + 10
        btn_width = 80
        btn_height = 36
        spacing = 5
        row_count = 9
        total_width = btn_width * (row_count - 1) + 36 + spacing * (row_count - 1)  # 指示灯宽度 36
        start_x = select_rect.center().x() - total_width // 2
        if btn_y + btn_height + spacing > self.height():
            btn_y = select_rect.top() - btn_height - spacing - 10
        rec_btns = [
            self.rec_cancel_btn, self.rec_close_btn, self.rec_save_btn, self.rec_stop_btn,
            self.rec_start_pause_btn, self.rec_indicator_btn, self.rec_video_btn, self.rec_mic_btn,
            self.rec_speaker_btn
        ]
        x_pos = start_x
        for i, btn in enumerate(rec_btns):
            w = 36 if btn is self.rec_indicator_btn else btn_width
            btn.setGeometry(x_pos, btn_y, w, btn_height)
            x_pos += w + spacing
            btn.show()
        self._update_recording_button_states()
    
    def _hide_recording_buttons(self):
        """隐藏所有录像按钮"""
        for btn in [self.rec_cancel_btn, self.rec_close_btn, self.rec_save_btn, self.rec_stop_btn,
                     self.rec_start_pause_btn, self.rec_indicator_btn, self.rec_video_btn, self.rec_mic_btn,
                     self.rec_speaker_btn]:
            btn.hide()
    
    def _update_recording_button_states(self):
        """根据当前状态更新录像按钮样式"""
        # 结束按钮：录制中→淡绿色，否则→灰色
        if self.is_recording:
            self.rec_stop_btn.setStyleSheet(
                "border: none; padding: 8px 16px; font-size: 14px; color: white; background-color: #90EE90;")
        else:
            self.rec_stop_btn.setStyleSheet(
                "border: none; padding: 8px 16px; font-size: 14px; color: white; background-color: #555555;")
        
        # 开始/暂停按钮
        if self.is_recording and not self.is_recording_paused:
            self.rec_start_pause_btn.setText('暂停')
            self.rec_start_pause_btn.setStyleSheet(
                "border: none; padding: 8px 16px; font-size: 14px; color: white; background-color: #228B22;")
        elif self.is_recording and self.is_recording_paused:
            self.rec_start_pause_btn.setText('继续')
            self.rec_start_pause_btn.setStyleSheet(
                "border: none; padding: 8px 16px; font-size: 14px; color: white; background-color: #DAA520;")
        else:
            self.rec_start_pause_btn.setText('开始')
            self.rec_start_pause_btn.setStyleSheet(
                "border: none; padding: 8px 16px; font-size: 14px; color: white; background-color: #DAA520;")
        
        # 保存按钮：无内容且三个toggle全灰→灰色，否则橙色
        has_content = len(self.recording_frames) > 0
        all_off = (not self.record_video_enabled and not self.record_mic_enabled
                   and not self.record_speaker_enabled)
        if not has_content and all_off:
            self.rec_save_btn.setStyleSheet(
                "border: none; padding: 8px 16px; font-size: 14px; color: white; background-color: #555555;")
        else:
            self.rec_save_btn.setStyleSheet(
                "border: none; padding: 8px 16px; font-size: 14px; color: white; background-color: #CD7F32;")

        # 指示灯按钮：录制中→绿色背景+红点动画，否则→灰色+黑点
        if self.is_recording and not self.is_recording_paused:
            self._start_indicator_animation()
            self._update_indicator_dot()
        else:
            self._stop_indicator_animation()
            self.rec_indicator_btn.setStyleSheet(
                "border: none; padding: 4px; font-size: 18px; color: #333; background-color: #555555;")

    def _start_indicator_animation(self):
        """启动指示灯红点动画"""
        if self._recording_indicator_timer is None:
            self._recording_indicator_timer = QTimer(self)
            self._recording_indicator_timer.timeout.connect(self._toggle_indicator_dot)
        if not self._recording_indicator_timer.isActive():
            self._recording_indicator_bright = False
            self._recording_indicator_timer.start(500)

    def _stop_indicator_animation(self):
        """停止指示灯动画"""
        if self._recording_indicator_timer:
            self._recording_indicator_timer.stop()

    def _toggle_indicator_dot(self):
        """切换指示灯明暗"""
        self._recording_indicator_bright = not self._recording_indicator_bright
        self._update_indicator_dot()

    def _update_indicator_dot(self):
        """更新指示灯圆点颜色（同时更新 ScreenshotWindow 和浮动窗口）"""
        if self._recording_indicator_bright:
            color = '#FF0000'  # 亮红
        else:
            color = '#8B0000'  # 暗红
        style = f"border: none; padding: 4px; font-size: 18px; color: {color}; background-color: #228B22;"
        self.rec_indicator_btn.setStyleSheet(style)
        # 同步更新浮动窗口指示灯
        if self._recording_float and hasattr(self, '_rf_indicator'):
            self._rf_indicator.setStyleSheet(
                f"border: none; padding: 2px; font-size: 16px; color: {color}; background-color: #228B22; border-radius: 3px;")
    
    def on_recording_cancel(self):
        """取消录像，返回截图模式"""
        self._stop_all_recording()
        self.recording_frames = []
        self.audio_frames = []
        self.is_recording_mode = False
        self._hide_recording_buttons()
        self._hide_recording_float()
        self.show_buttons()
        self.show()
    
    def on_recording_save(self):
        """保存录像为 MP4 或 MP3"""
        has_content = len(self.recording_frames) > 0
        all_off = (not self.record_video_enabled and not self.record_mic_enabled
                   and not self.record_speaker_enabled)
        if not has_content and all_off:
            return  # 按钮应是灰色，不响应
        # 先停止录制
        if self.is_recording:
            self._stop_all_recording()
        self._update_recording_button_states()
        self._update_recording_float_states()
        
        if self.record_video_enabled and self.recording_frames:
            self._save_as_mp4()
        elif not self.record_video_enabled and self.audio_frames:
            self._save_as_wav()
    
    def on_recording_stop(self):
        """停止录制"""
        if not self.is_recording:
            return
        self._stop_all_recording()
        self._hide_recording_float()
        # 恢复截图窗口以显示录像模式按钮
        self.show()
        self._update_recording_button_states()
    
    def on_recording_start_pause(self):
        """开始/暂停录制"""
        if not self.is_recording:
            # 开始录制
            self.is_recording = True
            self.is_recording_paused = False
            self.recording_frames = []
            self.audio_frames = []
            self.recording_start_time = datetime.now()
            # 显示浮动控制窗口，隐藏截图窗口（避免遮挡桌面）
            self._show_recording_float()
            # 启动帧采集定时器
            if self.recording_timer is None:
                self.recording_timer = QTimer(self)
                self.recording_timer.timeout.connect(self._capture_frame)
            self.recording_timer.start(66)  # ~15fps
            # 启动音频采集
            self._start_audio_capture()
        elif self.is_recording_paused:
            # 恢复录制
            self.is_recording_paused = False
            if self.recording_timer:
                self.recording_timer.start(66)
            self._start_audio_capture()
            self._update_recording_float_states()
        else:
            # 暂停录制
            self.is_recording_paused = True
            if self.recording_timer:
                self.recording_timer.stop()
            self._stop_audio_capture()
            self._update_recording_float_states()
        self._update_recording_button_states()
    
    def on_toggle_video(self):
        """切换视频录制开关"""
        self.record_video_enabled = not self.record_video_enabled
        if self.record_video_enabled:
            self.rec_video_btn.setStyleSheet(
                "border: none; padding: 8px 16px; font-size: 14px; color: white; background-color: #228B22;")
        else:
            self.rec_video_btn.setStyleSheet(
                "border: none; padding: 8px 16px; font-size: 14px; color: white; background-color: #555555;")
        self._update_recording_button_states()
        self._update_recording_float_states()
    
    def on_toggle_mic(self):
        """切换话筒录制开关"""
        self.record_mic_enabled = not self.record_mic_enabled
        if self.record_mic_enabled:
            self.rec_mic_btn.setStyleSheet(
                "border: none; padding: 8px 16px; font-size: 14px; color: white; background-color: #4169E1;")
        else:
            self.rec_mic_btn.setStyleSheet(
                "border: none; padding: 8px 16px; font-size: 14px; color: white; background-color: #555555;")
        self._update_recording_button_states()
        self._update_recording_float_states()
        # 如果正在录制，立即应用
        if self.is_recording and not self.is_recording_paused:
            if self.record_mic_enabled:
                self._start_audio_capture()
            else:
                self._stop_audio_capture()
    
    def on_toggle_speaker(self):
        """切换喇叭录制开关"""
        self.record_speaker_enabled = not self.record_speaker_enabled
        if self.record_speaker_enabled:
            self.rec_speaker_btn.setStyleSheet(
                "border: none; padding: 8px 16px; font-size: 14px; color: white; background-color: #CD5C5C;")
        else:
            self.rec_speaker_btn.setStyleSheet(
                "border: none; padding: 8px 16px; font-size: 14px; color: white; background-color: #555555;")
        self._update_recording_button_states()
        self._update_recording_float_states()

    # ===== 浮动录制控制窗口 =====
    def _ensure_recording_float(self):
        """懒加载创建浮动录制控制窗口"""
        if self._recording_float is not None:
            return
        self._recording_float = QWidget()
        self._recording_float.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self._recording_float.setStyleSheet("background-color: rgba(45,45,45,230); border-radius: 6px;")
        layout = QHBoxLayout(self._recording_float)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        style = "border: none; padding: 6px 14px; font-size: 13px; color: white; border-radius: 3px;"
        btn_specs = [
            ('cancel', '取消', '#4682B4', self.on_recording_cancel),
            ('close', '关闭', '#C0C0C0', self.close),
            ('save', '保存', '#CD7F32', self.on_recording_save),
            ('stop', '结束', '#555555', self.on_recording_stop),
            ('start', '开始', '#DAA520', self.on_recording_start_pause),
            ('video', '视频', '#228B22', self.on_toggle_video),
            ('mic', '话筒', '#4169E1', self.on_toggle_mic),
            ('speaker', '喇叭', '#CD5C5C', self.on_toggle_speaker),
        ]
        self._rf_buttons = {}
        for name, text, color, handler in btn_specs:
            btn = QPushButton(text)
            if name == 'close':
                btn.setStyleSheet(style + f"background-color: {color}; color: #333;")
            else:
                btn.setStyleSheet(style + f"background-color: {color};")
            btn.clicked.connect(handler)
            layout.addWidget(btn)
            self._rf_buttons[name] = btn

        # 指示灯（开始与视频之间）
        self._rf_indicator = QPushButton('●')
        self._rf_indicator.setFixedWidth(30)
        self._rf_indicator.setStyleSheet(
            "border: none; padding: 2px; font-size: 16px; color: #333; background-color: #555555; border-radius: 3px;")
        layout.insertWidget(5, self._rf_indicator)  # 插入到开始(4)和视频(5)之间

    def _show_recording_float(self):
        """显示浮动录制控制窗口，隐藏截图窗口，显示红色边框"""
        self._ensure_recording_float()
        select_rect = self.get_rect()
        top_left = self.mapToGlobal(QPoint(select_rect.x(), select_rect.y()))
        # 浮动控制窗口
        self._recording_float.adjustSize()
        fw = self._recording_float.width()
        btn_x = top_left.x() + (select_rect.width() - fw) // 2
        btn_y = top_left.y() + select_rect.height() + 5
        self._recording_float.move(btn_x, btn_y)
        self._recording_float.show()
        # 红色边框窗口
        if self._recording_border is None:
            self._recording_border = RecordingBorder()
        self._recording_border.setGeometry(
            top_left.x(), top_left.y(), select_rect.width(), select_rect.height())
        self._recording_border.show()
        self.hide()
        self._update_recording_float_states()

    def _hide_recording_float(self):
        """隐藏浮动控制窗口和红色边框，恢复截图窗口"""
        if self._recording_float:
            self._recording_float.hide()
        if self._recording_border:
            self._recording_border.hide()
        self.show()
        self._update_recording_button_states()

    def _update_recording_float_states(self):
        """更新浮动窗口按钮状态"""
        if not self._recording_float or not hasattr(self, '_rf_buttons'):
            return
        style = "border: none; padding: 6px 14px; font-size: 13px; color: white; border-radius: 3px;"
        # 结束按钮
        color = '#90EE90' if self.is_recording else '#555555'
        self._rf_buttons['stop'].setStyleSheet(style + f"background-color: {color};")
        # 开始/暂停按钮
        if self.is_recording and not self.is_recording_paused:
            self._rf_buttons['start'].setText('暂停')
            self._rf_buttons['start'].setStyleSheet(style + "background-color: #228B22;")
        elif self.is_recording and self.is_recording_paused:
            self._rf_buttons['start'].setText('继续')
            self._rf_buttons['start'].setStyleSheet(style + "background-color: #DAA520;")
        else:
            self._rf_buttons['start'].setText('开始')
            self._rf_buttons['start'].setStyleSheet(style + "background-color: #DAA520;")
        # 视频按钮
        vc = '#228B22' if self.record_video_enabled else '#555555'
        self._rf_buttons['video'].setStyleSheet(style + f"background-color: {vc};")
        # 话筒按钮
        mc = '#4169E1' if self.record_mic_enabled else '#555555'
        self._rf_buttons['mic'].setStyleSheet(style + f"background-color: {mc};")
        # 喇叭按钮
        sc = '#CD5C5C' if self.record_speaker_enabled else '#555555'
        self._rf_buttons['speaker'].setStyleSheet(style + f"background-color: {sc};")
        # 保存按钮：无内容且三开关全灰→灰色
        has_content = len(self.recording_frames) > 0 or len(self.audio_frames) > 0
        all_off = not self.record_video_enabled and not self.record_mic_enabled and not self.record_speaker_enabled
        scolor = '#555555' if (not has_content and all_off) else '#CD7F32'
        self._rf_buttons['save'].setStyleSheet(style + f"background-color: {scolor};")
        # 指示灯
        if self.is_recording and not self.is_recording_paused:
            dot_color = '#FF0000' if self._recording_indicator_bright else '#8B0000'
            self._rf_indicator.setStyleSheet(
                f"border: none; padding: 2px; font-size: 16px; color: {dot_color}; background-color: #228B22; border-radius: 3px;")
        else:
            self._rf_indicator.setStyleSheet(
                "border: none; padding: 2px; font-size: 16px; color: #333; background-color: #555555; border-radius: 3px;")

    def _capture_frame(self):
        """定时器回调：截取选区画面（使用 mss 直接捕获桌面，不受窗口遮挡影响）"""
        if not self.is_recording or self.is_recording_paused:
            return
        select_rect = self.get_rect()
        if select_rect.width() <= 0 or select_rect.height() <= 0:
            return
        try:
            import mss
            import numpy as np
            top_left = self.mapToGlobal(QPoint(select_rect.x(), select_rect.y()))
            with mss.MSS() as sct:
                monitor = {
                    'left': top_left.x(),
                    'top': top_left.y(),
                    'width': select_rect.width(),
                    'height': select_rect.height()
                }
                img = sct.grab(monitor)
                # mss 返回 BGRA，取 BGR 三通道
                arr = np.array(img)[:, :, :3]
                self._draw_cursor_on_frame(arr, select_rect, top_left)
                self.recording_frames.append(arr)
        except Exception:
            pass

    def _draw_cursor_on_frame(self, arr, select_rect, top_left):
        """在帧上绘制鼠标光标（使用 Windows API 获取真实光标图标）"""
        try:
            import ctypes
            import numpy as np
            from ctypes import wintypes, byref, sizeof, POINTER, cast

            # 获取光标信息
            class CURSORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("flags", wintypes.DWORD),
                    ("hCursor", wintypes.HANDLE),
                    ("ptScreenPos", wintypes.POINT),
                ]

            ci = CURSORINFO()
            ci.cbSize = sizeof(ci)
            if not ctypes.windll.user32.GetCursorInfo(byref(ci)):
                return
            if ci.flags & 1 == 0:  # CURSOR_SHOWING = 0x00000001
                return

            cx = ci.ptScreenPos.x
            cy = ci.ptScreenPos.y

            # 获取光标图标信息
            class ICONINFO(ctypes.Structure):
                _fields_ = [
                    ("fIcon", wintypes.BOOL),
                    ("xHotspot", wintypes.DWORD),
                    ("yHotspot", wintypes.DWORD),
                    ("hbmMask", wintypes.HANDLE),
                    ("hbmColor", wintypes.HANDLE),
                ]

            ii = ICONINFO()
            if not ctypes.windll.user32.GetIconInfo(ci.hCursor, byref(ii)):
                return

            hotspot_x = ii.xHotspot
            hotspot_y = ii.yHotspot

            # 计算光标在选区中的相对位置
            rel_x = cx - top_left.x() - hotspot_x
            rel_y = cy - top_left.y() - hotspot_y

            h, w = arr.shape[:2]

            if ii.hbmColor:
                # 彩色光标：获取 BITMAP 信息
                class BITMAP(ctypes.Structure):
                    _fields_ = [
                        ("bmType", wintypes.LONG),
                        ("bmWidth", wintypes.LONG),
                        ("bmHeight", wintypes.LONG),
                        ("bmWidthBytes", wintypes.LONG),
                        ("bmPlanes", wintypes.WORD),
                        ("bmBitsPixel", wintypes.WORD),
                        ("bmBits", wintypes.LPVOID),
                    ]

                bmp = BITMAP()
                ctypes.windll.gdi32.GetObjectW(ii.hbmColor, sizeof(bmp), byref(bmp))
                cw = bmp.bmWidth
                ch = bmp.bmHeight // 2  # 彩色+遮罩各占一半

                # 使用 DrawIconEx 绘制到内存 DC 获取光标像素
                hdc_screen = ctypes.windll.user32.GetDC(0)
                hdc_mem = ctypes.windll.gdi32.CreateCompatibleDC(hdc_screen)
                hbm = ctypes.windll.gdi32.CreateCompatibleBitmap(hdc_screen, cw, ch)
                old_bmp = ctypes.windll.gdi32.SelectObject(hdc_mem, hbm)

                # 填充黑色背景
                black_brush = ctypes.windll.gdi32.CreateSolidBrush(0)
                rect = wintypes.RECT(0, 0, cw, ch)
                ctypes.windll.user32.FillRect(hdc_mem, byref(rect), black_brush)
                ctypes.windll.gdi32.DeleteObject(black_brush)

                # 绘制光标图标
                ctypes.windll.user32.DrawIconEx(
                    hdc_mem, 0, 0, ci.hCursor, cw, ch, 0, 0, 3  # DI_NORMAL = 3
                )

                # 读取像素数据
                class BITMAPINFOHEADER(ctypes.Structure):
                    _fields_ = [
                        ("biSize", wintypes.DWORD),
                        ("biWidth", wintypes.LONG),
                        ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG),
                        ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD),
                    ]

                bi = BITMAPINFOHEADER()
                bi.biSize = sizeof(bi)
                bi.biWidth = cw
                bi.biHeight = -ch  # 负值表示自上而下
                bi.biPlanes = 1
                bi.biBitCount = 32
                bi.biCompression = 0  # BI_RGB

                buf_size = cw * ch * 4
                buf = (ctypes.c_ubyte * buf_size)()
                ctypes.windll.gdi32.GetDIBits(
                    hdc_mem, hbm, 0, ch, buf, ctypes.byref(bi), 0  # DIB_RGB_COLORS = 0
                )

                # 转换为 numpy 数组 BGRA
                cursor_arr = np.frombuffer(buf, dtype=np.uint8).reshape(ch, cw, 4)

                # 清理
                ctypes.windll.gdi32.SelectObject(hdc_mem, old_bmp)
                ctypes.windll.gdi32.DeleteObject(hbm)
                ctypes.windll.gdi32.DeleteDC(hdc_mem)
                ctypes.windll.user32.ReleaseDC(0, hdc_screen)

            else:
                # 单色光标（仅遮罩）：绘制简单指示器
                cw, ch = 32, 32

            # 计算绘制区域
            x1 = max(0, rel_x)
            y1 = max(0, rel_y)
            x2 = min(w, rel_x + cw)
            y2 = min(h, rel_y + ch)

            if x2 <= x1 or y2 <= y1:
                if ii.hbmColor:
                    ctypes.windll.gdi32.DeleteObject(ii.hbmColor)
                if ii.hbmMask:
                    ctypes.windll.gdi32.DeleteObject(ii.hbmMask)
                return

            if ii.hbmColor:
                # Alpha 混合光标到帧
                cx1 = x1 - rel_x
                cy1 = y1 - rel_y
                cx2 = cx1 + (x2 - x1)
                cy2 = cy1 + (y2 - y1)

                cursor_region = cursor_arr[cy1:cy2, cx1:cx2].astype(np.float32)
                alpha = cursor_region[:, :, 3:4] / 255.0
                frame_region = arr[y1:y2, x1:x2].astype(np.float32)
                blended = (cursor_region[:, :, :3] * alpha + frame_region * (1 - alpha)).astype(np.uint8)
                arr[y1:y2, x1:x2] = blended
            else:
                # 单色光标：画白色圆圈 + 黑色轮廓
                dot_x = cx - top_left.x()
                dot_y = cy - top_left.y()
                if 0 <= dot_x < w and 0 <= dot_y < h:
                    import cv2
                    cv2.circle(arr, (dot_x, dot_y), 10, (255, 255, 255), -1)
                    cv2.circle(arr, (dot_x, dot_y), 10, (0, 0, 0), 2)
                    cv2.line(arr, (dot_x, dot_y), (dot_x + 10, dot_y + 10), (0, 0, 0), 2)

            # 清理图标资源
            if ii.hbmColor:
                ctypes.windll.gdi32.DeleteObject(ii.hbmColor)
            if ii.hbmMask:
                ctypes.windll.gdi32.DeleteObject(ii.hbmMask)

        except Exception:
            pass
    
    def _start_audio_capture(self):
        """启动音频采集线程（分别采集话筒和扬声器）"""
        if not self.record_mic_enabled and not self.record_speaker_enabled:
            return
        if self.audio_thread and self.audio_thread.is_alive():
            return
        try:
            import pyaudio
            self.py_audio = pyaudio.PyAudio()
        except Exception:
            self.py_audio = None
            return

        self.audio_thread = threading.Thread(target=self._audio_capture_loop, daemon=True)
        self.audio_thread.start()

    def _find_audio_devices(self):
        """查找话筒和扬声器回环设备索引"""
        mic_idx = None
        speaker_idx = None
        if self.py_audio is None:
            return mic_idx, speaker_idx

        try:
            # 查找 WASAPI host API
            wasapi_host = None
            for i in range(self.py_audio.get_host_api_count()):
                info = self.py_audio.get_host_api_info_by_index(i)
                if 'wasapi' in info['name'].lower():
                    wasapi_host = i
                    break

            if wasapi_host is not None:
                for i in range(self.py_audio.get_device_count()):
                    dev = self.py_audio.get_device_info_by_index(i)
                    if dev['hostApi'] != wasapi_host:
                        continue
                    name = dev['name'].lower()
                    if dev['maxInputChannels'] > 0:
                        if 'loopback' in name:
                            speaker_idx = i
                        elif mic_idx is None:
                            mic_idx = i
            else:
                # 无 WASAPI：使用默认输入设备作为话筒
                mic_idx = self.py_audio.get_default_input_device_info()['index']
                if mic_idx < 0:
                    mic_idx = None
        except Exception:
            pass

        return mic_idx, speaker_idx

    def _audio_capture_loop(self):
        """音频采集循环（后台线程，分别采集话筒和扬声器）"""
        import pyaudio
        import numpy as np

        rate = 44100
        chunk = 1024
        fmt = pyaudio.paInt16
        channels = 1

        mic_stream = None
        speaker_stream = None

        try:
            mic_idx, speaker_idx = self._find_audio_devices()

            # 打开话筒流
            if self.record_mic_enabled and mic_idx is not None:
                try:
                    mic_stream = self.py_audio.open(
                        format=fmt, channels=channels, rate=rate,
                        input=True, input_device_index=mic_idx,
                        frames_per_buffer=chunk, stream_callback=None
                    )
                except Exception:
                    mic_stream = None

            # 打开扬声器回环流
            if self.record_speaker_enabled and speaker_idx is not None:
                try:
                    speaker_stream = self.py_audio.open(
                        format=fmt, channels=channels, rate=rate,
                        input=True, input_device_index=speaker_idx,
                        frames_per_buffer=chunk, stream_callback=None
                    )
                except Exception:
                    speaker_stream = None

            # 如果扬声器回环不可用，尝试使用默认输入设备捕获（Stereo Mix 等）
            if self.record_speaker_enabled and speaker_stream is None:
                try:
                    default_in = self.py_audio.get_default_input_device_info()
                    if default_in['index'] != mic_idx:
                        speaker_stream = self.py_audio.open(
                            format=fmt, channels=channels, rate=rate,
                            input=True, input_device_index=default_in['index'],
                            frames_per_buffer=chunk, stream_callback=None
                        )
                except Exception:
                    pass

            while self.is_recording and not self.is_recording_paused:
                if not self.record_mic_enabled and not self.record_speaker_enabled:
                    break

                frames = []
                has_data = False

                # 读取话筒数据
                if self.record_mic_enabled and mic_stream is not None:
                    try:
                        data = mic_stream.read(chunk, exception_on_overflow=False)
                        mic_arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                        frames.append(mic_arr)
                        has_data = True
                    except Exception:
                        pass

                # 读取扬声器数据
                if self.record_speaker_enabled and speaker_stream is not None:
                    try:
                        data = speaker_stream.read(chunk, exception_on_overflow=False)
                        spk_arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                        frames.append(spk_arr)
                        has_data = True
                    except Exception:
                        pass

                if not has_data:
                    # 无数据写入静音，短暂休眠避免 CPU 空转
                    import time
                    time.sleep(0.01)
                    silence = np.zeros(chunk, dtype=np.int16).tobytes()
                    self.audio_frames.append(silence)
                    continue

                # 混合多路音频
                if len(frames) == 1:
                    mixed = frames[0]
                else:
                    mixed = np.mean(frames, axis=0)

                # 裁剪到 16-bit 范围
                mixed = np.clip(mixed, -32768, 32767).astype(np.int16)
                self.audio_frames.append(mixed.tobytes())

        except Exception:
            pass
        finally:
            for s in [mic_stream, speaker_stream]:
                if s:
                    try:
                        s.stop_stream()
                        s.close()
                    except Exception:
                        pass
    
    def _stop_audio_capture(self):
        """停止音频采集"""
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=1.0)
        self.audio_thread = None
        if self.py_audio:
            try:
                self.py_audio.terminate()
            except Exception:
                pass
            self.py_audio = None
    
    def _stop_all_recording(self):
        """停止所有录制"""
        self.is_recording = False
        self.is_recording_paused = False
        self._stop_indicator_animation()
        if self.recording_timer:
            self.recording_timer.stop()
        self._stop_audio_capture()
    
    def _save_as_wav(self):
        """将音频保存为 WAV 文件"""
        if not self.audio_frames:
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, '保存音频', '', 'WAV (*.wav);;MP3 (*.mp3)')
        if not file_path:
            return
        try:
            rate = 44100
            channels = 1
            with wave.open(file_path, 'wb') as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(2)  # 16-bit = 2 bytes
                wf.setframerate(rate)
                wf.writeframes(b''.join(self.audio_frames))
        except Exception as e:
            logging.error(f"保存音频失败: {e}")
    
    def _save_as_mp4(self):
        """将帧序列 BGR numpy 数组编码为 MP4（含音频）"""
        if not self.recording_frames:
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, '保存视频', '', 'MP4 (*.mp4)')
        if not file_path:
            return

        h, w = self.recording_frames[0].shape[:2]
        if w % 2 != 0:
            w -= 1
        if h % 2 != 0:
            h -= 1
        if w <= 0 or h <= 0:
            return

        has_audio = len(self.audio_frames) > 0

        if not has_audio:
            # 纯视频：直接用 cv2.VideoWriter
            self._save_video_only(file_path, w, h)
        else:
            # 有音频：用 FFmpeg 合并视频和音频
            self._save_video_with_audio(file_path, w, h)

    def _save_video_only(self, file_path, w, h):
        """仅保存视频（无音频），使用 cv2.VideoWriter"""
        try:
            import cv2
            for fourcc_code in ['avc1', 'mp4v', 'H264']:
                fourcc = cv2.VideoWriter_fourcc(*fourcc_code)
                out = cv2.VideoWriter(file_path, fourcc, 15, (w, h))
                if out.isOpened():
                    break
                out.release()
            else:
                raise RuntimeError("cv2.VideoWriter 无法打开")

            for arr in self.recording_frames:
                frame = arr[:h, :w]
                out.write(frame)

            out.release()
            logging.info(f"视频已保存: {file_path}")
        except Exception as e:
            logging.warning(f"cv2 编码失败: {e}，尝试 FFmpeg...")
            self._save_video_with_audio(file_path, w, h)

    def _save_video_with_audio(self, file_path, w, h):
        """使用 FFmpeg 保存带音频的视频"""
        import cv2
        tmp_dir = tempfile.mkdtemp(prefix='picbot_video_')
        try:
            # 写入帧图片
            for i, arr in enumerate(self.recording_frames):
                fpath = os.path.join(tmp_dir, f'frame_{i:06d}.png')
                cv2.imwrite(fpath, arr[:h, :w])

            ffmpeg_cmd = [
                'ffmpeg', '-y',
                '-framerate', '15',
                '-i', os.path.join(tmp_dir, 'frame_%06d.png'),
            ]

            if self.audio_frames:
                audio_path = os.path.join(tmp_dir, 'audio.wav')
                with wave.open(audio_path, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(44100)
                    wf.writeframes(b''.join(self.audio_frames))
                ffmpeg_cmd += ['-i', audio_path]
                ffmpeg_cmd += [
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-preset', 'ultrafast', '-crf', '23',
                    '-c:a', 'aac', '-shortest',
                ]
            else:
                ffmpeg_cmd += [
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-preset', 'ultrafast', '-crf', '23',
                ]

            ffmpeg_cmd.append(file_path)
            subprocess.run(ffmpeg_cmd, capture_output=True, timeout=120)
            logging.info(f"视频已保存: {file_path}")
        except FileNotFoundError:
            logging.warning("FFmpeg 未找到")
        except subprocess.TimeoutExpired:
            logging.error("FFmpeg 编码超时")
        except Exception as e:
            logging.error(f"FFmpeg 编码失败: {e}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    
    def on_edit_text(self):
        if self.is_text_editing:
            if self.text_input.isVisible():
                self.save_undo_state()
                self.finalize_text()
            self.is_text_editing = False
            self.setCursor(Qt.ArrowCursor)
            self._hide_text_style_buttons()
            self.show_buttons()
            return
        if self.is_screenshot_doodle:
            self.is_screenshot_doodle = False
            self.doodle_last_pos = None
            self.doodle_btn.setText('涂鸦')
            self.setCursor(Qt.ArrowCursor)
        self.is_text_editing = True
        self.hide_buttons()
        self._show_text_style_buttons()
        self.setCursor(Qt.IBeamCursor)
    
    def on_end_edit(self):
        """结束编辑按钮：结束文本编辑，返回到截图区域并显示按钮"""
        if self.is_text_editing:
            if self.text_input and self.text_input.isVisible():
                self._finalizing = True
                try:
                    self.save_undo_state()
                    self.finalize_text()
                finally:
                    self._finalizing = False
            self.is_text_editing = False
            self.setCursor(Qt.ArrowCursor)
            self._hide_text_style_buttons()
            self.show_buttons()
    
    def finalize_text(self):
        text = self.text_input.text()
        if text and self.text_input_pos:
            # 使用与 text_input 相同的位置和尺寸绘制文字，确保对齐
            text_rect = QRectF(self.text_input_pos.x(), self.text_input_pos.y(),
                               self.text_input.width(), self.text_input.height())
            painter = QPainter(self.cropped_pixmap)
            painter.setFont(self.text_font)
            painter.setPen(QPen(self.text_color))
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap, text)
            painter.end()
            if self.edit_layer:
                painter = QPainter(self.edit_layer)
                painter.setFont(self.text_font)
                painter.setPen(QPen(self.text_color))
                painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap, text)
                painter.end()
        self.cropped_pixmap_original = None
        self.text_input.hide()
        self.update()
    
    def on_text_input_finished(self):
        self._finalizing = True
        try:
            self.save_undo_state()
            self.finalize_text()
        finally:
            self._finalizing = False
    
    def on_text_input_changed(self, text):
        # 不再实时在截图上预览文字，只在编辑框中显示
        pass
    
    def on_font_changed(self, font):
        """字体选择框变化时立即生效"""
        self.text_font = QFont(font)
        self.text_font.setPixelSize(self.text_size)
        self._apply_text_style()
    
    def on_size_changed(self, text):
        """字号选择框变化时立即生效"""
        if text:
            self.text_size = int(text)
            self.text_font.setPixelSize(self.text_size)
            self._apply_text_style()
    
    def on_color_changed(self, name):
        """颜色选择框变化时立即生效"""
        if name:
            for cname, hex_color in self._preset_colors:
                if cname == name:
                    self.text_color = QColor(hex_color)
                    self._apply_text_style()
                    break
    
    def _apply_text_style(self):
        color_name = self.text_color.name()
        self.text_input.setStyleSheet(
            f"background: transparent; border: 2px solid #4169E1;"
            f"color: {color_name}; font-size: {self.text_size}px;"
            f"font-weight: {'bold' if self.text_font.bold() else 'normal'};"
            f"font-family: {self.text_font.family()};"
        )
    
    def _show_text_style_buttons(self):
        select_rect = self.get_rect()
        btn_y = select_rect.bottom() + 10
        btn_height = 36
        spacing = 5
        
        if btn_y + btn_height * 2 + spacing > self.height():
            btn_y = select_rect.top() - btn_height * 2 - spacing - 10
        
        font_width = 140
        color_width = 70
        size_width = 60
        total_width = font_width + color_width + size_width + spacing * 2
        start_x = select_rect.center().x() - total_width // 2
        
        row2_y = btn_y + btn_height + spacing
        
        self.font_btn.setGeometry(start_x, row2_y, font_width, btn_height)
        self.color_btn.setGeometry(start_x + font_width + spacing, row2_y, color_width, btn_height)
        self.size_btn.setGeometry(start_x + font_width + color_width + spacing * 2, row2_y, size_width, btn_height)
        self.font_btn.show()
        self.color_btn.show()
        self.size_btn.show()
        
        # 结束编辑按钮放在第一行居中
        end_edit_width = 120
        end_edit_x = select_rect.center().x() - end_edit_width // 2
        self.end_edit_btn.setGeometry(end_edit_x, btn_y, end_edit_width, btn_height)
        self.end_edit_btn.show()
    
    def _hide_text_style_buttons(self):
        self.font_btn.hide()
        self.color_btn.hide()
        self.size_btn.hide()
        self.end_edit_btn.hide()
    
    def save_undo_state(self):
        if self.cropped_pixmap:
            edit_copy = self.edit_layer.copy() if self.edit_layer else None
            self.history.append((self.cropped_pixmap.copy(), edit_copy))
            if len(self.history) > self.max_history:
                self.history.pop(0)
            self.future.clear()
            self._update_undo_redo_buttons()
    
    def undo(self):
        if not self.history:
            return
        edit_copy = self.edit_layer.copy() if self.edit_layer else None
        self.future.append((self.cropped_pixmap.copy(), edit_copy))
        self.cropped_pixmap, self.edit_layer = self.history.pop()
        self.is_text_editing = False
        if self.text_input and self.text_input.isVisible():
            self.text_input.hide()
        self._update_undo_redo_buttons()
        self.update()
    
    def redo(self):
        if not self.future:
            return
        edit_copy = self.edit_layer.copy() if self.edit_layer else None
        self.history.append((self.cropped_pixmap.copy(), edit_copy))
        self.cropped_pixmap, self.edit_layer = self.future.pop()
        self.is_text_editing = False
        if self.text_input and self.text_input.isVisible():
            self.text_input.hide()
        self._update_undo_redo_buttons()
        self.update()
    
    def _update_undo_redo_buttons(self):
        """更新后退/前进按钮的颜色状态"""
        gray_style = "background-color: #555555; color: white; border: none; padding: 8px 16px; font-size: 14px;"
        if self.history:
            self.undo_btn.setStyleSheet("background-color: #CC3333; color: white; border: none; padding: 8px 16px; font-size: 14px;")
        else:
            self.undo_btn.setStyleSheet(gray_style)
        if self.future:
            self.redo_btn.setStyleSheet("background-color: #33AA33; color: white; border: none; padding: 8px 16px; font-size: 14px;")
        else:
            self.redo_btn.setStyleSheet(gray_style)
    
    def eventFilter(self, obj, event):
        if obj == self.text_input:
            from PyQt5.QtCore import QEvent
            if event.type() == QEvent.FocusOut:
                if not self._style_btn_active:
                    if not self._finalizing:
                        self.save_undo_state()
                        self.finalize_text()
                self._style_btn_active = False
                return True
        return super().eventFilter(obj, event)
    
    def _on_style_btn_pressed(self):
        self._style_btn_active = True
    
    def on_doodle(self):
        if not self.is_screenshot_doodle:
            self.is_screenshot_doodle = True
            self.doodle_btn.setText('结束涂鸦')
            
            # 隐藏按钮，显示涂鸦按钮和下拉框
            self.hide_buttons()
            self.doodle_btn.show()
            
            # 定位并显示颜色和粗细下拉框
            select_rect = self.get_rect()
            doodle_geo = self.doodle_btn.geometry()
            combo_y = doodle_geo.y()
            combo_x = doodle_geo.x() + doodle_geo.width() + 5
            self.doodle_color_combo.setGeometry(combo_x, combo_y, 70, 36)
            self.doodle_width_combo.setGeometry(combo_x + 75, combo_y, 55, 36)
            self.doodle_color_combo.show()
            self.doodle_width_combo.show()
            
            self.setCursor(self.create_pen_cursor())
        else:
            # 结束涂鸦
            self.is_screenshot_doodle = False
            self.doodle_btn.setText('涂鸦')
            self.doodle_last_pos = None
            self.doodle_color_combo.hide()
            self.doodle_width_combo.hide()
            self.show_buttons()
    
    def _on_doodle_color_changed(self, index):
        _, hex_color = self._doodle_colors[index]
        self._doodle_pen_color = QColor(hex_color)
        self.setCursor(self.create_pen_cursor())
    
    def _on_doodle_width_changed(self, index):
        self._doodle_pen_width = index + 1
    
    def create_pen_cursor(self):
        cursor_size = 40
        cursor_pixmap = QPixmap(cursor_size, cursor_size)
        cursor_pixmap.fill(Qt.transparent)
        
        painter = QPainter(cursor_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        pen_color = QColor(self._doodle_pen_color)
        body_color = pen_color.lighter(160)
        
        painter.setBrush(QBrush(body_color))
        painter.setPen(QPen(Qt.black, 1))
        painter.drawRect(5, 5, 10, 25)
        
        painter.setPen(QPen(Qt.gray, 1))
        painter.drawLine(5, 12, 15, 12)
        painter.drawLine(5, 18, 15, 18)
        
        painter.setBrush(QBrush(pen_color))
        painter.setPen(QPen(Qt.black, 1))
        tip_points = QPolygon([
            QPoint(5, 32),
            QPoint(15, 32),
            QPoint(10, cursor_size - 2)
        ])
        painter.drawPolygon(tip_points)
        
        painter.setBrush(QBrush(pen_color.lighter(130)))
        tip_inner = QPolygon([
            QPoint(7, 32),
            QPoint(13, 32),
            QPoint(10, cursor_size - 4)
        ])
        painter.drawPolygon(tip_inner)
        
        painter.end()
        
        from PyQt5.QtGui import QCursor
        return QCursor(cursor_pixmap, 5, cursor_size - 2)
    
    def on_doodle_finished(self, doodle_pixmap):
        select_rect = self.get_rect()
        
        if doodle_pixmap:
            doodle_crop = _copy_pixmap_rect(doodle_pixmap, select_rect)
            painter = QPainter(self.cropped_pixmap)
            painter.drawPixmap(0, 0, doodle_crop)
            painter.end()
            if self.edit_layer:
                painter = QPainter(self.edit_layer)
                painter.drawPixmap(0, 0, doodle_crop)
                painter.end()
        
        self.is_screenshot_doodle = False
        self.doodle_last_pos = None
        self.doodle_btn.setText('涂鸦')
        self.doodle_window = None
        
        self.show_buttons()
        self.is_text_editing = False
        self.update()
    
    def paintEvent(self, event):
        from PyQt5.QtGui import QPainter, QPen, QBrush, QPainterPath, QColor
        painter = QPainter(self)
        
        painter.drawPixmap(self.rect(), self.screenshot)
        
        if self.cropped_pixmap and self.start_pos and self.end_pos:
            select_rect = self.get_rect()
            painter.drawPixmap(select_rect.x(), select_rect.y(), self.cropped_pixmap)
        
        path = QPainterPath()
        rect = self.rect()
        path.addRect(rect.x(), rect.y(), rect.width(), rect.height())
        
        if self.start_pos and self.end_pos:
            select_rect = self.get_rect()
            path.addRect(select_rect.x(), select_rect.y(), select_rect.width(), select_rect.height())
            path.setFillRule(Qt.OddEvenFill)
        
        painter.fillPath(path, QBrush(QColor(0, 0, 0, 150)))
        
        if self.start_pos and self.end_pos:
            select_rect = self.get_rect()
            pen = QPen(Qt.red, 2)
            painter.setPen(pen)
            painter.drawRect(select_rect)
            
            if self.cropped_pixmap:
                handle_r = 8
                painter.setBrush(QBrush(Qt.red))
                painter.setPen(QPen(Qt.red, 2))
                painter.drawEllipse(QPoint(select_rect.x(), select_rect.y()), handle_r, handle_r)
                painter.drawEllipse(QPoint(select_rect.x() + select_rect.width(), select_rect.y()), handle_r, handle_r)
                painter.drawEllipse(QPoint(select_rect.x(), select_rect.y() + select_rect.height()), handle_r, handle_r)
                painter.drawEllipse(QPoint(select_rect.x() + select_rect.width(), select_rect.y() + select_rect.height()), handle_r, handle_r)
                painter.drawEllipse(QPoint(select_rect.x() + select_rect.width() // 2, select_rect.y()), handle_r, handle_r)
                painter.drawEllipse(QPoint(select_rect.x() + select_rect.width() // 2, select_rect.y() + select_rect.height()), handle_r, handle_r)
                painter.drawEllipse(QPoint(select_rect.x(), select_rect.y() + select_rect.height() // 2), handle_r, handle_r)
                painter.drawEllipse(QPoint(select_rect.x() + select_rect.width(), select_rect.y() + select_rect.height() // 2), handle_r, handle_r)
    
    def get_rect(self):
        x = min(self.start_pos.x(), self.end_pos.x())
        y = min(self.start_pos.y(), self.end_pos.y())
        width = abs(self.start_pos.x() - self.end_pos.x())
        height = abs(self.start_pos.y() - self.end_pos.y())
        return QRect(x, y, width, height)
    
    def _get_corner_at(self, pos):
        if not self.cropped_pixmap:
            return None
        select_rect = self.get_rect()
        handle_r = 6
        handles = {
            'tl': QPoint(select_rect.x(), select_rect.y()),
            'tr': QPoint(select_rect.x() + select_rect.width(), select_rect.y()),
            'bl': QPoint(select_rect.x(), select_rect.y() + select_rect.height()),
            'br': QPoint(select_rect.x() + select_rect.width(), select_rect.y() + select_rect.height()),
            'top': QPoint(select_rect.x() + select_rect.width() // 2, select_rect.y()),
            'bottom': QPoint(select_rect.x() + select_rect.width() // 2, select_rect.y() + select_rect.height()),
            'left': QPoint(select_rect.x(), select_rect.y() + select_rect.height() // 2),
            'right': QPoint(select_rect.x() + select_rect.width(), select_rect.y() + select_rect.height() // 2),
        }
        for name, pt in handles.items():
            if (pos - pt).manhattanLength() <= handle_r * 2:
                return name
        return None
    
    def mousePressEvent(self, event):
        if self.is_screenshot_doodle and self.cropped_pixmap:
            select_rect = self.get_rect()
            if select_rect.contains(event.pos()):
                self.save_undo_state()
                self.doodle_last_pos = QPoint(event.pos().x() - select_rect.x(), event.pos().y() - select_rect.y())
            return
        
        if self.is_text_editing and self.cropped_pixmap:
            select_rect = self.get_rect()
            if select_rect.contains(event.pos()):
                if self.text_input.isVisible():
                    self.on_text_input_finished()
                    self.text_input_pos = QPoint(event.pos().x() - select_rect.x(), event.pos().y() - select_rect.y())
                    self.text_input.move(event.pos())
                    self.text_input.clear()
                    self.text_input.show()
                    self.text_input.setFocus()
                    self._apply_text_style()
                    return
                self.cropped_pixmap_original = self.cropped_pixmap.copy()
                self.text_input_pos = QPoint(event.pos().x() - select_rect.x(), event.pos().y() - select_rect.y())
                self.text_input.move(event.pos())
                self.text_input.clear()
                self.text_input.show()
                self.text_input.setFocus()
                self._apply_text_style()
            return
        
        if self.cropped_pixmap:
            corner = self._get_corner_at(event.pos())
            if corner and event.button() == Qt.LeftButton:
                self.is_resizing = True
                self.resize_corner = corner
                select_rect = self.get_rect()
                if corner in ('tl', 'tr', 'bl', 'br'):
                    opposites = {
                        'tl': QPoint(select_rect.x() + select_rect.width(), select_rect.y() + select_rect.height()),
                        'tr': QPoint(select_rect.x(), select_rect.y() + select_rect.height()),
                        'bl': QPoint(select_rect.x() + select_rect.width(), select_rect.y()),
                        'br': QPoint(select_rect.x(), select_rect.y()),
                    }
                    self.resize_opposite = opposites[corner]
                else:
                    self.resize_opposite = None
                self.save_undo_state()
                return
            select_rect = self.get_rect()
            if select_rect.contains(event.pos()):
                self.is_dragging = True
                self.drag_offset = QPoint(event.pos().x() - select_rect.x(), event.pos().y() - select_rect.y())
                return
            if self.text_input.isVisible():
                self.on_text_input_finished()
            return
        if event.button() == Qt.LeftButton:
            self.cancel_btn.hide()
            self.start_pos = event.pos()
            self.end_pos = event.pos()
    
    def mouseMoveEvent(self, event):
        if self.is_resizing and self.cropped_pixmap:
            select_rect = self.get_rect()
            if self.resize_corner in ('tl', 'tr', 'bl', 'br'):
                new_x = event.pos().x()
                new_y = event.pos().y()
                new_x = max(0, min(new_x, self.screenshot.width() - 10))
                new_y = max(0, min(new_y, self.screenshot.height() - 10))
                self.start_pos = QPoint(new_x, new_y)
                self.end_pos = self.resize_opposite
            elif self.resize_corner == 'top':
                new_y = max(0, min(event.pos().y(), select_rect.y() + select_rect.height() - 10))
                self.start_pos = QPoint(select_rect.x(), new_y)
                self.end_pos = QPoint(select_rect.x() + select_rect.width(), select_rect.y() + select_rect.height())
            elif self.resize_corner == 'bottom':
                new_y = max(select_rect.y() + 10, min(event.pos().y(), self.screenshot.height()))
                self.start_pos = QPoint(select_rect.x(), select_rect.y())
                self.end_pos = QPoint(select_rect.x() + select_rect.width(), new_y)
            elif self.resize_corner == 'left':
                new_x = max(0, min(event.pos().x(), select_rect.x() + select_rect.width() - 10))
                self.start_pos = QPoint(new_x, select_rect.y())
                self.end_pos = QPoint(select_rect.x() + select_rect.width(), select_rect.y() + select_rect.height())
            elif self.resize_corner == 'right':
                new_x = max(select_rect.x() + 10, min(event.pos().x(), self.screenshot.width()))
                self.start_pos = QPoint(select_rect.x(), select_rect.y())
                self.end_pos = QPoint(new_x, select_rect.y() + select_rect.height())
            new_rect = self.get_rect()
            if new_rect.width() > 10 and new_rect.height() > 10:
                new_screen = _copy_pixmap_rect(self.screenshot, new_rect)
                edit_img = QImage(new_screen.width(), new_screen.height(), QImage.Format_ARGB32)
                edit_img.fill(Qt.transparent)
                self.edit_layer = QPixmap.fromImage(edit_img)
                if new_screen.devicePixelRatio() > 1.0:
                    self.edit_layer.setDevicePixelRatio(new_screen.devicePixelRatio())
                self.show_preview(new_screen, reset_edit_layer=False)
            return
        if self.is_screenshot_doodle and self.cropped_pixmap and self.doodle_last_pos:
            select_rect = self.get_rect()
            if select_rect.contains(event.pos()):
                current_pos = QPoint(event.pos().x() - select_rect.x(), event.pos().y() - select_rect.y())
                pen = QPen(self._doodle_pen_color, self._doodle_pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                painter = QPainter(self.cropped_pixmap)
                painter.setPen(pen)
                painter.drawLine(self.doodle_last_pos, current_pos)
                painter.end()
                if self.edit_layer:
                    painter = QPainter(self.edit_layer)
                    painter.setPen(pen)
                    painter.drawLine(self.doodle_last_pos, current_pos)
                    painter.end()
                self.doodle_last_pos = current_pos
                self.update()
            else:
                self.doodle_last_pos = None
            return
        if self.is_dragging and self.cropped_pixmap:
            select_rect = self.get_rect()
            width = select_rect.width()
            height = select_rect.height()
            new_x = event.pos().x() - self.drag_offset.x()
            new_y = event.pos().y() - self.drag_offset.y()
            new_x = max(0, min(new_x, self.screenshot.width() - width))
            new_y = max(0, min(new_y, self.screenshot.height() - height))
            self.start_pos = QPoint(new_x, new_y)
            self.end_pos = QPoint(new_x + width, new_y + height)
            new_rect = self.get_rect()
            new_screen = _copy_pixmap_rect(self.screenshot, new_rect)
            if self.edit_layer:
                painter = QPainter(new_screen)
                painter.drawPixmap(0, 0, self.edit_layer)
                painter.end()
            self.show_preview(new_screen, reset_edit_layer=False)
            return
        if self.cropped_pixmap:
            if self.is_text_editing:
                select_rect = self.get_rect()
                if select_rect.contains(event.pos()):
                    self.setCursor(Qt.IBeamCursor)
                else:
                    self.setCursor(Qt.ArrowCursor)
            elif self.is_screenshot_doodle:
                select_rect = self.get_rect()
                if select_rect.contains(event.pos()):
                    self.setCursor(self.create_pen_cursor())
                else:
                    self.setCursor(Qt.ArrowCursor)
            else:
                corner = self._get_corner_at(event.pos())
                if corner in ('top', 'bottom'):
                    self.setCursor(Qt.SizeVerCursor)
                elif corner in ('left', 'right'):
                    self.setCursor(Qt.SizeHorCursor)
                elif corner in ('tl', 'br'):
                    self.setCursor(Qt.SizeFDiagCursor)
                elif corner in ('tr', 'bl'):
                    self.setCursor(Qt.SizeBDiagCursor)
                else:
                    select_rect = self.get_rect()
                    if select_rect.contains(event.pos()):
                        self.setCursor(Qt.SizeAllCursor)
                    else:
                        self.setCursor(Qt.ArrowCursor)
            return
        if self.start_pos is None and self.cropped_pixmap is None:
            # 未开始选区时恢复十字光标（按钮 hover 由 cancel_btn.setCursor 控制）
            self.setCursor(self.crosshair_cursor)
            return
        if self.start_pos:
            self.end_pos = event.pos()
            self.update()
    
    def mouseReleaseEvent(self, event):
        if self.is_resizing:
            self.is_resizing = False
            self.resize_corner = None
            self.resize_opposite = None
            return
        if self.is_dragging:
            self.is_dragging = False
            return
        if self.is_screenshot_doodle:
            self.doodle_last_pos = None
            return
        if event.button() == Qt.LeftButton and self.start_pos and not self.cropped_pixmap:
            rect = self.get_rect()
            if rect.width() > 10 and rect.height() > 10:
                cropped_pixmap = _copy_pixmap_rect(self.screenshot, rect)
                self.show_preview(cropped_pixmap)
            else:
                self.screenshot_canceled.emit()
                self.close()
    
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.is_screenshot_doodle:
                self.is_screenshot_doodle = False
                self.doodle_last_pos = None
                self.doodle_btn.setText('涂鸦')
                self.setCursor(Qt.ArrowCursor)
                self.show_buttons()
                return
            if self.is_text_editing:
                if self.text_input.isVisible():
                    self.text_input.hide()
                self.is_text_editing = False
                self.setCursor(Qt.ArrowCursor)
                self._hide_text_style_buttons()
                self.show_buttons()
                return
            self.screenshot_canceled.emit()
            self.close()
    
    def closeEvent(self, event):
        self._stop_all_recording()
        if self._recording_float:
            self._recording_float.close()
            self._recording_float = None
        if self._recording_border:
            self._recording_border.close()
            self._recording_border = None
        self.setCursor(Qt.ArrowCursor)
        event.accept()


class DoodleToolbar(QWidget):
    """涂鸦工具栏：清屏按钮 + 背景下拉框 + 关闭/后退/前进按钮 + 颜色和线条粗细下拉框"""
    color_changed = pyqtSignal(QColor)
    width_changed = pyqtSignal(int)
    close_requested = pyqtSignal()
    undo_requested = pyqtSignal()
    redo_requested = pyqtSignal()
    clear_requested = pyqtSignal()
    background_changed = pyqtSignal(str)  # 'original'/'black'/'white'
    text_mode_requested = pyqtSignal()
    
    _DOODLE_COLORS = [
        ('赤', '#E60000'), ('橙', '#FF7F00'), ('黄', '#FFFF00'),
        ('绿', '#00FF00'), ('青', '#00FFFF'), ('蓝', '#0000FF'),
        ('紫', '#8B00FF'), ('粉', '#FFC0CB'), ('黑', '#000000'),
        ('白', '#FFFFFF'), ('棕', '#8B4513'), ('砖红', '#B22222'),
        ('大红', '#FF0000'), ('酒红', '#8B0000'),
    ]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #2A2A2A; border-radius: 4px;")
        self.setCursor(Qt.ArrowCursor)
        self._drag_offset = None
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 8, 4)
        layout.setSpacing(4)
        
        btn_style_base = ("QPushButton { border: none; border-radius: 3px; "
                          "min-width: 28px; min-height: 24px; font-size: 13px; font-weight: bold; }")
        
        # 关闭按钮（红色）
        self.close_btn = QPushButton('✕')
        self.close_btn.setStyleSheet(
            btn_style_base + "QPushButton { background-color: #CC0000; color: white; }"
            "QPushButton:hover { background-color: #FF0000; }"
        )
        self.close_btn.clicked.connect(self.close_requested.emit)
        layout.addWidget(self.close_btn)
        
        # 后退按钮（undo，默认灰色，可后退时蓝色）
        self.undo_btn = QPushButton('后退')
        self.undo_btn.setStyleSheet(
            btn_style_base + "QPushButton { background-color: #555; color: #999; }"
        )
        self.undo_btn.clicked.connect(self.undo_requested.emit)
        layout.addWidget(self.undo_btn)
        
        # 前进按钮（redo，默认灰色，可前进时绿色）
        self.redo_btn = QPushButton('前进')
        self.redo_btn.setStyleSheet(
            btn_style_base + "QPushButton { background-color: #555; color: #999; }"
        )
        self.redo_btn.clicked.connect(self.redo_requested.emit)
        layout.addWidget(self.redo_btn)
        
        # 清屏按钮（默认灰色，有内容后浅绿色）
        self.clear_btn = QPushButton('清屏')
        self.clear_btn.setStyleSheet(
            btn_style_base + "QPushButton { background-color: #555; color: #999; min-width: 36px; }"
        )
        self.clear_btn.clicked.connect(self.clear_requested.emit)
        layout.addWidget(self.clear_btn)
        
        # 文本按钮（紫色）：进入文本编辑模式
        self.text_btn = QPushButton('文本')
        self.text_btn.setStyleSheet(
            btn_style_base + "QPushButton { background-color: #8B008B; color: white; min-width: 36px; }"
            "QPushButton:hover { background-color: #9932CC; }"
        )
        self.text_btn.clicked.connect(self.text_mode_requested.emit)
        layout.addWidget(self.text_btn)
        
        # 背景下拉框（原屏/黑屏/白屏）
        self.bg_combo = QComboBox()
        self.bg_combo.setStyleSheet(
            "QComboBox { background-color: #333; color: white; border: 1px solid #555; "
            "padding: 4px 6px; font-size: 12px; min-width: 52px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background-color: #333; color: white; selection-background-color: #555; }"
        )
        self.bg_combo.addItems(['原屏', '黑屏', '白屏'])
        self.bg_combo.currentIndexChanged.connect(self._on_background_changed)
        layout.addWidget(self.bg_combo)
        
        # 颜色下拉框
        self.color_combo = QComboBox()
        self.color_combo.setStyleSheet(
            "QComboBox { background-color: #333; color: white; border: 1px solid #555; "
            "padding: 4px 8px; font-size: 12px; min-width: 80px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background-color: #333; color: white; selection-background-color: #555; }"
        )
        for name, hex_color in self._DOODLE_COLORS:
            pixmap = QPixmap(16, 16)
            pixmap.fill(QColor(hex_color))
            self.color_combo.addItem(QIcon(pixmap), name)
        self.color_combo.setCurrentIndex(0)
        self.color_combo.currentIndexChanged.connect(self._on_color_changed)
        layout.addWidget(self.color_combo)
        
        # 线条粗细下拉框
        self.width_combo = QComboBox()
        self.width_combo.setStyleSheet(
            "QComboBox { background-color: #333; color: white; border: 1px solid #555; "
            "padding: 4px 8px; font-size: 12px; min-width: 60px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background-color: #333; color: white; selection-background-color: #555; }"
        )
        self.width_combo.addItems([str(i) for i in range(1, 50)])
        self.width_combo.setCurrentIndex(4)
        self.width_combo.currentIndexChanged.connect(self._on_width_changed)
        layout.addWidget(self.width_combo)
        
        self.adjustSize()
    
    def update_undo_redo_state(self, has_undo, has_redo):
        """根据 undo/redo 可用性更新按钮颜色"""
        btn_base = ("QPushButton { border: none; border-radius: 3px; "
                    "min-width: 28px; min-height: 24px; font-size: 13px; font-weight: bold; }")
        if has_undo:
            self.undo_btn.setStyleSheet(
                btn_base + "QPushButton { background-color: #0066CC; color: white; }"
                "QPushButton:hover { background-color: #0088FF; }"
            )
        else:
            self.undo_btn.setStyleSheet(
                btn_base + "QPushButton { background-color: #555; color: #999; }"
            )
        if has_redo:
            self.redo_btn.setStyleSheet(
                btn_base + "QPushButton { background-color: #008800; color: white; }"
                "QPushButton:hover { background-color: #00AA00; }"
            )
        else:
            self.redo_btn.setStyleSheet(
                btn_base + "QPushButton { background-color: #555; color: #999; }"
            )
    
    def update_clear_button_state(self, has_content):
        """根据是否有涂鸦内容更新清屏按钮颜色"""
        btn_base = ("QPushButton { border: none; border-radius: 3px; "
                    "min-width: 36px; min-height: 24px; font-size: 13px; font-weight: bold; }")
        if has_content:
            self.clear_btn.setStyleSheet(
                btn_base + "QPushButton { background-color: #66CDAA; color: white; }"
                "QPushButton:hover { background-color: #7FFFD4; }"
            )
        else:
            self.clear_btn.setStyleSheet(
                btn_base + "QPushButton { background-color: #555; color: #999; }"
            )
    
    def _on_color_changed(self, index):
        _, hex_color = self._DOODLE_COLORS[index]
        self.color_changed.emit(QColor(hex_color))
    
    def _on_background_changed(self, index):
        modes = ['original', 'black', 'white']
        self.background_changed.emit(modes[index])
    
    def _on_width_changed(self, index):
        self.width_changed.emit(index + 1)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.pos()
    
    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and self.parent() is not None:
            # 转换为父控件（DoodleWindow）的本地坐标
            parent_pos = self.parent().mapFromGlobal(event.globalPos())
            self.move(parent_pos - self._drag_offset)
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = None
    
    def show_at_mouse_screen(self):
        """定位到当前鼠标所在屏幕的右上角（父控件本地坐标）"""
        cursor_pos = QCursor.pos()
        screen = QApplication.screenAt(cursor_pos)
        if screen is None:
            screen = QApplication.primaryScreen()
        geo = screen.geometry()
        margin = 10
        # 目标屏幕坐标
        sx = geo.right() - self.width() - margin
        sy = geo.top() + margin
        # 转换为父控件（DoodleWindow）的本地坐标
        if self.parent() is not None:
            parent_pos = self.parent().mapFromGlobal(QPoint(sx, sy))
            self.move(parent_pos)
        else:
            self.move(sx, sy)
        self.show()


class DoodleWindow(QWidget):
    doodle_finished = pyqtSignal(QPixmap)
    
    def __init__(self, screen_shot=None, transparent_mode=False):
        super().__init__()
        self.screen_shot = screen_shot
        self.transparent_mode = transparent_mode
        self.background_mode = 'original'  # 'original'/'black'/'white'
        self.text_mode = False  # 是否处于文本编辑模式
        self.text_font = QFont('微软雅黑', 20)
        self.text_color = QColor('#E60000')
        self.text_size = 20
        self.initUI()
        self.last_pos = None
        self.drawing = False
        self.history = []
        self.future = []
        self.max_history = 50
    
    def initUI(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background-color: transparent;")
        
        if self.transparent_mode:
            # 透明模式：画布只包含涂鸦笔迹，窗口透明显示下层内容
            w = self.screen_shot.width() if self.screen_shot else 1920
            h = self.screen_shot.height() if self.screen_shot else 1080
            self.canvas = QPixmap(w, h)
            self.canvas.fill(Qt.transparent)
        elif self.screen_shot:
            self.canvas = self.screen_shot.copy()
        else:
            # 捕获当前鼠标所在屏幕截图
            self.canvas = _capture_current_screen()
        
        self.pen_color = Qt.red
        self.pen_width = 5
        
        # 创建涂鸦工具栏（作为子控件，始终渲染在画布之上）
        self.toolbar = DoodleToolbar(self)
        self.toolbar.color_changed.connect(self._on_toolbar_color_changed)
        self.toolbar.width_changed.connect(self._on_toolbar_width_changed)
        self.toolbar.close_requested.connect(self.close)
        self.toolbar.undo_requested.connect(self.undo)
        self.toolbar.redo_requested.connect(self.redo)
        self.toolbar.clear_requested.connect(self._on_clear)
        self.toolbar.background_changed.connect(self._on_background_changed)
        self.toolbar.text_mode_requested.connect(self._on_text_mode_enter)
        self.toolbar.update_undo_redo_state(False, False)  # 初始状态：都不可用
        
        # ===== 文本编辑子面板（DoodleWindow 直接子控件，初始隐藏）=====
        self._text_panel = QWidget(self)
        self._text_panel.setStyleSheet(
            "background-color: #2A2A2A; border: 1px solid #555; border-radius: 4px;"
        )
        text_panel_layout = QHBoxLayout(self._text_panel)
        text_panel_layout.setContentsMargins(6, 4, 8, 4)
        text_panel_layout.setSpacing(4)
        
        text_btn_base = ("QPushButton { border: none; border-radius: 3px; "
                         "min-width: 36px; min-height: 24px; font-size: 12px; font-weight: bold; }")
        text_combo_base = ("QComboBox { border: 1px solid #555; border-radius: 3px; "
                           "padding: 2px 4px; font-size: 11px; min-height: 22px; color: white; }"
                           "QComboBox::drop-down { border: none; }"
                           "QComboBox QAbstractItemView { color: white; selection-background-color: #555; }")
        
        # 结束编辑按钮（浅蓝色）
        self.text_end_btn = QPushButton('结束编辑')
        self.text_end_btn.setStyleSheet(
            text_btn_base + "QPushButton { background-color: #4682B4; color: white; }"
            "QPushButton:hover { background-color: #5A9BD5; }"
        )
        self.text_end_btn.clicked.connect(self._on_text_mode_exit)
        text_panel_layout.addWidget(self.text_end_btn)
        
        # 字体下拉框（淡红色背景）
        self.text_font_combo = QFontComboBox()
        self.text_font_combo.setEditable(False)
        self.text_font_combo.setFontFilters(QFontComboBox.AllFonts)
        self.text_font_combo.setStyleSheet(
            text_combo_base + "QComboBox { background-color: #CD5C5C; min-width: 100px; }"
            "QComboBox QAbstractItemView { background-color: #8B3A3A; }"
        )
        idx = self.text_font_combo.findText('微软雅黑')
        if idx >= 0:
            self.text_font_combo.setCurrentIndex(idx)
        self.text_font_combo.currentFontChanged.connect(self._on_text_font_changed)
        text_panel_layout.addWidget(self.text_font_combo)
        
        # 文字颜色下拉框（橙色背景）
        self.text_color_combo = QComboBox()
        self.text_color_combo.setStyleSheet(
            text_combo_base + "QComboBox { background-color: #CD7F32; min-width: 60px; }"
            "QComboBox QAbstractItemView { background-color: #8B6914; }"
        )
        self._TEXT_COLORS = [
            ('赤', '#E60000'), ('橙', '#FF7F00'), ('黄', '#FFFF00'),
            ('绿', '#00FF00'), ('青', '#00FFFF'), ('蓝', '#0000FF'),
            ('紫', '#8B00FF'), ('酒红', '#8B0000'), ('砖红', '#B22222'),
            ('粉红', '#FFC0CB'), ('浅绿', '#90EE90'),
        ]
        for name, hex_color in self._TEXT_COLORS:
            pixmap = QPixmap(16, 16)
            pixmap.fill(QColor(hex_color))
            self.text_color_combo.addItem(QIcon(pixmap), name)
        self.text_color_combo.setCurrentIndex(0)  # 默认红色
        self.text_color_combo.currentIndexChanged.connect(self._on_text_color_changed)
        text_panel_layout.addWidget(self.text_color_combo)
        
        # 字体大小下拉框（淡黄色背景，1~50）
        self.text_size_combo = QComboBox()
        self.text_size_combo.setStyleSheet(
            text_combo_base + "QComboBox { background-color: #DAA520; min-width: 44px; }"
            "QComboBox QAbstractItemView { background-color: #8B7500; }"
        )
        self.text_size_combo.addItems([str(i) for i in range(1, 50)])
        self.text_size_combo.setCurrentIndex(19)  # 默认大小 20
        self.text_size_combo.currentIndexChanged.connect(self._on_text_size_changed)
        text_panel_layout.addWidget(self.text_size_combo)
        
        self._text_panel.hide()
        
        # 内联文本编辑框（参考 ScreenshotWindow 的 text_input）
        self.text_input = QLineEdit(self)
        self.text_input.setStyleSheet(
            "background: transparent; border: 2px solid #4169E1;"
            "color: red; font-size: 20px; font-family: Microsoft YaHei;"
        )
        self.text_input.setFixedSize(300, 40)
        self.text_input.hide()
        self.text_input.returnPressed.connect(self._on_text_input_finished)
        
        self.setCursor(self.create_pen_cursor())
    
    def _update_toolbar_state(self):
        """更新工具栏按钮的 undo/redo 状态和清屏按钮颜色"""
        has_content = len(self.history) > 0 or len(self.future) > 0
        self.toolbar.update_undo_redo_state(len(self.history) > 0, len(self.future) > 0)
        self.toolbar.update_clear_button_state(has_content)
    
    def _apply_background(self, mode):
        """根据模式重建画布背景"""
        src = self.screen_shot if self.screen_shot else self.canvas
        self.canvas = src.copy()  # 保留 DPR 和尺寸，避免坐标错位
        if mode == 'original':
            pass  # copy() 已经等于原屏
        elif mode == 'black':
            self.canvas.fill(Qt.black)
        elif mode == 'white':
            self.canvas.fill(Qt.white)
        self.background_mode = mode
        self.history.clear()
        self.future.clear()
        self.update()
        self._update_toolbar_state()
    
    def _on_clear(self):
        """清屏：恢复到当前背景模式的初始状态"""
        self._apply_background(self.background_mode)
    
    def _on_background_changed(self, mode):
        """背景下拉框变化时实时切换背景"""
        if mode == self.background_mode:
            return
        self._apply_background(mode)
    
    def _on_toolbar_color_changed(self, color):
        self.pen_color = color
        self.setCursor(self.create_pen_cursor())
    
    def _on_toolbar_width_changed(self, width):
        self.pen_width = width
        self.setCursor(self.create_pen_cursor())
    
    def _on_text_mode_enter(self):
        """进入文本编辑模式"""
        self.text_mode = True
        self.drawing = False
        self._show_text_panel()
        self.toolbar.text_btn.setStyleSheet(
            "QPushButton { border: none; border-radius: 3px; "
            "min-width: 36px; min-height: 24px; font-size: 13px; font-weight: bold; "
            "background-color: #9932CC; color: white; }"
        )
        self.setCursor(Qt.IBeamCursor)
    
    def _show_text_panel(self):
        """定位文本面板在工具栏下方并显示"""
        tb = self.toolbar
        pos = QPoint(tb.x(), tb.y() + tb.height() + 2)
        self._text_panel.move(pos)
        self._text_panel.adjustSize()
        self._text_panel.raise_()
        self._text_panel.show()
    
    def _on_text_mode_exit(self):
        """退出文本编辑模式"""
        # 如果正在内联编辑，先完成文本绘制
        if self.text_input.isVisible():
            self._on_text_input_finished()
        self.text_mode = False
        self._text_panel.hide()
        self.toolbar.text_btn.setStyleSheet(
            "QPushButton { border: none; border-radius: 3px; "
            "min-width: 36px; min-height: 24px; font-size: 13px; font-weight: bold; "
            "background-color: #8B008B; color: white; }"
            "QPushButton:hover { background-color: #9932CC; }"
        )
        self.setCursor(self.create_pen_cursor())
    
    def _on_text_font_changed(self, font):
        self.text_font = font
        self._apply_text_style_text_input()
    
    def _on_text_color_changed(self, index):
        hex_colors = [c[1] for c in self._TEXT_COLORS]
        if 0 <= index < len(hex_colors):
            self.text_color = QColor(hex_colors[index])
            self._apply_text_style_text_input()
    
    def _on_text_size_changed(self, index):
        self.text_size = index + 1
        self._apply_text_style_text_input()
    
    def _apply_text_style_text_input(self):
        """将当前字体/颜色/大小应用到内联编辑框"""
        if not self.text_input.isVisible():
            return
        color_name = self.text_color.name()
        self.text_input.setStyleSheet(
            f"background: transparent; border: 2px solid #4169E1;"
            f"color: {color_name}; font-size: {self.text_size}px;"
            f"font-family: {self.text_font.family()};"
        )
    
    def _on_text_input_finished(self):
        """内联编辑框回车：将文字绘制到 canvas 上"""
        text = self.text_input.text()
        if text:
            # 保存当前画布到历史（undo 支持）
            self.history.append(self.canvas.copy())
            if len(self.history) > self.max_history:
                self.history.pop(0)
            self.future.clear()
            # 在 canvas 上绘制文字
            painter = QPainter(self.canvas)
            font = QFont(self.text_font.family(), self.text_size)
            painter.setFont(font)
            painter.setPen(QPen(self.text_color))
            # 绘制在 text_input 的左上角位置
            draw_pos = QPoint(self.text_input.x(), self.text_input.y() + self.text_size + 2)
            painter.drawText(draw_pos, text)
            painter.end()
            self.update()
            self._update_toolbar_state()
        self.text_input.hide()
    
    def create_pen_cursor(self):
        # 创建一个更大更形象的画笔形状自定义光标
        cursor_size = 40
        cursor_pixmap = QPixmap(cursor_size, cursor_size)
        cursor_pixmap.fill(Qt.transparent)
        
        painter = QPainter(cursor_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 画笔主体颜色
        pen_color = QColor(self.pen_color)
        body_color = pen_color.lighter(160)  # 笔杆使用选中颜色的浅色版本
        
        # 绘制笔杆（矩形）
        painter.setBrush(QBrush(body_color))
        painter.setPen(QPen(Qt.black, 1))
        painter.drawRect(5, 5, 10, 25)
        
        # 绘制笔杆上的装饰线
        painter.setPen(QPen(Qt.gray, 1))
        painter.drawLine(5, 12, 15, 12)
        painter.drawLine(5, 18, 15, 18)
        
        # 绘制笔尖（三角形）
        painter.setBrush(QBrush(pen_color))
        painter.setPen(QPen(Qt.black, 1))
        # 笔尖三角形
        tip_points = QPolygon([
            QPoint(5, 32),
            QPoint(15, 32),
            QPoint(10, cursor_size - 2)
        ])
        painter.drawPolygon(tip_points)
        
        # 绘制笔尖内部高光
        highlight_color = pen_color.lighter(150)
        painter.setBrush(QBrush(highlight_color))
        tip_inner = QPolygon([
            QPoint(7, 32),
            QPoint(13, 32),
            QPoint(10, cursor_size - 4)
        ])
        painter.drawPolygon(tip_inner)
        
        # 绘制一些墨迹效果
        painter.setPen(QPen(pen_color, 3))
        painter.setBrush(QBrush(pen_color))
        painter.drawEllipse(22, 20, 5, 5)
        painter.drawEllipse(28, 25, 4, 4)
        painter.drawEllipse(25, 32, 6, 6)
        painter.drawEllipse(32, 28, 3, 3)
        
        painter.end()
        
        # 热点设置在笔尖位置
        return QCursor(cursor_pixmap, 10, cursor_size - 2)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.canvas)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.text_mode:
                # 文本编辑模式：在点击位置显示内联编辑框
                if self.text_input.isVisible():
                    self._on_text_input_finished()
                self.text_input.move(event.pos())
                self.text_input.clear()
                self.text_input.show()
                self.text_input.setFocus()
                self._apply_text_style_text_input()
                return
            self.history.append(self.canvas.copy())
            if len(self.history) > self.max_history:
                self.history.pop(0)
            self.future.clear()
            self.drawing = True
            self.last_pos = event.pos()
            self._update_toolbar_state()
    
    def mouseMoveEvent(self, event):
        if self.drawing and self.last_pos:
            painter = QPainter(self.canvas)
            painter.setPen(QPen(self.pen_color, self.pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawLine(self.last_pos, event.pos())
            self.last_pos = event.pos()
            self.update()
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drawing = False
            self.last_pos = None
    
    def undo(self):
        if not self.history:
            return
        self.future.append(self.canvas.copy())
        self.canvas = self.history.pop()
        self.update()
        self._update_toolbar_state()
    
    def redo(self):
        if not self.future:
            return
        self.history.append(self.canvas.copy())
        self.canvas = self.future.pop()
        self.update()
        self._update_toolbar_state()
    
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
    
    def closeEvent(self, event):
        # 发出涂鸦完成信号，传递涂鸦内容
        self.doodle_finished.emit(self.canvas)
        event.accept()


if __name__ == '__main__':
    print("Starting cutbot应用...")
    try:
        app = QApplication(sys.argv)
        
        def _on_image_saved(path):
            print(f"图片已保存: {path}")
        
        _image_saved_emitter.image_saved.connect(_on_image_saved)
        
        manager = HotkeyManager()
        manager.register_hotkeys()
        print("全局快捷键已注册，程序在后台运行...")
        print("ALT+1: 截图 | ALT+2: 粘贴 | ALT+3: 取消 | ALT+Q: 涂鸦 | ALT+W: 结束涂鸦 | ALT+A: 撤销 | ALT+S: 重做")
        sys.exit(app.exec_())
    except Exception as e:
        print(f"错误：{str(e)}")
        import traceback
        traceback.print_exc()

