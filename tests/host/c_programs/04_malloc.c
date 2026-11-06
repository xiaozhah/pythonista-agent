#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct node { int v; struct node *next; } node;
int main(void) {
  node *head = NULL;
  for (int i = 0; i < 1000; i++) { node *n = malloc(sizeof(node)); n->v = i; n->next = head; head = n; }
  long s = 0; int cnt = 0; while (head) { node *n = head; s += n->v; cnt++; head = n->next; free(n); }
  double *big = calloc(100000, sizeof(double)); big[99999] = 1.5;
  char *buf = malloc(32); strcpy_like: memcpy(buf, "abc", 4); buf = realloc(buf, 64);
  printf("%ld %d %f %s %d\n", s, cnt, big[99999] + big[0], buf, (int)strlen(buf));
  return 0;
}
