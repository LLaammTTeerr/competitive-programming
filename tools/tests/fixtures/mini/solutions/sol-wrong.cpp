/**
 * @tag        wrong-answer
 * @expect     g1=WA
 * @algorithm  Prints the difference instead of the sum.
 * @why-wrong  Wrong operator; every test with a != 0 catches it.
 * @complexity O(1)
 */
#include <iostream>
int main() { long long a, b; std::cin >> a >> b; std::cout << a - b << "\n"; }
