# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-27: simulation and pipeline trace smoke test.
# Modified in the personal fork on 2026-10-27: require a final long-latency result before exit.
.text
.globl _start
_start:
    li t0, 63
    li t1, 9
    div t2, t0, t1
    li a0, 0
    li a7, 93
    ecall
