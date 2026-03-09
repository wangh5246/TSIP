#!/usr/bin/env python3
import argparse
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.utils import prp, inv_prp, prp_token, inv_prp_token


def main() -> int:
    parser = argparse.ArgumentParser(description="PRP self-test")
    parser.add_argument("--domain", type=int, default=10000)
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--seed-b", type=int, default=12346)
    parser.add_argument("--round-a", type=int, default=1001)
    parser.add_argument("--round-b", type=int, default=1002)
    parser.add_argument("--max-overlap-rate", type=float, default=0.01)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    rng = random.Random(args.seed ^ 0x5A5A)
    mismatches = 0
    overlap = 0
    token_mismatches = 0
    token_cross_round_collisions = 0

    for _ in range(args.samples):
        x = rng.randrange(args.domain)
        y = prp(args.seed, x, args.domain, rounds=args.rounds)
        x2 = inv_prp(args.seed, y, args.domain, rounds=args.rounds)
        if x2 != x:
            mismatches += 1
            if args.strict:
                break

        y2 = prp(args.seed, x, args.domain, rounds=args.rounds)
        if y2 != y:
            mismatches += 1
            if args.strict:
                break

        y_other = prp(args.seed_b, x, args.domain, rounds=args.rounds)
        if y_other == y:
            overlap += 1
            if args.strict:
                break

        tok_a = prp_token(args.round_a, args.seed, x, args.domain, rounds=args.rounds)
        tok_a2 = prp_token(args.round_a, args.seed, x, args.domain, rounds=args.rounds)
        if tok_a2 != tok_a:
            token_mismatches += 1
            if args.strict:
                break
        x3 = inv_prp_token(args.round_a, args.seed, tok_a, args.domain, rounds=args.rounds)
        if x3 != x:
            token_mismatches += 1
            if args.strict:
                break
        tok_b = prp_token(args.round_b, args.seed_b, x, args.domain, rounds=args.rounds)
        if tok_b == tok_a:
            token_cross_round_collisions += 1
            if args.strict:
                break

    overlap_rate = (overlap / args.samples) if args.samples > 0 else 0.0
    print(
        "prp_self_test",
        "domain=", args.domain,
        "rounds=", args.rounds,
        "samples=", args.samples,
        "mismatches=", mismatches,
        "same_seed_overlap=", 0,
        "diff_seed_overlap=", overlap,
        "diff_seed_overlap_rate=", round(overlap_rate, 6),
        "token_mismatches=", token_mismatches,
        "token_cross_round_collisions=", token_cross_round_collisions,
    )
    if args.strict and (mismatches > 0 or overlap_rate > args.max_overlap_rate or token_mismatches > 0 or token_cross_round_collisions > 0):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
