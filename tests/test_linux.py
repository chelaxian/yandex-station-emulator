import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'qemu/mini2/tools'))
from start_linux import arguments


class LinuxRegression(unittest.TestCase):
    def test_management_forwarding_is_loopback_only(self):
        args = arguments()
        net = args[args.index('-netdev') + 1]
        self.assertEqual(net.count('hostfwd=tcp:127.0.0.1:'), 3)
        self.assertNotIn('coreaudio', ' '.join(args))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nv = root / 'firmware/backups/yandex-mini2-backup/mtd/mtd4_nv.bin'
            nv.parent.mkdir(parents=True)
            nv.write_bytes(b'test-only')
            with patch('start_linux.STAND', root / 'qemu/mini2'):
                self.assertIn('readonly=on', ' '.join(arguments()))

    @unittest.skipIf(sys.platform == 'win32', 'needs a POSIX shell')
    def test_emulated_led_reads_without_newlines_or_during_truncation(self):
        spec = importlib.util.spec_from_file_location('mini2_profile', REPO / 'integrations/yandex_station_web/mini2_profile.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        server = types.SimpleNamespace(Panel=type('Panel', (), {}), CLOCK_LEDS=list(range(36)), AdbError=RuntimeError)
        ns = {'PROFILES': {}, 'install': lambda *args: None}
        module.register(ns)
        ns['install'](server, 'mini2')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for digit in range(1, 5):
                for segment in 'ABCDEFG':
                    path = root / f'mini2:white:clock{segment}{digit}'
                    path.mkdir()
                    (path / 'brightness').write_text('7')
            for index in range(1, 7):
                for color in ('red', 'green', 'blue'):
                    path = root / f'mini2:{color}:ring{index}'
                    path.mkdir()
                    (path / 'brightness').write_text('' if (index, color) == (2, 'green') else '123')

            class Adb:
                def shell(self, command):
                    # Old adbd truncates commands longer than its small payload.
                    self_length = len(command.encode())
                    if self_length > 3500:
                        raise RuntimeError('command too long for old adbd')
                    result = subprocess.run(['sh', '-c', command.replace('/sys/class/leds', str(root))], capture_output=True, text=True, check=True)
                    return result.stdout, result.stderr, result.returncode

            panel = server.Panel()
            panel.adb = Adb()
            result = panel.clock_state()
            self.assertEqual(result['ring_all'][1], [123, 0, 123])
            self.assertEqual(result['ring_all'][2], [123, 123, 123])
            self.assertEqual(result['v'][:8], [7]*7 + [0])
            self.assertEqual(len(result['v']), 36)


if __name__ == '__main__':
    unittest.main()
