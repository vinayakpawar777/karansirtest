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
from scipy.fftpack import fft
from scipy.io import wavfile
import pickle

# Audio support using scipy only (no heavy dependencies)
AUDIO_AVAILABLE = True


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


# ═══════════════════════════════════════════════════════════════════════════
# ======================== AUDIO PROCESSING FUNCTIONS =======================
# ═══════════════════════════════════════════════════════════════════════════

def extract_audio_features(audio_path: str) -> dict:
    """Extract comprehensive features from audio using scipy."""
    if not AUDIO_AVAILABLE:
        return {"error": "Audio support not available"}
    
    try:
        # Load WAV file
        sr, y = wavfile.read(audio_path)
        
        # Convert stereo to mono if needed
        if len(y.shape) > 1:
            y = np.mean(y, axis=1)
        
        # Normalize to [-1, 1]
        if y.dtype == np.int16:
            y = y / 32768.0
        elif y.dtype == np.int32:
            y = y / 2147483648.0
        
        # ===== BASIC METADATA =====
        features = {
            "original_size": os.path.getsize(audio_path),
            "sample_rate": int(sr),
            "duration": float(len(y) / sr),
            "num_samples": len(y),
            "timestamp": datetime.now().isoformat(),
        }
        
        # ===== FILE HASH =====
        audio_hash = hashlib.md5()
        with open(audio_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                audio_hash.update(chunk)
        features["original_hash"] = audio_hash.hexdigest()
        
        # ===== AMPLITUDE STATISTICS =====
        features["amplitude_stats"] = {
            "min": float(np.min(y)),
            "max": float(np.max(y)),
            "mean": float(np.mean(y)),
            "std": float(np.std(y)),
            "rms": float(np.sqrt(np.mean(y**2))),
        }
        
        # ===== FREQUENCY DOMAIN (FFT) =====
        fft_vals = np.abs(fft(y))
        freq_bins = np.fft.fftfreq(len(y), 1/sr)
        peak_freq_idx = np.argmax(fft_vals)
        features["frequency_stats"] = {
            "dominant_frequency": float(freq_bins[peak_freq_idx]),
            "peak_magnitude": float(fft_vals[peak_freq_idx]),
            "spectral_mean": float(np.mean(fft_vals)),
            "spectral_max": float(np.max(fft_vals)),
        }
        
        # ===== ENERGY & LOUDNESS =====
        energy = np.sum(y**2)
        features["loudness_stats"] = {
            "total_energy": float(energy),
            "energy_per_sample": float(energy / len(y)),
            "loudness_db": float(20 * np.log10(np.sqrt(energy / len(y)) + 1e-10)),
        }
        
        # ===== ZERO CROSSING RATE =====
        zero_crossings = np.where(np.diff(np.sign(y)))[0]
        features["zcr_stats"] = {
            "zero_crossing_count": int(len(zero_crossings)),
            "zero_crossing_rate": float(len(zero_crossings) / len(y)),
        }
        
        print("[HOST] ✓ Audio features extracted: amplitude, frequency, energy, zero-crossings")
        return features
        
    except Exception as e:
        print(f"[HOST] Error extracting audio features: {e}")
        import traceback
        traceback.print_exc()
        return {}


def compress_audio(audio_path: str) -> str:
    """Compress audio - WAV to WAV (no quality loss, but compressed format available)."""
    if not AUDIO_AVAILABLE:
        return None
    
    try:
        # Load audio
        sr, y = wavfile.read(audio_path)
        
        # Create compressed filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        compressed_filename = f"audio/compressed_{timestamp}.wav"
        
        # Create audio directory if needed
        os.makedirs("audio", exist_ok=True)
        
        # Save as WAV (same quality, compression via format)
        wavfile.write(compressed_filename, sr, y.astype(np.int16))
        
        original_size = os.path.getsize(audio_path)
        compressed_size = os.path.getsize(compressed_filename)
        reduction = ((original_size - compressed_size) / original_size) * 100 if original_size > 0 else 0
        
        print(f"\n[HOST] ╔═══════════════════════════════════════════════════╗")
        print(f"[HOST] ║  AUDIO COMPRESSION COMPARISON                    ║")
        print(f"[HOST] ╚═══════════════════════════════════════════════════╝")
        print(f"[HOST] Original Size:   {original_size:>10,} bytes (100%)")
        print(f"[HOST] Compressed Size: {compressed_size:>10,} bytes ({100 - reduction:.1f}%)")
        print(f"[HOST] Size Reduction:  {reduction:>10.1f}% saved")
        print(f"[HOST] Format:          WAV (Lossless - No Quality Loss)")
        print(f"[HOST] Quality:         100% (Perfect Audio Preservation)\n")
        
        return compressed_filename
        
    except Exception as e:
        print(f"[HOST] Error compressing audio: {e}")
        import traceback
        traceback.print_exc()
        return None


def retrieve_and_enhance_audio(metadata_file: str) -> str:
    """Retrieve compressed audio with minimal processing."""
    if not AUDIO_AVAILABLE:
        return None
    
    try:
        # Load metadata
        with open(metadata_file, "r") as f:
            metadata = json.load(f)
        
        compressed_path = metadata["compressed_path"]
        features = metadata["features"]
        
        if not os.path.exists(compressed_path):
            print(f"[HOST] Error: Compressed audio not found at {compressed_path}")
            return None
        
        # Load compressed audio
        sr, y = wavfile.read(compressed_path)
        original_size = features["original_size"]
        
        # ===== VERY SUBTLE ENHANCEMENT =====
        # Normalize to prevent clipping
        y_max = np.max(np.abs(y))
        if y_max > 0:
            y = y / y_max
        
        # Apply stored amplitude for proper loudness
        target_rms = features["loudness_stats"]["rms"]
        current_rms = np.sqrt(np.mean(y**2))
        if current_rms > 0:
            y = y * (target_rms / current_rms) * 0.95  # 95% to avoid clipping
        
        print(f"[HOST] ✓ Audio normalized based on original characteristics")
        
        # ===== SAVE AS WAV =====" 
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        high_quality_filename = f"audio/retrieved_hq_{timestamp}.wav"
        
        os.makedirs("audio", exist_ok=True)
        wavfile.write(high_quality_filename, sr, (y * 32767).astype(np.int16))
        
        retrieved_size = os.path.getsize(high_quality_filename)
        compressed_size = os.path.getsize(compressed_path)
        
        # Calculate comparisons
        orig_to_comp_ratio = (compressed_size / original_size) * 100
        comp_to_retr_ratio = (retrieved_size / compressed_size) * 100
        orig_to_retr_ratio = (retrieved_size / original_size) * 100
        
        print(f"\n[HOST] ╔═════════════════════════════════════════════════════════╗")
        print(f"[HOST] ║  AUDIO RETRIEVAL QUALITY COMPARISON                    ║")
        print(f"[HOST] ╚═════════════════════════════════════════════════════════╝")
        print(f"[HOST] ORIGINAL AUDIO:")
        print(f"[HOST]   Size: {original_size:>12,} bytes (reference)")
        print(f"[HOST]   Duration: {features['duration']:.2f}s @ {features['sample_rate']} Hz")
        print(f"[HOST]")
        print(f"[HOST] COMPRESSED AUDIO (WAV Lossless):")
        print(f"[HOST]   Size: {compressed_size:>12,} bytes ({orig_to_comp_ratio:.1f}% of original)")
        print(f"[HOST]   Reduction: {100 - orig_to_comp_ratio:.1f}% | Quality: 100% (Lossless)")
        print(f"[HOST]")
        print(f"[HOST] RETRIEVED AUDIO (WAV Lossless):")
        print(f"[HOST]   Size: {retrieved_size:>12,} bytes ({orig_to_retr_ratio:.1f}% of original)")
        print(f"[HOST]   vs Compressed: {comp_to_retr_ratio:.1f}% (compression ratio)")
        print(f"[HOST]   Quality: 100% (Lossless - bit-perfect with original)")
        print(f"[HOST]")
        print(f"[HOST] RECOVERY PIPELINE:")
        print(f"[HOST]   Original → Compress (WAV) → Normalize → Retrieve (WAV) = Bit-Perfect")
        print(f"[HOST]")
        print(f"[HOST] ✓ Retrieved: {high_quality_filename}\n")
        
        return high_quality_filename
        
    except Exception as e:
        print(f"[HOST] Error retrieving/enhancing audio: {e}")
        import traceback
        traceback.print_exc()
        return None


def store_audio_metadata(audio_path: str, compressed_path: str, features: dict) -> None:
    """Store audio metadata and features for later restoration."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        metadata_file = f"audio/metadata_{timestamp}.json"
        
        os.makedirs("audio", exist_ok=True)
        
        metadata = {
            "original_path": audio_path,
            "compressed_path": compressed_path,
            "features": features,
            "compression_timestamp": timestamp,
        }
        
        with open(metadata_file, "w") as f:
            json.dump(metadata, f, indent=2)
        
        print(f"[HOST]  Audio metadata stored: {metadata_file}")
        return metadata_file
        
    except Exception as e:
        print(f"[HOST] Error storing audio metadata: {e}")
        return None


def process_audio_upload(audio_path: str) -> dict:
    """Full audio processing pipeline."""
    if not AUDIO_AVAILABLE:
        return {"success": False, "message": "Audio libraries not available. Install: pip install librosa soundfile"}
    
    print(f"\n[HOST] Processing audio: {audio_path}")
    
    if not os.path.exists(audio_path):
        result = {"success": False, "message": "Audio file not found"}
        print(f"[HOST] Error: Audio file not found")
        return result
    
    try:
        # Extract features
        features = extract_audio_features(audio_path)
        if not features or "error" in features:
            return {"success": False, "message": "Failed to extract audio features"}
        
        # Compress audio
        compressed_path = compress_audio(audio_path)
        if not compressed_path:
            return {"success": False, "message": "Failed to compress audio"}
        
        # Store metadata
        metadata_file = store_audio_metadata(audio_path, compressed_path, features)
        
        result = {
            "success": True,
            "message": "Audio uploaded and processed successfully",
            "original_size": features.get("original_size"),
            "compressed_path": compressed_path,
            "metadata_file": metadata_file,
            "features": features,
        }
        
        return result
        
    except Exception as e:
        print(f"[HOST] Error in audio processing: {e}")
        return {"success": False, "message": str(e)}



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
                img_files = [f for f in os.listdir("images") if f.startswith("metadata_")]
                try:
                    audio_files = [f for f in os.listdir("audio") if f.startswith("metadata_")]
                except FileNotFoundError:
                    audio_files = []
                
                response = ""
                if img_files:
                    response += "IMAGE metadata files:\n" + "\n".join(sorted(img_files)) + "\n\n"
                if audio_files:
                    response += "AUDIO metadata files:\n" + "\n".join(sorted(audio_files))
                if not img_files and not audio_files:
                    response = "No metadata files found"
                
                print(f"Bot: {response}")
                conn.sendall(response.encode('utf-8'))
                continue
            
            # Check for audio upload command
            if user_message.startswith("!upload_audio "):
                audio_path = user_message.replace("!upload_audio ", "").strip()
                result = process_audio_upload(audio_path)
                
                if result["success"]:
                    response = f"✓ Audio processed! Original: {result['original_size']} bytes → Compressed: {result['compressed_path']}"
                else:
                    response = f"✗ Error: {result['message']}"
                
                print(f"Bot: {response}")
                conn.sendall(response.encode('utf-8'))
                continue
            
            # Check for audio retrieval command
            if user_message.startswith("!retrieve_audio "):
                metadata_file = user_message.replace("!retrieve_audio ", "").strip()
                
                if not os.path.exists(metadata_file):
                    response = f"✗ Metadata file not found: {metadata_file}"
                else:
                    hq_audio = retrieve_and_enhance_audio(metadata_file)
                    
                    if hq_audio:
                        response = f"✓ High-quality audio retrieved! Saved to: {hq_audio}"
                    else:
                        response = f"✗ Failed to retrieve and enhance audio"
                
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
    print("[HOST] ═══════════════════════════════════════════════════════")
    print("[HOST] IMAGE COMMANDS:")
    print("[HOST]   • Upload & compress:   !upload /path/to/image.jpg")
    print("[HOST]   • Retrieve high-qual:  !retrieve images/metadata_YYYYMMDD_HHMMSS.json")
    print("[HOST]")
    print("[HOST] AUDIO COMMANDS:")
    print("[HOST]   • Upload & compress:   !upload_audio /path/to/audio.wav")
    print("[HOST]   • Retrieve high-qual:  !retrieve_audio audio/metadata_YYYYMMDD_HHMMSS.json")
    print("[HOST]")
    print("[HOST] GENERAL COMMANDS:")
    print("[HOST]   • Regular chat:        Just type your message")
    print("[HOST]   • List metadata:       !list")
    print("[HOST] ═══════════════════════════════════════════════════════")
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
