#include <stdio.h>
enum color { RED, GREEN = 5, BLUE };
static int sw(int x) { switch (x) { case 1: return 10; case 2: case 3: return 20; case GREEN: return 50; default: return -1; } }
int main(void) {
  int s = 0;
  for (int i = 0; i < 10; i++) { if (i == 7) break; if (i % 2) continue; s += i; }
  int k = 0; do { k++; if (k == 2) continue; } while (k < 5);
  int t = (s > 5 && k == 5) ? 1 : 0;
  printf("%d %d %d %d %d %d %d %d\n", s, k, t, sw(1), sw(3), sw(5), sw(9), BLUE);
  return 0;
}
