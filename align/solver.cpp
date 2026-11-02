#include "solver.h"

#include <algorithm>
#include <cmath>
#include <set>

namespace {

// The worst corner's actual error was at most about 3.7 times the fit's spread in 90% of cases, when a
// capture was replayed against a fit from all of it. Rounded up, so the figure errs high.
constexpr double kShowFactor = 4.0;
constexpr double kFocalPx = 318;   // about the side cameras' focal length: residuals read as pixels
// Frames from one spot share their errors, so they count as one view, not as evidence that adds up. Below
// this many spots (a 5 cm grid) the figure grows. A replayed still pass had a figure of 5.8 mm at a real 14 mm.
constexpr int kEnoughSpots = 12;
constexpr double kSizeGuessSpread = 0.3;   // how far a guessed size may be off (of its value), one sigma

V3 cross(V3 a, V3 b) { return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]}; }

void rotvec_to_matrix(const double v[3], double R[3][3]) {
    const double th = std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    const double a = th > 1e-12 ? std::sin(th) / th : 1, b = th > 1e-6 ? (1 - std::cos(th)) / (th * th) : 0.5;
    const double x = v[0], y = v[1], z = v[2];
    R[0][0] = 1 - b * (y * y + z * z), R[0][1] = b * x * y - a * z, R[0][2] = b * x * z + a * y;
    R[1][0] = b * x * y + a * z, R[1][1] = 1 - b * (x * x + z * z), R[1][2] = b * y * z - a * x;
    R[2][0] = b * x * z - a * y, R[2][1] = b * y * z + a * x, R[2][2] = 1 - b * (x * x + y * y);
}

void matrix_to_rotvec(const double R[3][3], double v[3]) {
    const double c = std::clamp((R[0][0] + R[1][1] + R[2][2] - 1) / 2, -1.0, 1.0);
    const double th = std::acos(c);
    if (th < 1e-9) {
        v[0] = v[1] = v[2] = 0;
    } else if (M_PI - th < 1e-6) {
        // Half a turn: the axis is the largest column of R + I.
        int k = 0;
        for (int i = 1; i < 3; ++i)
            if (R[i][i] > R[k][k]) k = i;
        V3 ax{R[0][k], R[1][k], R[2][k]};
        ax[k] += 1;
        ax = unit(ax) * th;
        v[0] = ax[0], v[1] = ax[1], v[2] = ax[2];
    } else {
        const double s = th / (2 * std::sin(th));
        v[0] = s * (R[2][1] - R[1][2]), v[1] = s * (R[0][2] - R[2][0]), v[2] = s * (R[1][0] - R[0][1]);
    }
}

V3 rotate(const double R[3][3], V3 p) {
    return {R[0][0] * p[0] + R[0][1] * p[1] + R[0][2] * p[2], R[1][0] * p[0] + R[1][1] * p[1] + R[1][2] * p[2],
            R[2][0] * p[0] + R[2][1] * p[1] + R[2][2] * p[2]};
}

// Solves A x = b for a symmetric positive definite n x n A (n up to 7). False if it isn't.
bool cholesky_solve(int n, const double A[7][7], const double b[7], double x[7]) {
    double L[7][7] = {};
    for (int i = 0; i < n; ++i)
        for (int j = 0; j <= i; ++j) {
            double s = A[i][j];
            for (int k = 0; k < j; ++k) s -= L[i][k] * L[j][k];
            if (i == j) {
                if (s <= 0) return false;
                L[i][i] = std::sqrt(s);
            } else {
                L[i][j] = s / L[j][j];
            }
        }
    double y[7];
    for (int i = 0; i < n; ++i) {
        y[i] = b[i];
        for (int k = 0; k < i; ++k) y[i] -= L[i][k] * y[k];
        y[i] /= L[i][i];
    }
    for (int i = n - 1; i >= 0; --i) {
        x[i] = y[i];
        for (int k = i + 1; k < n; ++k) x[i] -= L[k][i] * x[k];
        x[i] /= L[i][i];
    }
    return true;
}

// The unit eigenvector of a symmetric 9x9 matrix's smallest eigenvalue (Jacobi rotations).
void smallest_eigenvector(double A[9][9], double out[9]) {
    double V[9][9] = {};
    for (int i = 0; i < 9; ++i) V[i][i] = 1;
    for (int sweep = 0; sweep < 60; ++sweep) {
        double off = 0;
        for (int p = 0; p < 9; ++p)
            for (int q = p + 1; q < 9; ++q) off += A[p][q] * A[p][q];
        if (off < 1e-24) break;
        for (int p = 0; p < 9; ++p)
            for (int q = p + 1; q < 9; ++q) {
                if (std::fabs(A[p][q]) < 1e-300) continue;
                const double th = (A[q][q] - A[p][p]) / (2 * A[p][q]);
                const double t = (th >= 0 ? 1 : -1) / (std::fabs(th) + std::sqrt(th * th + 1));
                const double c = 1 / std::sqrt(t * t + 1), s = t * c;
                for (int k = 0; k < 9; ++k) {
                    const double akp = A[k][p], akq = A[k][q];
                    A[k][p] = c * akp - s * akq, A[k][q] = s * akp + c * akq;
                }
                for (int k = 0; k < 9; ++k) {
                    const double apk = A[p][k], aqk = A[q][k];
                    A[p][k] = c * apk - s * aqk, A[q][k] = s * apk + c * aqk;
                }
                for (int k = 0; k < 9; ++k) {
                    const double vkp = V[k][p], vkq = V[k][q];
                    V[k][p] = c * vkp - s * vkq, V[k][q] = s * vkp + c * vkq;
                }
            }
    }
    int best = 0;
    for (int i = 1; i < 9; ++i)
        if (A[i][i] < A[best][best]) best = i;
    for (int i = 0; i < 9; ++i) out[i] = V[i][best];
}

}  // namespace

Display make_display(int panel, int first_id, double width_m, double height_m, bool size_known, double tag, double margin) {
    Display d;
    d.panel = panel, d.first_id = first_id, d.width_m = width_m, d.height_m = height_m, d.size_known = size_known;
    const double side = tag * height_m, edge = margin * height_m;
    const double right = width_m / 2 - edge - side, bottom = height_m / 2 - edge - side;
    const double xs[4] = {-width_m / 2 + edge, right, -width_m / 2 + edge, right};
    const double ys[4] = {-height_m / 2 + edge, -height_m / 2 + edge, bottom, bottom};
    for (int i = 0; i < 4; ++i)
        d.tags[first_id + i] = {V3{xs[i], ys[i], 0}, V3{xs[i] + side, ys[i], 0}, V3{xs[i] + side, ys[i] + side, 0},
                                V3{xs[i], ys[i] + side, 0}};
    return d;
}

void panel_matrix(const Rigid &r, double m[12]) {
    // The screen's y runs down and its z into the screen; a panel's runs up and out toward you.
    for (int i = 0; i < 3; ++i) {
        m[i * 4 + 0] = r.R[i][0];
        m[i * 4 + 1] = -r.R[i][1];
        m[i * 4 + 2] = -r.R[i][2];
        m[i * 4 + 3] = r.t[i];
    }
}

void Solver::add(const Camera &cam, const double head[12], const std::map<int, TagCorners> &seen) {
    Obs o;
    const V3 r0{head[0], head[1], head[2]}, r1{head[4], head[5], head[6]}, r2{head[8], head[9], head[10]};
    const auto to_room = [&](V3 v) { return V3{dot(r0, v), dot(r1, v), dot(r2, v)}; };
    o.head = {head[3], head[7], head[11]};
    o.origin = to_room(cam.origin) + o.head;
    for (const auto &[id, corners] : seen) {
        const auto tag = display_.tags.find(id);
        if (tag == display_.tags.end()) continue;
        ++sightings_;
        for (int k = 0; k < 4; ++k) {
            o.rays.push_back(to_room(cam.ray(corners[k])));
            o.model.push_back(tag->second[k]);
        }
    }
    if (o.rays.empty()) return;
    std::lock_guard<std::mutex> g(mu_);
    obs_.push_back(std::move(o));
}

bool Solver::seed(const std::vector<const Obs *> &frames, double q[7]) const {
    // The frame showing the most corners, as a plane-to-ray homography: H = [r1 r2 (t - origin)] up to scale.
    const Obs *best = frames[0];
    for (const Obs *f : frames)
        if (f->rays.size() > best->rays.size()) best = f;
    double AtA[9][9] = {};
    for (size_t i = 0; i < best->rays.size(); ++i) {
        const V3 d = best->rays[i];
        const double x = best->model[i][0], y = best->model[i][1];
        const double row[3][9] = {{0, 0, 0, -d[2] * x, -d[2] * y, -d[2], d[1] * x, d[1] * y, d[1]},
                                  {d[2] * x, d[2] * y, d[2], 0, 0, 0, -d[0] * x, -d[0] * y, -d[0]},
                                  {-d[1] * x, -d[1] * y, -d[1], d[0] * x, d[0] * y, d[0], 0, 0, 0}};
        for (const auto &r : row)
            for (int a = 0; a < 9; ++a)
                for (int b = 0; b < 9; ++b) AtA[a][b] += r[a] * r[b];
    }
    double h[9];
    smallest_eigenvector(AtA, h);
    V3 h1{h[0], h[3], h[6]}, h2{h[1], h[4], h[7]}, h3{h[2], h[5], h[8]};
    double scale = 1 / norm(h1);
    double agree = 0;
    for (size_t i = 0; i < best->rays.size(); ++i)
        agree += dot(h1 * best->model[i][0] + h2 * best->model[i][1] + h3, best->rays[i]);
    if (agree < 0) scale = -scale;
    const V3 r1 = unit(h1 * scale);
    const V3 r2 = unit(h2 * scale - r1 * dot(h2 * scale, r1));
    const V3 r3 = cross(r1, r2);
    const double R[3][3] = {{r1[0], r2[0], r3[0]}, {r1[1], r2[1], r3[1]}, {r1[2], r2[2], r3[2]}};
    matrix_to_rotvec(R, q);
    const V3 t = h3 * scale + best->origin;
    q[3] = t[0], q[4] = t[1], q[5] = t[2], q[6] = 1;
    return std::isfinite(q[0]) && std::isfinite(q[3]);
}

bool Solver::solve(Fit &out, int max_frames) {
    std::vector<const Obs *> frames;
    {
        std::lock_guard<std::mutex> g(mu_);
        for (const Obs &o : obs_) frames.push_back(&o);
    }
    if (frames.size() < 3) return false;
    if (int(frames.size()) > max_frames) {
        std::vector<const Obs *> some;
        for (int i = 0; i < max_frames; ++i) some.push_back(frames[size_t(i * (frames.size() - 1.0) / (max_frames - 1))]);
        frames = std::move(some);
    }
    size_t n = 0;
    for (const Obs *f : frames) n += f->rays.size();

    // The size given, or a seventh parameter for it, held near the guess so a still head can't run away with it.
    const int np = display_.size_known ? 6 : 7;
    const auto residuals = [&](const double q[7], std::vector<double> &r) {
        double R[3][3];
        rotvec_to_matrix(q, R);
        const V3 t{q[3], q[4], q[5]};
        const double scale = np == 7 ? q[6] : 1;
        r.resize(n * 3 + (np == 7 ? 1 : 0));
        size_t at = 0;
        for (const Obs *f : frames)
            for (size_t i = 0; i < f->rays.size(); ++i) {
                const V3 c = cross(unit(rotate(R, f->model[i] * scale) + t - f->origin), f->rays[i]);
                r[at++] = c[0] * kFocalPx, r[at++] = c[1] * kFocalPx, r[at++] = c[2] * kFocalPx;
            }
        if (np == 7) r[at] = (scale - 1) / kSizeGuessSpread;
    };
    const auto cost = [](const std::vector<double> &r) {   // soft L1: a bad corner can't drag the fit far
        double c = 0;
        for (double v : r) c += 2 * (std::sqrt(1 + v * v) - 1);
        return c;
    };

    double q[7];
    if (have_q_) {
        std::copy(q_, q_ + 7, q);
    } else if (!seed(frames, q)) {
        return false;
    }
    std::vector<double> r, rd, trial;
    std::vector<std::array<double, 7>> J(n * 3 + (np == 7 ? 1 : 0));
    residuals(q, r);
    double c = cost(r), lambda = 1e-3;
    double JtJ[7][7];
    const auto jacobian = [&]() {
        for (int a = 0; a < np; ++a) {
            double qd[7];
            std::copy(q, q + 7, qd);
            const double step = 1e-6;
            qd[a] += step;
            residuals(qd, rd);
            for (size_t i = 0; i < r.size(); ++i) J[i][a] = (rd[i] - r[i]) / step;
        }
    };
    for (int iter = 0; iter < 25; ++iter) {
        jacobian();
        double g[7] = {};
        for (auto &row : JtJ) std::fill(row, row + 7, 0.0);
        for (size_t i = 0; i < r.size(); ++i) {
            const double w = 1 / std::sqrt(1 + r[i] * r[i]);
            for (int a = 0; a < np; ++a) {
                g[a] -= w * J[i][a] * r[i];
                for (int b = 0; b < np; ++b) JtJ[a][b] += w * J[i][a] * J[i][b];
            }
        }
        bool improved = false;
        for (int tries = 0; tries < 8 && !improved; ++tries) {
            double A[7][7], dq[7];
            std::copy(&JtJ[0][0], &JtJ[0][0] + 49, &A[0][0]);
            for (int a = 0; a < np; ++a) A[a][a] *= 1 + lambda;
            if (cholesky_solve(np, A, g, dq)) {
                double qn[7];
                std::copy(q, q + 7, qn);
                for (int a = 0; a < np; ++a) qn[a] = q[a] + dq[a];
                residuals(qn, trial);
                const double cn = cost(trial);
                if (cn < c) {
                    const double drop = c - cn;
                    std::copy(qn, qn + 7, q);
                    r = trial, c = cn, lambda = std::max(lambda / 3, 1e-9), improved = true;
                    if (drop < 1e-6 * c) iter = 25;
                    continue;
                }
            }
            lambda *= 4;
        }
        if (!improved) break;
    }
    jacobian();
    for (auto &row : JtJ) std::fill(row, row + 7, 0.0);
    for (size_t i = 0; i < r.size(); ++i) {
        const double w = 1 / std::sqrt(1 + r[i] * r[i]);
        for (int a = 0; a < np; ++a)
            for (int b = 0; b < np; ++b) JtJ[a][b] += w * J[i][a] * J[i][b];
    }

    // The residuals' size, without outliers.
    std::vector<double> mags;
    for (double v : r) mags.push_back(std::fabs(v));
    std::nth_element(mags.begin(), mags.begin() + mags.size() / 2, mags.end());
    const double limit = 3 * std::max(mags[mags.size() / 2] * 1.5, 0.3);
    double sum = 0;
    size_t kept = 0;
    for (double v : r)
        if (std::fabs(v) < limit) sum += v * v, ++kept;
    const double sigma2 = kept ? sum / kept : 1;

    // Each column of the covariance, then how far it could move each screen corner.
    double cov[7][7];
    for (int a = 0; a < np; ++a) {
        double e[7] = {}, col[7];
        e[a] = 1;
        if (!cholesky_solve(np, JtJ, e, col)) return false;
        for (int b = 0; b < np; ++b) cov[b][a] = col[b] * sigma2;
    }
    const double scale = np == 7 ? q[6] : 1;
    const double hw = display_.width_m / 2, hh = display_.height_m / 2;
    const V3 model[4] = {V3{-hw, -hh, 0}, V3{hw, -hh, 0}, V3{hw, hh, 0}, V3{-hw, hh, 0}};
    Rigid pose;
    rotvec_to_matrix(q, pose.R);
    pose.t = {q[3], q[4], q[5]};
    V3 corners[4];
    double spread = 0, change = 0;
    for (int k = 0; k < 4; ++k) {
        corners[k] = rotate(pose.R, model[k] * scale) + pose.t;
        double Jc[3][7];
        for (int a = 0; a < np; ++a) {
            double qd[7], Rd[3][3];
            std::copy(q, q + 7, qd);
            qd[a] += 1e-6;
            rotvec_to_matrix(qd, Rd);
            const V3 moved = rotate(Rd, model[k] * (np == 7 ? qd[6] : 1)) + V3{qd[3], qd[4], qd[5]};
            for (int i = 0; i < 3; ++i) Jc[i][a] = (moved[i] - corners[k][i]) / 1e-6;
        }
        double var = 0;
        for (int i = 0; i < 3; ++i)
            for (int a = 0; a < np; ++a)
                for (int b = 0; b < np; ++b) var += Jc[i][a] * cov[a][b] * Jc[i][b];
        spread = std::max(spread, std::sqrt(std::max(var, 0.0)));
        if (have_corners_) change = std::max(change, norm(corners[k] - corners_[k]));
    }
    std::copy(corners, corners + 4, corners_);
    have_corners_ = true;
    std::copy(q, q + 7, q_);
    have_q_ = true;

    out.pose = pose;
    out.width_m = display_.width_m * scale;
    out.height_m = display_.height_m * scale;
    std::set<std::array<int, 3>> spots;
    for (const Obs *f : frames)
        spots.insert({int(std::floor(f->head[0] / 0.05)), int(std::floor(f->head[1] / 0.05)), int(std::floor(f->head[2] / 0.05))});
    out.spread_mm = spread * 1000;
    out.spots = int(spots.size());
    out.shown_mm = out.spread_mm * kShowFactor * std::sqrt(std::max(1.0, double(kEnoughSpots) / out.spots));
    out.change_mm = change * 1000;
    out.rms_px = std::sqrt(sigma2);
    out.frames = int(frames.size());
    V3 lo{1e9, 1e9, 1e9}, hi{-1e9, -1e9, -1e9};
    double dist = 0;
    const V3 axes[3] = {V3{pose.R[0][0], pose.R[1][0], pose.R[2][0]}, V3{pose.R[0][1], pose.R[1][1], pose.R[2][1]},
                        V3{pose.R[0][2], pose.R[1][2], pose.R[2][2]}};
    for (const Obs *f : frames) {
        dist += norm(f->head - pose.t);
        for (int i = 0; i < 3; ++i) {
            const double v = dot(f->head, axes[i]);
            lo[i] = std::min(lo[i], v), hi[i] = std::max(hi[i], v);
        }
    }
    out.head_range_mm = (hi - lo) * 1000;
    out.distance_m = dist / frames.size();
    return true;
}
