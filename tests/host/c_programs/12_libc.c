#include <assert.h>
#include <ctype.h>
#include <limits.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void) {
  char buf[64], name[16];
  int n = sprintf(buf, "%d-%s-%.2f", 7, "x", 2.5);
  printf("%s %d\n", buf, n);
  n = snprintf(buf, 5, "%s", "abcdefgh");
  printf("%s %d\n", buf, n);
  strcpy(name, "py");
  strcat(name, "coder");
  strncpy(buf, name, 3);
  buf[3] = 0;
  printf("%s %s %d %d %d\n", name, buf, (int)strlen(name), strncmp(name, "pyc", 3) == 0, strchr(name, 'c') - name);
  printf("%d %d %d %c %c\n", isdigit('7'), isalpha('7') != 0, isspace('\t') != 0, toupper('q'), tolower('Q'));
  printf("%g %g %g %g %g %G\n", 0.00001, 123456.0, 1234567.0, 0.5, 100.0, 1e-10);
  printf("%.3f %.3f %.3f %.3f %.3f\n", atan2(1.0, 1.0), fmod(7.5, 2.0), round(-2.5), ceil(1.2), log10(1000.0));
  printf("%+d % d %05d %-3d| %5.1f\n", 5, 5, -42, 7, M_PI);
  printf("%d %d %u\n", INT_MAX, INT_MIN, UINT32_MAX);
  bool ok = true;
  assert(ok);
  printf("%d %.1f %ld\n", atoi("123"), atof("2.5"), 1234567L);
  printf("caf\xc3\xa9\n");
  int *p = malloc(16);
  p[0] = 41;
  p = realloc(p, 4096);
  printf("%d\n", p[0] + 1);
  free(p);
  exit(3);
  return 0;
}
