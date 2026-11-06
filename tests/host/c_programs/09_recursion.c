#include <stdio.h>
static int ack(int m, int n) { if (m == 0) return n + 1; if (n == 0) return ack(m - 1, 1); return ack(m - 1, ack(m, n - 1)); }
static void qsort_i(int *a, int lo, int hi) {
  if (lo >= hi) return; int p = a[(lo + hi) / 2], i = lo, j = hi;
  while (i <= j) { while (a[i] < p) i++; while (a[j] > p) j--; if (i <= j) { int t = a[i]; a[i] = a[j]; a[j] = t; i++; j--; } }
  qsort_i(a, lo, j); qsort_i(a, i, hi);
}
int main(void) {
  int a[200]; unsigned int x = 12345; for (int i = 0; i < 200; i++) { x = x * 1103515245u + 12345u; a[i] = (x >> 16) % 1000; }
  qsort_i(a, 0, 199); int ok = 1; for (int i = 1; i < 200; i++) if (a[i - 1] > a[i]) ok = 0;
  printf("%d %d %d %d\n", ack(2, 3), ok, a[0], a[199]);
  return 0;
}
