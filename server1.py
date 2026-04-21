"""Client side - Send messages and receive automated responses."""

import socket
import threading

HOST = "127.0.0.1"
PORT = 5000

def receive_responses(sock):
    """Receive and display responses from server."""
    try:
        while True:
            data = sock.recv(1024)
            if not data:
                print("\n[Connection closed by server]")
                break
            
            response = data.decode('utf-8', errors='replace')
            print(f"\nBot: {response}\n> ", end="")
            
    except ConnectionResetError:
        print("\n[Connection reset by server]")
    except OSError as e:
        print(f"\n[Error: {e}]")
    finally:
        try:
            sock.close()
        except:
            pass


def send_messages(sock):
    """Send user messages to server."""
    try:
        print("Enter your messages (type '/quit' to exit):\n")
        while True:
            message = input("> ").strip()
            
            if not message:
                continue
            
            if message.lower() == "/quit":
                print("[Closing connection...]")
                break
            
            sock.sendall(message.encode('utf-8'))
            
    except (EOFError, KeyboardInterrupt):
        print("\n[Connection interrupted]")
    finally:
        try:
            sock.close()
        except:
            pass


def main():
    print(f"[CLIENT] Connecting to {HOST}:{PORT}...")
    print("[CLIENT] Make sure host1.py is running!\n")
    
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((HOST, PORT))
        print("[CLIENT] Connected!\n")
        
        # Start receiver thread
        receiver_thread = threading.Thread(target=receive_responses, args=(client_socket,), daemon=True)
        receiver_thread.start()
        
        # Send messages from main thread
        send_messages(client_socket)
        
        receiver_thread.join(timeout=1)
        
    except ConnectionRefusedError:
        print("[CLIENT] Error: Could not connect to server")
        print("[CLIENT] Make sure host1.py is running first!")
    except OSError as e:
        print(f"[CLIENT] Error: {e}")
    finally:
        print("[CLIENT] Disconnected")


if __name__ == "__main__":
    main()
