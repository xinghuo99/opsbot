import socket
import json
import logging
from datetime import datetime

# 配置日志
logging.basicConfig(
    filename='clientlog',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

def get_client_ip():
    # 获取客户端IP地址
    try:
        # 创建一个临时套接字来获取本地IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'

def main():
    # 创建TCP套接字
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    # 连接到服务端
    server_address = ('localhost', 8888)
    logging.info(f'正在连接到服务器 {server_address}...')
    print(f'正在连接到服务器 {server_address}...')
    
    try:
        client_socket.connect(server_address)
        logging.info('连接成功！')
        print('连接成功！')
        
        # 获取客户端IP地址
        client_ip = get_client_ip()
        
        # 构造JSON数据
        data = {
            'ip': client_ip,
            'greeting': 'Hello, server!',
            'time': datetime.now().isoformat()
        }
        
        # 发送数据
        client_socket.sendall(json.dumps(data).encode('utf-8'))
        logging.info(f'已发送数据: {data}')
        print(f'已发送数据: {data}')
        
        # 持续接收服务端消息
        print('等待接收服务端消息...')
        while True:
            try:
                # 接收服务端消息
                message = client_socket.recv(1024).decode('utf-8')
                if message:
                    logging.info(f'收到服务端消息: {message}')
                    print(f'收到服务端消息: {message}')
                else:
                    # 连接已关闭
                    break
            except Exception as e:
                logging.error(f'接收消息时出错: {e}')
                print(f'接收消息时出错: {e}')
                break
        
    except Exception as e:
        logging.error(f'连接服务器时出错: {e}')
        print(f'连接服务器时出错: {e}')
    finally:
        # 关闭连接
        client_socket.close()
        logging.info('连接已关闭')
        print('连接已关闭')

if __name__ == '__main__':
    main()