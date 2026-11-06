#include <stdio.h>
struct point { int x; int y; };
typedef struct { double re, im; } cplx;
static int sum_points(struct point *p, int n) { int s = 0; for (int i = 0; i < n; i++) s += p[i].x * p[i].y; return s; }
static cplx mul(const cplx *a, const cplx *b) { cplx r; r.re = a->re*b->re - a->im*b->im; r.im = a->re*b->im + a->im*b->re; return r; }
int main(void) {
  struct point pts[3] = {{1, 2}, {3, 4}, {5, 6}};
  cplx a = {1.0, 2.0}, b = {3.0, -1.0};
  cplx c = mul(&a, &b);
  struct point q = pts[1]; q.x = 10;
  printf("%d %f %f %d %d %d\n", sum_points(pts, 3), c.re, c.im, q.x, pts[1].x, (int)sizeof(cplx));
  return 0;
}
