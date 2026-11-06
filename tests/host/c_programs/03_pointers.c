#include <stdio.h>
static void swap(int *a, int *b) { int t = *a; *a = *b; *b = t; }
static int twice(int x) { return 2 * x; }
static int apply(int (*f)(int), int x) { return f(x); }
int main(void) {
  int a = 1, b = 2; swap(&a, &b);
  int arr[5] = {5, 4, 3, 2, 1}; int *p = arr + 1; p[1] = 99;
  int m[2][3] = {{1,2,3},{4,5,6}};
  const char *s = "hello"; int n = 0; while (s[n]) n++;
  printf("%d %d %d %d %d %d %d\n", a, b, arr[2], *(p + 2), m[1][2], n, apply(twice, 21));
  return 0;
}
