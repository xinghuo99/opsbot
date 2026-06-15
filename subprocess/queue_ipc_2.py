import sys
import multiprocessing
from multiprocessing import Process, Queue
from PyQt5.QtCore import pyqtSignal, QThread
from PyQt5.QtWidgets import (QApplication, QWidget, QPushButton,
                             QTextEdit, QVBoxLayout)


# ---------- 子进程：发送窗口 ----------
class ChildCmdListener(QThread):
    """子进程监听线程：等待主进程的命令"""
    quit_received = pyqtSignal()

    def __init__(self, cmd_queue):
        super().__init__()
        self.cmd_queue = cmd_queue

    def run(self):
        try:
            while True:
                cmd = self.cmd_queue.get()
                if cmd == "__QUIT__":
                    self.quit_received.emit()
                    break
        except (EOFError, BrokenPipeError):
            pass


class ChildWindow(QWidget):
    def __init__(self, msg_queue, cmd_queue):
        super().__init__()
        self.msg_queue = msg_queue
        self.cmd_queue = cmd_queue
        self.setWindowTitle("子进程 - 发送端")
        self.resize(400, 300)

        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("在此输入要发送的消息...")
        self.send_btn = QPushButton("发送到主进程")
        self.send_btn.clicked.connect(self.send_message)

        layout = QVBoxLayout()
        layout.addWidget(self.text_edit)
        layout.addWidget(self.send_btn)
        self.setLayout(layout)

        # 监听命令队列的线程
        self.cmd_listener = ChildCmdListener(cmd_queue)
        self.cmd_listener.quit_received.connect(self.on_quit_received)
        self.cmd_listener.start()

    def send_message(self):
        text = self.text_edit.toPlainText().strip()
        if text:
            try:
                self.msg_queue.put(text)
            except (BrokenPipeError, EOFError):
                pass

    def on_quit_received(self):
        """收到主进程退出命令，发送终止标记后退出"""
        try:
            self.msg_queue.put(None)  # 通知主进程监听线程结束
        except (BrokenPipeError, EOFError):
            pass
        QApplication.instance().quit()

    def closeEvent(self, event):
        """用户点击窗口关闭按钮（X）时触发"""
        # 1. 发送终止标记给主进程，解除其监听线程的阻塞
        try:
            self.msg_queue.put(None)
        except (BrokenPipeError, EOFError):
            pass
        # 2. 停止命令监听线程
        self.cmd_listener.quit()
        self.cmd_listener.wait()
        # 3. 接受关闭事件
        super().closeEvent(event)


def run_child(msg_queue, cmd_queue):
    """子进程入口"""
    app = QApplication(sys.argv)
    window = ChildWindow(msg_queue, cmd_queue)
    window.show()
    sys.exit(app.exec())


# ---------- 主进程：接收窗口 ----------
class MainMsgListener(QThread):
    """主进程监听线程：从消息队列循环接收"""
    message_received = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, msg_queue):
        super().__init__()
        self.msg_queue = msg_queue

    def run(self):
        try:
            while True:
                msg = self.msg_queue.get()
                if msg is None:          # 子进程发来的终止信号
                    break
                self.message_received.emit(msg)
        except (EOFError, BrokenPipeError):
            pass
        self.finished.emit()


class MainWindow(QWidget):
    def __init__(self, msg_queue, cmd_queue, child_process):
        super().__init__()
        self.msg_queue = msg_queue
        self.cmd_queue = cmd_queue
        self.child_process = child_process
        self.setWindowTitle("主进程 - 接收端")
        self.resize(500, 350)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlaceholderText("等待子进程消息...")
        self.shutdown_btn = QPushButton("关闭程序")
        self.shutdown_btn.clicked.connect(self.request_shutdown)

        layout = QVBoxLayout()
        layout.addWidget(self.text_edit)
        layout.addWidget(self.shutdown_btn)
        self.setLayout(layout)

        # 监听消息队列的线程
        self.listener = MainMsgListener(msg_queue)
        self.listener.message_received.connect(self.append_message)
        self.listener.finished.connect(self.on_child_exited)
        self.listener.start()

    def append_message(self, msg):
        self.text_edit.append(msg)

    def request_shutdown(self):
        """点击按钮，通知子进程退出"""
        self.shutdown_btn.setEnabled(False)
        self.shutdown_btn.setText("正在关闭...")
        try:
            self.cmd_queue.put("__QUIT__")
        except (BrokenPipeError, EOFError):
            pass

    def on_child_exited(self):
        """子进程已退出（监听线程结束），等待其完全结束，然后关闭主窗口"""
        if self.child_process.is_alive():
            self.child_process.join(timeout=2)
        self.close()

    def closeEvent(self, event):
        """主窗口关闭时的清理工作"""
        # 如果监听线程仍在运行，强制终止（关闭队列会导致 get 抛出异常）
        if self.listener.isRunning():
            try:
                # 关闭队列的后台线程，导致 get 抛出 OSError 或类似
                self.msg_queue.close()
                self.msg_queue.join_thread()
            except:
                pass
            self.listener.quit()
            self.listener.wait(3000)
        # 确保子进程被终止
        if self.child_process.is_alive():
            self.child_process.terminate()
            self.child_process.join()
        super().closeEvent(event)


# ---------- 启动逻辑 ----------
def main():
    app = QApplication(sys.argv)

    # 创建两个队列
    msg_queue = Queue()   # 子进程 → 主进程（消息）
    cmd_queue = Queue()   # 主进程 → 子进程（命令）

    child = Process(target=run_child, args=(msg_queue, cmd_queue))
    child.start()

    window = MainWindow(msg_queue, cmd_queue, child)
    window.show()

    ret = app.exec_()

    # 程序退出后的资源清理
    try:
        msg_queue.close()
        msg_queue.join_thread()
    except:
        pass
    try:
        cmd_queue.close()
        cmd_queue.join_thread()
    except:
        pass

    sys.exit(ret)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()