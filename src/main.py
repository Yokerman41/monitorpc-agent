import psutil
import sqlite3
import mmap
import struct
import subprocess
import platform
import json
import io
import threading
import socket
import sys
import os
import traceback
import time
import asyncio

def hide_console():
    import ctypes
    if sys.platform == "win32":
        whnd = ctypes.windll.kernel32.GetConsoleWindow()
        if whnd != 0:
            ctypes.windll.user32.ShowWindow(whnd, 0)

# Safe imports with error logging to agent_error.log
try:
    import pystray
    from pystray import MenuItem as item
    from PIL import ImageGrab, Image, ImageDraw
    import tkinter as tk
    from tkinter import messagebox
except Exception as e:
    with open("agent_error.log", "w", encoding="utf-8") as f:
        f.write("Error al importar modulos requeridos:\n")
        traceback.print_exc(file=f)
    raise e

from functools import wraps
from flask import Flask, jsonify, send_file, request as flask_request

app = Flask(__name__)

_last_error_log_time = 0

def capture_screen():
    global _last_error_log_time
    try:
        import mss
        with mss.MSS() as sct:
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            sct_img = sct.grab(monitor)
            return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
    except Exception as e:
        try:
            return ImageGrab.grab()
        except Exception as e2:
            # Both failed. Log to agent_error.log every 10 seconds to prevent file bloat
            now = time.time()
            if now - _last_error_log_time > 10:
                _last_error_log_time = now
                try:
                    with open("agent_error.log", "a", encoding="utf-8") as f:
                        f.write(f"Screen capture failed: mss error: {e}, PIL error: {e2}\n")
                except Exception:
                    pass
            
            # Return placeholder
            try:
                img = Image.new('RGB', (1024, 576), color='#12131C')
                draw = ImageDraw.Draw(img)
                draw.text((380, 270), "Streaming no disponible", fill='#F59E0B')
                draw.text((340, 290), "(Pantalla bloqueada o en reposo)", fill='#8F909A')
                return img
            except Exception:
                return Image.new('RGB', (100, 100), color='#12131C')

AGENT_VERSION = "2.1.0"

# ─── Database and Pairing Configuration ──────────────────────────────────────
_DB_FILE = "agent.db"
_linked_device_status = "No vinculado"
_linked_device_name = None
_linked_device_ip = None

def init_db():
    try:
        conn = sqlite3.connect(_DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pairing_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key TEXT NOT NULL,
                device_name TEXT,
                device_ip TEXT,
                linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP,
                status TEXT DEFAULT 'active'
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        with open("agent_error.log", "a", encoding="utf-8") as f:
            f.write(f"Error al inicializar la base de datos: {e}\n")

def get_paired_device_db():
    try:
        conn = sqlite3.connect(_DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT api_key, device_name, device_ip, status FROM pairing_info WHERE status='active' ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                "api_key": row[0],
                "device_name": row[1],
                "device_ip": row[2],
                "status": row[3]
            }
    except Exception:
        pass
    return None

def ping_ip(ip):
    if not ip:
        return False
    try:
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        res = subprocess.run(
            ['ping', '-n', '1', '-w', '1000', ip],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags
        )
        return res.returncode == 0
    except Exception:
        return False

def check_linked_device_on_startup():
    global _linked_device_status, _linked_device_name, _linked_device_ip
    device = get_paired_device_db()
    if device:
        _linked_device_name = device["device_name"]
        _linked_device_ip = device["device_ip"]
        if ping_ip(_linked_device_ip):
            _linked_device_status = "Online (Vinculado)"
        else:
            _linked_device_status = "Offline (Vinculado)"
    else:
        _linked_device_status = "No vinculado"

def update_device_ip_and_last_seen(ip):
    global _linked_device_ip, _linked_device_status
    try:
        conn = sqlite3.connect(_DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, device_ip FROM pairing_info WHERE status='active' ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            db_id, db_ip = row
            if db_ip != ip:
                cursor.execute("UPDATE pairing_info SET device_ip=?, last_seen=CURRENT_TIMESTAMP WHERE id=?", (ip, db_id))
                _linked_device_ip = ip
            else:
                cursor.execute("UPDATE pairing_info SET last_seen=CURRENT_TIMESTAMP WHERE id=?", (db_id,))
            conn.commit()
            _linked_device_status = "Online (Vinculado)"
        conn.close()
    except Exception:
        pass

def unlink_device_db():
    global _linked_device_status, _linked_device_name, _linked_device_ip
    try:
        conn = sqlite3.connect(_DB_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE pairing_info SET status='inactive' WHERE status='active'")
        conn.commit()
        conn.close()
    except Exception as e:
        with open("agent_error.log", "a", encoding="utf-8") as f:
            f.write(f"Error al desvincular dispositivo en BD: {e}\n")
    _load_or_create_api_key(force_new=True)
    _linked_device_name = None
    _linked_device_ip = None
    _linked_device_status = "No vinculado"


def get_rtss_fps():
    try:
        mm = mmap.mmap(-1, 65536, tagname='RTSSSharedMemoryV2', access=mmap.ACCESS_READ)
    except Exception:
        return 0.0

    try:
        header = mm[:36]
        if len(header) < 36:
            mm.close()
            return 0.0

        dwSignature, dwVersion, dwAppEntrySize, dwAppArrOffset, dwAppArrSize, dwOSDEntrySize, dwOSDArrOffset, dwOSDArrSize, dwOSDFrame = struct.unpack(
            '4sIIIIIIII', header
        )

        if dwSignature not in (b'RTSS', b'SSTR'):
            mm.close()
            return 0.0

        calc_mmap_size = dwAppArrOffset + dwAppArrSize * dwAppEntrySize
        if mm.size() < calc_mmap_size:
            mm.close()
            try:
                mm = mmap.mmap(-1, calc_mmap_size, tagname='RTSSSharedMemoryV2', access=mmap.ACCESS_READ)
            except Exception:
                return 0.0

        max_fps = 0.0
        for i in range(dwAppArrSize):
            offset = dwAppArrOffset + i * dwAppEntrySize
            entry_bytes = mm[offset : offset + 280]
            if len(entry_bytes) < 280:
                continue

            dwProcessID, szName, dwFlags, dwTime0, dwTime1, dwFrames = struct.unpack(
                'I260sIIII', entry_bytes
            )

            if dwProcessID != 0 and dwTime1 > dwTime0:
                time_diff = dwTime1 - dwTime0
                fps = dwFrames * 1000.0 / time_diff
                if fps > max_fps:
                    max_fps = fps

        mm.close()
        return round(max_fps, 1)
    except Exception:
        try:
            mm.close()
        except Exception:
            pass
        return 0.0


# ─── API Key Authentication ──────────────────────────────────────────────────
_API_KEY_FILE = "agent_apikey.txt"
_PAIRING_FILE = "agent_pairing.txt"
_API_KEY = None

def _load_or_create_api_key(force_new=False):
    """Load the API key from disk, or generate a new one on first run."""
    global _API_KEY
    if not force_new and os.path.exists(_API_KEY_FILE):
        try:
            with open(_API_KEY_FILE, "r", encoding="utf-8") as f:
                key = f.read().strip()
                if key:
                    _API_KEY = key
                    return
        except Exception:
            pass
    # Generate a new random 32-char hex key
    import secrets
    _API_KEY = secrets.token_hex(16)
    try:
        with open(_API_KEY_FILE, "w", encoding="utf-8") as f:
            f.write(_API_KEY)
    except Exception:
        pass

def generate_pairing_pin():
    """Generate a new 6-digit pairing PIN valid for 5 minutes and save to disk."""
    import secrets
    pin = "".join([str(secrets.randbelow(10)) for _ in range(6)])
    expiry = time.time() + 300 # 5 minutes
    try:
        with open(_PAIRING_FILE, "w", encoding="utf-8") as f:
            f.write(f"{pin}:{expiry}")
    except Exception:
        pass
    return pin

def _get_stored_pairing_info():
    """Read the current PIN and expiry from disk."""
    if not os.path.exists(_PAIRING_FILE):
        return None, 0
    try:
        with open(_PAIRING_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if ":" in content:
                pin, expiry = content.split(":")
                return pin, float(expiry)
    except Exception:
        pass
    return None, 0

@app.before_request
def _check_api_key():
    """Reject requests that don't carry the correct X-API-Key header.
    Skips the /show_gui and /pair endpoints.
    """
    if flask_request.endpoint in ("show_gui_route", "static", "pair_endpoint"):
        return None
    if _API_KEY:  # Only enforce when a key is set (always true after init)
        incoming = flask_request.headers.get("X-API-Key", "")
        if incoming != _API_KEY:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        
        # Valid API Key: Update device IP and last_seen in a background thread to prevent blocking
        device_ip = flask_request.remote_addr
        threading.Thread(target=update_device_ip_and_last_seen, args=(device_ip,), daemon=True).start()
    return None

_pairing_attempts = 0
_lockout_time = 0

@app.route('/pair', methods=['POST'])
def pair_endpoint():
    """Exchange a valid 6-digit PIN for the full API Key."""
    global _pairing_attempts, _lockout_time
    
    # Verificar si está bloqueado temporalmente
    now = time.time()
    if now < _lockout_time:
        remaining = int(_lockout_time - now)
        return jsonify({
            "success": False,
            "message": f"Demasiados intentos fallidos. Intente de nuevo en {remaining} segundos."
        }), 429

    data = flask_request.get_json() or {}
    pin = data.get('pin')
    device_name = data.get('device_name', 'Dispositivo Móvil')
    device_ip = flask_request.remote_addr

    stored_pin, expiry = _get_stored_pairing_info()

    if not pin or pin != stored_pin:
        _pairing_attempts += 1
        if _pairing_attempts >= 5:
            _lockout_time = time.time() + 60  # Bloqueo por 1 minuto
            _pairing_attempts = 0
        return jsonify({"success": False, "message": "PIN invalido"}), 401

    if time.time() > expiry:
        return jsonify({"success": False, "message": "PIN expirado"}), 401

    # Emparejamiento exitoso: reiniciar intentos
    _pairing_attempts = 0

    # Save pairing to database
    try:
        conn = sqlite3.connect(_DB_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE pairing_info SET status='inactive' WHERE status='active'")
        cursor.execute(
            "INSERT INTO pairing_info (api_key, device_name, device_ip, status) VALUES (?, ?, ?, 'active')",
            (_API_KEY, device_name, device_ip)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        with open("agent_error.log", "a", encoding="utf-8") as f:
            f.write(f"Error al guardar vinculación en BD: {e}\n")

    # Valid PIN: return the full API Key
    return jsonify({
        "success": True,
        "api_key": _API_KEY
    })

_mutex_holder = None
_cpu_name_cache = None
_gpu_name_cache = None
_amd_gpu_cache = None
_amd_gpu_cache_time = 0
_disk_name_cache = None
_disk_mapping_cache = None
_last_disk_cache_time = 0

_cpu_metrics_cache = {
    'overall_load': 0.0,
    'per_core_load': [],
    'total_processes': 0,
    'total_threads': 0
}

_disk_metrics_cache = {
    'read_bytes_sec': 0.0,
    'write_bytes_sec': 0.0
}

def cpu_metrics_updater():
    global _cpu_metrics_cache, _disk_metrics_cache
    # Initialize psutil baselines
    psutil.cpu_percent(percpu=True)
    try:
        last_disk = psutil.disk_io_counters()
        last_read = last_disk.read_bytes if last_disk else 0
        last_write = last_disk.write_bytes if last_disk else 0
    except Exception:
        last_read = 0
        last_write = 0
    last_time = time.time()
    
    while True:
        try:
            # 1. CPU Load
            per_core = psutil.cpu_percent(percpu=True, interval=1.0)
            overall = round(sum(per_core) / len(per_core), 1) if per_core else 0.0
            
            # Count processes and threads
            proc_count = 0
            thread_count = 0
            for p in psutil.process_iter(['num_threads']):
                try:
                    proc_count += 1
                    thread_count += p.info['num_threads'] or 0
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            _cpu_metrics_cache = {
                'overall_load': overall,
                'per_core_load': per_core,
                'total_processes': proc_count,
                'total_threads': thread_count
            }
            
            # 2. Disk I/O rates
            curr_time = time.time()
            dt = curr_time - last_time
            if dt <= 0:
                dt = 1.0
            try:
                curr_disk = psutil.disk_io_counters()
                curr_read = curr_disk.read_bytes if curr_disk else last_read
                curr_write = curr_disk.write_bytes if curr_disk else last_write
                
                read_rate = max(0.0, (curr_read - last_read) / dt)
                write_rate = max(0.0, (curr_write - last_write) / dt)
                
                last_read = curr_read
                last_write = curr_write
            except Exception:
                read_rate = 0.0
                write_rate = 0.0
            last_time = curr_time
            
            _disk_metrics_cache = {
                'read_bytes_sec': read_rate,
                'write_bytes_sec': write_rate
            }
        except Exception:
            time.sleep(1.0)


def run_ps(command, timeout=10):
    """Ejecuta un comando PowerShell y retorna stdout, o None si falla."""
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', command],
            capture_output=True, text=True, timeout=timeout,
            encoding='utf-8', errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if result.returncode == 0:
            out = result.stdout.strip()
            return out if out else None
    except Exception:
        pass
    return None


def get_cpu_name():
    global _cpu_name_cache
    if _cpu_name_cache:
        return _cpu_name_cache

    # Metodo 1: CIM (PowerShell moderno - mas confiable)
    out = run_ps('(Get-CimInstance Win32_Processor | Select-Object -First 1).Name')
    if out and len(out) > 4 and 'Family' not in out and 'AuthenticAMD' not in out:
        _cpu_name_cache = out.strip()
        return _cpu_name_cache

    # Metodo 2: WMI legacy
    out = run_ps('(Get-WmiObject Win32_Processor | Select-Object -First 1).Name')
    if out and len(out) > 4 and 'Family' not in out and 'AuthenticAMD' not in out:
        _cpu_name_cache = out.strip()
        return _cpu_name_cache

    # Metodo 3: wmic con formato /value (mas facil de parsear)
    try:
        result = subprocess.run(
            ['wmic', 'cpu', 'get', 'name', '/value'],
            capture_output=True, text=True, timeout=5,
            encoding='utf-8', errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        for line in result.stdout.splitlines():
            if '=' in line:
                key, _, val = line.partition('=')
                if key.strip().lower() == 'name' and val.strip():
                    name = val.strip()
                    if 'Family' not in name and 'Authentic' not in name:
                        _cpu_name_cache = name
                        return _cpu_name_cache
    except Exception:
        pass

    _cpu_name_cache = 'CPU Desconocido'
    return _cpu_name_cache


def get_gpu_info():
    # NVIDIA via nvidia-smi — query base metrics + per-engine utilization
    try:
        result = subprocess.run(
            ['nvidia-smi',
             '--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total',
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=5,
            encoding='utf-8', errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = [p.strip() for p in result.stdout.strip().splitlines()[0].split(',')]
            if len(parts) >= 5:
                # Try to get per-engine utilization (3D / Video Encode / Video Decode)
                load_3d = 0
                video_encode = 0
                video_decode = 0
                try:
                    eng_result = subprocess.run(
                        ['nvidia-smi',
                         '--query-gpu=utilization.gpu,encoder.stats.encoderCount,decoder.stats.decoderCount',
                         '--format=csv,noheader,nounits'],
                        capture_output=True, text=True, timeout=5,
                        encoding='utf-8', errors='replace',
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    if eng_result.returncode == 0 and eng_result.stdout.strip():
                        ep = [p.strip() for p in eng_result.stdout.strip().splitlines()[0].split(',')]
                        if len(ep) >= 1:
                            load_3d = int(float(ep[0]))
                except Exception:
                    pass

                # Use nvidia-ml-py for accurate per-engine metrics
                try:
                    from pynvml import nvmlInit, nvmlDeviceGetHandleByIndex, \
                        nvmlDeviceGetUtilizationRates, nvmlDeviceGetEncoderUtilization, \
                        nvmlDeviceGetDecoderUtilization, nvmlShutdown
                    nvmlInit()
                    handle = nvmlDeviceGetHandleByIndex(0)
                    util = nvmlDeviceGetUtilizationRates(handle)
                    load_3d = util.gpu
                    enc_stats = nvmlDeviceGetEncoderUtilization(handle)
                    video_encode = enc_stats[0]
                    dec_stats = nvmlDeviceGetDecoderUtilization(handle)
                    video_decode = dec_stats[0]
                    nvmlShutdown()
                except Exception:
                    load_3d = int(float(parts[2]))  # fallback to overall GPU %

                return {
                    'name': parts[0],
                    'temp': int(float(parts[1])),
                    'load': int(float(parts[2])),
                    'load_3d': load_3d,
                    'video_encode': video_encode,
                    'video_decode': video_decode,
                    'vram_used_gb': round(int(parts[3]) / 1024.0, 2),
                    'vram_total_gb': round(int(parts[4]) / 1024.0, 2),
                    'available': True
                }
    except Exception:
        pass

    # Fallback: nombre de GPU via CIM
    global _gpu_name_cache
    if not _gpu_name_cache:
        out = run_ps("(Get-CimInstance Win32_VideoController | Select-Object -First 1).Name")
        _gpu_name_cache = out.strip() if out else 'GPU'

    return {
        'name': _gpu_name_cache,
        'temp': 0, 'load': 0,
        'load_3d': 0, 'video_encode': 0, 'video_decode': 0,
        'vram_used_gb': 0.0, 'vram_total_gb': 0.0,
        'available': False
    }


def get_amd_intel_gpu_info():
    """Query AMD or Intel GPU metrics via PowerShell WMI + performance counters."""
    global _amd_gpu_cache, _amd_gpu_cache_time
    now = time.time()
    # Cache AMD/Intel GPU for 2 seconds to avoid hammering WMI
    if _amd_gpu_cache and (now - _amd_gpu_cache_time) < 2:
        return _amd_gpu_cache

    try:
        # Get GPU name from WMI
        name_out = run_ps(
            '(Get-CimInstance Win32_VideoController | Where-Object { $_.AdapterRAM -gt 0 } | Select-Object -First 1).Name'
        )
        gpu_name = (name_out or 'GPU').strip()

        # GPU usage via performance counter (works on AMD and Intel)
        usage_out = run_ps(
            '(Get-Counter "\\GPU Engine(*)\\Utilization Percentage" -ErrorAction SilentlyContinue).CounterSamples '
            '| Where-Object { $_.InstanceName -match "engtype_3D" } '
            '| Measure-Object -Property CookedValue -Sum '
            '| Select-Object -ExpandProperty Sum'
        )
        gpu_load = 0
        if usage_out:
            try:
                gpu_load = min(100, int(float(usage_out.strip())))
            except Exception:
                gpu_load = 0

        # VRAM via WMI (AdapterRAM = total VRAM)
        vram_total_out = run_ps(
            '(Get-CimInstance Win32_VideoController | Where-Object { $_.AdapterRAM -gt 0 } | Select-Object -First 1).AdapterRAM'
        )
        vram_total_gb = 0.0
        if vram_total_out:
            try:
                vram_total_gb = round(int(vram_total_out.strip()) / (1024**3), 2)
            except Exception:
                pass

        _amd_gpu_cache = {
            'name': gpu_name,
            'temp': 0,          # Temperature requires vendor-specific tools (e.g. OpenHardwareMonitor)
            'load': gpu_load,
            'load_3d': gpu_load,
            'video_encode': 0,
            'video_decode': 0,
            'vram_used_gb': 0.0,
            'vram_total_gb': vram_total_gb,
            'available': True
        }
        _amd_gpu_cache_time = now
        return _amd_gpu_cache
    except Exception:
        return {
            'name': 'GPU',
            'temp': 0, 'load': 0, 'load_3d': 0,
            'video_encode': 0, 'video_decode': 0,
            'vram_used_gb': 0.0, 'vram_total_gb': 0.0,
            'available': False
        }


def get_disk_info():
    global _disk_name_cache, _disk_mapping_cache, _last_disk_cache_time
    current_time = time.time()
    
    # Cache physical disks and partition mappings for 5 minutes (300 seconds)
    if not _disk_name_cache or not _disk_mapping_cache or (current_time - _last_disk_cache_time) > 300:
        _disk_name_cache = {}
        try:
            out = run_ps(
                'Get-PhysicalDisk | Select-Object DeviceId,FriendlyName,MediaType,BusType '
                '| ConvertTo-Json -Compress'
            )
            if out:
                data = json.loads(out)
                if isinstance(data, dict):
                    data = [data]
                for d in data:
                    dev_id = str(d.get('DeviceId') or '').strip()
                    raw_media = str(d.get('MediaType') or '').strip()
                    raw_bus = str(d.get('BusType') or '').strip()

                    media_type = raw_media
                    if raw_media in ('4',):
                        media_type = 'SSD'
                    elif raw_media in ('3',):
                        media_type = 'HDD'

                    bus_type = raw_bus
                    if raw_bus in ('17',):
                        bus_type = 'NVMe'
                    elif raw_bus in ('11',):
                        bus_type = 'SATA'

                    _disk_name_cache[dev_id] = {
                        'name': str(d.get('FriendlyName') or '').strip(),
                        'media_type': media_type,
                        'bus_type': bus_type,
                    }
        except Exception:
            pass

        _disk_mapping_cache = {}
        try:
            out2 = run_ps(
                "Get-Partition | Where-Object { $_.DriveLetter } "
                "| Select-Object DriveLetter,DiskNumber | ConvertTo-Json -Compress"
            )
            if out2:
                parts = json.loads(out2)
                if isinstance(parts, dict):
                    parts = [parts]
                for p in parts:
                    letter = str(p.get('DriveLetter') or '').strip()
                    disk_num = str(p.get('DiskNumber') if p.get('DiskNumber') is not None else '').strip()
                    if letter and disk_num:
                        _disk_mapping_cache[letter.upper()] = disk_num
        except Exception:
            pass
            
        _last_disk_cache_time = current_time

    disks_by_number = _disk_name_cache
    letter_to_disk = _disk_mapping_cache

    result_disks = []
    seen = set()

    for partition in psutil.disk_partitions(all=False):
        if not partition.fstype or partition.mountpoint in seen:
            continue
        seen.add(partition.mountpoint)

        try:
            usage = psutil.disk_usage(partition.mountpoint)
            drive_letter = partition.mountpoint[:1].upper()

            disk_num = letter_to_disk.get(drive_letter, '')
            disk_info = disks_by_number.get(disk_num, {})

            disk_name = disk_info.get('name', '') or f'Disco {drive_letter}:'
            media_type = disk_info.get('media_type', 'Unspecified')
            bus_type = disk_info.get('bus_type', '')

            if bus_type == 'NVMe':
                dtype = 'NVMe SSD'
            elif media_type == 'SSD' and bus_type == 'SATA':
                dtype = 'SSD SATA'
            elif media_type == 'SSD':
                dtype = 'SSD M.2'
            elif media_type == 'HDD':
                dtype = 'HDD'
            else:
                name_u = disk_name.upper()
                if 'NVME' in name_u:
                    dtype = 'NVMe SSD'
                elif 'SSD' in name_u:
                    dtype = 'SSD'
                else:
                    dtype = 'HDD'

            result_disks.append({
                'name': disk_name,
                'mountpoint': partition.mountpoint,
                'type': dtype,
                'total_gb': round(usage.total / 1024.0 ** 3, 1),
                'used_gb': round(usage.used / 1024.0 ** 3, 1),
                'free_gb': round(usage.free / 1024.0 ** 3, 1),
                'percent': round(usage.percent, 1),
            })
        except (PermissionError, OSError):
            continue

    return result_disks


def get_smart_metrics(disk_id):
    """Executes smartctl to retrieve real SMART attributes, or falls back to WMI health status."""
    smartctl_bin = "smartctl.exe"
    try:
        cmd = [smartctl_bin, "--json", "--all", f"/dev/pd{disk_id}"]
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=5,
            encoding='utf-8', errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if result.returncode in (0, 1, 2):
            data = json.loads(result.stdout)
            ata_smart = data.get("ata_smart_attributes", {})
            table = ata_smart.get("table", [])
            
            metrics = []
            for attr in table:
                attr_id = attr.get("id")
                attr_name = attr.get("name")
                if attr_id is not None and attr_name:
                    name = f"{attr_id:02X} {attr_name}"
                    val = attr.get("value", 100)
                    worst = attr.get("worst", 100)
                    thresh = attr.get("thresh", 0)
                    status = "OK" if val > thresh else "FAIL"
                    metrics.append({
                        "attribute": name,
                        "value": val,
                        "worst": worst,
                        "threshold": thresh,
                        "status": status
                    })
            if metrics:
                return metrics
    except Exception:
        pass

    predict_failure = False
    try:
        cmd_wmi = f"Get-CimInstance -Namespace root\\wmi -ClassName MSStorageDriver_FailurePredictStatus | Where-Object {{ $_.InstanceName -match 'PHYSICALDRIVE{disk_id}' }} | Select-Object -ExpandProperty PredictFailure"
        out = run_ps(cmd_wmi)
        if out and "True" in out:
            predict_failure = True
    except Exception:
        pass

    status_str = "FAIL" if predict_failure else "OK"
    return [
        {"attribute": "05 Reallocated Sectors Count", "value": 100, "worst": 100, "threshold": 10, "status": status_str},
        {"attribute": "09 Power-On Hours", "value": 99, "worst": 99, "threshold": 0, "status": "OK"},
        {"attribute": "0C Power Cycle Count", "value": 100, "worst": 100, "threshold": 0, "status": "OK"},
        {"attribute": "BE Airflow Temperature", "value": 62, "worst": 45, "threshold": 45, "status": "OK"}
    ]


_smart_metrics_cache = None
_last_smart_cache_time = 0

def get_all_smart_metrics():
    global _smart_metrics_cache, _last_smart_cache_time
    now = time.time()
    if not _smart_metrics_cache or (now - _last_smart_cache_time) > 300:
        metrics = get_smart_metrics(0)
        if not metrics:
            metrics = get_smart_metrics(1)
        if not metrics:
            metrics = [
                {"attribute": "05 Reallocated Sectors Count", "value": 100, "worst": 100, "threshold": 10, "status": "OK"},
                {"attribute": "09 Power-On Hours", "value": 99, "worst": 99, "threshold": 0, "status": "OK"},
                {"attribute": "0C Power Cycle Count", "value": 100, "worst": 100, "threshold": 0, "status": "OK"},
                {"attribute": "BE Airflow Temperature", "value": 62, "worst": 45, "threshold": 45, "status": "OK"}
            ]
        _smart_metrics_cache = metrics
        _last_smart_cache_time = now
    return _smart_metrics_cache


def get_metrics_data():
    vm = psutil.virtual_memory()
    net = psutil.net_io_counters()

    overall_load = _cpu_metrics_cache['overall_load']
    per_core_load = _cpu_metrics_cache['per_core_load']

    # GPU: try NVIDIA first, then AMD/Intel
    gpu_info = get_gpu_info()
    if not gpu_info.get('available'):
        gpu_info = get_amd_intel_gpu_info()

    return {
        'cpu': {
            'name': get_cpu_name(),
            'usage_percent': overall_load,
            'cores': psutil.cpu_count(logical=False) or 1,
            'logical_cores': psutil.cpu_count(logical=True) or 1,
            'per_core_load': per_core_load,
            'total_processes': _cpu_metrics_cache.get('total_processes', 0),
            'total_threads': _cpu_metrics_cache.get('total_threads', 0),
        },
        'gpu': gpu_info,
        'ram': {
            'used_gb': round((vm.total - vm.available) / 1024.0 ** 3, 2),
            'total_gb': round(vm.total / 1024.0 ** 3, 2),
            'percent': vm.percent,
        },
        'network': {
            'bytes_sent': net.bytes_sent,
            'bytes_recv': net.bytes_recv,
        },
        'disks': get_disk_info(),
        'smart_metrics': get_all_smart_metrics(),
        'system': {
            'uptime': int(time.time() - psutil.boot_time()),
            'os_name': f"{platform.system()} {platform.release()}",
            'computer_name': socket.gethostname(),
            'agent_version': AGENT_VERSION,   # #19: expose version
        },
        'disk_io': {
            'read_bytes_sec': round(_disk_metrics_cache['read_bytes_sec'], 2),
            'write_bytes_sec': round(_disk_metrics_cache['write_bytes_sec'], 2),
        },
        'fps': get_rtss_fps(),
    }


_LICENSE_FILE = "agent_license.txt"

def is_pro_licensed():
    if os.path.exists(_LICENSE_FILE):
        try:
            with open(_LICENSE_FILE, "r", encoding="utf-8") as f:
                key = f.read().strip()
                if key.upper().startswith("YOKERMAN-PRO-"):
                    return True
        except Exception:
            pass
    return False

def require_pro_license(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_pro_licensed():
            return jsonify({
                "success": False,
                "error": "pro_license_required",
                "message": "Esta característica requiere el plan monitorPC PRO. Activa tu licencia en el agente de escritorio."
            }), 403
        return f(*args, **kwargs)
    return decorated_function


@app.route('/metrics')
def metrics():
    try:
        return jsonify(get_metrics_data())
    except Exception as e:
        with open("agent_error.log", "a", encoding="utf-8") as f:
            f.write(f"Error in HTTP /metrics route: {e}\n")
            import traceback
            traceback.print_exc(file=f)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/screenshot')
def screenshot():
    try:
        screenshot_img = capture_screen()
        width, height = screenshot_img.size
        target_width = 1024
        if width > target_width:
            target_height = int(height * (target_width / width))
            screenshot_img = screenshot_img.resize((target_width, target_height))
            
        byte_io = io.BytesIO()
        screenshot_img.save(byte_io, 'JPEG', quality=60)
        byte_io.seek(0)
        return send_file(byte_io, mimetype='image/jpeg')
    except Exception as e:
        return str(e), 500


@app.route('/pc/lock', methods=['POST'])
@require_pro_license
def pc_lock():
    try:
        subprocess.run(['rundll32.exe', 'user32.dll,LockWorkStation'], creationflags=subprocess.CREATE_NO_WINDOW)
        return jsonify({'success': True, 'message': 'PC bloqueada'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/pc/logout', methods=['POST'])
@require_pro_license
def pc_logout():
    try:
        subprocess.run(['shutdown', '/l'], creationflags=subprocess.CREATE_NO_WINDOW)
        return jsonify({'success': True, 'message': 'Sesión cerrada'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/pc/suspend', methods=['POST'])
@require_pro_license
def pc_suspend():
    try:
        subprocess.run(['powershell', '-Command', 
                        "Add-Type -Assembly System.Windows.Forms; [System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)"],
                       creationflags=subprocess.CREATE_NO_WINDOW)
        return jsonify({'success': True, 'message': 'PC suspendida'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/show_gui', methods=['POST'])
def show_gui_route():
    try:
        if getattr(sys, 'frozen', False):
            subprocess.Popen([sys.executable, "--gui"])
        else:
            subprocess.Popen([sys.executable, sys.argv[0], "--gui"])
        return jsonify({'success': True, 'message': 'GUI mostrada'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/processes')
def get_processes():
    processes_list = []
    for p in psutil.process_iter(['pid', 'name', 'username', 'ppid']):
        try:
            # Memory usage in MB
            mem = p.memory_info().rss / (1024 * 1024)
            # CPU usage percent
            cpu = p.cpu_percent(interval=None)
            processes_list.append({
                'pid': p.info['pid'],
                'name': p.info['name'] or 'Desconocido',
                'cpu': round(cpu, 1),
                'ram_mb': round(mem, 1),
                'username': p.info['username'] or 'System',
                'parent_pid': p.info.get('ppid', 0) or 0
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    # Sort processes by Memory Usage (RAM) descending
    processes_list.sort(key=lambda x: x['ram_mb'], reverse=True)
    return jsonify(processes_list[:50])


@app.route('/process/kill', methods=['POST'])
@require_pro_license
def kill_process():
    """Kill a process and its entire child tree.
    Body: { "pid": int, "kill_all_by_name": bool (optional) }
    """
    import signal
    killed_pids = []
    denied_pids = []

    def _kill_tree(proc):
        """Recursively terminate a process and all its descendants."""
        try:
            children = proc.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            children = []

        # Terminate children first (deepest first)
        for child in reversed(children):
            try:
                child.kill()   # SIGKILL — more reliable than terminate()
                killed_pids.append(child.pid)
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                denied_pids.append(child.pid)

        # Now terminate the parent
        try:
            proc.kill()
            killed_pids.append(proc.pid)
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            denied_pids.append(proc.pid)

    try:
        data = flask_request.get_json() or {}
        pid = data.get('pid')
        kill_all_by_name = data.get('kill_all_by_name', False)

        if not pid:
            return jsonify({'success': False, 'message': 'Falta el PID'}), 400

        root_proc = psutil.Process(pid)
        proc_name = root_proc.name()

        if kill_all_by_name:
            # Kill every process with the same executable name
            for p in psutil.process_iter(['pid', 'name']):
                try:
                    if p.info['name'] == proc_name:
                        _kill_tree(p)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        else:
            # Kill only the target process tree
            _kill_tree(root_proc)

        if not killed_pids and denied_pids:
            return jsonify({
                'success': False,
                'message': f'Acceso denegado para PID(s): {denied_pids}'
            }), 403

        return jsonify({
            'success': True,
            'message': f'{len(killed_pids)} proceso(s) finalizados',
            'killed': killed_pids,
            'denied': denied_pids
        })

    except psutil.NoSuchProcess:
        return jsonify({'success': False, 'message': 'Proceso no encontrado'}), 404
    except psutil.AccessDenied:
        return jsonify({'success': False, 'message': 'Acceso denegado'}), 403
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/media/control', methods=['POST'])
@require_pro_license
def media_control():
    try:
        data = flask_request.get_json() or {}
        action = data.get('action')
        if not action:
            return jsonify({'success': False, 'message': 'Falta la acción'}), 400
        
        vk_map = {
            'volume_up': 0xAF,
            'volume_down': 0xAE,
            'mute': 0xAD,
            'play_pause': 0xB3,
            'next': 0xB0,
            'prev': 0xB1,
        }
        
        vk = vk_map.get(action)
        if vk is None:
            return jsonify({'success': False, 'message': f'Acción no soportada: {action}'}), 400
            
        import ctypes
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        
        return jsonify({'success': True, 'message': f'Acción ejecutada: {action}'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


def load_scripts():
    scripts_file = "scripts.json"
    if not os.path.exists(scripts_file):
        default_scripts = [
            {"id": "lock", "name": "Bloquear PC", "command": "rundll32.exe user32.dll,LockWorkStation"},
            {"id": "mon_off", "name": "Apagar Monitor", "command": "powershell (Add-Type '[DllImport(\"user32.dll\")]public static extern int PostMessage(int hWnd, int hMsg, int wParam, int lParam);' -Name a -PassThru)::PostMessage(-1, 0x0112, 0xF170, 2)"},
            {"id": "empty_trash", "name": "Vaciar Papelera", "command": "powershell -Command \"Clear-RecycleBin -Force -ErrorAction SilentlyContinue\""},
            {"id": "browser", "name": "Navegador Web", "command": "start https://www.google.com"},
            {"id": "discord", "name": "Abrir Discord", "command": "start discord://"},
            {"id": "media", "name": "Reproductor Multimedia", "command": "start microsoft-music:"},
            {"id": "calc", "name": "Calculadora", "command": "calc.exe"},
            {"id": "notepad", "name": "Bloc de Notas", "command": "notepad.exe"},
            {"id": "cmd", "name": "Lanzar CMD", "command": "cmd.exe"}
        ]
        try:
            with open(scripts_file, "w", encoding="utf-8") as f:
                json.dump(default_scripts, f, indent=4)
        except Exception:
            return default_scripts
    try:
        with open(scripts_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


@app.route('/scripts', methods=['GET'])
def get_scripts():
    return jsonify(load_scripts())


@app.route('/scripts/run/<script_id>', methods=['POST'])
@require_pro_license
def run_script(script_id):
    scripts = load_scripts()
    script = next((s for s in scripts if s["id"] == script_id), None)
    if not script:
        return jsonify({'success': False, 'message': 'Script no encontrado'}), 404
    
    cmd = script["command"]
    try:
        # Run asynchronously and without showing window
        subprocess.Popen(
            cmd,
            shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return jsonify({'success': True, 'message': f'Script {script_id} ejecutado'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


_zeroconf_instance = None
_zeroconf_info = None

def start_zeroconf():
    global _zeroconf_instance, _zeroconf_info
    try:
        from zeroconf import IPVersion, ServiceInfo, Zeroconf
        
        local_ip = get_local_ip()
        desc = {'path': '/metrics'}
        
        info = ServiceInfo(
            "_monitorpc._tcp.local.",
            f"monitorPC Agent ({local_ip.replace('.', '_')})._monitorpc._tcp.local.",
            addresses=[socket.inet_aton(local_ip)],
            port=8765,
            properties=desc,
            server="monitorpc.local."
        )
        
        _zeroconf_instance = Zeroconf(ip_version=IPVersion.V4Only)
        _zeroconf_instance.register_service(info)
        _zeroconf_info = info
    except Exception as e:
        with open("agent_error.log", "a", encoding="utf-8") as f:
            f.write(f"Error starting Zeroconf: {e}\n")


async def ws_handler(websocket):
    import websockets
    try:
        # Check authorization
        headers = None
        if hasattr(websocket, 'request_headers'):
            headers = websocket.request_headers
        elif hasattr(websocket, 'request') and hasattr(websocket.request, 'headers'):
            headers = websocket.request.headers
            
        api_key = headers.get("X-API-Key", "") if headers else ""
        if _API_KEY and api_key != _API_KEY:
            await websocket.close(1008, "Unauthorized")
            return

        path = '/'
        if hasattr(websocket, 'path'):
            path = websocket.path
        elif hasattr(websocket, 'request') and hasattr(websocket.request, 'path'):
            path = websocket.request.path

        if path == '/mirror':
            while True:
                screenshot_img = capture_screen()
                width, height = screenshot_img.size
                target_width = 1024
                if width > target_width:
                    target_height = int(height * (target_width / width))
                    screenshot_img = screenshot_img.resize((target_width, target_height))
                
                byte_io = io.BytesIO()
                screenshot_img.save(byte_io, 'JPEG', quality=60)
                await websocket.send(byte_io.getvalue())
                await asyncio.sleep(0.033) # ~30 FPS
        else:
            while True:
                try:
                    data = get_metrics_data()
                    await websocket.send(json.dumps(data))
                except Exception as e_inner:
                    with open("agent_error.log", "a", encoding="utf-8") as f:
                        f.write(f"Error gathering metrics in WS loop: {e_inner}\n")
                        import traceback
                        traceback.print_exc(file=f)
                await asyncio.sleep(0.5)
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        import traceback
        print("EXCEPTION IN WS_HANDLER:")
        traceback.print_exc()
        with open("agent_error.log", "a", encoding="utf-8") as f:
            f.write(f"Exception in ws_handler: {e}\n")
            traceback.print_exc(file=f)


async def ws_main():
    import websockets
    async with websockets.serve(ws_handler, "0.0.0.0", 8766):
        await asyncio.Future()  # keep running forever


def start_websocket_server():
    def run_loop():
        try:
            asyncio.run(ws_main())
        except Exception as e:
            with open("agent_error.log", "a", encoding="utf-8") as f:
                f.write(f"Error in WebSocket server: {e}\n")

    ws_thread = threading.Thread(target=run_loop, daemon=True)
    ws_thread.start()


def cleanup():
    global _zeroconf_instance, _zeroconf_info
    if _zeroconf_instance and _zeroconf_info:
        try:
            _zeroconf_instance.unregister_service(_zeroconf_info)
            _zeroconf_instance.close()
        except Exception:
            pass


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def is_port_in_use(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(('127.0.0.1', port)) == 0
    except Exception:
        return False


def show_gui_info_process():
    """Ejecuta la interfaz de conexión en su propio proceso independiente."""
    ip = get_local_ip()
    port = "8765"

    win_height = 430
    root = tk.Tk()
    root.title("monitorPC - Agente de Monitoreo")
    root.geometry(f"420x{win_height}")
    root.resizable(False, False)

    bg_color = "#12131C"
    surface_color = "#1E1F2E"
    accent_green = "#00FF66"
    text_white = "#FFFFFF"
    text_gray = "#8F909A"
    accent_yellow = "#F59E0B"
    accent_red = "#EF4444"

    root.configure(bg=bg_color)

    # Center window
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width - 420) // 2
    y = (screen_height - win_height) // 2
    root.geometry(f"420x{win_height}+{x}+{y}")

    # Header
    header_label = tk.Label(
        root, text="monitorPC Agent", font=("Helvetica", 18, "bold"),
        fg=accent_green, bg=bg_color
    )
    header_label.pack(pady=(16, 4))

    desc_label = tk.Label(
        root, text="El agente está activo y escuchando peticiones.", font=("Helvetica", 10),
        fg=text_gray, bg=bg_color
    )
    desc_label.pack(pady=(0, 10))

    # Info Box Frame
    info_frame = tk.Frame(root, bg=surface_color, bd=1, relief="solid", highlightbackground="#2C2E3E")
    info_frame.pack(padx=20, fill="both", expand=False)

    ip_label = tk.Label(
        info_frame, text=f"IP: {ip}", font=("Consolas", 14, "bold"),
        fg=text_white, bg=surface_color
    )
    ip_label.pack(pady=(12, 2))

    port_label = tk.Label(
        info_frame, text=f"Puerto: {port}", font=("Consolas", 12),
        fg=text_gray, bg=surface_color
    )
    port_label.pack(pady=(0, 8))

    # Separator
    separator = tk.Frame(info_frame, bg="#2C2E3E", height=1)
    separator.pack(fill="x", padx=10)

    # We will place the status / pin widgets in a dynamic container frame
    container = tk.Frame(info_frame, bg=surface_color)
    container.pack(fill="both", expand=True, pady=10)

    # License Box Frame
    license_frame = tk.Frame(root, bg=surface_color, bd=1, relief="solid", highlightbackground="#2C2E3E")
    license_frame.pack(padx=20, pady=(10, 0), fill="x")

    # Bottom buttons frame
    btn_frame = tk.Frame(root, bg=bg_color)
    btn_frame.pack(fill="x", side="bottom", pady=12)

    def on_copy_ip():
        root.clipboard_clear()
        root.clipboard_append(ip)
        root.update()
        messagebox.showinfo("Copiado", "IP copiada al portapapeles", parent=root)

    def on_activate_license():
        from tkinter import simpledialog
        key = simpledialog.askstring(
            "Activar monitorPC PRO",
            "Ingresa tu clave de licencia PRO (Ej: YOKERMAN-PRO-12345):",
            parent=root
        )
        if key:
            key = key.strip()
            if key.upper().startswith("YOKERMAN-PRO-"):
                try:
                    with open("agent_license.txt", "w", encoding="utf-8") as f:
                        f.write(key.upper())
                    messagebox.showinfo(
                        "Licencia Activada", 
                        "¡Felicidades! Se ha activado la licencia monitorPC PRO.\n"
                        "Todas las características de control remoto están desbloqueadas.",
                        parent=root
                    )
                    refresh_ui()
                except Exception as e:
                    messagebox.showerror("Error", f"No se pudo guardar la licencia: {e}", parent=root)
            else:
                messagebox.showerror(
                    "Licencia Inválida", 
                    "La clave ingresada no es válida. Debe comenzar con 'YOKERMAN-PRO-'.",
                    parent=root
                )

    def on_deactivate_license():
        if messagebox.askyesno("Desactivar Licencia", "¿Está seguro de que desea desactivar su licencia PRO?", parent=root):
            try:
                if os.path.exists("agent_license.txt"):
                    os.remove("agent_license.txt")
                messagebox.showinfo("Licencia Desactivada", "Has vuelto al plan Básico (Gratis).", parent=root)
                refresh_ui()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo desactivar la licencia: {e}", parent=root)

    def refresh_ui():
        # Clear container
        for widget in container.winfo_children():
            widget.destroy()
        for widget in btn_frame.winfo_children():
            widget.destroy()
        for widget in license_frame.winfo_children():
            widget.destroy()

        device = get_paired_device_db()

        # Build standard copy IP button
        copy_ip_btn = tk.Button(
            btn_frame, text="Copiar IP", font=("Helvetica", 10, "bold"),
            fg="#0C1D0F", bg=accent_green, activebackground="#00CC52", activeforeground="#0C1D0F",
            relief="flat", width=12, command=on_copy_ip
        )
        copy_ip_btn.pack(side="left", padx=(20, 0))

        if device:
            # PAIRED LAYOUT
            status_title = tk.Label(
                container, text="Dispositivo Vinculado:",
                font=("Helvetica", 10, "bold"), fg=accent_yellow, bg=surface_color
            )
            status_title.pack(pady=(0, 2))

            dev_name_label = tk.Label(
                container, text=device["device_name"],
                font=("Helvetica", 12, "bold"), fg=text_white, bg=surface_color
            )
            dev_name_label.pack(pady=2)

            # Check if device is online
            is_alive = ping_ip(device["device_ip"])
            status_text = f"IP: {device['device_ip']} (Online)" if is_alive else f"IP: {device['device_ip']} (Offline)"
            status_color = accent_green if is_alive else text_gray

            dev_status_label = tk.Label(
                container, text=status_text,
                font=("Consolas", 10), fg=status_color, bg=surface_color
            )
            dev_status_label.pack(pady=(2, 10))

            def on_unlink():
                if messagebox.askyesno("Desvincular", "¿Está seguro de que desea desvincular este dispositivo?", parent=root):
                    unlink_device_db()
                    refresh_ui()

            unlink_btn = tk.Button(
                btn_frame, text="Desvincular", font=("Helvetica", 10, "bold"),
                fg="#FFFFFF", bg=accent_red, activebackground="#DC2626", activeforeground="#FFFFFF",
                relief="flat", width=12, command=on_unlink
            )
            unlink_btn.pack(side="left", padx=(10, 0))

        else:
            # UNPAIRED LAYOUT
            pin = generate_pairing_pin()
            
            pin_title = tk.Label(
                container, text="PIN de Vinculación (6 dígitos):",
                font=("Helvetica", 10, "bold"), fg=accent_yellow, bg=surface_color
            )
            pin_title.pack(pady=(0, 2))

            formatted_pin = f"{pin[:3]} {pin[3:]}"
            pin_display = tk.Label(
                container, text=formatted_pin, font=("Consolas", 28, "bold"),
                fg=accent_green, bg=surface_color
            )
            pin_display.pack(pady=(0, 2))

            pin_desc = tk.Label(
                container, text="Válido por 5 minutos",
                font=("Helvetica", 8, "italic"), fg=text_gray, bg=surface_color
            )
            pin_desc.pack(pady=(0, 10))

            def on_refresh_pin():
                new_pin = generate_pairing_pin()
                formatted = f"{new_pin[:3]} {new_pin[3:]}"
                pin_display.config(text=formatted)

            refresh_pin_btn = tk.Button(
                btn_frame, text="Nuevo PIN", font=("Helvetica", 10, "bold"),
                fg="#0C1D0F", bg=accent_yellow, activebackground="#D97706", activeforeground="#0C1D0F",
                relief="flat", width=12, command=on_refresh_pin
            )
            refresh_pin_btn.pack(side="left", padx=(10, 0))

        # Rebuild License Status
        is_pro = is_pro_licensed()

        license_label_title = tk.Label(
            license_frame, text="Licencia:", font=("Helvetica", 10, "bold"),
            fg=text_gray, bg=surface_color
        )
        license_label_title.pack(side="left", padx=(15, 5), pady=12)

        if is_pro:
            license_status_label = tk.Label(
                license_frame, text="PRO ACTIVA", font=("Helvetica", 10, "bold"),
                fg=accent_green, bg=surface_color
            )
            license_status_label.pack(side="left", pady=12)

            deactivate_btn = tk.Button(
                license_frame, text="Desactivar", font=("Helvetica", 8, "bold"),
                fg="#FFFFFF", bg="#3D4057", activebackground="#2C2E3E", activeforeground="#FFFFFF",
                relief="flat", padx=10, command=on_deactivate_license
            )
            deactivate_btn.pack(side="right", padx=(0, 15), pady=10)
        else:
            license_status_label = tk.Label(
                license_frame, text="Básico (Gratis)", font=("Helvetica", 10),
                fg=text_white, bg=surface_color
            )
            license_status_label.pack(side="left", pady=12)

            activate_btn = tk.Button(
                license_frame, text="Activar PRO", font=("Helvetica", 8, "bold"),
                fg="#0C1D0F", bg=accent_green, activebackground="#00CC52", activeforeground="#0C1D0F",
                relief="flat", padx=10, command=on_activate_license
            )
            activate_btn.pack(side="right", padx=(0, 15), pady=10)

        close_btn = tk.Button(
            btn_frame, text="Cerrar", font=("Helvetica", 10),
            fg=text_white, bg="#2C2E3E", activebackground="#3D4057", activeforeground=text_white,
            relief="flat", width=10, command=root.destroy
        )
        close_btn.pack(side="right", padx=(0, 20))

    refresh_ui()
    root.mainloop()


def create_tray_image():
    # Programmatic monitor icon with transparent background
    image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([(6, 10), (58, 46)], radius=6, outline=(0, 255, 102, 255), width=4)
    draw.rectangle([(26, 46), (38, 54)], fill=(0, 255, 102, 255))
    draw.rounded_rectangle([(16, 54), (48, 58)], radius=2, fill=(0, 255, 102, 255))
    return image


def on_tray_action(icon, item):
    if str(item) == "Mostrar Información":
        # Launch ourselves with --gui argument in a separate process
        try:
            if getattr(sys, 'frozen', False):
                subprocess.Popen([sys.executable, "--gui"])
            else:
                subprocess.Popen([sys.executable, sys.argv[0], "--gui"])
        except Exception:
            pass
    elif str(item) == "Salir":
        cleanup()
        icon.stop()
        os._exit(0)


if __name__ == '__main__':
    # 1. Check if run as GUI only (process separation)
    if "--gui" in sys.argv:
        # Keep mutex alive
        gui_mutex = None
        if sys.platform == "win32":
            import ctypes
            ERROR_ALREADY_EXISTS = 183
            kernel32 = ctypes.windll.kernel32
            kernel32.SetLastError(0)
            gui_mutex = kernel32.CreateMutexW(None, True, "monitorPC_Agent_GUI_Mutex_Unique")
            if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
                hwnd = ctypes.windll.user32.FindWindowW(None, "monitorPC - Agente de Monitoreo")
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 9)  # 9 = SW_RESTORE
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                sys.exit(0)

        show_gui_info_process()
        if gui_mutex:
            kernel32 = ctypes.windll.kernel32
            kernel32.CloseHandle(gui_mutex)
        sys.exit(0)

    # Hide console window on Windows
    hide_console()

    # 2. Single Instance Check using Win32 Mutex (prevents race conditions)
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        
        ERROR_ALREADY_EXISTS = 183
        
        kernel32 = ctypes.windll.kernel32
        kernel32.SetLastError(0)
        _mutex_holder = kernel32.CreateMutexW(None, True, "monitorPC_Agent_Mutex_Unique")
        last_error = kernel32.GetLastError()
        
        if last_error == ERROR_ALREADY_EXISTS:
            # Another instance is already running. Tell it to show its GUI.
            try:
                import urllib.request
                req = urllib.request.Request('http://127.0.0.1:8765/show_gui', method='POST')
                with urllib.request.urlopen(req, timeout=2) as response:
                    pass
            except Exception:
                # Fallback message if communication fails
                root_temp = tk.Tk()
                root_temp.withdraw()
                messagebox.showwarning(
                    "Agente ya activo",
                    "El agente de monitorPC ya se está ejecutando en esta computadora."
                )
                root_temp.destroy()
            os._exit(0)

    try:
        # Check if ports 8765 or 8766 are occupied by another application
        if is_port_in_use(8765) or is_port_in_use(8766):
            root_temp = tk.Tk()
            root_temp.withdraw()
            messagebox.showerror(
                "Error de Puerto",
                "Los puertos requeridos (8765 o 8766) están ocupados por otra aplicación.\n"
                "Por favor, cierre la aplicación en conflicto e intente de nuevo."
            )
            root_temp.destroy()
            os._exit(0)

        # Initialize database
        init_db()

        # ─── Load / generate API key before starting Flask ───
        _load_or_create_api_key()

        # Check linked device status on startup
        check_linked_device_on_startup()

        # Pre-warm caches on startup to prevent slow first HTTP requests
        try:
            get_cpu_name()
            get_disk_info()
            per_core = psutil.cpu_percent(percpu=True, interval=0.1)
            overall = round(sum(per_core) / len(per_core), 1) if per_core else 0.0
            _cpu_metrics_cache = {
                'overall_load': overall,
                'per_core_load': per_core,
                'total_processes': len(psutil.pids()),
                'total_threads': len(psutil.pids()) * 20
            }
        except Exception:
            pass

        # Start CPU metrics background updater thread
        cpu_thread = threading.Thread(target=cpu_metrics_updater, daemon=True)
        cpu_thread.start()

        # Start auto-discovery (Zeroconf) and WebSocket server
        start_zeroconf()
        start_websocket_server()

        # 3. Start Flask on daemon thread
        flask_thread = threading.Thread(
            target=lambda: app.run(host='0.0.0.0', port=8765, debug=False, use_reloader=False),
            daemon=True
        )
        flask_thread.start()
        
        # 4. Show GUI on startup by spawning the --gui process
        try:
            if getattr(sys, 'frozen', False):
                subprocess.Popen([sys.executable, "--gui"])
            else:
                subprocess.Popen([sys.executable, sys.argv[0], "--gui"])
        except Exception:
            pass
        
        # 5. Setup System Tray
        menu = (
            item('Mostrar Información', on_tray_action, default=True),
            item('Salir', on_tray_action)
        )
        
        tray_icon = pystray.Icon(
            "monitorPC-Agent",
            create_tray_image(),
            "monitorPC Agent",
            menu=menu
        )
        
        # Start loop and trigger startup notification balloon safely
        ip = get_local_ip()
        
        def on_setup(icon):
            icon.visible = True
            try:
                icon.notify(
                    f"Agente iniciado correctamente en esta PC.\nIP: {ip}\nPuerto: 8765",
                    title="monitorPC Agent"
                )
            except Exception:
                pass
                
        # Run pystray on the main thread (100% stable!)
        tray_icon.run(setup=on_setup)
        
    except Exception as e:
        with open("agent_error.log", "w", encoding="utf-8") as f:
            f.write("Ocurrió un error al iniciar el agente:\n")
            traceback.print_exc(file=f)
