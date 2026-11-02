// The solver against made-up cameras, where the true pose is known.
#include "../solver.h"

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <thread>

static int failures = 0;
#define CHECK(cond, ...)                 \
    do {                                 \
        if (!(cond)) {                   \
            std::printf("FAIL: " __VA_ARGS__); \
            std::printf("\n");           \
            ++failures;                  \
        }                                \
    } while (0)

// An ideal fisheye looking along -z of the head, with the head frame's x and an image y that runs down.
static Camera test_camera() {
    Camera c;
    c.name = "test", c.width = 1056, c.height = 1024;
    c.fx = c.fy = 318, c.cx = 528, c.cy = 512;
    c.R[0][0] = 1, c.R[1][1] = -1, c.R[2][2] = -1;   // camera x right, y down, z forward, in the head frame
    return c;
}

static void look_at(V3 eye, V3 target, double head[12]) {
    const V3 fwd = unit(target - eye);
    const V3 right = unit(V3{-fwd[2], 0, fwd[0]});
    const V3 up{right[1] * fwd[2] - right[2] * fwd[1], right[2] * fwd[0] - right[0] * fwd[2],
                right[0] * fwd[1] - right[1] * fwd[0]};
    for (int i = 0; i < 3; ++i) {
        head[i * 4 + 0] = right[i], head[i * 4 + 1] = up[i], head[i * 4 + 2] = -fwd[i], head[i * 4 + 3] = eye[i];
    }
}

static V3 room_from_screen(const Rigid &p, V3 m) {
    V3 out = p.t;
    for (int i = 0; i < 3; ++i) out[i] += p.R[i][0] * m[0] + p.R[i][1] * m[1] + p.R[i][2] * m[2];
    return out;
}

// A monitor facing +z at z = -1, with its y running down and its z into the screen.
static Rigid true_pose() {
    Rigid p;
    p.R[1][1] = -1, p.R[2][2] = -1;
    p.t = {0.1, 1.5, -1.0};
    return p;
}

static std::map<int, TagCorners> see(const Camera &cam, const double head[12], const Display &d, const Rigid &truth,
                                     std::mt19937 *rng, double noise) {
    std::normal_distribution<double> n(0, noise);
    std::map<int, TagCorners> seen;
    const V3 r0{head[0], head[4], head[8]}, r1{head[1], head[5], head[9]}, r2{head[2], head[6], head[10]};
    const V3 eye{head[3], head[7], head[11]};
    for (const auto &[id, model] : d.tags) {
        TagCorners tc;
        for (int k = 0; k < 4; ++k) {
            const V3 v = room_from_screen(truth, model[k]) - eye;
            double depth;
            V2 uv = cam.project(V3{dot(r0, v), dot(r1, v), dot(r2, v)}, &depth);
            if (rng) uv[0] += n(*rng), uv[1] += n(*rng);
            tc[k] = uv;
        }
        seen[id] = tc;
    }
    return seen;
}

static double worst_corner_mm(const Display &d, const Rigid &a, const Rigid &b) {
    const double hw = d.width_m / 2, hh = d.height_m / 2;
    double worst = 0;
    for (V3 m : {V3{-hw, -hh, 0}, V3{hw, -hh, 0}, V3{hw, hh, 0}, V3{-hw, hh, 0}})
        worst = std::max(worst, norm(room_from_screen(a, m) - room_from_screen(b, m)) * 1000);
    return worst;
}

int main() {
    const Camera cam = test_camera();
    const Display d = make_display(103, 0, 0.7127, 0.4009);
    const Rigid truth = true_pose();

    CHECK(d.tags.size() == 4, "a display has four tags");
    CHECK(d.tags.count(0) && d.tags.count(3) && !d.tags.count(4), "tags take the display's own IDs");

    {   // Exact corners from many viewpoints: the fit finds the truth.
        Solver s(d);
        Fit fit;
        CHECK(!s.solve(fit), "no fit from nothing");
        for (int i = 0; i < 30; ++i) {
            double head[12];
            const double a = i * 0.21;
            look_at(V3{0.1 + 0.3 * std::sin(a), 1.5 + 0.2 * std::cos(a), -0.2}, truth.t, head);
            s.add(cam, head, see(cam, head, d, truth, nullptr, 0));
        }
        CHECK(s.solve(fit), "fits from 30 frames");
        const double err = worst_corner_mm(d, fit.pose, truth);
        CHECK(err < 0.5, "exact corners: worst corner %.3f mm off", err);
        CHECK(fit.shown_mm < 1, "exact corners: figure %.3f mm", fit.shown_mm);
        CHECK(fit.head_range_mm[0] > 300, "the head's travel along the screen: %.0f mm", fit.head_range_mm[0]);
    }
    {   // Noisy corners with a few wild ones: the error stays small, and the figure covers it.
        std::mt19937 rng(7);
        Solver s(d);
        for (int i = 0; i < 40; ++i) {
            double head[12];
            const double a = i * 0.3;
            look_at(V3{0.1 + 0.3 * std::sin(a), 1.5 + 0.2 * std::cos(a), -0.25}, truth.t, head);
            auto seen = see(cam, head, d, truth, &rng, 0.5);
            if (i % 10 == 0) seen.begin()->second[0][0] += 40;
            s.add(cam, head, seen);
        }
        Fit fit;
        CHECK(s.solve(fit), "fits from noisy frames");
        const double err = worst_corner_mm(d, fit.pose, truth);
        CHECK(err < 6, "noisy corners: worst corner %.2f mm off", err);
        CHECK(fit.shown_mm > err * 0.5, "the figure %.2f mm should be near or above the actual %.2f mm", fit.shown_mm, err);
    }
    {   // A still head says much less: the figure must say so.
        std::mt19937 rng(9);
        Solver still(d), moving(d);
        Fit a, b;
        for (int i = 0; i < 30; ++i) {
            double head[12];
            look_at(V3{0.1, 1.5, -0.2}, truth.t, head);
            still.add(cam, head, see(cam, head, d, truth, &rng, 0.5));
            look_at(V3{0.1 + 0.3 * std::sin(i * 0.3), 1.5 + 0.2 * std::cos(i * 0.3), -0.2}, truth.t, head);
            moving.add(cam, head, see(cam, head, d, truth, &rng, 0.5));
        }
        CHECK(still.solve(a) && moving.solve(b), "fits still and moving");
        CHECK(a.shown_mm > b.shown_mm * 1.5, "still %.2f mm vs moving %.2f mm", a.shown_mm, b.shown_mm);
    }
    {   // Another display's tags are ignored, so several solvers can share every frame.
        const Display other = make_display(102, 4, 0.7127, 0.4009);
        Solver s(other);
        double head[12];
        look_at(V3{0, 1.5, 0}, truth.t, head);
        s.add(cam, head, see(cam, head, d, truth, nullptr, 0));
        CHECK(s.sightings() == 0, "another display's tags count for nothing");
    }
    {   // One thread adds frames while another fits, as live does.
        std::mt19937 rng(11);
        Solver s(d);
        std::atomic<bool> stop{false};
        std::atomic<int> fits{0};
        Fit last;
        std::thread fitter([&] {
            while (!stop) {
                Fit f;
                if (s.solve(f)) last = f, ++fits;
            }
        });
        for (int i = 0; i < 400; ++i) {
            double head[12];
            look_at(V3{0.1 + 0.3 * std::sin(i * 0.1), 1.5 + 0.2 * std::cos(i * 0.1), -0.25}, truth.t, head);
            s.add(cam, head, see(cam, head, d, truth, &rng, 0.5));
            std::this_thread::sleep_for(std::chrono::microseconds(500));
        }
        stop = true;
        fitter.join();
        CHECK(fits > 0, "fits while frames arrive");
        CHECK(worst_corner_mm(d, last.pose, truth) < 6, "fit while frames arrive: %.2f mm off", worst_corner_mm(d, last.pose, truth));
    }
    {   // Told a wrong size, with head movement, it measures the real one. The tags are where the true size puts them.
        std::mt19937 rng(13);
        const Display guess = make_display(103, 0, 0.60, 0.60 * 0.4009 / 0.7127, false);
        Solver s(guess);
        for (int i = 0; i < 60; ++i) {
            double head[12];
            look_at(V3{0.1 + 0.35 * std::sin(i * 0.3), 1.5 + 0.25 * std::cos(i * 0.3), -0.3 + 0.2 * std::sin(i * 0.11)}, truth.t, head);
            s.add(cam, head, see(cam, head, d, truth, &rng, 0.5));
        }
        Fit fit;
        CHECK(s.solve(fit), "fits with a guessed size");
        CHECK(std::fabs(fit.width_m - 0.7127) < 0.02, "measured the width as %.4f m, not 0.7127", fit.width_m);
        CHECK(std::fabs(fit.height_m - 0.4009) < 0.012, "measured the height as %.4f m, not 0.4009", fit.height_m);
    }
    if (failures) {
        std::printf("%d failed\n", failures);
        return 1;
    }
    return 0;
}
