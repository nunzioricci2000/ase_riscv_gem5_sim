#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-28: reject host-dependent truncation of simulated FP registers.
"""Compile the actual gem5 conversion helpers with native and narrow fast integers."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


def check(source):
    header = (source / 'src/arch/riscv/regs/float.hh').read_text()
    # Keep the upstream notice and exact conversion helpers, excluding the
    # unrelated register-class declarations and generated debug dependencies.
    conversion = header.split('namespace float_reg\n{', 1)[0]
    for include in ('cpu/reg_class.hh', 'debug/FloatRegs.hh'):
        conversion = conversion.replace(f'#include "{include}"', '')
    conversion += '\n} }\n#endif\n'
    assertions = '''
using namespace gem5::RiscvISA;
static_assert(freg(UINT64_C(0xffffffff40200000)).v == UINT64_C(0xffffffff40200000));
static_assert(freg(UINT64_C(0x4022000000000000)).v == UINT64_C(0x4022000000000000));
static_assert(f32(freg(UINT64_C(0xffffffff40200000))).v == UINT32_C(0x40200000));
static_assert(f64(freg(UINT64_C(0x4022000000000000))).v == UINT64_C(0x4022000000000000));
static_assert(f16(freg(UINT64_C(0xffffffffffff3c00))).v == UINT16_C(0x3c00));
int main() {}
'''
    with tempfile.TemporaryDirectory(prefix='ase-fpreg-') as directory:
        directory = Path(directory)
        for narrow in (False, True):
            text = conversion
            if narrow:
                text = text.replace('namespace RiscvISA\n{',
                    'namespace RiscvISA\n{\nusing uint_fast16_t = std::uint16_t;', 1)
            unit = directory / ('narrow.cc' if narrow else 'native.cc')
            unit.write_text(text + assertions)
            subprocess.run([os.getenv('CXX', 'c++'), '-std=c++17', '-O3',
                '-I' + str(source / 'src'), '-I' + str(source / 'ext/softfloat'),
                str(unit), '-o', str(directory / 'check')], check=True)
            subprocess.run([str(directory / 'check')], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    check(parser.parse_args().source.resolve())
