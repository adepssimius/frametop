#include "pointer-map.h"

void ft_pointer_for_row(int count, const double *widths, const double *heights,
                        const int *present, int index, double *x, double *y) {
    if (!x || !y || !widths || !heights || index < 0 || index >= count)
        return;
    double origin = 0, total = 0, mine_w = 0, mine_h = 0, max_h = 0;
    int n = 0;
    for (int i = 0; i < count; ++i) {
        if (present && !present[i])
            continue;
        double w = widths[i], h = heights[i];
        if (w <= 0 || h <= 0)
            continue;
        if (i < index)
            origin += w;
        if (i == index) {
            mine_w = w;
            mine_h = h;
        }
        total += w;
        if (h > max_h)
            max_h = h;
        n++;
    }
    if (n < 2 || mine_w <= 0 || total <= 0)
        return;
    *x = (origin + *x) * mine_w / total;
    if (mine_h > 0 && max_h > mine_h)
        *y = *y * mine_h / max_h;
}
