"""Minimal pure-Python AES-128-CBC decryption.

Codeforces guards some pages with a JS challenge that hands the browser an AES
key, IV and ciphertext (the ``toNumbers("...")`` triple).  Decrypting it yields
the value of the ``RCPC`` cookie.  That is the only thing we need AES for, so we
implement just the inverse cipher here instead of pulling in a crypto
dependency (which would also mean a compiled wheel for every Python version).
"""

from __future__ import annotations


def _xtime(a: int) -> int:
    a <<= 1
    if a & 0x100:
        a = (a ^ 0x1B) & 0xFF
    return a


def _gmul(a: int, b: int) -> int:
    result = 0
    for _ in range(8):
        if b & 1:
            result ^= a
        b >>= 1
        a = _xtime(a)
    return result


def _build_sbox() -> tuple[list[int], list[int]]:
    # Multiplicative inverse in GF(2^8) by brute force; 0 maps to 0.
    inverse = [0] * 256
    for i in range(1, 256):
        for j in range(1, 256):
            if _gmul(i, j) == 1:
                inverse[i] = j
                break

    def rotl8(x: int, shift: int) -> int:
        return ((x << shift) | (x >> (8 - shift))) & 0xFF

    sbox = [0] * 256
    for i in range(256):
        x = inverse[i]
        sbox[i] = x ^ rotl8(x, 1) ^ rotl8(x, 2) ^ rotl8(x, 3) ^ rotl8(x, 4) ^ 0x63

    inv_sbox = [0] * 256
    for i, value in enumerate(sbox):
        inv_sbox[value] = i
    return sbox, inv_sbox


SBOX, INV_SBOX = _build_sbox()
RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _expand_key(key: bytes) -> list[list[int]]:
    """AES-128 key schedule: 11 round keys of 16 bytes each."""
    if len(key) != 16:
        raise ValueError(f"AES-128 needs a 16-byte key, got {len(key)}")
    words = [list(key[i * 4 : i * 4 + 4]) for i in range(4)]
    for i in range(4, 44):
        temp = list(words[i - 1])
        if i % 4 == 0:
            temp = temp[1:] + temp[:1]
            temp = [SBOX[b] for b in temp]
            temp[0] ^= RCON[i // 4 - 1]
        words.append([words[i - 4][j] ^ temp[j] for j in range(4)])
    return [
        [byte for word in words[r * 4 : r * 4 + 4] for byte in word] for r in range(11)
    ]


def _add_round_key(state: list[int], round_key: list[int]) -> None:
    for i in range(16):
        state[i] ^= round_key[i]


def _inv_shift_rows(state: list[int]) -> None:
    # State is column-major: byte at (row, col) lives at index col * 4 + row.
    for row in range(1, 4):
        column = [state[col * 4 + row] for col in range(4)]
        column = column[-row:] + column[:-row]  # rotate right by `row`
        for col in range(4):
            state[col * 4 + row] = column[col]


def _inv_sub_bytes(state: list[int]) -> None:
    for i in range(16):
        state[i] = INV_SBOX[state[i]]


def _inv_mix_columns(state: list[int]) -> None:
    for col in range(4):
        base = col * 4
        a0, a1, a2, a3 = state[base : base + 4]
        state[base + 0] = _gmul(a0, 14) ^ _gmul(a1, 11) ^ _gmul(a2, 13) ^ _gmul(a3, 9)
        state[base + 1] = _gmul(a0, 9) ^ _gmul(a1, 14) ^ _gmul(a2, 11) ^ _gmul(a3, 13)
        state[base + 2] = _gmul(a0, 13) ^ _gmul(a1, 9) ^ _gmul(a2, 14) ^ _gmul(a3, 11)
        state[base + 3] = _gmul(a0, 11) ^ _gmul(a1, 13) ^ _gmul(a2, 9) ^ _gmul(a3, 14)


def decrypt_block(block: bytes, round_keys: list[list[int]]) -> bytes:
    state = list(block)
    _add_round_key(state, round_keys[10])
    for rnd in range(9, 0, -1):
        _inv_shift_rows(state)
        _inv_sub_bytes(state)
        _add_round_key(state, round_keys[rnd])
        _inv_mix_columns(state)
    _inv_shift_rows(state)
    _inv_sub_bytes(state)
    _add_round_key(state, round_keys[0])
    return bytes(state)


def decrypt_cbc(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    """Decrypt AES-128-CBC without unpadding (the challenge payload is exact)."""
    if len(ciphertext) % 16:
        raise ValueError("ciphertext length must be a multiple of 16")
    round_keys = _expand_key(key)
    out = bytearray()
    previous = iv
    for offset in range(0, len(ciphertext), 16):
        block = ciphertext[offset : offset + 16]
        plain = decrypt_block(block, round_keys)
        out.extend(bytes(x ^ y for x, y in zip(plain, previous)))
        previous = block
    return bytes(out)
