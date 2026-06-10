import sys
from multiprocessing import Process, Queue

from PyQt5.QtCore import pyqtSignal, QThread
from PyQt5.QtWidgets import (QApplication, QWidget, QPushButton,
                             QTextEdit, QVBoxLayout)


# ------------------ 子进程：发送窗口 ------------------
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
            # 主进程强制关闭管道时触发
            pass


class ChildWindow(QWidget):
    def __init__(self, msg_queue, cmd_queue):
        super().__init__()
        self.msg_queue = msg_queue
        self.cmd_queue = cmd_queue
        self.setWindowTitle("子进程 - 消息发送端")
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
                pass  # 主进程已退出，忽略

    def on_quit_received(self):
        # 收到退出命令，向主进程发送终止标记，然后关闭自身
        try:
            self.msg_queue.put(None)  # 通知主进程监听线程结束
        except (BrokenPipeError, EOFError):
            pass
        QApplication.instance().quit()

    def closeEvent(self, event):
        # 窗口被关闭（如用户点击X）时，也尝试发送终止标记
        try:
            self.msg_queue.put(None)
        except (BrokenPipeError, EOFError):
            pass
        self.cmd_listener.quit()
        self.cmd_listener.wait()
        super().closeEvent(event)


def run_child(msg_queue, cmd_queue):
    app = QApplication(sys.argv)
    window = ChildWindow(msg_queue, cmd_queue)
    window.show()
    sys.exit(app.exec())


# ------------------ 主进程：接收窗口 ------------------
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
        self.setWindowTitle("主进程 - 消息接收端")
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
        self.listener.finished.connect(self.on_listener_finished)
        self.listener.start()

    def append_message(self, msg):
        self.text_edit.append(msg)

    def request_shutdown(self):
        self.shutdown_btn.setEnabled(False)
        self.shutdown_btn.setText("正在关闭...")
        # 向子进程发送退出命令
        self.cmd_queue.put("__QUIT__")

    def on_listener_finished(self):
        # 消息监听线程结束后，等待子进程退出，然后关闭主窗口
        self.child_process.join()
        self.close()


def main():
    app = QApplication(sys.argv)

    # 创建两个队列：一个用于子进程向主进程发送消息，一个用于主进程向子进程发送命令
    msg_queue = Queue()
    cmd_queue = Queue()

    child = Process(target=run_child, args=(msg_queue, cmd_queue))
    child.start()

    window = MainWindow(msg_queue, cmd_queue, child)
    window.show()

    ret = app.exec()
    # 清理：确保所有线程结束，并正确关闭队列
    if window.listener.isRunning():
        window.listener.quit()
        window.listener.wait()
    msg_queue.close()
    msg_queue.join_thread()
    cmd_queue.close()
    cmd_queue.join_thread()
    sys.exit(ret)


if __name__ == "__main__":
    main()