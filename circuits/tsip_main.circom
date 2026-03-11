pragma circom 2.1.9;

include "circomlib/circuits/comparators.circom";

template TSIPMain() {
    signal input x1;
    signal input y1;
    signal input x2;
    signal input y2;

    signal input hash_prev;
    signal input hash_curr;
    signal input max_dist_sq;

    signal calc_prev;
    signal calc_curr;

    calc_prev <== x1 * 1315423911 + y1 * 2654435761 + 97531;
    calc_curr <== x2 * 1315423911 + y2 * 2654435761 + 97531;

    calc_prev === hash_prev;
    calc_curr === hash_curr;

    signal dx;
    signal dy;
    signal dx2;
    signal dy2;
    signal dist_sq;

    dx <== x2 - x1;
    dy <== y2 - y1;
    dx2 <== dx * dx;
    dy2 <== dy * dy;
    dist_sq <== dx2 + dy2;

    component leq = LessEqThan(64);
    leq.in[0] <== dist_sq;
    leq.in[1] <== max_dist_sq;
    leq.out === 1;

    component rangeX1 = LessThan(32);
    component rangeY1 = LessThan(32);
    component rangeX2 = LessThan(32);
    component rangeY2 = LessThan(32);

    rangeX1.in[0] <== x1;
    rangeX1.in[1] <== 1000000;
    rangeX1.out === 1;

    rangeY1.in[0] <== y1;
    rangeY1.in[1] <== 1000000;
    rangeY1.out === 1;

    rangeX2.in[0] <== x2;
    rangeX2.in[1] <== 1000000;
    rangeX2.out === 1;

    rangeY2.in[0] <== y2;
    rangeY2.in[1] <== 1000000;
    rangeY2.out === 1;
}

component main {public [hash_prev, hash_curr, max_dist_sq]} = TSIPMain();
