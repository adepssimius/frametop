#include "pointer-map.c"
#include <stdio.h>
#include <math.h>

static int close_to(double got, double want) {
    return fabs(got - want) < 0.01;
}

int main(void) {
    double widths[3] = {1920, 1920, 1920};
    double heights[3] = {1080, 1080, 1080};
    int present[3] = {1, 1, 1};
    double x, y;

    x = 960; y = 540;
    ft_pointer_for_row(1, widths, heights, present, 0, &x, &y);
    if (!close_to(x, 960) || !close_to(y, 540)) return 1;

    x = 960; y = 540;
    ft_pointer_for_row(2, widths, heights, present, 0, &x, &y);
    if (!close_to(x, 480) || !close_to(y, 540)) return 2;

    x = 960; y = 540;
    ft_pointer_for_row(2, widths, heights, present, 1, &x, &y);
    if (!close_to(x, 1440) || !close_to(y, 540)) return 3;

    x = 100; y = 10;
    ft_pointer_for_row(3, widths, heights, present, 2, &x, &y);
    if (!close_to(x, (3840 + 100) * 1920 / 5760.0) || !close_to(y, 10)) return 4;

    present[1] = 0;
    x = 100; y = 10;
    ft_pointer_for_row(3, widths, heights, present, 2, &x, &y);
    if (!close_to(x, (1920 + 100) * 1920 / 3840.0)) return 5;

    heights[2] = 540;
    x = 0; y = 270;
    present[1] = 1;
    ft_pointer_for_row(3, widths, heights, present, 2, &x, &y);
    if (!close_to(y, 270 * 540 / 1080.0)) return 6;

    printf("pointer-map: ok\n");
    return 0;
}
