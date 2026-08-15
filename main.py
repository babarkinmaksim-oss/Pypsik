#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

devices = {}

# ========== 1. РЕГИСТРАЦИЯ ==========
@app.route('/register', methods=['POST'])
def register():
    data = request.json
    device_id = data.get('id')
    dev_type = data.get('type', 'pc')
    if not device_id:
        return jsonify({'ok': False}), 400
    if device_id not in devices:
        devices[device_id] = {}
    devices[device_id].update({
        'deviceType': dev_type,
        'last_seen': datetime.now().isoformat(),
        'online': True,
        'screen': None,
        'cmd': None,
        'cmd_x': 0,
        'cmd_y': 0,
        'auto_screen': True
    })
    return jsonify({'ok': True})

# ========== 2. ОПРОС ==========
@app.route('/poll/<device_id>')
def poll(device_id):
    if device_id not in devices:
        return jsonify({'cmd': None})
    dev = devices[device_id]
    dev['last_seen'] = datetime.now().isoformat()
    dev['online'] = True
    cmd = dev.get('cmd')
    x = dev.get('cmd_x', 0)
    y = dev.get('cmd_y', 0)
    if cmd:
        dev['cmd'] = None
        return jsonify({'cmd': cmd, 'x': x, 'y': y})
    return jsonify({'cmd': None})

# ========== 3. ПРИЁМ СКРИНОВ ==========
@app.route('/screen', methods=['POST'])
def screen():
    data = request.json
    device_id = data.get('id')
    screen_data = data.get('screen')
    if device_id not in devices:
        return jsonify({'ok': False}), 404
    devices[device_id]['screen'] = screen_data
    devices[device_id]['last_seen'] = datetime.now().isoformat()
    devices[device_id]['online'] = True
    return jsonify({'ok': True})

# ========== 4. АДМИН: ДОБАВИТЬ ==========
@app.route('/admin/add', methods=['POST'])
def admin_add():
    data = request.json
    device_id = data.get('id')
    if not device_id:
        return jsonify({'ok': False}), 400
    if device_id not in devices:
        devices[device_id] = {
            'deviceType': 'unknown',
            'last_seen': datetime.now().isoformat(),
            'online': False,
            'screen': None,
            'cmd': None,
            'cmd_x': 0,
            'cmd_y': 0,
            'auto_screen': True
        }
    return jsonify({'ok': True})

# ========== 5. АДМИН: КОМАНДА ==========
@app.route('/cmd', methods=['POST'])
def send_cmd():
    data = request.json
    device_id = data.get('id')
    cmd = data.get('cmd')
    if device_id not in devices:
        return jsonify({'ok': False}), 404
    devices[device_id]['cmd'] = cmd
    devices[device_id]['cmd_x'] = data.get('x', 0)
    devices[device_id]['cmd_y'] = data.get('y', 0)
    return jsonify({'ok': True})

# ========== 6. АДМИН: СПИСОК ==========
@app.route('/devices')
def list_devices():
    clean = {}
    now = datetime.now()
    for k, v in devices.items():
        if v.get('last_seen'):
            try:
                last = datetime.fromisoformat(v['last_seen'])
                if (now - last).seconds > 60:
                    v['online'] = False
            except:
                pass
        clean[k] = {key: val for key, val in v.items() if key not in ['cmd', 'cmd_x', 'cmd_y']}
    return jsonify(clean)

# ========== 7. СТРАНИЦЫ ==========
MASK_PAGE = '''
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>DDS_MrL</title>
  <style>
    *{margin:0;padding:0;box-sizing:border-box}
    body{background:#0b0e1a;color:#c0caf5;font-family:system-ui,sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;flex-direction:column;padding:20px;text-align:center;}
    .box{background:#161b22;padding:30px;border-radius:16px;border:1px solid #30363d;max-width:400px;width:100%;}
    .id{font-size:20px;font-weight:bold;color:#58a6ff;word-break:break-all;background:#0d1117;padding:12px;border-radius:8px;margin:15px 0;border:1px solid #30363d;}
    .btn{background:#238636;border:none;padding:12px;border-radius:8px;color:#fff;font-weight:bold;font-size:16px;width:100%;cursor:pointer;margin-top:10px;}
    .small{font-size:12px;color:#484f58;margin-top:10px;}
  </style>
</head>
<body>
<div class="box">
  <h2>📡 DDS_MrL</h2>
  <div style="color:#8b949e;font-size:14px;">Ваш ID устройства:</div>
  <div class="id" id="deviceId">---</div>
  <button class="btn" id="regBtn">🔗 Активировать управление</button>
  <div class="small" id="statusText">Нажмите кнопку для активации</div>
</div>
<script>
  (function() {
    const deviceId = localStorage.getItem("dds_id") || crypto.randomUUID();
    localStorage.setItem("dds_id", deviceId);
    document.getElementById('deviceId').innerText = deviceId;
    let deviceType = "pc";
    if(/android|iphone|ipad|tablet/i.test(navigator.userAgent)) deviceType = "tablet";
    if(/mobile/i.test(navigator.userAgent) && !/tablet/i.test(navigator.userAgent)) deviceType = "phone";
    let active = false;
    let screenInterval = null;

    document.getElementById('regBtn').addEventListener('click', function() {
      fetch("/register", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({id: deviceId, type: deviceType})
      }).then(r => r.json()).then(data => {
        if(data.ok) {
          active = true;
          document.getElementById('statusText').innerText = "✅ Активно! Авто-скриншоты включены";
          document.getElementById('regBtn').innerText = "🔄 Обновить регистрацию";
          pollCommands();
          startAutoScreen();
        } else {
          document.getElementById('statusText').innerText = "❌ Ошибка, попробуйте снова";
        }
      }).catch(() => {
        document.getElementById('statusText').innerText = "❌ Ошибка сети";
      });
    });

    function pollCommands() {
      if(!active) return;
      fetch("/poll/" + deviceId)
        .then(r => r.json())
        .then(data => {
          if(data.cmd) executeCmd(data.cmd, data.x, data.y);
          setTimeout(pollCommands, 2000);
        }).catch(() => setTimeout(pollCommands, 5000));
    }

    function executeCmd(cmd, x, y) {
      if(cmd === "mouse_move") {
        document.dispatchEvent(new MouseEvent("mousemove", {clientX: x, clientY: y, bubbles: true}));
      } else if(cmd === "click") {
        document.dispatchEvent(new MouseEvent("click", {clientX: x, clientY: y, bubbles: true}));
      } else if(cmd === "block_mouse") {
        document.body.style.pointerEvents = "none";
        document.addEventListener("mousedown", e=>e.preventDefault(), true);
        document.addEventListener("touchstart", e=>e.preventDefault(), true);
      } else if(cmd === "unblock_mouse") {
        document.body.style.pointerEvents = "auto";
      } else if(cmd === "capture_screen") {
        captureScreen();
      }
    }

    function startAutoScreen() {
      if(screenInterval) clearInterval(screenInterval);
      captureScreen();
      screenInterval = setInterval(captureScreen, 3000);
    }

    async function captureScreen() {
      if(!active) return;
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
        await fetch("/screen", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({id: deviceId, screen: dataUrl})
        });
      } catch(e){}
    }

    window.addEventListener('beforeunload', function() {
      if(screenInterval) clearInterval(screenInterval);
    });
  })();
</script>
</body>
</html>
'''

ADMIN_PANEL = '''
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>DDS_MrL Admin</title>
  <style>
    *{margin:0;padding:0;box-sizing:border-box}
    body{background:#0d1117;color:#c9d1d9;font-family:system-ui,sans-serif;padding:15px;max-width:900px;margin:auto;}
    .box{background:#161b22;padding:20px;border-radius:12px;border:1px solid #30363d;margin-bottom:15px;}
    input{width:100%;padding:12px;background:#0d1117;border:1px solid #30363d;color:#fff;border-radius:6px;font-size:16px;margin-bottom:10px;}
    .btn{background:#1f6feb;border:none;padding:10px 20px;border-radius:6px;color:#fff;font-weight:bold;cursor:pointer;margin-right:8px;font-size:14px;}
    .btn-danger{background:#da3633;}
    .btn-success{background:#238636;}
    .device-card{background:#161b22;border:1px solid #2ea043;border-radius:10px;padding:14px;margin-bottom:12px;}
    .device-card.offline{border-color:#da3633;opacity:0.6;}
    .id{font-size:14px;color:#58a6ff;word-break:break-all;}
    .type{font-size:12px;color:#8b949e;}
    .btn-group{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px;}
    .btn-group button{padding:6px 12px;border-radius:6px;border:1px solid #30363d;background:#21262d;color:#c9d1d9;cursor:pointer;font-size:12px;}
    .screen-img{max-width:100%;border-radius:6px;margin-top:8px;border:1px solid #30363d;}
    .viewer-area{background:#161b22;padding:15px;border-radius:10px;margin-top:15px;border:1px solid #30363d;}
    .viewer-area img{max-width:100%;border-radius:6px;height:auto;}
    .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:10px;}
    .row input[type="number"]{width:60px;padding:4px;background:#0d1117;border:1px solid #30363d;color:#fff;border-radius:4px;}
    .row button{background:#21262d;border:1px solid #30363d;color:#c9d1d9;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px;}
    .stats{margin-bottom:12px;}
    .stat{display:inline-block;background:#21262d;padding:4px 14px;border-radius:20px;margin:3px 3px 0 0;font-size:13px;}
  </style>
</head>
<body>
<div id="app">
  <h1>🛸 DDS_MrL — Управление</h1>
  <div class="box">
    <h3>➕ Добавить устройство по ID</h3>
    <input type="text" id="deviceIdInput" placeholder="Вставьте ID устройства">
    <button class="btn btn-success" onclick="addDevice()">Добавить</button>
    <button class="btn" onclick="refreshDevices()">🔄 Обновить список</button>
  </div>
  <div class="stats">
    <span class="stat" id="onlineCount">🟢 0 онлайн</span>
    <span class="stat" id="autoCount">📸 Авто-скрины: 0</span>
  </div>
  <div id="deviceList"></div>
  <div id="viewerArea" class="viewer-area" style="display:none;">
    <h3 id="viewerTitle">Просмотр (обновляется каждые 3 сек)</h3>
    <img id="viewerScreen" src="" />
    <div class="row">
      <button class="btn" onclick="sendCmd(currentViewId, 'capture_screen')">📸 Ручной скрин</button>
      <button class="btn-danger" onclick="sendCmd(currentViewId, 'block_mouse')">🖱️ Заблок.</button>
      <button onclick="sendCmd(currentViewId, 'unblock_mouse')">🖱️ Разблок.</button>
      <span>X</span><input type="number" id="mx" value="300">
      <span>Y</span><input type="number" id="my" value="200">
      <button onclick="sendCmd(currentViewId, 'mouse_move', parseInt(document.getElementById('mx').value), parseInt(document.getElementById('my').value))">⬆️ Двиг</button>
      <button onclick="sendCmd(currentViewId, 'click', parseInt(document.getElementById('mx').value), parseInt(document.getElementById('my').value))">🔘 Клик</button>
    </div>
  </div>
</div>
<script>
  let devices = {};
  let currentViewId = null;
  let viewerInterval = null;

  function addDevice() {
    const id = document.getElementById('deviceIdInput').value.trim();
    if(!id) return alert('Введите ID');
    fetch("/admin/add", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({id: id})
    }).then(r => r.json()).then(data => {
      if(data.ok) { refreshDevices(); document.getElementById('deviceIdInput').value = ''; }
      else alert('Ошибка');
    });
  }

  function refreshDevices() {
    fetch("/devices").then(r => r.json()).then(data => { devices = data; renderDevices(); updateViewer(); });
  }

  function sendCmd(id, cmd, x, y) {
    fetch("/cmd", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({id: id, cmd: cmd, x: x || 0, y: y || 0})
    });
  }

  function viewDevice(id) {
    currentViewId = id;
    document.getElementById('viewerArea').style.display = 'block';
    document.getElementById('viewerTitle').innerText = 'Просмотр: ' + id.slice(0,8) + '... (обновляется)';
    if(viewerInterval) clearInterval(viewerInterval);
    viewerInterval = setInterval(updateViewer, 3000);
    updateViewer();
  }

  function updateViewer() {
    if(!currentViewId) return;
    const scr = (devices[currentViewId] && devices[currentViewId].screen) ? devices[currentViewId].screen : '';
    document.getElementById('viewerScreen').src = scr;
  }

  function renderDevices() {
    let html = '', online = 0, autoCount = 0;
    for(let id in devices) {
      let d = devices[id];
      if(!d) continue;
      if(d.online) online++;
      if(d.auto_screen) autoCount++;
      let cls = d.online ? '' : 'offline';
      let scr = (d.screen) ? '<img src="'+d.screen+'" class="screen-img" />' : '';
      let lastSeen = d.last_seen || '—';
      let autoLabel = d.auto_screen ? '📸 авт' : '⏸️ пауза';
      html += '<div class="device-card '+cls+'">';
      html += '<div class="id">'+id+'</div>';
      html += '<div class="type">'+d.deviceType+' | '+autoLabel+' | последний: '+lastSeen+'</div>';
      html += '<div class="btn-group">';
      html += '<button onclick="sendCmd(\''+id+'\', \'capture_screen\')">📸 Скрин</button>';
      html += '<button onclick="viewDevice(\''+id+'\')">👁️ Смотреть</button>';
      html += '<button onclick="sendCmd(\''+id+'\', \'block_mouse\')">🖱️ Заблок.</button>';
      html += '<button onclick="sendCmd(\''+id+'\', \'unblock_mouse\')">🖱️ Разблок.</button>';
      html += '<button onclick="sendCmd(\''+id+'\', \'click\', 100, 100)">🔘 Клик</button>';
      html += '<button onclick="sendCmd(\''+id+'\', \'mouse_move\', 200, 200)">⬆️ Двиг</button>';
      html += '</div>'+scr+'</div>';
    }
    document.getElementById('deviceList').innerHTML = html;
    document.getElementById('onlineCount').innerText = '🟢 '+online+' онлайн';
    document.getElementById('autoCount').innerText = '📸 Авто-скрины: '+autoCount;
    if(currentViewId && !devices[currentViewId]) {
      document.getElementById('viewerArea').style.display = 'none';
      currentViewId = null;
      if(viewerInterval) clearInterval(viewerInterval);
    }
  }

  refreshDevices();
  setInterval(refreshDevices, 5000);
</script>
</body>
</html>
'''

@app.route('/')
def index():
    return MASK_PAGE

@app.route('/admin')
def admin():
    return ADMIN_PANEL

# ========== ЗАПУСК ==========
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
