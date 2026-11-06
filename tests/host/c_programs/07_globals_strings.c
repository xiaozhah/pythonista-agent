#include <stdio.h>
#include <string.h>
static int counter = 3;
int table[4] = {10, 20, 30, 40};
const char *names[] = {"zero", "one", "two"};
static char buf[64];
static int next(void) { static int n = 100; return n++; }
static int add1(int x) { return x + 1; }
static int (*ops[2])(int) = {add1, 0};
int extra(void) { return ops[0](41) + (ops[1] == 0); }
int main(void) {
  counter += table[2];
  for (int i = 0; i < 3; i++) buf[i] = 'a' + i; buf[3] = 0;
  int a = next(); int b = next();
  printf("%d %s %s %d %d %d %d\n", counter, names[2], buf, a, b, strcmp(names[1], "one"), extra());
  return 0;
}
