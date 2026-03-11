pragma circom 2.1.9;

include "circomlib/circuits/comparators.circom";

template MiMC7() {
    signal input in;
    signal output out;

    signal states[33];
    signal t[32];
    signal t2[32];
    signal t4[32];
    signal t6[32];
    states[0] <== in;

    for (var i = 0; i < 32; i++) {
        t[i] <== states[i] + (i + 1);
        t2[i] <== t[i] * t[i];
        t4[i] <== t2[i] * t2[i];
        t6[i] <== t4[i] * t2[i];
        states[i + 1] <== t6[i] * t[i];
    }

    out <== states[32];
}

template MiMCHash2() {
    signal input a;
    signal input b;
    signal output out;

    signal s1in;
    s1in <== a;
    component h1 = MiMC7();
    h1.in <== s1in;

    signal s2in;
    s2in <== h1.out + b;
    component h2 = MiMC7();
    h2.in <== s2in;

    out <== h2.out;
}

template TSIPMain() {
    signal input x1;
    signal input y1;
    signal input x2;
    signal input y2;

    signal input hash_prev;
    signal input hash_curr;
    signal input max_dist_sq;

    component prevHash = MiMCHash2();
    prevHash.a <== x1;
    prevHash.b <== y1;
    prevHash.out === hash_prev;

    component currHash = MiMCHash2();
    currHash.a <== x2;
    currHash.b <== y2;
    currHash.out === hash_curr;

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
