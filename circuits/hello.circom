pragma circom 2.1.9;

template Hello() {
    signal input a;
    signal input b;
    signal output c;
    c <== a * b;
}
component main = Hello();
