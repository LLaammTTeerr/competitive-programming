# Black Magic — constant-factor optimization toolbox

Last-resort techniques for problems whose time or memory limit is brutally
tight, where a correct and asymptotically optimal solution still fails on
constant factors. Everything here trades readability, portability, and
debuggability for speed. Reach for it only after confirming the algorithm's
complexity is already right — none of this fixes a wrong asymptotic class.

Assumes a GCC / Codeforces-style judge with AVX2 available. Verify the judge
supports these features before relying on them; some judges reject the target
pragmas or lack AVX2.

Apply in escalation order and stop as soon as the solution passes. Levels 1–2
are almost free; the later levels get progressively uglier and more bug-prone.

## Level 1 — compiler pragmas and fast I/O

**Optimization pragmas** at the very top of the file, before includes:

```cpp
#pragma GCC optimize("O3,unroll-loops")
#pragma GCC target("avx2,bmi,bmi2,lzcnt,popcnt")
```

`optimize` raises the optimization level and unrolls loops even if the judge
compiles at a lower `-O`. `target` enables the instruction-set features so both
auto-vectorization and hand-written intrinsics can use them. Try these alone
first — auto-vectorization at `-O3` with AVX2 enabled often clears the bar
without any manual SIMD.

**Custom integer reader.** `cin` (even with sync off) and `scanf` are slow for
large inputs. Read a big block and parse digits by hand:

```cpp
static char buf[1 << 25];
int bufPos = 0, bufLen = 0;

inline char readChar() {
    if (bufPos == bufLen) {
        bufLen = (int)fread(buf, 1, sizeof(buf), stdin);
        bufPos = 0;
        if (bufLen == 0) return -1;
    }
    return buf[bufPos++];
}

inline int readInt() {
    char c = readChar();
    while (c != '-' && (c < '0' || c > '9')) c = readChar();
    bool neg = (c == '-');
    if (neg) c = readChar();
    int value = 0;
    while (c >= '0' && c <= '9') {
        value = value * 10 + (c - '0');
        c = readChar();
    }
    return neg ? -value : value;
}
```

For output, build into a buffer and flush once with `fwrite`, or use
`putchar_unlocked`. Never use `endl` in a hot path — it flushes every call.

## Level 2 — memory layout and cache

Memory stalls dominate many tight problems. Restructure so the CPU streams
sequentially through cache:

- **Struct-of-arrays over array-of-structs.** Store `xs[]`, `ys[]`, `vals[]`
  as separate arrays rather than an array of structs, so each pass touches only
  the fields it needs and packs cache lines densely. This also lets SIMD load
  contiguous data.
- **Flat, index-based structures.** Represent graphs with CSR adjacency (a flat
  edge array plus per-node offsets) instead of `vector<vector<int>>`, and trees
  with index arrays instead of pointer nodes. Pointer chasing wrecks the cache.
- **Smallest type that fits.** Use `int` over `long long`, or even `short` /
  `char`, when values allow, to fit more of the working set in cache — but guard
  against overflow.
- **Loop order for stride-1 access.** In nested loops over a matrix, arrange the
  inner loop to walk memory contiguously (e.g. `i, k, j` order for matrix
  multiply so the inner loop strides along rows).
- **Blocking / tiling.** Process matrices or grids in cache-sized tiles so a
  block stays hot across the inner loops.
- **Prefetch** upcoming memory when the access pattern is predictable but not
  sequential: `__builtin_prefetch(&data[nextIndex]);`.

## Level 3 — drop slow STL containers

- Replace `std::map` / `std::unordered_map` (cache-hostile, high constant) with
  a sorted array plus binary search, or a custom open-addressing hash table.
  `__gnu_pbds::gp_hash_table` is a fast drop-in. Seed any hash with a random
  value to defeat anti-hash tests.
- Replace `std::vector` in the hot path with fixed-size static arrays
  (`static int data[N];`) to avoid allocation and get predictable layout.
- Use a memory pool / arena for node-based structures instead of per-node
  allocation.
- Avoid `std::function`, virtual dispatch, and (already-off) exceptions in hot
  code.

## Level 4 — branchless and bit tricks

- **Bitset DP.** `std::bitset<N>` compresses boolean DP into 64-bit words, giving
  an N/64 speedup for subset-sum reachability, transitive closure, and similar.
  Custom `uint64_t` word arrays with manual shifts go further.
- **Branchless selection.** Replace unpredictable branches with arithmetic or
  conditional moves: `result = (cond) ? a : b;` compiles to `cmov`, or use bit
  masks: `result = b ^ ((a ^ b) & -(int64_t)cond);`.
- **Built-ins.** `__builtin_popcountll`, `__builtin_clzll`, `__builtin_ctzll`
  map to single instructions (enabled by the `popcnt`/`lzcnt`/`bmi` targets).
- **Cheaper arithmetic.** Division and modulo are expensive. For a fixed modulus
  used in a hot loop, apply Montgomery or Barrett reduction; for power-of-two
  moduli, mask with `& (m - 1)`. Hoist invariant computations out of loops.
- **`__int128`** avoids overflow in products without the cost of big-integer
  arithmetic.

## Level 5 — hand-written SIMD (AVX2)

When auto-vectorization won't take, write intrinsics directly:

```cpp
#include <immintrin.h>
```

- Operate on 8×`int32` or 4×`int64` (or 8×`float`) per `__m256i` / `__m256`.
- Load with `_mm256_loadu_si256` (unaligned) or `_mm256_load_si256` (requires
  32-byte alignment: declare buffers `alignas(32)`).
- Vectorize inner loops that do the same op across an array: sums, dot products,
  element-wise min/max, comparisons and counting, saturating arithmetic.
- Reduce a vector accumulator to a scalar with a horizontal reduction at the end
  (shuffle-and-add, or extract the two 128-bit halves and combine).
- Handle the tail (array length not a multiple of the lane count) with a scalar
  loop.

Example shape — sum an `int` array:

```cpp
long long simdSum(const int* data, int n) {
    __m256i acc = _mm256_setzero_si256();
    int i = 0;
    for (; i + 8 <= n; i += 8) {
        __m256i chunk = _mm256_loadu_si256((const __m256i*)(data + i));
        acc = _mm256_add_epi32(acc, chunk);
    }
    int lanes[8];
    _mm256_storeu_si256((__m256i*)lanes, acc);
    long long total = 0;
    for (int k = 0; k < 8; ++k) total += lanes[k];
    for (; i < n; ++i) total += data[i];   // tail
    return total;
}
```

(Watch for lane overflow: accumulate into wider lanes or periodically drain if
values are large.)

## Caveats

- **Confirm the asymptotics first.** These tricks multiply speed by a constant.
  An algorithm in the wrong complexity class needs a better algorithm, not black
  magic.
- **Keep the clean solution.** This code is bug-prone; retain the readable
  version, and test the optimized one against samples plus stress tests before
  trusting it.
- **Portability.** The pragmas and intrinsics are GCC/Clang- and x86-specific.
  Confirm the target judge supports them.
