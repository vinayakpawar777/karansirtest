"""Client side - Send messages and receive automated responses.
Supports image and audio compression/retrieval commands."""

import socket
import threading

HOST = "127.0.0.1"
PORT = 5000


def receive_responses(sock):
    """Receive and display responses from server."""
    try:
        while True:
            data = sock.recv(4096)
            if not data:
                print("\n[CLIENT] Connection closed by server")
                break

            response = data.decode('utf-8', errors='replace')
            print(f"\nBot:\n{response}\n")
            print("> ", end="", flush=True)

    except ConnectionResetError:
        print("\n[CLIENT] Connection reset by server")
    except OSError as e:
        print(f"\n[CLIENT] Error: {e}")
    finally:
        try:
            sock.close()
        except Exception:
            pass


def print_help():
    """Print available commands."""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║                     AVAILABLE COMMANDS                          ║
╠══════════════════════════════════════════════════════════════════╣
║  📷 IMAGE COMMANDS                                              ║
║    !upload /path/to/image.jpg                                   ║
║        → Compresses image (JPEG 94%) and stores features        ║
║    !retrieve images/metadata_YYYYMMDD_HHMMSS.json               ║
║        → Retrieves high-quality PNG using stored features       ║
║                                                                  ║
║  🎵 AUDIO COMMANDS                                              ║
║    !upload_audio /path/to/audio.wav                             ║
║        → Compresses audio (downsample to 8kHz) & stores data   ║
║    !retrieve_audio audio/metadata_YYYYMMDD_HHMMSS.json          ║
║        → Retrieves high-quality WAV (upsampled + normalized)   ║
║                                                                  ║
║  📋 GENERAL COMMANDS                                            ║
║    !list         → List all stored metadata files               ║
║    help          → Show this help message                       ║
║    /quit         → Exit client                                  ║
╚══════════════════════════════════════════════════════════════════╝
""")


def send_messages(sock):
    """Send user messages to server."""
    print_help()
    print("Type your message or a command above. Press Enter to send.\n")

    try:
        while True:
            try:
                message = input("> ").strip()
            except EOFError:
                break

            if not message:
                continue

            if message.lower() == "/quit":
                print("[CLIENT] Closing connection...")
                break

            if message.lower() in ("help", "?"):
                print_help()
                continue

            sock.sendall(message.encode('utf-8'))

    except KeyboardInterrupt:
        print("\n[CLIENT] Interrupted by user")
    finally:
        try:
            sock.close()
        except Exception:
            pass


def main():
    print(f"[CLIENT] Connecting to {HOST}:{PORT}...")
    print("[CLIENT] Make sure host1.py is running first!\n")

    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((HOST, PORT))
        print("[CLIENT] Connected!\n")

        # Start receiver thread (daemon so it exits when main thread exits)
        receiver_thread = threading.Thread(
            target=receive_responses,
            args=(client_socket,),
            daemon=True
        )
        receiver_thread.start()

        # Main thread handles sending
        send_messages(client_socket)

        receiver_thread.join(timeout=1)

    except ConnectionRefusedError:
        print("[CLIENT] Error: Could not connect to server.")
        print("[CLIENT] Make sure host1.py is running first!")
    except OSError as e:
        print(f"[CLIENT] Error: {e}")
    finally:
        print("[CLIENT] Disconnected.")


if __name__ == "__main__":
    main()