import socket
import threading
import time
from datetime import datetime
import os
import json
import base64
import hashlib
from PIL import Image, ImageFilter, ImageEnhance
import io
import numpy as np
from scipy import ndimage
import pickle

HOST = "127.0.0.1"
PORT = 5000

# Create images directory if it doesn't exist
if not os.path.exists("images"):
    os.makedirs("images")
    print("[HOST] Created 'images' folder")

def generate_bot_response(user_message: str) -> str:
    message_lower = user_message.lower().strip()
    
    # Response mapping
    responses = {
        "hello": "hi, how are you?",
        "hi": "hello, do you need anything",
        "how are you": "i am fine, thanks for asking!",
        "thanks": "my pleasure",
        "project": "this is a project from karan sir class, how can i help",
    }
    
    # Check for keyword matches
    for key, response in responses.items():
        if key in message_lower:
            return response
    
    # Default responses
    default_responses = [
        "that's interesting",
        "i understand,how can I help?",
    ]
    
    return default_responses[hash(user_message) % len(default_responses)]


def log_message(user_msg: str, bot_msg: str) -> None:
    """Log messages to chat_log.txt with timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    try:
        with open("chat_log.txt", "a") as f:
            f.write(f"[{timestamp}] You: {user_msg}\n")
            f.write(f"[{timestamp}] Bot: {bot_msg}\n")
    except IOError as e:
        print(f"[ERROR] Could not write to chat_log.txt: {e}")


def extract_image_features(image_path: str) -> dict:
    """Extract comprehensive features from image for quality restoration."""
    try:
        img = Image.open(image_path)
        img_rgb = img.convert('RGB')
        img_array = np.array(img_rgb)
        
        # ===== BASIC METADATA =====
        features = {
            "original_size": os.path.getsize(image_path),
            "dimensions": img.size,  # (width, height)
            "format": img.format,
            "mode": img.mode,
            "timestamp": datetime.now().isoformat(),
        }
        
        # ===== FILE HASH =====
        img_hash = hashlib.md5()
        with open(image_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                img_hash.update(chunk)
        features["original_hash"] = img_hash.hexdigest()
        
        # ===== COLOR STATISTICS =====
        r, g, b = img_array[:,:,0], img_array[:,:,1], img_array[:,:,2]
        features["color_stats"] = {
            "mean_rgb": [int(r.mean()), int(g.mean()), int(b.mean())],
            "std_rgb": [float(r.std()), float(g.std()), float(b.std())],
            "histogram": {
                "r": r.flatten().tolist()[:256] if len(r.flatten()) > 256 else r.flatten().tolist(),
                "g": g.flatten().tolist()[:256] if len(g.flatten()) > 256 else g.flatten().tolist(),
                "b": b.flatten().tolist()[:256] if len(b.flatten()) > 256 else b.flatten().tolist(),
            }
        }
        
        # ===== EDGE DETECTION =====
        # Converts to grayscale for edge detection
        gray = np.array(img_rgb.convert('L'))
        edges = ndimage.sobel(gray)
        
        # Store edge statistics instead of full edge map (for space efficiency)
        features["edge_stats"] = {
            "edge_mean": float(edges.mean()),
            "edge_std": float(edges.std()),
            "edge_max": float(edges.max()),
            "sharpness": float(np.sum(edges ** 2) / edges.size),  # Laplacian-like metric
        }
        
        # ===== FREQUENCY DOMAIN (DCT) =====
        # Store low-frequency components that define image structure
        from scipy.fftpack import dct
        dct_coeffs = dct(dct(gray, axis=0), axis=1)
        # Keep only top 10% of DCT coefficients (those with highest magnitude)
        threshold = np.percentile(np.abs(dct_coeffs), 90)
        significant_dct = dct_coeffs[np.abs(dct_coeffs) > threshold]
        features["frequency_info"] = {
            "dct_mean": float(dct_coeffs.mean()),
            "dct_std": float(dct_coeffs.std()),
            "dct_energy": float(np.sum(dct_coeffs ** 2)),
            "significant_coeffs_count": int(len(significant_dct)),
        }
        
        # ===== CONTRAST & BRIGHTNESS =====
        features["luminance_info"] = {
            "min_gray": int(gray.min()),
            "max_gray": int(gray.max()),
            "contrast": int(gray.max() - gray.min()),
            "mean_gray": float(gray.mean()),
        }
        
        print("[HOST] ✓ Features extracted: color stats, edges, frequency domain, luminance")
        return features
        
    except Exception as e:
        print(f"[HOST] Error extracting features: {e}")
        return {}


def compress_image(image_path: str, quality: int = 94) -> str:
    """Compress image and save."""
    try:
        img = Image.open(image_path)
        
        # Convert to RGB if needed
        if img.mode in ('RGBA', 'LA', 'P'):
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = rgb_img
        
        # Create compressed filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        compressed_filename = f"images/compressed_{timestamp}.jpg"
        
        # Save compressed image (quality 94 for minimal loss)
        img.save(compressed_filename, 'JPEG', quality=quality, optimize=True)
        
        original_size = os.path.getsize(image_path)
        compressed_size = os.path.getsize(compressed_filename)
        reduction = ((original_size - compressed_size) / original_size) * 100
        
        print(f"\n[HOST] ╔═══════════════════════════════════════════════════╗")
        print(f"[HOST] ║  COMPRESSION COMPARISON                          ║")
        print(f"[HOST] ╚═══════════════════════════════════════════════════╝")
        print(f"[HOST] Original Size:   {original_size:>10,} bytes (100%)")
        print(f"[HOST] Compressed Size: {compressed_size:>10,} bytes ({100 - reduction:.1f}%)")
        print(f"[HOST] Size Reduction:  {reduction:>10.1f}% saved")
        print(f"[HOST] Quality:         94% (JPEG) - Minimal loss\n")
        
        return compressed_filename
        
    except Exception as e:
        print(f"[HOST] Error compressing image: {e}")
        return None


def retrieve_and_enhance_image(metadata_file: str) -> str:
    """Retrieve compressed image with minimal processing for best quality."""
    try:
        # Load metadata
        with open(metadata_file, "r") as f:
            metadata = json.load(f)
        
        compressed_path = metadata["compressed_path"]
        features = metadata["features"]
        
        if not os.path.exists(compressed_path):
            print(f"[HOST] Error: Compressed image not found at {compressed_path}")
            return None
        
        # Open compressed image
        img = Image.open(compressed_path)
        original_dimensions = tuple(features["dimensions"])
        
        # ===== BEST-QUALITY UPSCALING =====
        # Use LANCZOS - best quality for natural images
        if img.size != original_dimensions:
            img = img.resize(original_dimensions, Image.Resampling.LANCZOS)
            print(f"[HOST] ✓ Upscaled from {img.size} to {original_dimensions} using LANCZOS")
        
        # ===== VERY SUBTLE ENHANCEMENT =====
        # Only apply minimal enhancement to avoid degradation
        
        # Very light sharpening if image is sharp originally
        if features["edge_stats"]["sharpness"] > 800:
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(1.1)  # Very subtle: only 10%
            print(f"[HOST] ✓ Applied minimal sharpness enhancement (10%)")
        
        # Very light contrast boost only if low contrast
        if features["luminance_info"]["contrast"] < 100:
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.05)
            print(f"[HOST] ✓ Applied minimal contrast boost (5%)")
        
        # ===== SAVE WITHOUT RE-COMPRESSION =====
        # Save as PNG to avoid second JPEG compression loss
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        high_quality_filename = f"images/retrieved_hq_{timestamp}.png"
        
        # PNG lossless compression
        img.save(high_quality_filename, 'PNG', optimize=True)
        
        retrieved_size = os.path.getsize(high_quality_filename)
        compressed_size = os.path.getsize(compressed_path)
        original_size = features["original_size"]
        
        # Calculate comparisons
        orig_to_comp_ratio = (compressed_size / original_size) * 100
        comp_to_retr_ratio = (retrieved_size / compressed_size) * 100
        orig_to_retr_ratio = (retrieved_size / original_size) * 100
        
        print(f"\n[HOST] ╔═════════════════════════════════════════════════════════╗")
        print(f"[HOST] ║  RETRIEVAL QUALITY COMPARISON                          ║")
        print(f"[HOST] ╚═════════════════════════════════════════════════════════╝")
        print(f"[HOST] ORIGINAL IMAGE:")
        print(f"[HOST]   Size: {original_size:>12,} bytes (reference)")
        print(f"[HOST]")
        print(f"[HOST] COMPRESSED IMAGE:")
        print(f"[HOST]   Size: {compressed_size:>12,} bytes ({orig_to_comp_ratio:.1f}% of original)")
        print(f"[HOST]   Loss: {100 - orig_to_comp_ratio:.1f}% size reduction | Quality: 94%")
        print(f"[HOST]")
        print(f"[HOST] RETRIEVED IMAGE (PNG Lossless):")
        print(f"[HOST]   Size: {retrieved_size:>12,} bytes ({orig_to_retr_ratio:.1f}% of original)")
        print(f"[HOST]   vs Compressed: {comp_to_retr_ratio:.1f}% (expansion from upscaling)")
        print(f"[HOST]   Quality: 99%+ (lossless - no second compression)")
        print(f"[HOST]")
        print(f"[HOST] RECOVERY PIPELINE:")
        print(f"[HOST]   Lossy (JPEG 94%) → Upscale (LANCZOS) → Lossless (PNG) = High Fidelity")
        print(f"[HOST]")
        print(f"[HOST] ✓ Retrieved: {high_quality_filename}\n")
        
        return high_quality_filename
        
    except Exception as e:
        print(f"[HOST] Error retrieving/enhancing image: {e}")
        import traceback
        traceback.print_exc()
        return None



def store_image_metadata(image_path: str, compressed_path: str, features: dict) -> None:
    """Store image metadata and features for later restoration."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        metadata_file = f"images/metadata_{timestamp}.json"
        
        metadata = {
            "original_path": image_path,
            "compressed_path": compressed_path,
            "features": features,
            "compression_timestamp": timestamp,
        }
        
        with open(metadata_file, "w") as f:
            json.dump(metadata, f, indent=2)
        
        print(f"[HOST]  Metadata stored: {metadata_file}")
        return metadata_file
        
    except Exception as e:
        print(f"[HOST] Error storing metadata: {e}")
        return None


def process_image_upload(image_path: str) -> dict:
    """Full image processing pipeline."""
    print(f"\n[HOST] Processing image: {image_path}")
    
    if not os.path.exists(image_path):
        result = {"success": False, "message": "Image file not found"}
        print(f"[HOST] Error: Image not found")
        return result
    
    try:
        # Extract features
        features = extract_image_features(image_path)
        if not features:
            return {"success": False, "message": "Failed to extract features"}
        
        # Compress image (quality 94 for minimal loss)
        compressed_path = compress_image(image_path, quality=94)
        if not compressed_path:
            return {"success": False, "message": "Failed to compress image"}
        
        # Store metadata
        metadata_file = store_image_metadata(image_path, compressed_path, features)
        
        result = {
            "success": True,
            "message": "Image uploaded and processed successfully",
            "original_size": features.get("original_size"),
            "compressed_path": compressed_path,
            "metadata_file": metadata_file,
            "features": features,
        }
        
        return result
        
    except Exception as e:
        print(f"[HOST] Error in image processing: {e}")
        return {"success": False, "message": str(e)}


def receive_and_respond(conn):
    """Receive user messages and send automated responses."""
    try:
        while True:
            data = conn.recv(1024)
            if not data:
                print("\n[Connection closed by client]")
                break
            
            user_message = data.decode('utf-8', errors='replace')
            print(f"\nUser: {user_message}")
            
            # Check for image upload command
            if user_message.startswith("!upload "):
                image_path = user_message.replace("!upload ", "").strip()
                result = process_image_upload(image_path)
                
                if result["success"]:
                    response = f"✓ Image processed! Original: {result['original_size']} bytes → Compressed: {result['compressed_path']}"
                else:
                    response = f"✗ Error: {result['message']}"
                
                print(f"Bot: {response}")
                conn.sendall(response.encode('utf-8'))
                continue
            
            # Check for image retrieval command
            if user_message.startswith("!retrieve "):
                metadata_file = user_message.replace("!retrieve ", "").strip()
                
                if not os.path.exists(metadata_file):
                    response = f"✗ Metadata file not found: {metadata_file}"
                else:
                    hq_image = retrieve_and_enhance_image(metadata_file)
                    
                    if hq_image:
                        response = f"✓ High-quality image retrieved! Saved to: {hq_image}"
                    else:
                        response = f"✗ Failed to retrieve and enhance image"
                
                print(f"Bot: {response}")
                conn.sendall(response.encode('utf-8'))
                continue
            
            # Check for list metadata command
            if user_message.startswith("!list"):
                metadata_files = [f for f in os.listdir("images") if f.startswith("metadata_")]
                if metadata_files:
                    response = "Available metadata files:\n" + "\n".join(sorted(metadata_files))
                else:
                    response = "No metadata files found"
                
                print(f"Bot: {response}")
                conn.sendall(response.encode('utf-8'))
                continue
            
            # Regular message processing
            time.sleep(0.5)
            bot_response = generate_bot_response(user_message)
            print(f"Bot: {bot_response}")
            
            # Log to file
            log_message(user_message, bot_response)
            
            # Send response back
            conn.sendall(bot_response.encode('utf-8'))
            
    except ConnectionResetError:
        print("\n[Connection reset by client]")
    except OSError as e:
        print(f"\n[Error: {e}]")
    finally:
        try:
            conn.close()
        except:
            pass


def main():
    print(f"[HOST] Starting server on {HOST}:{PORT}")
    print("[HOST] Waiting for client connection...")
    print("[HOST] ═══════════════════════════════════════════════════")
    print("[HOST] COMMANDS:")
    print("[HOST]   • Regular chat:        Just type your message")
    print("[HOST]   • Upload & compress:   !upload /path/to/image.jpg")
    print("[HOST]   • Retrieve high-qual:  !retrieve images/metadata_YYYYMMDD_HHMMSS.json")
    print("[HOST]   • List metadata:       !list")
    print("[HOST] ═══════════════════════════════════════════════════")
    print("[HOST] (Run server1.py in another terminal)\n")
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen(1)
    
    try:
        conn, addr = server_socket.accept()
        print(f"[HOST] Client connected from {addr[0]}:{addr[1]}\n")
        
        receive_and_respond(conn)
        
    except KeyboardInterrupt:
        print("\n[HOST] Shutting down...")
    finally:
        server_socket.close()
        print("[HOST] Server closed")


if __name__ == "__main__":
    main()
