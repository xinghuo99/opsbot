import sys
from multiprocessing import Process, Pipe

from PyQt5.QtCore import pyqtSignal, QThread
from PyQt5.QtWidgets import (QApplication, QWidget, QPushButton,
                             QTextEdit, QVBoxLayout)


# ------------------ 子进程：发送窗口 ------------------
class ChildListener(QThread):
    """子进程监听线程：等待主进程的退出命令"""
    quit_received = pyqtSignal()

    def __init__(self, conn):
        super().__init__()
        self.conn = conn

    def run(self):
        try:
            while True:
                msg = self.conn.recv()
                if msg == "__QUIT__":
                    self.quit_received.emit()  # 通知主线程退出
                    break
        except EOFError:
            # 管道对端关闭，线程自动结束
            pass
        finally:
            self.conn.close()


class ChildWindow(QWidget):
    def __init__(self, child_conn):
        super().__init__()
        self.child_conn = child_conn
        self.setWindowTitle("子进程 - 消息发送端")
        self.resize(400, 300)

        # 界面控件
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("在此输入要发送的消息...")
        self.send_btn = QPushButton("发送到主进程")
        self.send_btn.clicked.connect(self.send_message)

        layout = QVBoxLayout()
        layout.addWidget(self.text_edit)
        layout.addWidget(self.send_btn)
        self.setLayout(layout)

        # 启动监听线程（等待主进程的退出指令）
        self.listener = ChildListener(child_conn)
        self.listener.quit_received.connect(self.on_quit_received)
        self.listener.start()

    def send_message(self):
        """将输入框内容通过管道发送给主进程"""
        text = self.text_edit.toPlainText().strip()
        if text:
            try:
                self.child_conn.send(text)
            except BrokenPipeError:
                # 主进程已关闭管道，可忽略
                pass

    def on_quit_received(self):
        """收到退出指令，关闭本窗口和事件循环"""
        QApplication.instance().quit()

    def closeEvent(self, event):
        """窗口关闭时保证监听线程安全结束"""
        self.listener.quit()
        self.listener.wait()
        super().closeEvent(event)


def run_child(child_conn):
    """子进程入口"""
    app = QApplication(sys.argv)
    window = ChildWindow(child_conn)
    window.show()
    sys.exit(app.exec())


# ------------------ 主进程：接收窗口 ------------------
class MainListener(QThread):
    """主进程监听线程：循环接收子进程消息"""
    message_received = pyqtSignal(str)
    finished = pyqtSignal()  # 线程正常结束时的通知

    def __init__(self, conn):
        super().__init__()
        self.conn = conn

    def run(self):
        try:
            while True:
                msg = self.conn.recv()
                # 收到子进程消息，发射信号显示
                self.message_received.emit(msg)
        except EOFError:
            # 管道对端（子进程）关闭，循环退出
            pass
        finally:
            self.conn.close()
            self.finished.emit()


class MainWindow(QWidget):
    def __init__(self, parent_conn, child_process):
        super().__init__()
        self.parent_conn = parent_conn
        self.child_process = child_process
        self.setWindowTitle("主进程 - 消息接收端")
        self.resize(500, 350)

        # 界面控件
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlaceholderText("等待子进程消息...")
        self.shutdown_btn = QPushButton("关闭程序")
        self.shutdown_btn.clicked.connect(self.request_shutdown)

        layout = QVBoxLayout()
        layout.addWidget(self.text_edit)
        layout.addWidget(self.shutdown_btn)
        self.setLayout(layout)

        # 启动监听线程
        self.listener = MainListener(parent_conn)
        self.listener.message_received.connect(self.append_message)
        self.listener.finished.connect(self.on_listener_finished)
        self.listener.start()

    def append_message(self, msg):
        """将收到的消息显示到文本框"""
        self.text_edit.append(msg)

    def request_shutdown(self):
        """点击关闭按钮：通知子进程退出"""
        self.shutdown_btn.setEnabled(False)
        self.shutdown_btn.setText("正在关闭...")
        # 发送退出指令（子进程收到后会关闭自身，管道对端随之关闭）
        self.parent_conn.send("__QUIT__")

    def on_listener_finished(self):
        """监听线程因管道关闭而结束时调用"""
        # 等待子进程彻底退出
        self.child_process.join()
        # 关闭主窗口，结束主事件循环
        self.close()


def main():
    # 主进程 PyQt 应用（无 GUI 时需要 QApplication 来驱动事件循环）
    app = QApplication(sys.argv)

    # 创建双向管道（主、子均可读写）
    parent_conn, child_conn = Pipe(duplex=True)

    # 启动子进程
    child = Process(target=run_child, args=(child_conn,))
    child.start()
    child_conn.close()  # 主进程不再需要子进程端的连接

    # 创建并显示主窗口
    window = MainWindow(parent_conn, child)
    window.show()

    # 进入事件循环
    ret = app.exec()
    # 确保线程和进程完全退出
    if window.listener.isRunning():
        window.listener.wait()
    sys.exit(ret)


if __name__ == "__main__":
    main()