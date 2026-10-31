import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

import axml

ROOT = Path(__file__).resolve().parent
ORIGINAL_SHA256 = '2941a49eaf332930580b81bb2e8012b6684e6103031551d176a765b4ed152848'
ORIGINAL_PACKAGE = 'com.MadOut.BIG'
PACKAGE = 'com.MadOut.BIG.backend1018'
ACTIVITY = 'com.bigcitylegacy.backend.BackendActivity'
ADDITIONS = {'classes4.dex', 'lib/armeabi-v7a/libbackend1018.so', 'assets/backend-defaults.properties'}


def sha256(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def signature(name):
    return name.upper().startswith('META-INF/') and name.upper().endswith(('.RSA', '.DSA', '.EC', '.SF', '.MF'))


def patch_manifest(data):
    chunks = list(axml.chunks(data))
    pool = next(raw for _, kind, raw in chunks if kind == 1)
    strings = axml.strings(pool)
    replacements = {}
    for _, kind, raw in chunks:
        if kind != 0x102:
            continue
        element, attrs = axml.start_attributes(raw, strings)
        for _, name, value, _, value_type in attrs:
            if value_type != 3:
                continue
            if element == 'manifest' and name == 'package':
                if value != ORIGINAL_PACKAGE:
                    raise ValueError('Unexpected original package')
                replacements[value] = PACKAGE
            elif element == 'activity' and name == 'name' and value == 'com.unity3d.player.UnityPlayerActivity':
                replacements[value] = ACTIVITY
            elif name == 'authorities':
                replacements[value] = value + '.backend1018'
            elif value.startswith(ORIGINAL_PACKAGE + '.') and ('permission' in element or name == 'permission'):
                replacements[value] = value.replace(ORIGINAL_PACKAGE + '.', PACKAGE + '.', 1)
    if replacements.get(ORIGINAL_PACKAGE) != PACKAGE or ACTIVITY not in replacements.values():
        raise ValueError('Expected package and Unity launcher not found')
    indices = {}
    for old, new in replacements.items():
        pool, indices[old] = axml.append_string(pool, new)
    result = bytearray(data[:8])
    for _, kind, raw in chunks:
        chunk = bytearray(raw)
        if kind == 1:
            chunk = pool
        elif kind == 0x102:
            _, attrs = axml.start_attributes(raw, strings)
            for at, _, value, _, value_type in attrs:
                if value_type == 3 and value in indices:
                    struct.pack_into('<I', chunk, at + 8, indices[value])
                    struct.pack_into('<I', chunk, at + 16, indices[value])
        result += chunk
    struct.pack_into('<I', result, 4, len(result))
    expected = axml.describe(data)
    for element in expected:
        for name, value in element['attributes'].items():
            if isinstance(value, str) and value in replacements:
                element['attributes'][name] = replacements[value]
    if axml.describe(result) != expected:
        raise ValueError('Unexpected manifest changes')
    return bytes(result)


def patch_resources(data):
    result = bytearray(data)
    changed = 0
    for offset, kind, raw in axml.chunks(data):
        if kind == 0x200 and raw[12:268].decode('utf-16-le').split('\0', 1)[0] == ORIGINAL_PACKAGE:
            encoded = PACKAGE.encode('utf-16-le')
            result[offset + 12:offset + 268] = encoded.ljust(256, b'\0')
            changed += 1
    if changed != 1 or len(result) != len(data):
        raise ValueError('Unexpected resources.arsc package table')
    return bytes(result)


def validate_original(apk):
    if sha256(apk) != ORIGINAL_SHA256:
        raise ValueError('Only the original ARMv7 APK 10.18 / 100118 with SHA256 ' + ORIGINAL_SHA256 + ' is supported')
    with zipfile.ZipFile(apk) as source:
        if len(source.namelist()) != len(set(source.namelist())) or ADDITIONS.intersection(source.namelist()):
            raise ValueError('Unexpected or already modified APK entries')
        if source.testzip() is not None:
            raise ValueError('Original APK ZIP integrity check failed')


def payload():
    metadata = json.loads((ROOT / 'payload/manifest.json').read_text(encoding='utf-8'))
    for name, digest in metadata['files'].items():
        if name not in ('classes.dex', 'armeabi-v7a/libbackend1018.so') or sha256(ROOT / 'payload' / name) != digest:
            raise ValueError('Payload checksum mismatch: ' + name)
    if set(metadata['files']) != {'classes.dex', 'armeabi-v7a/libbackend1018.so'}:
        raise ValueError('Payload manifest is incomplete')
    return metadata


def write_unsigned(original, output, host, port):
    address = ipaddress.IPv4Address(host)
    if address.is_unspecified or address.is_multicast or not 1 <= port <= 65535:
        raise ValueError('Use a destination IPv4 address and port 1..65535')
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(output, 'w') as target:
        for item in source.infolist():
            if signature(item.filename):
                continue
            data = source.read(item)
            if item.filename == 'AndroidManifest.xml':
                data = patch_manifest(data)
            elif item.filename == 'resources.arsc':
                data = patch_resources(data)
            target.writestr(item, data)
        target.writestr('classes4.dex', (ROOT / 'payload/classes.dex').read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
        target.writestr('lib/armeabi-v7a/libbackend1018.so', (ROOT / 'payload/armeabi-v7a/libbackend1018.so').read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
        target.writestr('assets/backend-defaults.properties', f'ip={address}\nport={port}\n'.encode('ascii'), compress_type=zipfile.ZIP_DEFLATED)


def verify_content(original, patched, host, port):
    preserved = 0
    with zipfile.ZipFile(original) as before, zipfile.ZipFile(patched) as after:
        if after.testzip() is not None or len(after.namelist()) != len(set(after.namelist())):
            raise ValueError('Patched APK ZIP integrity check failed')
        expected = set(n for n in before.namelist() if not signature(n)) | ADDITIONS
        actual = set(n for n in after.namelist() if not signature(n))
        if actual != expected:
            raise ValueError('Unexpected APK file set')
        for name in before.namelist():
            if signature(name):
                continue
            expected_bytes = before.read(name)
            if name == 'AndroidManifest.xml':
                expected_bytes = patch_manifest(expected_bytes)
            elif name == 'resources.arsc':
                expected_bytes = patch_resources(expected_bytes)
            else:
                preserved += 1
            if after.read(name) != expected_bytes:
                raise ValueError('Original entry changed unexpectedly: ' + name)
        for apk_name, payload_name in [('classes4.dex', 'classes.dex'), ('lib/armeabi-v7a/libbackend1018.so', 'armeabi-v7a/libbackend1018.so')]:
            if after.read(apk_name) != (ROOT / 'payload' / payload_name).read_bytes():
                raise ValueError('Embedded payload differs: ' + apk_name)
        if after.read('assets/backend-defaults.properties') != f'ip={ipaddress.IPv4Address(host)}\nport={port}\n'.encode('ascii'):
            raise ValueError('Embedded endpoint differs')
    return preserved


def executable(name, java_home=None):
    suffix = '.exe' if os.name == 'nt' else ''
    home = java_home or os.environ.get('JAVA_HOME')
    candidate = Path(home) / 'bin' / (name + suffix) if home else None
    found = candidate if candidate and candidate.is_file() else shutil.which(name)
    if not found:
        raise ValueError(f'{name} not found; set JAVA_HOME or --java-home')
    return str(found)


def sdk_tools(sdk=None, build_tools=None):
    if build_tools:
        directory = Path(build_tools)
    else:
        home = sdk or os.environ.get('ANDROID_SDK_ROOT') or os.environ.get('ANDROID_HOME')
        if not home:
            raise ValueError('Set ANDROID_SDK_ROOT or --android-sdk')
        candidates = sorted((Path(home) / 'build-tools').glob('*'), key=lambda p: tuple(int(s) if s.isdigit() else 0 for s in p.name.split('.')), reverse=True)
        directory = next((p for p in candidates if (p / 'lib/apksigner.jar').is_file()), None)
        if directory is None:
            raise ValueError('Android SDK Build Tools with apksigner.jar not found')
    align = directory / ('zipalign.exe' if os.name == 'nt' else 'zipalign')
    signer = directory / 'lib/apksigner.jar'
    if not align.is_file() or not signer.is_file():
        raise ValueError('Build Tools must contain zipalign and lib/apksigner.jar')
    return align, signer


def run(command, env=None):
    result = subprocess.run([str(x) for x in command], capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
    if result.returncode:
        raise ValueError((result.stdout + result.stderr)[-6000:])
    return result.stdout


def main(argv=None):
    parser = argparse.ArgumentParser(description='Patch the original MadOut2 10.18 ARMv7 APK for AccountBackend1018. Python 3.11+ and Android SDK Build Tools are required.')
    parser.add_argument('apk', type=Path)
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', type=int, default=10118)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/MadOut-10.18-AccountBackend.apk')
    parser.add_argument('--android-sdk', type=Path)
    parser.add_argument('--build-tools', type=Path)
    parser.add_argument('--java-home', type=Path)
    parser.add_argument('--keystore', type=Path)
    parser.add_argument('--key-alias', default='apkpatcher1018')
    parser.add_argument('--store-pass-env', default='APKPATCHER_STORE_PASS')
    parser.add_argument('--key-pass-env')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args(argv)
    original, output = args.apk.resolve(), args.output.resolve()
    report_path = output.with_suffix(output.suffix + '.report.json')
    if original == output:
        raise ValueError('Output must differ from the original APK')
    if not args.force and (output.exists() or report_path.exists()):
        raise ValueError('Output already exists; choose another path or pass --force')
    address = ipaddress.IPv4Address(args.host)
    if address.is_unspecified or address.is_multicast or not 1 <= args.port <= 65535:
        raise ValueError('Use a destination IPv4 address and port 1..65535')
    validate_original(original)
    metadata = payload()
    java = executable('java', args.java_home)
    align, signer = sdk_tools(args.android_sdk, args.build_tools)
    env = dict(os.environ)
    if args.keystore:
        key = args.keystore.resolve()
        if not key.is_file() or not env.get(args.store_pass_env):
            raise ValueError('Provide an existing keystore and its password using --store-pass-env')
        store_env = args.store_pass_env
        key_env = args.key_pass_env or store_env
        if not env.get(key_env):
            raise ValueError('Key password environment variable is empty')
    else:
        key = ROOT / '.keys/local-test.keystore'
        store_env = key_env = 'APKPATCHER_LOCAL_TEST_PASS'
        env[store_env] = 'android'
        if not key.exists():
            key.parent.mkdir(parents=True, exist_ok=True)
            run([executable('keytool', args.java_home), '-genkeypair', '-keystore', key, '-storepass:env', store_env, '-keypass:env', key_env,
                 '-alias', args.key_alias, '-keyalg', 'RSA', '-keysize', '2048', '-validity', '3650', '-dname', 'CN=APKPatcher1018 Local Test'], env)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='apkpatcher1018-', dir=output.parent) as temporary:
        work = Path(temporary)
        unsigned, aligned, signed = work / 'unsigned.apk', work / 'aligned.apk', work / 'signed.apk'
        write_unsigned(original, unsigned, str(address), args.port)
        run([align, '-f', '-p', '4', unsigned, aligned])
        run([java, '-jar', signer, 'sign', '--ks', key, '--ks-key-alias', args.key_alias,
             '--ks-pass', 'env:' + store_env, '--key-pass', 'env:' + key_env,
             '--v1-signing-enabled', 'true', '--v2-signing-enabled', 'true', '--out', signed, aligned], env)
        signature_result = run([java, '-jar', signer, 'verify', '--verbose', signed])
        run([align, '-c', '-p', '4', signed])
        preserved = verify_content(original, signed, str(address), args.port)
        report = dict(original_sha256=ORIGINAL_SHA256, output_sha256=sha256(signed), package=PACKAGE, version_code=100118,
                      abi='armeabi-v7a', endpoint=f'{address}:{args.port}', preserved_original_entries=preserved,
                      payload=metadata, signature_verification=signature_result.strip())
        temporary_report = work / 'report.json'
        temporary_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(signed, output)
        os.replace(temporary_report, report_path)
    print(f'APK: {output}\nReport: {report_path}\nPackage: {PACKAGE}\nBackend: {address}:{args.port}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, zipfile.BadZipFile, KeyError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
