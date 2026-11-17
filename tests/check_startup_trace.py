"""Synthetic checks for the metadata/xref logic used by startup investigation."""
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from trace_resource_startup import Image


def main():
    im = Image.__new__(Image)
    d = bytearray(0x2200)
    im.sections = {('__TEXT', '__text'): (0x1000, 16, 0),
                   ('__TEXT', '__cstring'): (0x2000, 0x200, 0x100),
                   ('__DATA', '__objc_classlist'): (0x3000, 8, 0x400),
                   ('__DATA', '__objc_data'): (0x3100, 0x1000, 0x500)}
    im.function_starts = [0x1000]
    # ADRP x1, page 0x2000; ADD x1,x1,#0x40; RET.
    struct.pack_into('<IIII', d, 0, 0xb0000001, 0x91010021, 0xd65f03c0, 0)
    def at(addr):
        for base, size, offset in im.sections.values():
            if base <= addr < base + size:
                return offset + addr - base
        raise ValueError('fixture address')
    def ptr(addr, value):
        struct.pack_into('<Q', d, at(addr), value)
    ptr(0x3000, 0x3100)
    ptr(0x3100, 0x3180)  # metaclass
    ptr(0x3120, 0x3200)  # class_ro
    ptr(0x31a0, 0x3280)  # metaclass_ro
    ptr(0x3218, 0x2080)  # name
    ptr(0x3220, 0x3300)  # methods
    d[at(0x2080):at(0x2080)+5] = b'Test\0'
    d[at(0x20a0):at(0x20a0)+6] = b'start\0'
    struct.pack_into('<II', d, at(0x3300), 24, 1)
    ptr(0x3308, 0x20a0); ptr(0x3318, 0x1000)
    im.data = bytes(d)
    ms = im.objc_methods()
    assert ms == [{'class': 'Test', 'kind': 'instance', 'selector': 'start', 'implementation': 0x1000}]
    refs = im.xrefs({0x2040: 'catalogue'})
    assert len(refs) == 1 and refs[0]['function'] == 0x1000 and refs[0]['add'] == 0x1004
    assert im.xrefs({0x2041: 'wrong address'}) == []
    # Relative, direct selector method-list layout.
    struct.pack_into('<II', d, at(0x3300), 0xc000000c, 1)
    struct.pack_into('<iii', d, at(0x3308), 0x20a0-0x3308, 0, 0x1000-0x3310)
    im.data = bytes(d)
    assert im.objc_methods() == ms
    try:
        im.offset(0x5000)
        raise AssertionError('Unmapped pointer accepted')
    except ValueError:
        pass
    print('Startup trace: absolute/relative Objective-C methods, exact ADRP+ADD xref, function attribution and unmapped-address rejection passed.')


if __name__ == '__main__':
    main()
