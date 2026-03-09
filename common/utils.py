import hashlib
import hmac
import math
import random
from typing import Iterable, List


def seed_from_round(round_id: int, secret: str) -> int:
    """
    Derive a deterministic 64-bit seed from round_id + secret.
    """
    h = hashlib.sha256(f"{secret}:{round_id}".encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big", signed=False)


def _gaussian_stream(seed: int) -> Iterable[float]:
    """
    Deterministic Gaussian(0,1) stream using Box-Muller and a local RNG.
    """
    rng = random.Random(int(seed))
    while True:
        u1 = rng.random()
        u2 = rng.random()
        if u1 <= 0.0:
            u1 = 1e-12
        r = math.sqrt(-2.0 * math.log(u1))
        theta = 2.0 * math.pi * u2
        z0 = r * math.cos(theta)
        z1 = r * math.sin(theta)
        yield z0
        yield z1


def gaussian_vectors(seed: int, m: int, dim: int, mu: float = 0.0, sigma: float = 1.0) -> List[List[float]]:
    """
    Return m vectors of length dim from N(mu, sigma^2), deterministically.
    """
    if m < 0 or dim < 0:
        raise ValueError("m and dim must be >= 0")
    if sigma < 0:
        raise ValueError("sigma must be >= 0")
    out: List[List[float]] = []
    stream = _gaussian_stream(seed)
    for _ in range(m):
        row = []
        for _ in range(dim):
            row.append(mu + sigma * next(stream))
        out.append(row)
    return out


def gaussian_preview(seed: int, m: int, dim: int, n: int = 3, mu: float = 0.0, sigma: float = 1.0) -> List[float]:
    """
    Return the first n numbers of the flattened Gaussian vectors.
    """
    if n <= 0:
        return []
    stream = _gaussian_stream(seed)
    total = m * dim
    count = min(n, total)
    out = []
    for _ in range(count):
        out.append(mu + sigma * next(stream))
    return out


def norm_ppf(p: float) -> float:
    """
    Approximate inverse CDF for standard normal using Acklam's method.
    """
    if not (0.0 < p < 1.0):
        raise ValueError("p must be in (0, 1)")

    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]

    plow = 0.02425
    phigh = 1.0 - plow

    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        )
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        )

    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    )


def chi2_ppf(p: float, df: int) -> float:
    """
    Approximate chi-square inverse CDF via Wilson-Hilferty transform.
    """
    if df <= 0:
        raise ValueError("df must be > 0")
    if not (0.0 < p < 1.0):
        raise ValueError("p must be in (0, 1)")

    z = norm_ppf(p)
    k = float(df)
    x = k * (1.0 - (2.0 / (9.0 * k)) + z * math.sqrt(2.0 / (9.0 * k))) ** 3
    return max(0.0, x)


def _prp_bits(domain: int) -> int:
    if domain <= 0:
        raise ValueError("domain must be > 0")
    bits = max(1, (int(domain) - 1).bit_length())
    if bits % 2 != 0:
        bits += 1
    return bits


def _prp_round_function(seed: int, round_idx: int, r: int, out_bits: int) -> int:
    key = str(int(seed)).encode("utf-8")
    data = f"{int(round_idx)}:{int(r)}".encode("utf-8")
    digest = hmac.new(key, data, hashlib.sha256).digest()
    val = int.from_bytes(digest, "big")
    if out_bits <= 0:
        return 0
    return val & ((1 << out_bits) - 1)


def _feistel_prp(seed: int, x: int, bits: int, rounds: int) -> int:
    half = bits // 2
    mask = (1 << half) - 1
    l = (int(x) >> half) & mask
    r = int(x) & mask
    for rnd in range(rounds):
        f = _prp_round_function(seed, rnd, r, half)
        l, r = r, (l ^ f) & mask
    return (l << half) | r


def _feistel_inv(seed: int, x: int, bits: int, rounds: int) -> int:
    half = bits // 2
    mask = (1 << half) - 1
    l = (int(x) >> half) & mask
    r = int(x) & mask
    for rnd in reversed(range(rounds)):
        r_prev = l
        f = _prp_round_function(seed, rnd, r_prev, half)
        l_prev = (r ^ f) & mask
        l, r = l_prev, r_prev
    return (l << half) | r


def prp(seed: int, x: int, domain: int, rounds: int = 6) -> int:
    """
    Feistel-based PRP on [0, domain), using cycle-walking if needed.
    """
    if rounds <= 0:
        raise ValueError("rounds must be > 0")
    if not (0 <= int(x) < int(domain)):
        raise ValueError("x out of range")
    bits = _prp_bits(domain)
    mod = 1 << bits
    y = int(x) % mod
    while True:
        y = _feistel_prp(seed, y, bits, rounds)
        if y < domain:
            return y


def inv_prp(seed: int, x: int, domain: int, rounds: int = 6) -> int:
    """
    Inverse of prp() for the same seed/domain/rounds.
    """
    if rounds <= 0:
        raise ValueError("rounds must be > 0")
    if not (0 <= int(x) < int(domain)):
        raise ValueError("x out of range")
    bits = _prp_bits(domain)
    mod = 1 << bits
    y = int(x) % mod
    while True:
        y = _feistel_inv(seed, y, bits, rounds)
        if y < domain:
            return y


def prp_token(round_id: int, seed: int, x: int, domain: int, rounds: int = 6) -> int:
    """
    Round-separated token: round_id * domain + prp(seed, x).
    """
    if int(round_id) < 0:
        raise ValueError("round_id must be >= 0")
    y = prp(seed, x, domain, rounds=rounds)
    return int(round_id) * int(domain) + y


def inv_prp_token(round_id: int, seed: int, token: int, domain: int, rounds: int = 6) -> int:
    """
    Invert prp_token for a known round_id.
    """
    if int(round_id) < 0:
        raise ValueError("round_id must be >= 0")
    base = int(round_id) * int(domain)
    y = int(token) - base
    if not (0 <= y < int(domain)):
        raise ValueError("token out of round range")
    return inv_prp(seed, y, domain, rounds=rounds)


def hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    """
    Minimal HKDF-SHA256 implementation (RFC 5869).
    """
    if length <= 0:
        raise ValueError("length must be > 0")
    salt = salt or b"\x00" * hashlib.sha256().digest_size
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    okm = b""
    t = b""
    i = 1
    while len(okm) < length:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
        i += 1
    return okm[:length]


def derive_prp_seed(round_id: int, share_a: bytes, share_r: bytes, domain: int) -> int:
    """
    Derive PRP seed from two key shares and round_id.
    """
    if len(share_a) != len(share_r):
        raise ValueError("share length mismatch")
    combined = bytes(a ^ b for a, b in zip(share_a, share_r))
    info = f"CLOVER:{int(round_id)}:{int(domain)}".encode("utf-8")
    okm = hkdf_sha256(combined, salt=b"CLOVER", info=info, length=8)
    return int.from_bytes(okm, "big", signed=False)


def derive_prp_seed_from_share(round_id: int, share: bytes, domain: int, role: str) -> int:
    """
    Derive a PRP seed from a single key share.
    """
    if not role:
        raise ValueError("role must be non-empty")
    info = f"CLOVER:{role}:{int(round_id)}:{int(domain)}".encode("utf-8")
    okm = hkdf_sha256(share, salt=b"CLOVER", info=info, length=8)
    return int.from_bytes(okm, "big", signed=False)
