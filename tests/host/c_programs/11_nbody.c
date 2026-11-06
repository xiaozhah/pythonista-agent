#include <stdio.h>
#include <stdlib.h>
#include <math.h>
typedef struct { double x, y, z, vx, vy, vz, m; } Body;
static void advance(Body *b, int n, double dt) {
  for (int i = 0; i < n; i++)
    for (int j = i + 1; j < n; j++) {
      double dx = b[i].x - b[j].x, dy = b[i].y - b[j].y, dz = b[i].z - b[j].z;
      double d2 = dx * dx + dy * dy + dz * dz, mag = dt / (d2 * sqrt(d2));
      b[i].vx -= dx * b[j].m * mag; b[i].vy -= dy * b[j].m * mag; b[i].vz -= dz * b[j].m * mag;
      b[j].vx += dx * b[i].m * mag; b[j].vy += dy * b[i].m * mag; b[j].vz += dz * b[i].m * mag;
    }
  for (int i = 0; i < n; i++) { b[i].x += dt * b[i].vx; b[i].y += dt * b[i].vy; b[i].z += dt * b[i].vz; }
}
static double energy(Body *b, int n) {
  double e = 0;
  for (int i = 0; i < n; i++) {
    e += 0.5 * b[i].m * (b[i].vx * b[i].vx + b[i].vy * b[i].vy + b[i].vz * b[i].vz);
    for (int j = i + 1; j < n; j++) {
      double dx = b[i].x - b[j].x, dy = b[i].y - b[j].y, dz = b[i].z - b[j].z;
      e -= b[i].m * b[j].m / sqrt(dx * dx + dy * dy + dz * dz);
    }
  }
  return e;
}
int main(void) {
  int n = 5;
  Body *b = malloc(n * sizeof(Body));
  for (int i = 0; i < n; i++) {
    b[i].x = i; b[i].y = (i * 7) % 3; b[i].z = (i * 5) % 4 * 0.5;
    b[i].vx = 0.01 * i; b[i].vy = -0.02 * (i % 2); b[i].vz = 0; b[i].m = 1.0 + i * 0.1;
  }
  printf("energy before: %.9f\n", energy(b, n));
  for (int s = 0; s < 20000; s++) advance(b, n, 0.001);
  printf("energy after:  %.9f\n", energy(b, n));
  free(b);
  return 0;
}
