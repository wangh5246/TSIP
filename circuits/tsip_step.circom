pragma circom 2.1.9;
include "comparators.circom";

/*
  单步速度约束（最小版）:
  dx^2 + dy^2 <= (vmax * dt)^2
*/
template TSIPStep() {
    signal input dx;
    signal input dy;
    signal input dt;
    signal input vmax;
    signal output ok;

    signal dist2;
    signal limit2;
    signal dx2;
    signal dy2;
    signal vmax2;
    signal dt2;

    dx2 <== dx * dx;
    dy2 <== dy * dy;
    dist2 <== dx2 + dy2;

    vmax2 <== vmax * vmax;
    dt2 <== dt * dt;
    limit2 <== vmax2 * dt2;

    component leq = LessEqThan(64);
    leq.in[0] <== dist2;
    leq.in[1] <== limit2;
    leq.out === 1;

    ok <== 1;
}

component main = TSIPStep();
