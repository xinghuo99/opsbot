"""
进程间通信示例：父进程非阻塞方式接收子进程发送的字符串。
- 子进程使用 sys.exit(app.exec()) 方式运行 Qt 事件循环
- 父进程退出时自动关闭子进程
"""

import sys
import atexit
import multiprocessing
import time
import random

from PyQt5.QtWidgets import QApplication, QLabel
from PyQt5.QtCore import QTimer


def child_task(conn):
    """子进程A：以 Qt 事件循环方式运行，完成特定任务后向父进程发送字符串"""
    app = QApplication(sys.argv)

    label = QLabel("子进程A运行中...")
    label.show()

    def on_task_finished():
        delay = random.uniform(1, 4)
        result = f"子进程任务完成 (耗时 {delay:.1f}s)"
        conn.send(result)
        conn.close()
        app.quit()

    QTimer.singleShot(int(random.uniform(1, 4) * 1000), on_task_finished)

    sys.exit(app.exec())


def main():
    parent_conn, child_conn = multiprocessing.Pipe()

    proc = multiprocessing.Process(target=child_task, args=(child_conn,))
    proc.start()
    child_conn.close()

    # 注册退出清理：父进程退出时关闭子进程
    atexit.register(lambda: proc.terminate() if proc.is_alive() else None)

    print("父进程：子进程A已启动（Qt事件循环），父进程继续工作（非阻塞）...")

    received = False
    while not received:
        try:
            if parent_conn.poll():
                msg = parent_conn.recv()
                print(f"父进程收到: {msg}")
                received = True
        except (EOFError, OSError):
            break

        if not proc.is_alive() and not received:
            break

        if not received:
            print("父进程做其他事情...")
            time.sleep(0.5)

    # 清理子进程
    if proc.is_alive():
        proc.terminate()
    proc.join()
    parent_conn.close()
    print("父进程：结束")


if __name__ == "__main__":
    main()