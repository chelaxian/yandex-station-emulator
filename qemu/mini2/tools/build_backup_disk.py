#!/usr/bin/env python3
"""Build a writable Linux disk from the verified UBIFS backup, preserving metadata."""
import json
import os
import shutil
import subprocess
from pathlib import Path

from ubireader.ubi_io import ubi_file
from ubireader.ubifs import ubifs, walk

stand = Path(__file__).resolve().parents[1]
backup = stand.parents[1] / 'firmware/backups/yandex-mini2-backup'
source = backup / 'rootfs_extracted'
target = stand / 'backup_rootfs_files'
image = stand / 'mini2-backup.ext4'
if image.exists():
    raise SystemExit('Disk exists; refusing to overwrite persistent guest data.')
if not target.exists():
    shutil.copytree(source, target, symlinks=True)
shutil.copytree(backup / 'sanitized/data', target / 'bkupgrade/data', dirs_exist_ok=True)
uf = ubi_file(str(backup / 'ubivol/ubi0_0_rootfs.img'), 126976)
fs = ubifs(uf)
inodes, bad = {}, []
walk.index(fs, fs.master_node.root_lnum, fs.master_node.root_offs, inodes, bad)
if bad:
    raise SystemExit(f'Corrupt UBIFS blocks: {bad}')
metadata = []
def visit(number, name):
    node = inodes[number]
    ino = node['ino']
    metadata.append((name, ino.uid, ino.gid, ino.mode))
    path = target / name.lstrip('/')
    if not path.is_symlink() and path.exists():
        # The unprivileged host must read executable-only firmware files.
        # Exact Linux modes are restored in the image with debugfs below.
        path.chmod((ino.mode & 0o7777) | (0o700 if path.is_dir() else 0o400))
    for dent in node.get('dent', []):
        visit(dent.inum, name.rstrip('/') + '/' + dent.name)
visit(1, '/')
uf.close()
(stand / 'run/backup-inode-metadata.json').write_text(json.dumps(metadata, indent=2))
for directory in ('tmp', 'run', 'proc', 'sys', 'dev', 'tee', 'emulator'):
    (target / directory).mkdir(exist_ok=True)
cfg = json.loads((target / 'system/vendor/quasar/launch.json').read_text())
for node in cfg['nodes']:
    node['tasks'] = [task for task in node['tasks'] if task['name'] != 'updatesd']
(target / 'emulator/launch.json').write_text(json.dumps(cfg, indent=2))
shutil.copy2(stand / 'guest/alice-start.sh', target / 'emulator/alice-start.sh')
(target / 'emulator/alice-start.sh').chmod(0o755)
cmdline = (backup / 'meta/device-info.txt').read_text(encoding='utf-8-sig').split('### cat /proc/cmdline')[1].split('###')[0].strip()
(stand / 'alpine_root/etc/fake_cmdline').write_text(cmdline + '\n')
with image.open('wb') as f:
    f.truncate(512 * 1024 * 1024)
subprocess.run(['/opt/homebrew/opt/e2fsprogs/sbin/mke2fs', '-q', '-F', '-t', 'ext4', '-L', 'mini2', '-d', str(target), str(image)], check=True)
commands = []
for name, uid, gid, mode in metadata:
    # debugfs uses octal modes and literal, quoted filesystem paths.
    for field, value in [('uid', str(uid)), ('gid', str(gid)), ('mode', '0' + format(mode, 'o'))]:
        commands.append(f'set_inode_field "{name}" {field} {value}')
script = stand / 'run/restore-inodes.debugfs'
script.write_text('\n'.join(commands) + '\n')
with (stand / 'run/restore-inodes.log').open('w') as log:
    subprocess.run(['/opt/homebrew/opt/e2fsprogs/sbin/debugfs', '-w', '-f', str(script), str(image)], stdout=log, stderr=log, check=True)
print(f'Built {image}; restored {len(metadata)} original inode records.')
