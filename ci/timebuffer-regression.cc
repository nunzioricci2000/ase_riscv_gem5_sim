// SPDX-License-Identifier: GPL-2.0-only
// Created in the personal fork on 2026-10-27: exercise optimized TimeBuffer initialization.
#include <cstdlib>
#include <cstring>
#include <memory>
#include <cstdio>
#include "cpu/timebuf.hh"

// Make uninitialized counters observable instead of relying on fresh zero pages.
void *operator new[](std::size_t size)
{
    void *data = std::malloc(size);
    if (!data) throw std::bad_alloc();
    std::memset(data, 0x5a, size);
    return data;
}
void operator delete[](void *data) noexcept { std::free(data); }
void operator delete[](void *data, std::size_t) noexcept { std::free(data); }

struct Slot {
    int size;
    std::shared_ptr<int> entries[12];
};

int main()
{
    gem5::TimeBuffer<Slot> buffer(256, 256);
    for (int index = -256; index <= 256; ++index) {
        if (buffer[index].size != 0) {
            std::fprintf(stderr, "TimeBuffer counter was not initialized at %d\n", index);
            return 1;
        }
    }
    buffer[0].size = 42;
    for (int cycle = 0; cycle < 513; ++cycle) buffer.advance();
    if (buffer[0].size != 0) return 1;
    std::puts("TimeBuffer initialization and slot recycling verified at -O3");
}
