# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-27: exercise FP dependencies, stores and final writeback.
.data
.balign 8
inputs:
    .float 2.5
    .balign 8
    .double 9.0, 2.0
result:
    .word 0

.text
.globl _start
_start:
    la t0, inputs
    flw ft0, 0(t0)
    fmul.s ft1, ft0, ft0
    fadd.s ft2, ft1, ft0
    fdiv.s ft3, ft2, ft0
    fsw ft3, 24(t0)
    fld ft4, 8(t0)
    fld ft5, 16(t0)
    li a0, 0
    li a7, 93
    fdiv.d ft6, ft4, ft5
    ecall
