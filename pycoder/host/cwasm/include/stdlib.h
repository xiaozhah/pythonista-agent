#ifndef _STDLIB_H
#define _STDLIB_H
#include <stddef.h>
#define RAND_MAX 2147483647
#define EXIT_SUCCESS 0
#define EXIT_FAILURE 1
void *malloc(size_t n);
void *calloc(size_t n, size_t m);
void *realloc(void *p, size_t n);
void free(void *p);
int abs(int x);
int atoi(const char *s);
double atof(const char *s);
int rand(void);
void srand(unsigned int seed);
void exit(int code);
void abort(void);
#endif
