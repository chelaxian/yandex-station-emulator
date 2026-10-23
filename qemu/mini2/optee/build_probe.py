#!/usr/bin/env python3
"""Build an isolated initramfs for the secure-world probe."""
import gzip
from pathlib import Path
from elftools.elf.elffile import ELFFile

root = Path(__file__).resolve().parent
stand = root.parent
version = '6.1.0-53-arm64'
modules = root / 'linux/lib/modules' / version
data = gzip.decompress((stand / 'alpine/initramfs-9p.cpio.gz.before-backup').read_bytes())
entries = {}
offset = 0
while offset + 110 <= len(data):
    header = data[offset:offset+110]
    if header[:6] != b'070701': break
    n, size = int(header[94:102],16), int(header[54:62],16)
    name = data[offset+110:offset+110+n-1].decode().removeprefix('./')
    start = (offset+110+n+3)&~3
    if name == 'TRAILER!!!': break
    if not name.startswith('lib/modules') and name != 'init':
        entries[name] = (int(header[14:22],16), data[start:start+size])
    offset = (start+size+3)&~3

index, depends = {}, {}
for p in modules.rglob('*.ko'):
    with p.open('rb') as f:
        section = ELFFile(f).get_section_by_name('.modinfo')
        fields = section.data().split(b'\0') if section else []
    info = dict(x.split(b'=',1) for x in fields if b'=' in x)
    name = info.get(b'name',p.stem.encode()).decode().replace('-','_')
    index[name] = p
    depends[name] = info.get(b'depends',b'').decode().replace('-','_').split(',')
selected = set()
def add(name):
    if not name or name in selected: return
    if name not in index: return  # built in
    selected.add(name)
    for dep in depends[name]: add(dep)
for name in ['virtio','virtio_ring','virtio_mmio','virtio_pci','9pnet','9pnet_virtio','9p','tee','optee','virtio_blk','ext4','crc32c_generic','vfat','nls_cp437','nls_iso8859_1','virtio_net']:
    add(name)
prefix = f'lib/modules/{version}/'
lines = []
for name in sorted(selected):
    p = index[name]
    relative = str(p.relative_to(modules))
    entries[prefix+relative] = (0o100644,p.read_bytes())
    all_deps = []
    def collect(n):
        for d in depends[n]:
            if d in index and d not in all_deps:
                all_deps.append(d)
                collect(d)
    collect(name)
    lines.append(relative+': '+' '.join(str(index[d].relative_to(modules)) for d in all_deps))
entries[prefix+'modules.dep'] = (0o100644, ('\n'.join(lines)+'\n').encode())
entries[prefix+'modules.alias'] = (0o100644,b'')
entries['init'] = (0o100755, b'''#!/bin/busybox sh
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
/bin/busybox --install -s /bin
mkdir -p /proc /sys /dev /tmp /mini2 /alpine /nv
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
for m in virtio_pci virtio_mmio 9pnet_virtio 9p tee optee virtio_blk crc32c_generic ext4 nls_cp437 nls_iso8859_1 vfat virtio_net; do modprobe "$m"; done
echo '=== OP-TEE probe ==='
ls -l /dev/tee*
mount -t 9p -o trans=virtio,version=9p2000.L alpine /alpine
if mount /dev/vda /mini2; then
    mount -t proc proc /mini2/proc
    mount -o bind /dev /mini2/dev
    mount -t tmpfs tmpfs /mini2/tmp
    mkdir -p /dev/shm
    mount -t tmpfs tmpfs /dev/shm
    if mount -t vfat -o ro,iocharset=iso8859-1 /dev/vdb /nv; then
        cp -a /nv/. /mini2/tee/
    fi
    if [ -f /alpine/opt/mini2/probe-keymaster.ta ]; then
        cp /alpine/opt/mini2/probe-keymaster.ta /mini2/lib/teetz/8efb1e1c-37e5-4326-a5d68c33726c7d57.ta
        cp /alpine/opt/mini2/probe-keymaster.ta /mini2/lib/teetz/8efb1e1c-37e5-4326-a5d6-8c33726c7d57.ta
    fi
    chroot /mini2 /bin/tee-supplicant >/tmp/tee-supplicant.log 2>&1 &
    sleep 1
    chroot /mini2 /usr/bin/keymaster_svc >/tmp/keymaster.log 2>&1 &
    sleep 1
    timeout -k 1 5 chroot /mini2 /system/vendor/quasar/keymaster_proxy_app /dev/keymaster_svc show-key >/tmp/public-probe.log 2>&1
    echo "Public-key probe exit: $? (details in /tmp/public-probe.log)"
    cat /tmp/keymaster.log
fi
echo '=== diagnostic shell ==='
exec setsid sh -c 'exec sh </dev/ttyAMA0 >/dev/ttyAMA0 2>&1'
''')
for name in list(entries):
    for parent in Path(name).parents:
        if str(parent) != '.': entries.setdefault(str(parent),(0o40755,b''))
out = bytearray()
def record(name, mode, content, ino):
    fields = [ino, mode,0,0,1,0,len(content),0,0,0,0,len(name.encode())+1,0]
    out.extend(('070701'+''.join(f'{v:08x}' for v in fields)).encode()+name.encode()+b'\0')
    out.extend(b'\0'*(-len(out)%4)); out.extend(content); out.extend(b'\0'*(-len(out)%4))
for ino,(name,(mode,content)) in enumerate(sorted(entries.items(),key=lambda x:(len(Path(x[0]).parts),x[0])),1): record(name,mode,content,ino)
record('TRAILER!!!',0,b'',0)
(root/'probe-initramfs.gz').write_bytes(gzip.compress(out))
print('Probe initramfs:',len(out),'bytes;',len(selected),'modules')
