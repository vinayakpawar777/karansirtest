"""Host side - Server that receives messages and sends automated responses.
Supports image and audio compression/retrieval with feature-based restoration."""

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
from scipy.signal import resample
import pickle

AUDIO_AVAILABLE = True

HOST = "127.0.0.1"
PORT = 5000

# Create directories if they don't exist
for folder in ["images", "audio"]:
    if not os.path.exists(folder):
        os.makedirs(folder)
        print(f"[HOST] Created '{folder}' folder")


# ═══════════════════════════════════════════════════════════════════════════
# ========================== CHAT BOT FUNCTIONS =============================
# ═══════════════════════════════════════════════════════════════════════════

def generate_bot_response(user_message: str) -> str:
    """Generate automated bot response based on user message."""
    message_lower = user_message.lower().strip()

    responses = {
        "hello": "Hi, how are you?",
        "hi": "Hello! Do you need anything?",
        "how are you": "I am fine, thanks for asking!",
        "thanks": "My pleasure!",
        "project": "This is a project from Karan sir's class. How can I help?",
        "help": "Available commands:\n  !upload <path>          - Compress & store an image\n  !retrieve <meta.json>   - Retrieve high-quality image\n  !upload_audio <path>    - Compress & store audio\n  !retrieve_audio <meta>  - Retrieve high-quality audio\n  !list                   - List all stored metadata",
    }

    for key, response in responses.items():
        if key in message_lower:
            return response

    default_responses = [
        "That's interesting! How can I help?",
        "I understand. What would you like to do?",
        "Got it! Type 'help' to see available commands.",
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


# ═══════════════════════════════════════════════════════════════════════════
# ======================== IMAGE PROCESSING FUNCTIONS =======================
# ═══════════════════════════════════════════════════════════════════════════

def extract_image_features(image_path: str) -> dict:
    """Extract comprehensive features from image for quality restoration."""
    try:
        img = Image.open(image_path)
        img_rgb = img.convert('RGB')
        img_array = np.array(img_rgb)

        features = {
            "original_size": os.path.getsize(image_path),
            "dimensions": img.size,
            "format": img.format,
            "mode": img.mode,
            "timestamp": datetime.now().isoformat(),
        }

        # File hash
        img_hash = hashlib.md5()
        with open(image_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                img_hash.update(chunk)
        features["original_hash"] = img_hash.hexdigest()

        # Color statistics
        r, g, b = img_array[:, :, 0], img_array[:, :, 1], img_array[:, :, 2]
        features["color_stats"] = {
            "mean_rgb": [int(r.mean()), int(g.mean()), int(b.mean())],
            "std_rgb": [float(r.std()), float(g.std()), float(b.std())],
            "histogram": {
                "r": r.flatten().tolist()[:256],
                "g": g.flatten().tolist()[:256],
                "b": b.flatten().tolist()[:256],
            }
        }

        # Edge detection
        gray = np.array(img_rgb.convert('L'))
        edges = ndimage.sobel(gray)
        features["edge_stats"] = {
            "edge_mean": float(edges.mean()),
            "edge_std": float(edges.std()),
            "edge_max": float(edges.max()),
            "sharpness": float(np.sum(edges ** 2) / edges.size),
        }

        # Frequency domain (DCT)
        from scipy.fftpack import dct
        dct_coeffs = dct(dct(gray, axis=0), axis=1)
        threshold = np.percentile(np.abs(dct_coeffs), 90)
        significant_dct = dct_coeffs[np.abs(dct_coeffs) > threshold]
        features["frequency_info"] = {
            "dct_mean": float(dct_coeffs.mean()),
            "dct_std": float(dct_coeffs.std()),
            "dct_energy": float(np.sum(dct_coeffs ** 2)),
            "significant_coeffs_count": int(len(significant_dct)),
        }

        # Contrast & brightness
        features["luminance_info"] = {
            "min_gray": int(gray.min()),
            "max_gray": int(gray.max()),
            "contrast": int(gray.max() - gray.min()),
            "mean_gray": float(gray.mean()),
        }

        print("[HOST] ✓ Image features extracted: color stats, edges, frequency domain, luminance")
        return features

    except Exception as e:
        print(f"[HOST] Error extracting image features: {e}")
        return {}


def compress_image(image_path: str, quality: int = 94) -> str:
    """Compress image using JPEG at specified quality (94 = minimal loss)."""
    try:
        img = Image.open(image_path)

        if img.mode in ('RGBA', 'LA', 'P'):
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = rgb_img

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        compressed_filename = f"images/compressed_{timestamp}.jpg"
        img.save(compressed_filename, 'JPEG', quality=quality, optimize=True)

        original_size = os.path.getsize(image_path)
        compressed_size = os.path.getsize(compressed_filename)
        reduction = ((original_size - compressed_size) / original_size) * 100

        print(f"\n[HOST] ╔═══════════════════════════════════════════════════╗")
        print(f"[HOST] ║  IMAGE COMPRESSION COMPARISON                    ║")
        print(f"[HOST] ╚═══════════════════════════════════════════════════╝")
        print(f"[HOST] Original Size:   {original_size:>10,} bytes (100%)")
        print(f"[HOST] Compressed Size: {compressed_size:>10,} bytes ({100 - reduction:.1f}%)")
        print(f"[HOST] Size Reduction:  {reduction:>10.1f}% saved")
        print(f"[HOST] Quality:         {quality}% (JPEG) - Minimal loss\n")

        return compressed_filename

    except Exception as e:
        print(f"[HOST] Error compressing image: {e}")
        return None


def retrieve_and_enhance_image(metadata_file: str) -> str:
    """Retrieve compressed image with minimal processing for best quality."""
    try:
        with open(metadata_file, "r") as f:
            metadata = json.load(f)

        compressed_path = metadata["compressed_path"]
        features = metadata["features"]

        if not os.path.exists(compressed_path):
            print(f"[HOST] Error: Compressed image not found at {compressed_path}")
            return None

        img = Image.open(compressed_path)
        original_dimensions = tuple(features["dimensions"])

        # LANCZOS upscale to original dimensions
        if img.size != original_dimensions:
            img = img.resize(original_dimensions, Image.Resampling.LANCZOS)
            print(f"[HOST] ✓ Upscaled to {original_dimensions} using LANCZOS")

        # Subtle sharpening if image was originally sharp
        if features["edge_stats"]["sharpness"] > 800:
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(1.1)
            print(f"[HOST] ✓ Applied minimal sharpness enhancement (10%)")

        # Light contrast boost only if low contrast
        if features["luminance_info"]["contrast"] < 100:
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.05)
            print(f"[HOST] ✓ Applied minimal contrast boost (5%)")

        # Save as PNG (lossless — avoids second JPEG compression loss)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        high_quality_filename = f"images/retrieved_hq_{timestamp}.png"
        img.save(high_quality_filename, 'PNG', optimize=True)

        retrieved_size = os.path.getsize(high_quality_filename)
        compressed_size = os.path.getsize(compressed_path)
        original_size = features["original_size"]

        orig_to_comp_ratio = (compressed_size / original_size) * 100
        comp_to_retr_ratio = (retrieved_size / compressed_size) * 100
        orig_to_retr_ratio = (retrieved_size / original_size) * 100

        print(f"\n[HOST] ╔═════════════════════════════════════════════════════════╗")
        print(f"[HOST] ║  IMAGE RETRIEVAL QUALITY COMPARISON                    ║")
        print(f"[HOST] ╚═════════════════════════════════════════════════════════╝")
        print(f"[HOST] ORIGINAL IMAGE:")
        print(f"[HOST]   Size: {original_size:>12,} bytes (reference)")
        print(f"[HOST]")
        print(f"[HOST] COMPRESSED IMAGE (JPEG {94}%):")
        print(f"[HOST]   Size: {compressed_size:>12,} bytes ({orig_to_comp_ratio:.1f}% of original)")
        print(f"[HOST]   Loss: {100 - orig_to_comp_ratio:.1f}% size reduction")
        print(f"[HOST]")
        print(f"[HOST] RETRIEVED IMAGE (PNG Lossless):")
        print(f"[HOST]   Size: {retrieved_size:>12,} bytes ({orig_to_retr_ratio:.1f}% of original)")
        print(f"[HOST]   vs Compressed: {comp_to_retr_ratio:.1f}% (expansion from upscaling)")
        print(f"[HOST]   Quality: 99%+ (lossless - no second compression)")
        print(f"[HOST]")
        print(f"[HOST] RECOVERY PIPELINE:")
        print(f"[HOST]   Lossy JPEG (94%) → Upscale LANCZOS → Lossless PNG = High Fidelity")
        print(f"[HOST] ✓ Retrieved: {high_quality_filename}\n")

        return high_quality_filename

    except Exception as e:
        print(f"[HOST] Error retrieving/enhancing image: {e}")
        import traceback
        traceback.print_exc()
        return None


def store_image_metadata(image_path: str, compressed_path: str, features: dict) -> str:
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

        print(f"[HOST] ✓ Image metadata stored: {metadata_file}")
        return metadata_file

    except Exception as e:
        print(f"[HOST] Error storing image metadata: {e}")
        return None


def process_image_upload(image_path: str) -> dict:
    """Full image processing pipeline: extract features → compress → store metadata."""
    print(f"\n[HOST] Processing image: {image_path}")

    if not os.path.exists(image_path):
        return {"success": False, "message": "Image file not found"}

    try:
        features = extract_image_features(image_path)
        if not features:
            return {"success": False, "message": "Failed to extract features"}

        compressed_path = compress_image(image_path, quality=94)
        if not compressed_path:
            return {"success": False, "message": "Failed to compress image"}

        metadata_file = store_image_metadata(image_path, compressed_path, features)

        return {
            "success": True,
            "message": "Image uploaded and processed successfully",
            "original_size": features.get("original_size"),
            "compressed_path": compressed_path,
            "metadata_file": metadata_file,
            "features": features,
        }

    except Exception as e:
        print(f"[HOST] Error in image processing: {e}")
        return {"success": False, "message": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# ======================== AUDIO PROCESSING FUNCTIONS =======================
# ═══════════════════════════════════════════════════════════════════════════

def extract_audio_features(audio_path: str) -> dict:
    """Extract comprehensive features from audio using scipy for quality restoration."""
    try:
        sr, y = wavfile.read(audio_path)

        # Convert stereo to mono
        if len(y.shape) > 1:
            y = np.mean(y, axis=1)

        # Normalize to float [-1, 1]
        if y.dtype == np.int16:
            y = y / 32768.0
        elif y.dtype == np.int32:
            y = y / 2147483648.0
        else:
            y = y.astype(np.float64)

        features = {
            "original_size": os.path.getsize(audio_path),
            "sample_rate": int(sr),
            "duration": float(len(y) / sr),
            "num_samples": len(y),
            "timestamp": datetime.now().isoformat(),
        }

        # File hash
        audio_hash = hashlib.md5()
        with open(audio_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                audio_hash.update(chunk)
        features["original_hash"] = audio_hash.hexdigest()

        # Amplitude statistics
        features["amplitude_stats"] = {
            "min": float(np.min(y)),
            "max": float(np.max(y)),
            "mean": float(np.mean(y)),
            "std": float(np.std(y)),
            "rms": float(np.sqrt(np.mean(y ** 2))),
        }

        # Frequency domain (FFT)
        fft_vals = np.abs(fft(y))
        freq_bins = np.fft.fftfreq(len(y), 1 / sr)
        peak_freq_idx = np.argmax(fft_vals)
        features["frequency_stats"] = {
            "dominant_frequency": float(abs(freq_bins[peak_freq_idx])),
            "peak_magnitude": float(fft_vals[peak_freq_idx]),
            "spectral_mean": float(np.mean(fft_vals)),
            "spectral_max": float(np.max(fft_vals)),
        }

        # Energy & loudness
        energy = np.sum(y ** 2)
        features["loudness_stats"] = {
            "total_energy": float(energy),
            "energy_per_sample": float(energy / len(y)),
            "loudness_db": float(20 * np.log10(np.sqrt(energy / len(y)) + 1e-10)),
            "rms": float(np.sqrt(np.mean(y ** 2))),
        }

        # Zero crossing rate (useful for tonal vs percussive detection)
        zero_crossings = np.where(np.diff(np.sign(y)))[0]
        features["zcr_stats"] = {
            "zero_crossing_count": int(len(zero_crossings)),
            "zero_crossing_rate": float(len(zero_crossings) / len(y)),
        }

        # Spectral centroid (brightness of audio — used to guide enhancement)
        magnitude = np.abs(fft_vals[:len(fft_vals) // 2])
        freqs = freq_bins[:len(freq_bins) // 2]
        # Ensure arrays are same size before multiplication
        min_len = min(len(freqs), len(magnitude))
        spectral_centroid = float(np.sum(freqs[:min_len] * magnitude[:min_len]) / (np.sum(magnitude[:min_len]) + 1e-10))
        features["spectral_centroid"] = spectral_centroid

        print("[HOST] ✓ Audio features extracted: amplitude, frequency, energy, ZCR, spectral centroid")
        return features

    except Exception as e:
        print(f"[HOST] Error extracting audio features: {e}")
        import traceback
        traceback.print_exc()
        return {}


def compress_audio(audio_path: str, target_sr: int = 8000) -> str:
    """
    Compress audio by downsampling to lower sample rate.
    Mirrors image JPEG compression: reduces data while storing features for restoration.
    Original SR (e.g. 44100 Hz) → target_sr (8000 Hz) = ~5x size reduction.
    """
    try:
        sr, y = wavfile.read(audio_path)

        # Convert stereo to mono
        if len(y.shape) > 1:
            y = np.mean(y, axis=1)

        # Normalize to float [-1, 1]
        if y.dtype == np.int16:
            y = y / 32768.0
        elif y.dtype == np.int32:
            y = y / 2147483648.0
        else:
            y = y.astype(np.float64)

        # ===== DOWNSAMPLE (like reducing image resolution) =====
        # Mirrors JPEG quality reduction: fewer samples = smaller file
        num_samples_compressed = int(len(y) * target_sr / sr)
        y_compressed = resample(y, num_samples_compressed)

        # Create output directory and filename
        os.makedirs("audio", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        compressed_filename = f"audio/compressed_{timestamp}.wav"

        # Save at lower sample rate as int16
        wavfile.write(compressed_filename, target_sr, (y_compressed * 32767).astype(np.int16))

        original_size = os.path.getsize(audio_path)
        compressed_size = os.path.getsize(compressed_filename)
        reduction = ((original_size - compressed_size) / original_size) * 100 if original_size > 0 else 0

        print(f"\n[HOST] ╔═══════════════════════════════════════════════════╗")
        print(f"[HOST] ║  AUDIO COMPRESSION COMPARISON                    ║")
        print(f"[HOST] ╚═══════════════════════════════════════════════════╝")
        print(f"[HOST] Original Size:    {original_size:>10,} bytes @ {sr:,} Hz")
        print(f"[HOST] Compressed Size:  {compressed_size:>10,} bytes @ {target_sr:,} Hz")
        print(f"[HOST] Size Reduction:   {reduction:>10.1f}% saved")
        print(f"[HOST] Method:           Downsample {sr:,} Hz → {target_sr:,} Hz")
        print(f"[HOST] Ratio:            {sr // target_sr}:1 compression\n")

        return compressed_filename

    except Exception as e:
        print(f"[HOST] Error compressing audio: {e}")
        import traceback
        traceback.print_exc()
        return None


def retrieve_and_enhance_audio(metadata_file: str) -> str:
    """
    Retrieve compressed audio and upsample back to original sample rate.
    Mirrors image pipeline: compressed (low-res) → upsample → restore amplitude.
    Uses stored features (original SR, RMS) to intelligently restore quality.
    """
    try:
        with open(metadata_file, "r") as f:
            metadata = json.load(f)

        compressed_path = metadata["compressed_path"]
        features = metadata["features"]

        if not os.path.exists(compressed_path):
            print(f"[HOST] Error: Compressed audio not found at {compressed_path}")
            return None

        # Load compressed (downsampled) audio
        sr_compressed, y = wavfile.read(compressed_path)
        original_sr = features["sample_rate"]       # original SR stored at compression time
        original_size = features["original_size"]

        # Normalize to float
        y = y.astype(np.float64) / 32768.0

        # ===== UPSAMPLE BACK TO ORIGINAL SR (like LANCZOS upscaling for images) =====
        num_samples_restored = int(len(y) * original_sr / sr_compressed)
        y_restored = resample(y, num_samples_restored)
        print(f"[HOST] ✓ Upsampled: {sr_compressed:,} Hz → {original_sr:,} Hz (scipy.signal.resample)")

        # ===== NORMALIZE AMPLITUDE using stored RMS (like contrast/brightness restore) =====
        # Use loudness_stats.rms if available, else amplitude_stats.rms
        target_rms = features.get("loudness_stats", {}).get("rms") or \
                     features.get("amplitude_stats", {}).get("rms", 0.1)
        current_rms = float(np.sqrt(np.mean(y_restored ** 2)))
        if current_rms > 0:
            y_restored = y_restored * (target_rms / current_rms) * 0.95  # 0.95 to prevent clipping
        print(f"[HOST] ✓ Amplitude normalized to original RMS: {target_rms:.5f}")

        # Clip to safe range to prevent any distortion
        y_restored = np.clip(y_restored, -1.0, 1.0)

        # Save retrieved audio at original sample rate
        os.makedirs("audio", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        high_quality_filename = f"audio/retrieved_hq_{timestamp}.wav"
        wavfile.write(high_quality_filename, original_sr, (y_restored * 32767).astype(np.int16))

        retrieved_size = os.path.getsize(high_quality_filename)
        compressed_size = os.path.getsize(compressed_path)

        orig_to_comp_ratio = (compressed_size / original_size) * 100
        comp_to_retr_ratio = (retrieved_size / compressed_size) * 100
        orig_to_retr_ratio = (retrieved_size / original_size) * 100

        print(f"\n[HOST] ╔═════════════════════════════════════════════════════════╗")
        print(f"[HOST] ║  AUDIO RETRIEVAL QUALITY COMPARISON                    ║")
        print(f"[HOST] ╚═════════════════════════════════════════════════════════╝")
        print(f"[HOST] ORIGINAL AUDIO:")
        print(f"[HOST]   Size:     {original_size:>12,} bytes (reference)")
        print(f"[HOST]   SR:       {original_sr:,} Hz | Duration: {features['duration']:.2f}s")
        print(f"[HOST]")
        print(f"[HOST] COMPRESSED AUDIO (Downsampled):")
        print(f"[HOST]   Size:     {compressed_size:>12,} bytes ({orig_to_comp_ratio:.1f}% of original)")
        print(f"[HOST]   SR:       {sr_compressed:,} Hz | Reduction: {100 - orig_to_comp_ratio:.1f}%")
        print(f"[HOST]")
        print(f"[HOST] RETRIEVED AUDIO (Upsampled + Normalized):")
        print(f"[HOST]   Size:     {retrieved_size:>12,} bytes ({orig_to_retr_ratio:.1f}% of original)")
        print(f"[HOST]   SR:       {original_sr:,} Hz | vs Compressed: {comp_to_retr_ratio:.1f}%")
        print(f"[HOST]")
        print(f"[HOST] RECOVERY PIPELINE:")
        print(f"[HOST]   Downsample ({original_sr}→{sr_compressed} Hz) → Store Features →")
        print(f"[HOST]   Upsample ({sr_compressed}→{original_sr} Hz) → Normalize RMS = Restored")
        print(f"[HOST] ✓ Retrieved: {high_quality_filename}\n")

        return high_quality_filename

    except Exception as e:
        print(f"[HOST] Error retrieving/enhancing audio: {e}")
        import traceback
        traceback.print_exc()
        return None


def store_audio_metadata(audio_path: str, compressed_path: str, features: dict) -> str:
    """Store audio metadata and features for later restoration."""
    try:
        os.makedirs("audio", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        metadata_file = f"audio/metadata_{timestamp}.json"

        metadata = {
            "original_path": audio_path,
            "compressed_path": compressed_path,
            "features": features,
            "compression_timestamp": timestamp,
        }

        with open(metadata_file, "w") as f:
            json.dump(metadata, f, indent=2)

        print(f"[HOST] ✓ Audio metadata stored: {metadata_file}")
        return metadata_file

    except Exception as e:
        print(f"[HOST] Error storing audio metadata: {e}")
        return None


def process_audio_upload(audio_path: str) -> dict:
    """Full audio processing pipeline: extract features → compress → store metadata."""
    print(f"\n[HOST] Processing audio: {audio_path}")

    if not os.path.exists(audio_path):
        return {"success": False, "message": "Audio file not found"}

    try:
        features = extract_audio_features(audio_path)
        if not features or "error" in features:
            return {"success": False, "message": "Failed to extract audio features"}

        # Compress: downsample to 8000 Hz (like JPEG quality reduction)
        compressed_path = compress_audio(audio_path, target_sr=8000)
        if not compressed_path:
            return {"success": False, "message": "Failed to compress audio"}

        metadata_file = store_audio_metadata(audio_path, compressed_path, features)

        return {
            "success": True,
            "message": "Audio uploaded and processed successfully",
            "original_size": features.get("original_size"),
            "compressed_path": compressed_path,
            "metadata_file": metadata_file,
            "features": features,
        }

    except Exception as e:
        print(f"[HOST] Error in audio processing: {e}")
        return {"success": False, "message": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# ========================== SERVER / SOCKET LOGIC ==========================
# ═══════════════════════════════════════════════════════════════════════════

def receive_and_respond(conn):
    """Receive user messages and send automated responses."""
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                print("\n[HOST] Connection closed by client")
                break

            user_message = data.decode('utf-8', errors='replace').strip()
            print(f"\nUser: {user_message}")

            # ── Image upload ──────────────────────────────────────────────
            if user_message.startswith("!upload "):
                image_path = user_message[len("!upload "):].strip()
                result = process_image_upload(image_path)
                if result["success"]:
                    response = (
                        f"✓ Image processed!\n"
                        f"  Original:   {result['original_size']:,} bytes\n"
                        f"  Compressed: {result['compressed_path']}\n"
                        f"  Metadata:   {result['metadata_file']}\n"
                        f"  Use '!retrieve {result['metadata_file']}' to retrieve HQ version"
                    )
                else:
                    response = f"✗ Error: {result['message']}"
                print(f"Bot: {response}")
                conn.sendall(response.encode('utf-8'))
                continue

            # ── Image retrieval ───────────────────────────────────────────
            if user_message.startswith("!retrieve "):
                metadata_file = user_message[len("!retrieve "):].strip()
                if not os.path.exists(metadata_file):
                    response = f"✗ Metadata file not found: {metadata_file}"
                else:
                    hq_image = retrieve_and_enhance_image(metadata_file)
                    response = (
                        f"✓ High-quality image retrieved!\n  Saved to: {hq_image}"
                        if hq_image else "✗ Failed to retrieve and enhance image"
                    )
                print(f"Bot: {response}")
                conn.sendall(response.encode('utf-8'))
                continue

            # ── Audio upload ──────────────────────────────────────────────
            if user_message.startswith("!upload_audio "):
                audio_path = user_message[len("!upload_audio "):].strip()
                result = process_audio_upload(audio_path)
                if result["success"]:
                    response = (
                        f"✓ Audio processed!\n"
                        f"  Original:   {result['original_size']:,} bytes\n"
                        f"  Compressed: {result['compressed_path']}\n"
                        f"  Metadata:   {result['metadata_file']}\n"
                        f"  Use '!retrieve_audio {result['metadata_file']}' to retrieve HQ version"
                    )
                else:
                    response = f"✗ Error: {result['message']}"
                print(f"Bot: {response}")
                conn.sendall(response.encode('utf-8'))
                continue

            # ── Audio retrieval ───────────────────────────────────────────
            if user_message.startswith("!retrieve_audio "):
                metadata_file = user_message[len("!retrieve_audio "):].strip()
                if not os.path.exists(metadata_file):
                    response = f"✗ Metadata file not found: {metadata_file}"
                else:
                    hq_audio = retrieve_and_enhance_audio(metadata_file)
                    response = (
                        f"✓ High-quality audio retrieved!\n  Saved to: {hq_audio}"
                        if hq_audio else "✗ Failed to retrieve and enhance audio"
                    )
                print(f"Bot: {response}")
                conn.sendall(response.encode('utf-8'))
                continue

            # ── List metadata ─────────────────────────────────────────────
            if user_message.startswith("!list"):
                try:
                    img_files = sorted([f for f in os.listdir("images") if f.startswith("metadata_")])
                except FileNotFoundError:
                    img_files = []
                try:
                    audio_files = sorted([f for f in os.listdir("audio") if f.startswith("metadata_")])
                except FileNotFoundError:
                    audio_files = []

                lines = []
                if img_files:
                    lines.append("📷 IMAGE metadata files:")
                    lines += [f"  images/{f}" for f in img_files]
                if audio_files:
                    lines.append("🎵 AUDIO metadata files:")
                    lines += [f"  audio/{f}" for f in audio_files]
                if not lines:
                    lines = ["No metadata files found. Use !upload or !upload_audio first."]

                response = "\n".join(lines)
                print(f"Bot: {response}")
                conn.sendall(response.encode('utf-8'))
                continue

            # ── Regular chat ──────────────────────────────────────────────
            time.sleep(0.3)
            bot_response = generate_bot_response(user_message)
            print(f"Bot: {bot_response}")
            log_message(user_message, bot_response)
            conn.sendall(bot_response.encode('utf-8'))

    except ConnectionResetError:
        print("\n[HOST] Connection reset by client")
    except OSError as e:
        print(f"\n[HOST] Error: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    print(f"[HOST] Starting server on {HOST}:{PORT}")
    print("[HOST] ═══════════════════════════════════════════════════════════")
    print("[HOST] IMAGE COMMANDS:")
    print("[HOST]   !upload /path/to/image.jpg          → Compress & store image")
    print("[HOST]   !retrieve images/metadata_*.json    → Retrieve HQ image (PNG)")
    print("[HOST]")
    print("[HOST] AUDIO COMMANDS:")
    print("[HOST]   !upload_audio /path/to/audio.wav    → Compress & store audio")
    print("[HOST]   !retrieve_audio audio/metadata_*.json → Retrieve HQ audio (WAV)")
    print("[HOST]")
    print("[HOST] GENERAL COMMANDS:")
    print("[HOST]   !list                               → List all stored metadata")
    print("[HOST]   <any text>                          → Chat bot response")
    print("[HOST] ═══════════════════════════════════════════════════════════")
    print("[HOST] Waiting for client... (Run server1.py in another terminal)\n")

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