#include <stdio.h>
int main(void) { printf("hi %d %s %5.2f|%-4d|%x %c %u %e %g\n", 42, "str", 3.14159, 7, 255, 65, 4000000000u, 12345.678, 0.0001); puts("done"); putchar('!'); putchar('\n'); return 0; }
