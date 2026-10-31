import struct

NO_INDEX = 0xffffffff

def chunks(data):
    at = struct.unpack_from('<H', data, 2)[0]
    while at < len(data):
        kind, header, size = struct.unpack_from('<HHI', data, at)
        if size < header or at + size > len(data):
            raise ValueError('Invalid AXML chunk')
        yield at, kind, data[at:at + size]
        at += size
    if at != len(data):
        raise ValueError('AXML trailing bytes')

def length(data, at, utf8):
    if utf8:
        value = data[at]; at += 1
        if value & 0x80: value = ((value & 0x7f) << 8) | data[at]; at += 1
    else:
        value = struct.unpack_from('<H', data, at)[0]; at += 2
        if value & 0x8000: value = ((value & 0x7fff) << 16) | struct.unpack_from('<H', data, at)[0]; at += 2
    return value, at

def strings(pool):
    header = struct.unpack_from('<H', pool, 2)[0]
    count, _, flags, start, _ = struct.unpack_from('<5I', pool, 8)
    result = []
    for i in range(count):
        at = start + struct.unpack_from('<I', pool, header + i * 4)[0]
        size, at = length(pool, at, bool(flags & 0x100))
        if flags & 0x100:
            size, at = length(pool, at, True)
            result.append(pool[at:at + size].decode('utf-8'))
        else:
            result.append(pool[at:at + size * 2].decode('utf-16-le'))
    return result

def append_string(pool, value):
    header = struct.unpack_from('<H', pool, 2)[0]
    count, styles, flags, start, style_start = struct.unpack_from('<5I', pool, 8)
    string_data = pool[start:style_start or len(pool)]
    if flags & 0x100:
        encoded = value.encode('utf-8')
        def pack_len(v): return bytes([v]) if v < 128 else bytes([0x80 | (v >> 8), v & 255])
        encoded = pack_len(len(value.encode('utf-16-le')) // 2) + pack_len(len(encoded)) + encoded + b'\0'
    else:
        encoded = struct.pack('<H', len(value.encode('utf-16-le')) // 2) + value.encode('utf-16-le') + b'\0\0'
    data = string_data + encoded
    data += b'\0' * (-len(data) % 4)
    offsets = pool[header:header + count * 4] + struct.pack('<I', len(string_data))
    style_offsets = pool[header + count * 4:header + (count + styles) * 4]
    style_data = pool[style_start:] if style_start else b''
    new_start = start + 4
    result = bytearray(pool[:header]) + offsets + style_offsets + pool[header + (count + styles) * 4:start] + data + style_data
    struct.pack_into('<I', result, 4, len(result))
    struct.pack_into('<5I', result, 8, count + 1, styles, flags & ~1, new_start, new_start + len(data) if style_start else 0)
    assert strings(result) == strings(pool) + [value]
    return bytes(result), count

def start_attributes(chunk, pool_strings):
    element = pool_strings[struct.unpack_from('<I', chunk, 20)[0]]
    start, size, count = struct.unpack_from('<HHH', chunk, 24)
    attributes = []
    for i in range(count):
        at = 16 + start + i * size
        name = pool_strings[struct.unpack_from('<I', chunk, at + 4)[0]]
        raw, = struct.unpack_from('<I', chunk, at + 8)
        kind = chunk[at + 15]
        value, = struct.unpack_from('<I', chunk, at + 16)
        text = pool_strings[value] if kind == 3 else value
        attributes.append((at, name, text, raw, kind))
    return element, attributes

def describe(data):
    pool_strings = []
    elements = []
    for _, kind, chunk in chunks(data):
        if kind == 1: pool_strings = strings(chunk)
        elif kind == 0x102:
            name, attributes = start_attributes(chunk, pool_strings)
            elements.append({'element': name, 'attributes': {n: v for _, n, v, _, _ in attributes}})
    return elements
