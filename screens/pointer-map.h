#ifndef FT_POINTER_MAP_H
#define FT_POINTER_MAP_H
// Hyprland's warpAbsolute maps a 0-1 pointer across the bounding box of
// every monitor (PointerManager::warpAbsolute, v0.56). Aquamarine sends
// that fraction of the one surface the laser hit. On a row of N equal
// screens the cursor lands at N times the local x, which on the right-hand
// screen is a long way left of the laser. The value written back here is
// the surface coordinate whose fraction lands on this screen's global x.
void ft_pointer_for_row(int count, const double *widths, const double *heights,
                        const int *present, int index, double *x, double *y);
#endif
