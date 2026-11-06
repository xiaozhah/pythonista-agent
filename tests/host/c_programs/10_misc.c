#include <stdio.h>
#define SQUARE(x) ((x) * (x))
#define N 4
union u { int i; float f; };
int main(void) {
  union u v; v.f = 1.0f;
  int arr[N]; for (int i = 0, j = 10; i < N; i++, j--) arr[i] = SQUARE(i) + j;
  int x = 5; x <<= 2; x |= 1; x ^= 3; x %= 7;
  char s[] = "abc";
  printf("%d %d %d %d %d %x %d\n", arr[0], arr[3], x, (int)sizeof(s), (int)sizeof(arr), v.i, N);
  return 0;
}
