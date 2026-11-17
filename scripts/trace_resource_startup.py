"""Read-only ARM64 Mach-O metadata/xrefs; no disassembly or patch execution.

Input must be an isolated executable component, output outside the repository.
ADRP+ADD candidates and Objective-C metadata are static leads, not runtime proof.
"""
import argparse
import bisect
import json
from pathlib import Path
import re
import struct


class Image:
    def __init__(self, data):
        self.data = data
        if data[:4] != b'\xcf\xfa\xed\xfe':
            raise ValueError('Expected thin little-endian Mach-O 64')
        self.sections = {}
        self.function_starts = []
        self.commands = []
        at = 32
        for _ in range(struct.unpack_from('<I', data, 16)[0]):
            cmd, size = struct.unpack_from('<II', data, at)
            if size < 8 or at + size > len(data):
                raise ValueError('Invalid load command')
            self.commands.append((cmd, at))
            if cmd == 0x19:
                seg = data[at + 8:at + 24].split(b'\0')[0].decode()
                for i in range(struct.unpack_from('<I', data, at + 64)[0]):
                    p = at + 72 + 80 * i
                    name = data[p:p + 16].split(b'\0')[0].decode()
                    addr, length = struct.unpack_from('<QQ', data, p + 32)
                    offset = struct.unpack_from('<I', data, p + 48)[0]
                    self.sections[(seg, name)] = (addr, length, offset)
            at += size
        text_base = next(v[0] - v[2] for k, v in self.sections.items() if k == ('__TEXT', '__text'))
        for cmd, at in self.commands:
            if cmd != 0x26:
                continue
            offset, size = struct.unpack_from('<II', data, at + 8)
            current, value, shift = text_base, 0, 0
            for byte in data[offset:offset + size]:
                value |= (byte & 127) << shift
                if byte & 128:
                    shift += 7
                else:
                    if value == 0:
                        break
                    current += value
                    self.function_starts.append(current)
                    value, shift = 0, 0

    def offset(self, address, length=1):
        for base, size, offset in self.sections.values():
            if base <= address and address + length <= base + size:
                result = offset + address - base
                if result + length <= len(self.data):
                    return result
        raise ValueError('Unmapped address')

    def u64(self, address):
        return struct.unpack_from('<Q', self.data, self.offset(address, 8))[0]

    def string(self, address):
        off = self.offset(address)
        end = self.data.find(b'\0', off, min(off + 1024, len(self.data)))
        if end < 0:
            raise ValueError('Unterminated string')
        return self.data[off:end].decode('utf-8', 'replace')

    def objc_methods(self):
        result = []
        for (_, name), (base, size, _) in self.sections.items():
            if name != '__objc_classlist':
                continue
            for at in range(base, base + size, 8):
                try:
                    cls = self.u64(at)
                    ro = self.u64(cls + 32) & ~7
                    class_name = self.string(self.u64(ro + 24))
                    for kind, class_address in [('instance', cls), ('class', self.u64(cls))]:
                        class_ro = self.u64(class_address + 32) & ~7
                        methods = self.u64(class_ro + 32)
                        if not methods:
                            continue
                        off = self.offset(methods, 8)
                        flags, count = struct.unpack_from('<II', self.data, off)
                        stride = flags & 0xffff
                        if count > 10000 or stride not in (12, 24):
                            continue
                        for i in range(count):
                            entry = methods + 8 + stride * i
                            if flags & 0x80000000:
                                p = self.offset(entry, 12)
                                n, _, imp = struct.unpack_from('<iii', self.data, p)
                                selector = entry + n
                                if not flags & 0x40000000:
                                    selector = self.u64(selector)
                                implementation = entry + 8 + imp
                            else:
                                selector = self.u64(entry)
                                implementation = self.u64(entry + 16)
                            result.append({'class': class_name, 'kind': kind,
                                           'selector': self.string(selector),
                                           'implementation': implementation})
                except (ValueError, struct.error):
                    continue
        return result

    def xrefs(self, targets):
        base, size, off = self.sections[('__TEXT', '__text')]
        words = struct.unpack_from('<' + 'I' * (size // 4), self.data, off)
        result = []
        for i, ins in enumerate(words):
            if ins & 0x9f000000 != 0x90000000:
                continue
            imm = ((ins >> 5) & 0x7ffff) << 2 | ((ins >> 29) & 3)
            if imm & (1 << 20):
                imm -= 1 << 21
            page = ((base + 4 * i) & ~0xfff) + (imm << 12)
            reg = ins & 31
            for j in range(i + 1, min(i + 5, len(words))):
                add = words[j]
                if add & 0xffc00000 == 0x91000000 and ((add >> 5) & 31) == reg:
                    address = page + ((add >> 10) & 0xfff)
                    if address in targets:
                        pc = base + 4 * i
                        idx = bisect.bisect_right(self.function_starts, pc) - 1
                        result.append({'target': targets[address], 'adrp': pc,
                                       'add': base + 4 * j,
                                       'function': self.function_starts[idx] if idx >= 0 else None})
                # A control transfer invalidates this small straight-line candidate.
                if add & 0x7c000000 == 0x14000000 or add & 0xfffffc1f in (0xd63f0000, 0xd61f0000):
                    break
        return result

    def labels(self):
        labels = {v['implementation']: v['class'] + ' ' + v['selector']
                  for v in self.objc_methods()}
        d = self.data
        sym = next(at for cmd, at in self.commands if cmd == 2)
        symoff, count, stroff, _ = struct.unpack_from('<IIII', d, sym + 8)
        dysym = next(at for cmd, at in self.commands if cmd == 0xb)
        indoff, nind = struct.unpack_from('<II', d, dysym + 56)
        indices = struct.unpack_from('<' + 'I' * nind, d, indoff)
        for cmd, at in self.commands:
            if cmd != 0x19:
                continue
            for i in range(struct.unpack_from('<I', d, at + 64)[0]):
                s = at + 72 + i * 80
                base, size = struct.unpack_from('<QQ', d, s + 32)
                flags, first, stride = struct.unpack_from('<III', d, s + 64)
                if flags & 255 != 8 or stride == 0:
                    continue
                for j, addr in enumerate(range(base, base + size, stride)):
                    idx = indices[first + j]
                    if idx < count:
                        start = stroff + struct.unpack_from('<I', d, symoff + 16 * idx)[0]
                        labels[addr] = d[start:d.index(b'\0', start)].decode('utf-8', 'replace')
        for (_, name), (base, size, off) in self.sections.items():
            if name != '__objc_stubs':
                continue
            # This build's optimized stubs are 32 bytes. Unknown layouts stay unlabeled.
            for addr in range(base, base + size - 23, 32):
                regs = {}
                for j in range(0, 24, 4):
                    ins = struct.unpack_from('<I', d, off + addr - base + j)[0]
                    if ins & 0x9f000000 == 0x90000000:
                        imm = ((ins >> 5) & 0x7ffff) << 2 | ((ins >> 29) & 3)
                        if imm & (1 << 20):
                            imm -= 1 << 21
                        regs[ins & 31] = ((addr + j) & ~4095) + (imm << 12)
                    elif ins & 0xffc00000 == 0xf9400000 and ins & 31 == 1 and ((ins >> 5) & 31) in regs:
                        pointer = regs[(ins >> 5) & 31] + (((ins >> 10) & 4095) * 8)
                        try:
                            labels[addr] = 'objc ' + self.string(self.u64(pointer))
                        except ValueError:
                            pass
        return labels


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    if a.output.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        p.error('Detailed report must be outside repository')
    image = Image(a.binary.read_bytes())
    methods = image.objc_methods()
    selected = [v for v in methods if re.search(r'AssetManager|AssetDownload|AppDelegate|AppController', v['class'])
                or re.search(r'didFinishLaunching|willFinishLaunching|^constructPart(One|Two)$', v['selector'])]
    needles = (b'/asset_list_base.txtCache.txt', b'CC: Constructing FileManager',
               b'CC: AssetManager::LoadAssetList()', b'InitialAssetDownload',
               b'IsAssetDownloadComplete')
    base, size, off = image.sections[('__TEXT', '__cstring')]
    data = image.data[off:off + size]
    targets = {}
    cursor = 0
    for value in data.split(b'\0'):
        if any(n in value for n in needles):
            targets[base + cursor] = value.decode('utf-8', 'replace')
        cursor += len(value) + 1
    result = {'objc_method_count': len(methods), 'selected_methods': selected,
              'function_starts': len(image.function_starts),
              'resource_string_xrefs': image.xrefs(targets),
              'limits': 'Static straight-line ADRP+ADD leads, not a full dataflow/callgraph or runtime verification.'}
    with a.output.open('x') as f:
        json.dump(result, f, indent=2)
    print('ObjC methods:', len(methods), 'selected:', len(selected),
          'resource xrefs:', len(result['resource_string_xrefs']))
    for v in selected[:16]:
        print(v['class'], v['selector'], hex(v['implementation']))
    for v in result['resource_string_xrefs'][:12]:
        print('Resource reference:', v['target'][:90], 'function:', hex(v['function'] or 0))


if __name__ == '__main__':
    main()
