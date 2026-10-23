#!/usr/bin/env python3
"""Replace only /init in the existing newc initramfs; retain bootstrap modules."""
import gzip
import shutil
from pathlib import Path

stand = Path(__file__).resolve().parents[1]
def atomic_write(path, data, mode=0o644):
    temporary = path.with_name(path.name + '.new')
    temporary.write_bytes(data)
    temporary.chmod(mode)
    temporary.replace(path)

def deploy(source, target, mode=0o644):
    atomic_write(target, source.read_bytes(), mode)
archive = stand / 'alpine/initramfs-9p.cpio.gz'
backup = archive.with_suffix('.gz.before-backup')
if not backup.exists():
    shutil.copy2(archive, backup)
data = gzip.decompress(backup.read_bytes())
result = bytearray()
offset = 0
replaced = False
records = []
while offset + 110 <= len(data):
    header = bytearray(data[offset:offset + 110])
    if header[:6] not in (b'070701', b'070702'):
        break
    namesize = int(header[94:102], 16)
    size = int(header[54:62], 16)
    name = data[offset + 110:offset + 110 + namesize]
    start = (offset + 110 + namesize + 3) & ~3
    content = data[start:start + size]
    if name.rstrip(b'\0') in (b'init', b'./init'):
        content = (stand / 'guest/init').read_bytes()
        header[54:62] = f'{len(content):08x}'.encode()
        replaced = True
    if name.rstrip(b'\0') != b'TRAILER!!!':
        records.append((header, name, content))
    offset = (start + size + 3) & ~3
    if name.rstrip(b'\0') == b'TRAILER!!!':
        break
assert replaced
modules = stand / 'alpine_root/lib/modules/6.6.142-0-lts'
if modules.exists():
    # Keep the bootstrap small: include only 9p/PCI modules and their dependencies.
    records = [r for r in records if not r[1].rstrip(b'\0').lstrip(b'./').startswith(b'lib/modules')]
    deps = {}
    for line in (modules / 'modules.dep').read_text().splitlines():
        module, needs = line.split(':', 1)
        deps[module] = needs.split()
    selected = set()
    def add(module):
        if module in selected:
            return
        selected.add(module)
        for need in deps.get(module, []):
            add(need)
    wanted = {'virtio', 'virtio_ring', 'virtio_mmio', 'virtio_pci', '9pnet', '9pnet_virtio', '9p'}
    for module in deps:
        if Path(module).name.split('.ko')[0].replace('-', '_') in wanted:
            add(module)
    paths = {modules / module for module in selected}
    paths.update(modules.glob('modules.*'))
    directories = set()
    for path in paths:
        directories.update(path.relative_to(stand / 'alpine_root').parents)
    ino = 10000
    def record(name, content, mode):
        global ino
        ino += 1
        fields = [ino, mode, 0, 0, 1, 0, len(content), 0, 0, 0, 0, len(name.encode()) + 1, 0]
        records.append((bytearray(('070701' + ''.join(f'{v:08x}' for v in fields)).encode()), name.encode() + b'\0', content))
    for directory in sorted(directories, key=lambda p: (len(p.parts), str(p))):
        if str(directory) != '.':
            record(str(directory), b'', 0o40755)
    for path in sorted(paths):
        record(str(path.relative_to(stand / 'alpine_root')), path.read_bytes(), 0o100644)
trailer = bytearray(b'070701' + b'00000000' * 13)
trailer[94:102] = b'0000000b'
records.append((trailer, b'TRAILER!!!\0', b''))
for header, name, content in records:
    result.extend(header + name)
    result.extend(b'\0' * (-len(result) % 4))
    result.extend(content)
    result.extend(b'\0' * (-len(result) % 4))
atomic_write(archive, gzip.compress(bytes(result)))
deploy(stand / 'guest/mini2.start', stand / 'alpine_root/etc/local.d/mini2.start', 0o755)
(stand / 'alpine_root/opt/mini2').mkdir(parents=True, exist_ok=True)
deploy(stand / 'guest/alice-start.sh', stand / 'alpine_root/opt/mini2/alice-start.sh', 0o755)
deploy(stand / 'guest/asound.conf', stand / 'alpine_root/opt/mini2/asound.conf')
deploy(stand / 'guest/status.sh', stand / 'alpine_root/opt/mini2/status.sh', 0o755)
deploy(stand / 'guest/wpa-wired.conf', stand / 'alpine_root/opt/mini2/wpa-wired.conf')
deploy(stand / 'guest/lan-dhcp.sh', stand / 'alpine_root/opt/mini2/lan-dhcp.sh', 0o755)
import json
cfg = json.loads((stand / 'backup_rootfs_files/system/vendor/quasar/launch.json').read_text())
for node in cfg['nodes']:
    node['tasks'] = [task for task in node['tasks'] if task['name'] != 'updatesd']
    for task in node['tasks']:
        task['log'] = True
atomic_write(stand / 'alpine_root/opt/mini2/launch.json', json.dumps(cfg, indent=2).encode())
atomic_write(stand / 'alpine_root/etc/inittab', b'::sysinit:/etc/local.d/mini2.start\nttyAMA0::respawn:-/bin/sh\n::shutdown:/bin/busybox umount -a -r\n')
print('Built initramfs and guest startup for the backup disk.')
