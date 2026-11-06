#ifndef _ASSERT_H
#define _ASSERT_H
void __assert_fail(const char *expr, int line);
#define assert(e) ((e) ? (void)0 : __assert_fail(#e, __LINE__))
#endif
