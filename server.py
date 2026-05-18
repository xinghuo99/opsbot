import socket
import json
import os
import logging

# 配置日志
logging.basicConfig(
    filename='serverlog',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

def main():
    # 创建TCP套接字
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    # 绑定地址和端口
    server_address = ('', 8888)
    server_socket.bind(server_address)
    
    # 开始监听
    server_socket.listen(5)
    logging.info('服务器已启动，等待客户端连接...')
    print('服务器已启动，等待客户端连接...')
    
    # 存储客户端信息的字典
    clients = {}
    client_id = 0
    
    # 启动一个线程来处理群发消息
    import threading
    def broadcast_message():
        # 自动发送测试消息
        import time
        time.sleep(5)  # 等待5秒，确保客户端已连接
        test_message = 'Hello from server! This is a test message.'
        print(f'\n发送测试消息: {test_message}')
        # 遍历所有客户端并发送消息
        for client_name, (client_socket, client_address) in clients.items():
            try:
                client_socket.sendall(test_message.encode('utf-8'))
                logging.info(f'已向客户端 {client_name} ({client_address[0]}) 发送消息: {test_message}')
                print(f'已向客户端 {client_name} ({client_address[0]}) 发送消息: {test_message}')
            except Exception as e:
                logging.error(f'向客户端 {client_name} 发送消息时出错: {e}')
                print(f'向客户端 {client_name} 发送消息时出错: {e}')
        
        # 继续等待用户输入
        while True:
            message = input('请输入要群发的消息（输入exit退出）: ')
            if message == 'exit':
                break
            # 遍历所有客户端并发送消息
            for client_name, (client_socket, client_address) in clients.items():
                try:
                    client_socket.sendall(message.encode('utf-8'))
                    logging.info(f'已向客户端 {client_name} ({client_address[0]}) 发送消息: {message}')
                    print(f'已向客户端 {client_name} ({client_address[0]}) 发送消息: {message}')
                except Exception as e:
                    logging.error(f'向客户端 {client_name} 发送消息时出错: {e}')
                    print(f'向客户端 {client_name} 发送消息时出错: {e}')
    
    # 启动广播线程
    broadcast_thread = threading.Thread(target=broadcast_message)
    broadcast_thread.daemon = True
    broadcast_thread.start()
    
    # 处理单个客户端的函数
    def handle_client(client_socket, client_address, client_name):
        try:
            # 接收客户端数据
            data = client_socket.recv(1024).decode('utf-8')
            if data:
                # 解析JSON数据
                client_data = json.loads(data)
                logging.info(f'接收到客户端 {client_name} 数据: {client_data}')
                print(f'接收到客户端 {client_name} 数据: {client_data}')
                
                # 以IP地址为文件名，存储问候语
                ip_address = client_address[0]
                file_name = f'{ip_address}.json'
                
                # 构建存储数据
                storage_data = {
                    'greeting': client_data.get('greeting', ''),
                    'time': client_data.get('time', '')
                }
                
                # 写入文件
                with open(file_name, 'w', encoding='utf-8') as f:
                    json.dump(storage_data, f, ensure_ascii=False, indent=2)
                
                logging.info(f'已将问候语存储到 {file_name}')
                print(f'已将问候语存储到 {file_name}')
            
            # 保持连接打开，持续监听客户端消息
            while True:
                try:
                    # 接收客户端消息（如果有的话）
                    data = client_socket.recv(1024).decode('utf-8')
                    if not data:
                        # 客户端断开连接
                        break
                    logging.info(f'接收到客户端 {client_name} 消息: {data}')
                    print(f'接收到客户端 {client_name} 消息: {data}')
                except Exception as e:
                    logging.error(f'接收客户端 {client_name} 消息时出错: {e}')
                    print(f'接收客户端 {client_name} 消息时出错: {e}')
                    break
                    
        except Exception as e:
            logging.error(f'处理客户端 {client_name} 数据时出错: {e}')
            print(f'处理客户端 {client_name} 数据时出错: {e}')
        finally:
            # 从客户端列表中移除
            if client_name in clients:
                del clients[client_name]
                logging.info(f'客户端 {client_name} ({client_address[0]}) 已断开连接')
                print(f'客户端 {client_name} ({client_address[0]}) 已断开连接')
                print(f'当前连接的客户端: {list(clients.keys())}')
                
                # 通知其他客户端该客户端已断开
                leave_message = f'客户端 {client_name} 已离开聊天室！当前在线人数: {len(clients)}'
                print(f'\n发送离开消息: {leave_message}')
                for c_name, (c_socket, c_address) in clients.items():
                    try:
                        c_socket.sendall(leave_message.encode('utf-8'))
                        logging.info(f'已向客户端 {c_name} ({c_address[0]}) 发送消息: {leave_message}')
                        print(f'已向客户端 {c_name} ({c_address[0]}) 发送消息: {leave_message}')
                    except Exception as e:
                        logging.error(f'向客户端 {c_name} 发送消息时出错: {e}')
                        print(f'向客户端 {c_name} 发送消息时出错: {e}')
            # 关闭客户端连接
            client_socket.close()
    
    while True:
        # 接受客户端连接
        client_socket, client_address = server_socket.accept()
        client_id += 1
        client_name = f'Client-{client_id}'
        
        # 记录客户端信息
        clients[client_name] = (client_socket, client_address)
        logging.info(f'客户端 {client_name} ({client_address[0]}) 已连接')
        print(f'客户端 {client_name} ({client_address[0]}) 已连接')
        print(f'当前连接的客户端: {list(clients.keys())}')
        
        # 向所有客户端发送欢迎消息
        welcome_message = f'欢迎 {client_name} 加入聊天室！当前在线人数: {len(clients)}'
        print(f'\n发送欢迎消息: {welcome_message}')
        for c_name, (c_socket, c_address) in clients.items():
            try:
                c_socket.sendall(welcome_message.encode('utf-8'))
                logging.info(f'已向客户端 {c_name} ({c_address[0]}) 发送消息: {welcome_message}')
                print(f'已向客户端 {c_name} ({c_address[0]}) 发送消息: {welcome_message}')
            except Exception as e:
                logging.error(f'向客户端 {c_name} 发送消息时出错: {e}')
                print(f'向客户端 {c_name} 发送消息时出错: {e}')
        
        # 为客户端创建一个新线程
        client_thread = threading.Thread(target=handle_client, args=(client_socket, client_address, client_name))
        client_thread.daemon = True
        client_thread.start()

if __name__ == '__main__':
    main()