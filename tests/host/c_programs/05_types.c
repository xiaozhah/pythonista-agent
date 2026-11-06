#include <stdio.h>
int main(void) {
  unsigned int u = 4000000000u; u += 500000000u;           /* wraps at 2^32 */
  unsigned int h = 2166136261u; for (int i = 0; i < 4; i++) h = (h ^ (unsigned)i) * 16777619u;
  long long big = 1LL << 40; big = big * 3 + 7;
  unsigned char c = 250; c += 10;
  short sh = 32767; sh++;
  int neg = -7; int q = neg / 2, r = neg % 2;
  unsigned int sh_r = 0x80000000u >> 31;
  int ar = -16 >> 2;
  float f = 1.5f; double d = f * 2;
  printf("%u %u %lld %d %d %d %d %u %d %f %d\n", u, h, big, c, sh, q, r, sh_r, ar, d, (int)(3.99));
  return 0;
}
