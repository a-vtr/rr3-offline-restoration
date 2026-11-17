"""Checked, reversible two-level UIApplicationMain import redirection for RR3.

No instruction, entry-point, game method or resource address is changed. Reject
other layouts rather than guessing how to patch them. No signing/device access.
"""
import hashlib
import struct
from trace_resource_startup import Image

LIBRARY = '@executable_path/Frameworks/RR3Initializer.framework/RR3Initializer'


def patch_main(original):
    image = Image(original)
    commands = image.commands
    libraries = [(cmd, at) for cmd, at in commands
                 if cmd in (0xc, 0x80000018, 0x8000001f, 0x80000023, 0x20)]
    ordinal = len(libraries) + 1
    if ordinal >= 128 or not struct.unpack_from('<I', original, 24)[0] & 0x80:
        raise ValueError('Expected two-level namespace and one-byte ordinal')
    ui = [i + 1 for i, (_, at) in enumerate(libraries)
          if original[at + 24:original.index(b'\0', at + 24)] ==
          b'/System/Library/Frameworks/UIKit.framework/UIKit']
    if len(ui) != 1 or ui[0] < 16:
        raise ValueError('Unexpected UIKit import layout')
    bind = next(at for cmd, at in commands if cmd == 0x80000022)
    offset, length = struct.unpack_from('<II', original, bind + 32)
    lazy = original[offset:offset + length]
    symbol = b'_UIApplicationMain\0'
    if lazy.count(symbol) != 1:
        raise ValueError('Expected exactly one UIApplicationMain lazy import')
    at = lazy.index(symbol)
    # SET_DYLIB_ORDINAL_ULEB(oldUIKit), SET_SYMBOL_TRAILING_FLAGS(weak).
    if lazy[at - 3:at] != bytes([0x20, ui[0], 0x41]) or lazy[at + len(symbol):at + len(symbol) + 2] != b'\x90\x00':
        raise ValueError('Unexpected binding opcodes; no patch applied')
    output = bytearray(original)
    edits = []

    def change(where, value):
        before = bytes(output[where:where + len(value)])
        output[where:where + len(value)] = value
        edits.append({'offset':where,'before':before.hex(),'after':value.hex()})

    change(offset + at - 2, bytes([ordinal]))
    sym = next(at for cmd, at in commands if cmd == 2)
    symoff, count, stroff, _ = struct.unpack_from('<IIII', original, sym + 8)
    matches = []
    for i in range(count):
        pos = symoff + i * 16
        start = stroff + struct.unpack_from('<I', original, pos)[0]
        if original[start:original.index(b'\0', start)] == symbol[:-1]:
            desc = struct.unpack_from('<H', original, pos + 6)[0]
            if (desc >> 8) != ui[0] or original[pos + 4] & 0x0e:
                raise ValueError('Unexpected symbol descriptor')
            matches.append(pos)
            change(pos + 6, struct.pack('<H', (ordinal << 8) | (desc & 255)))
    if len(matches) != 1:
        raise ValueError('Expected one undefined UIKit entry in symbol table')
    ncmd, sizeofcmds = struct.unpack_from('<II', original, 16)
    end = 32 + sizeofcmds
    first = min(v[2] for v in image.sections.values() if v[2])
    size = (24 + len(LIBRARY.encode()) + 1 + 7) & ~7
    if end + size > first or any(original[end:end + size]):
        raise ValueError('No verified zero load-command padding')
    command = struct.pack('<6I', 0xc, size, 24, 0, 0x10000, 0x10000)
    command += LIBRARY.encode() + b'\0'
    command = command.ljust(size, b'\0')
    change(end, command)
    change(16, struct.pack('<II', ncmd + 1, sizeofcmds + size))
    # Validate both import metadata representations and unchanged instruction bytes.
    patched = bytes(output)
    text = image.sections[('__TEXT', '__text')]
    assert patched[text[2]:text[2] + text[1]] == original[text[2]:text[2] + text[1]]
    assert len(Image(patched).commands) == len(commands) + 1
    rollback = bytearray(patched)
    for edit in reversed(edits):
        pos = edit['offset'];rollback[pos:pos + len(bytes.fromhex(edit['before']))] = bytes.fromhex(edit['before'])
    assert rollback == original
    return patched, {'mechanism':'two-level UIApplicationMain import to pre-nib bootstrap',
        'new_library_ordinal':ordinal,'original_uikit_ordinal':ui[0],
        'text_instruction_bytes_unchanged':True,'rollback_reconstructs_input':True,
        'before_sha256':hashlib.sha256(original).hexdigest(),
        'after_sha256':hashlib.sha256(patched).hexdigest(),'edits':edits}
