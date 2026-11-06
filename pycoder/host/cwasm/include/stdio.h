#ifndef _STDIO_H
#define _STDIO_H
#include <stddef.h>
int printf(const char *fmt, ...);
int sprintf(char *buf, const char *fmt, ...);
int snprintf(char *buf, size_t n, const char *fmt, ...);
int puts(const char *s);
int putchar(int c);
#endif
