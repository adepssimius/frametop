// Finds where a physical monitor is in the room, from the corners of the AprilTags it shows, seen by
// the headset's cameras as the head moves. No VR and no cameras here, so tests can run it anywhere.
// docs/monitor-alignment.md has the method and what the tests found.
#pragma once

#include "../hands/track/calib.h"

#include <array>
#include <atomic>
#include <deque>
#include <map>
#include <mutex>
#include <vector>

using TagCorners = std::array<V2, 4>;    // top left, top right, bottom right, bottom left, as drawn

// A display: its panel in ft-screens, the tags it shows, and its size. Model coordinates are metres
// from the screen's centre at the size given: +x right, +y down, z 0. Tags are placed as fractions of the
// screen, so its resolution and scaling don't matter. tag and margin are fractions of its height.
struct Display {
    int panel = 0;
    int first_id = 0;
    double width_m = 0, height_m = 0;
    bool size_known = true;      // false: width_m is a guess, and the fit measures the real size
    std::map<int, std::array<V3, 4>> tags;
};

constexpr double kTagFraction = 0.43, kMarginFraction = 0.056;
Display make_display(int panel, int first_id, double width_m, double height_m, bool size_known = true,
                     double tag = kTagFraction, double margin = kMarginFraction);

struct Rigid {
    double R[3][3] = {{1, 0, 0}, {0, 1, 0}, {0, 0, 1}};   // screen axes (columns) in the room
    V3 t{};                                               // the screen's centre in the room
};

// 12 numbers, row by row, for ft-screens' pose command: a panel's +y is up and its +z faces the viewer.
void panel_matrix(const Rigid &r, double m[12]);

struct Fit {
    Rigid pose;
    double width_m = 0, height_m = 0;   // the screen's size: as given, or as measured
    double spread_mm = 0;    // how far the worst screen corner could be off, from the fit alone
    double shown_mm = 0;     // the figure to show: spread_mm scaled by real captures, more if the head hardly moved
    double change_mm = 0;    // how far the worst corner moved since the last fit
    double rms_px = 0;       // the fit's residual, about in pixels
    int frames = 0;          // frames the fit used
    int spots = 0;           // how many different places the head saw it from
    V3 head_range_mm{};      // how far the head travelled along the screen's x, y and normal
    double distance_m = 0;   // the head's mean distance from the screen
    double solve_ms = 0;     // how long the fit took (set by the caller)
};

class Solver {
public:
    explicit Solver(const Display &d) : display_(d) {}

    // One camera frame: the head's pose in the room (3 rows of 4) and the tags seen, by ID. Tags from
    // other displays are ignored, so every display can be given every frame. One thread can add while
    // another solves; only one thread may solve.
    void add(const Camera &cam, const double head[12], const std::map<int, TagCorners> &seen);

    // Fits from up to max_frames frames, evenly spread over what's been seen. False without enough yet.
    bool solve(Fit &out, int max_frames = 160);

    int sightings() const { return sightings_; }   // tags seen so far: unchanged means nothing new to fit

private:
    struct Obs {
        V3 origin, head;
        std::vector<V3> rays, model;
    };
    Display display_;
    std::mutex mu_;           // guards obs_ while add() grows it; a deque keeps what solve() is reading in place
    std::deque<Obs> obs_;
    double q_[7] = {0, 0, 0, 0, 0, 0, 1};   // rotation vector, centre, and scale of the size given
    bool have_q_ = false;
    bool have_corners_ = false;
    V3 corners_[4];
    std::atomic<int> sightings_{0};

    bool seed(const std::vector<const Obs *> &frames, double q[7]) const;
};

// The joined curved monitor: two equal panels as arcs of one cylinder, tangent at the seam. radius 0
// keeps the turn the two panels already have between them. Each panel's pose and the radius come back.
struct Join {
    double left[12], right[12];
    double radius = 0, turn_deg = 0, sag_mm = 0;
};
bool join_panels(const double left[12], const double right[12], double width, double radius, Join &out);
