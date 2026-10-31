import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import struct
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from patch import executable, sdk_tools


def run(command):
    subprocess.run([str(x) for x in command], cwd=ROOT, check=True)


def short_path(path):
    path = Path(path).resolve()
    if os.name != 'nt':
        return str(path)
    buffer = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer)):
        raise OSError('Cannot resolve NDK short path: ' + str(path))
    return buffer.value.replace('\\', '/')


def main():
    parser = argparse.ArgumentParser(description='Rebuild the client payload from C++ and Java sources.')
    parser.add_argument('--android-sdk', type=Path, required=True)
    parser.add_argument('--ndk', type=Path, required=True)
    parser.add_argument('--java-home', type=Path)
    parser.add_argument('--cmake', default='cmake')
    parser.add_argument('--ninja', default='ninja')
    parser.add_argument('--android-api', default='28')
    args = parser.parse_args()
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    ndk = short_path(args.ndk)
    ninja = shutil.which(args.ninja) or str(Path(args.ninja).resolve())
    run([args.cmake, '-S', ROOT, '-B', build / 'native', '-G', 'Ninja', '-DCMAKE_MAKE_PROGRAM=' + ninja.replace('\\', '/'),
         '-DCMAKE_TOOLCHAIN_FILE=' + ndk + '/build/cmake/android.toolchain.cmake', '-DANDROID_NDK=' + ndk,
         '-DANDROID_ABI=armeabi-v7a', '-DANDROID_ARM_MODE=arm', '-DANDROID_PLATFORM=android-21', '-DANDROID_STL=c++_static',
         '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_POLICY_VERSION_MINIMUM=3.5'])
    run([args.cmake, '--build', build / 'native', '--target', 'backend1018', '--parallel', '4'])
    android_jar = args.android_sdk / 'platforms' / ('android-' + args.android_api) / 'android.jar'
    if not android_jar.is_file():
        raise ValueError('Android platform jar not found: ' + str(android_jar))
    java, javac, jar = [executable(name, args.java_home) for name in ('java', 'javac', 'jar')]
    with tempfile.TemporaryDirectory(dir=build) as temporary:
        work = Path(temporary)
        stubs, classes, dex = [work / name for name in ('stubs', 'classes', 'dex')]
        for directory in (stubs, classes, dex):
            directory.mkdir()
        run([javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-bootclasspath', android_jar,
             '-d', stubs, *sorted((ROOT / 'compile-stubs').rglob('*.java'))])
        stub_jar = work / 'compile-stubs.jar'
        run([jar, 'cf', stub_jar, '-C', stubs, '.'])
        run([javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-bootclasspath', android_jar,
             '-classpath', stub_jar, '-d', classes, *sorted((ROOT / 'java').rglob('*.java'))])
        align, _ = sdk_tools(args.android_sdk)
        run([java, '-cp', align.parent / 'lib/d8.jar', 'com.android.tools.r8.D8', '--release', '--min-api', '21',
             '--lib', android_jar, '--classpath', stub_jar, '--output', dex, *sorted(classes.rglob('*.class'))])
        target = ROOT / 'payload'
        (target / 'armeabi-v7a').mkdir(parents=True, exist_ok=True)
        library = target / 'armeabi-v7a/libbackend1018.so'
        shutil.copy2(build / 'native/libbackend1018.so', library)
        strip = next(args.ndk.glob('toolchains/arm-linux-androideabi-*/prebuilt/*/bin/arm-linux-androideabi-strip*'), None)
        if not strip:
            raise ValueError('ARMv7 strip tool not found in the selected NDK r16b')
        run([strip, '--strip-unneeded', library])
        dex_bytes = bytearray((dex / 'classes.dex').read_bytes())
        if not dex_bytes.startswith(b'dex\n') or struct.unpack_from('<I', dex_bytes, 32)[0] != len(dex_bytes):
            raise ValueError('Unexpected DEX output')
        dex_bytes[12:32] = hashlib.sha1(dex_bytes[32:]).digest()
        struct.pack_into('<I', dex_bytes, 8, zlib.adler32(dex_bytes[12:]))
        (target / 'classes.dex').write_bytes(dex_bytes)
        files = {name: hashlib.sha256((target / name).read_bytes()).hexdigest() for name in ('classes.dex', 'armeabi-v7a/libbackend1018.so')}
        metadata = dict(version=1, abi='armeabi-v7a', dobby_commit='2b988dc976f9f8630c6ce8d87aaa9f0deb21bbba', files=files)
        (target / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
