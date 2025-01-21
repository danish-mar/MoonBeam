import socket
import ssl
import threading
import json
import logging
from queue import Queue
from threading import Lock
import time
from typing import Dict, List, Optional

class ProxyConfig:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config: Dict = {}
        self.lock = Lock()
        self.load_config()
        
    def load_config(self):
        with self.lock:
            with open(self.config_path, 'r') as f:
                self.config = json.load(f)
    
    def get_backend_servers(self) -> List[str]:
        with self.lock:
            return self.config.get('backend_servers', [])
    
    def get_ssl_config(self) -> Dict:
        with self.lock:
            return self.config.get('ssl', {})

class LoadBalancer:
    def __init__(self):
        self.current = 0
        self.lock = Lock()
    
    def get_next_server(self, servers: List[str]) -> str:
        with self.lock:
            if not servers:
                raise ValueError("No backend servers available")
            server = servers[self.current]
            self.current = (self.current + 1) % len(servers)
            return server

class ProxyServer:
    def __init__(self, host: str, port: int, config_path: str):
        self.host = host
        self.port = port
        self.config = ProxyConfig(config_path)
        self.load_balancer = LoadBalancer()
        self.setup_logging()
        
    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
    
    def create_ssl_context(self) -> Optional[ssl.SSLContext]:
        ssl_config = self.config.get_ssl_config()
        if not ssl_config:
            return None
            
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(
            certfile=ssl_config['cert_file'],
            keyfile=ssl_config['key_file']
        )
        return context
    
    def handle_client(self, client_socket: socket.socket, address: str):
        try:
            backend_servers = self.config.get_backend_servers()
            target_server = self.load_balancer.get_next_server(backend_servers)
            
            # Parse target server address
            target_host, target_port = target_server.split(':')
            target_port = int(target_port)
            
            # Connect to backend server
            backend_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            backend_socket.connect((target_host, target_port))
            
            # Set up bidirectional data forwarding
            def forward(source: socket.socket, destination: socket.socket):
                try:
                    while True:
                        data = source.recv(8192)
                        if not data:
                            break
                        destination.send(data)
                except Exception as e:
                    logging.error(f"Forwarding error: {e}")
                finally:
                    source.close()
                    destination.close()
            
            # Create threads for bidirectional forwarding
            client_to_backend = threading.Thread(
                target=forward,
                args=(client_socket, backend_socket)
            )
            backend_to_client = threading.Thread(
                target=forward,
                args=(backend_socket, client_socket)
            )
            
            client_to_backend.start()
            backend_to_client.start()
            
        except Exception as e:
            logging.error(f"Error handling client {address}: {e}")
            client_socket.close()
    
    def start(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((self.host, self.port))
        server_socket.listen(100)
        
        ssl_context = self.create_ssl_context()
        if ssl_context:
            server_socket = ssl_context.wrap_socket(
                server_socket,
                server_side=True
            )
        
        logging.info(f"Proxy server started on {self.host}:{self.port}")
        
        while True:
            try:
                client_socket, address = server_socket.accept()
                logging.info(f"New connection from {address}")
                
                client_thread = threading.Thread(
                    target=self.handle_client,
                    args=(client_socket, address)
                )
                client_thread.daemon = True
                client_thread.start()
                
            except Exception as e:
                logging.error(f"Error accepting connection: {e}")

if __name__ == "__main__":

    
    proxy = ProxyServer("0.0.0.0", 443, "config.json")
    proxy.start()