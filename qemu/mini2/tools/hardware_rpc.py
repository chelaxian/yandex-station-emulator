#!/usr/bin/env python3
"""Loopback-only bridge to the firmware's actual GATT implementation."""
import base64
import json
import re
import shlex
import subprocess
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = threading.Lock()
def rpc(action, index, data=b'', offset=0):
    if index not in range(6) or action not in ('read','write','subscribe','unsubscribe'):
        raise ValueError('Invalid GATT operation')
    if not 0 <= offset <= 65535: raise ValueError('Invalid offset')
    base = ['chroot','/mini2','/usr/bin/gdbus','call','--system','--dest','ru.yandex.quasar',
            '--object-path',f'/ru/yandex/quasar/gatt/service0/char{index}','--method']
    if action == 'read': args = ['org.bluez.GattCharacteristic1.ReadValue', "{'offset': <uint16 %d>}" % offset]
    elif action == 'write':
        if len(data)>65536: raise ValueError('Write too large')
        value = '['+','.join('0x%02x'%b for b in data)+']' if data else '@ay []'
        args = ['org.bluez.GattCharacteristic1.WriteValue',value,"{'offset': <uint16 %d>}" % offset]
    else: args = ['org.bluez.GattCharacteristic1.'+('StartNotify' if action=='subscribe' else 'StopNotify')]
    temporary = None
    command = shlex.join(base+args)
    if action == 'write':
        directory=ROOT/'alpine_root/opt/mini2/ble-rpc'
        directory.mkdir(mode=0o700,exist_ok=True);directory.chmod(0o700)
        temporary=directory/uuid.uuid4().hex
        temporary.write_text(value);temporary.chmod(0o600)
        command=shlex.join(base+[args[0]])+' "$(cat /opt/mini2/ble-rpc/'+temporary.name+')" '+shlex.quote(args[2])
    try:
        with LOCK:
            result = subprocess.run(['/usr/bin/python3',str(ROOT/'tools/console.py'),command,'--timeout','6'],capture_output=True,text=True,timeout=12)
    finally:
        if temporary: temporary.unlink(missing_ok=True)
    lines = result.stdout.splitlines()
    answer = next((x.strip() for x in lines if x.strip().startswith('([')),None)
    if action=='read':
        if answer is None: raise RuntimeError('Firmware did not return a GATT value')
        return bytes(int(x,16) for x in re.findall(r'0x([0-9a-fA-F]{2})',answer))
    if not any(x.strip()=='()' for x in lines): raise RuntimeError('Firmware rejected GATT operation')
    return b''

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size>100000: raise ValueError('Request too large')
            req=json.loads(self.rfile.read(size)); value=rpc(req['action'],int(req['index']),base64.b64decode(req.get('data',''),validate=True),int(req.get('offset',0)))
            out=json.dumps({'ok':True,'data':base64.b64encode(value).decode()}).encode();code=200
        except Exception as e: out=json.dumps({'ok':False,'error':str(e)}).encode();code=502
        self.send_response(code); self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(out)));self.end_headers();self.wfile.write(out)
    def log_message(self,*args): pass  # BLE writes may contain account credentials.

if __name__=='__main__': ThreadingHTTPServer(('127.0.0.1',19092),Handler).serve_forever()
