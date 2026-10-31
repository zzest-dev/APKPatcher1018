import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import patch


class PayloadTests(unittest.TestCase):
    def test_checksums(self):
        metadata = patch.payload()
        self.assertEqual(metadata['abi'], 'armeabi-v7a')

    def test_native_architecture(self):
        data = (ROOT / 'payload/armeabi-v7a/libbackend1018.so').read_bytes()
        self.assertEqual(data[:6], b'\x7fELF\x01\x01')
        self.assertEqual(struct.unpack_from('<HH', data, 16), (3, 40))
        self.assertIn(b'Java_com_bigcitylegacy_backend_BackendActivity_nativeInitialize', data)
        self.assertNotIn(b'Java_com_bigcitylegacy_backend_BackendActivity_nativeEnableGameServer', data)

    def test_dex_integrity_and_no_compile_stubs(self):
        data = (ROOT / 'payload/classes.dex').read_bytes()
        self.assertTrue(data.startswith(b'dex\n'))
        self.assertEqual(struct.unpack_from('<I', data, 32)[0], len(data))
        self.assertEqual(data[12:32], hashlib.sha1(data[32:]).digest())
        self.assertEqual(struct.unpack_from('<I', data, 8)[0], zlib.adler32(data[12:]))
        string_count, string_offset = struct.unpack_from('<II', data, 56)
        strings = []
        for i in range(string_count):
            offset = struct.unpack_from('<I', data, string_offset + i * 4)[0]
            while data[offset] & 128:
                offset += 1
            offset += 1
            strings.append(data[offset:data.index(0, offset)].decode('utf-8', errors='replace'))
        _, type_offset = struct.unpack_from('<II', data, 64)
        class_count, class_offset = struct.unpack_from('<II', data, 96)
        definitions = []
        for i in range(class_count):
            class_index = struct.unpack_from('<I', data, class_offset + i * 32)[0]
            string_index = struct.unpack_from('<I', data, type_offset + class_index * 4)[0]
            definitions.append(strings[string_index])
        self.assertTrue(definitions)
        self.assertTrue(all(name.startswith('Lcom/bigcitylegacy/backend/BackendActivity') for name in definitions), definitions)

    def test_corrupt_payload_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'payload/armeabi-v7a').mkdir(parents=True)
            (root / 'payload/manifest.json').write_bytes((ROOT / 'payload/manifest.json').read_bytes())
            (root / 'payload/classes.dex').write_bytes(b'corrupt')
            with mock.patch.object(patch, 'ROOT', root):
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    patch.payload()

    def test_unknown_apk_refused_without_modification(self):
        with tempfile.TemporaryDirectory() as temporary:
            original = Path(temporary) / 'wrong.apk'
            original.write_bytes(b'not the supported game')
            with self.assertRaisesRegex(ValueError, 'Only the original ARMv7'):
                patch.validate_original(original)
            self.assertEqual(original.read_bytes(), b'not the supported game')

    def test_invalid_destination_refused(self):
        for host, port in [('0.0.0.0', 10118), ('224.0.0.1', 10118), ('192.168.1.10', 0), ('192.168.1.10', 65536)]:
            with self.subTest(host=host, port=port), self.assertRaises(ValueError):
                patch.write_unsigned('missing.apk', 'unused.apk', host, port)

    def test_original_cannot_be_output(self):
        with self.assertRaisesRegex(ValueError, 'Output must differ'):
            patch.main(['original.apk', '--host', '127.0.0.1', '--output', 'original.apk'])

    def test_existing_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'existing.apk'
            target.write_bytes(b'keep')
            with self.assertRaisesRegex(ValueError, 'Output already exists'):
                patch.main(['missing.apk', '--host', '127.0.0.1', '--output', str(target)])
            self.assertEqual(target.read_bytes(), b'keep')


@unittest.skipUnless(os.environ.get('ORIGINAL_APK_1018'), 'Set ORIGINAL_APK_1018 for original APK integration checks')
class OriginalApkTests(unittest.TestCase):
    def test_preservation_and_tamper_detection(self):
        original = Path(os.environ['ORIGINAL_APK_1018'])
        patch.validate_original(original)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'unsigned.apk'
            patch.write_unsigned(original, output, '192.168.1.10', 10118)
            self.assertGreater(patch.verify_content(original, output, '192.168.1.10', 10118), 100)
            bad = Path(temporary) / 'tampered.apk'
            with zipfile.ZipFile(output) as source, zipfile.ZipFile(bad, 'w') as target:
                for item in source.infolist():
                    data = source.read(item)
                    if item.filename == 'lib/armeabi-v7a/libil2cpp.so':
                        data = b'x' + data[1:]
                    target.writestr(item, data)
            with self.assertRaisesRegex(ValueError, 'changed unexpectedly'):
                patch.verify_content(original, bad, '192.168.1.10', 10118)


if __name__ == '__main__':
    unittest.main()
