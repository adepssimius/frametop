// ft-align: finds the physical monitors from the AprilTags they show, and moves their panels onto them.
// Frames come from ft-camd's ring, head poses from OpenVR, and panels move through ft-screens' socket.
//
//   ft-align run SPEC.json            live: JSON status lines on stdout; "lock N" and "quit" on stdin
//   ft-align replay DIR SPEC.json     a capture (index.json, its PGM frames, poses.csv): prints each fit
//
// SPEC.json: {"displays": [{"panel": 103, "first_id": 0, "width": 2560, "height": 1440, "pitch": 0.0002784}]},
// with optional "tag" and "margin" in pixels. docs/monitor-alignment.md has the rest.
#include "../hands/camd/fhring.h"
#include "solver.h"

#include <apriltag/apriltag.h>
#include <apriltag/tag36h11.h>
#include <fcntl.h>
#include <json/json.h>
#include <openvr.h>
#include <poll.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <deque>
#include <fstream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>

namespace {

constexpr double kPoseOffsetNs = 16e6;   // a frame's dequeue time, less this, best matches the head pose
constexpr double kPlaceBelowMm = 100;    // the first estimates can be far off: panels wait for this
constexpr uint64_t kFitEveryNs = 250000000;   // each display at most this often, to leave the CPU to SteamVR

uint64_t now_ns() {
    timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return uint64_t(ts.tv_sec) * 1000000000ull + uint64_t(ts.tv_nsec);
}

bool load_spec(const std::string &path, std::vector<Display> &out, std::string &err) {
    std::ifstream f(path);
    Json::Value v;
    Json::CharReaderBuilder b;
    if (!f || !Json::parseFromStream(b, f, &v, &err)) {
        err = "can't read " + path + ": " + err;
        return false;
    }
    for (const auto &d : v["displays"])
        out.push_back(make_display(d["panel"].asInt(), d["first_id"].asInt(), d["width"].asInt(), d["height"].asInt(),
                                   d["pitch"].asDouble(), d.get("tag", 0).asInt(), d.get("margin", 0).asInt()));
    if (out.empty()) err = path + " lists no displays";
    return !out.empty();
}

class Detector {
public:
    Detector() {
        family_ = tag36h11_create();
        td_ = apriltag_detector_create();
        apriltag_detector_add_family_bits(td_, family_, 1);
        td_->quad_decimate = 1.0;   // the tags are small in these lenses
        td_->nthreads = 2;
        td_->refine_edges = true;
    }
    ~Detector() {
        apriltag_detector_destroy(td_);
        tag36h11_destroy(family_);
    }
    std::map<int, TagCorners> detect(const uint8_t *img, int w, int h, int stride) {
        image_u8_t im{w, h, stride, const_cast<uint8_t *>(img)};
        zarray_t *found = apriltag_detector_detect(td_, &im);
        std::map<int, TagCorners> out;
        for (int i = 0; i < zarray_size(found); ++i) {
            apriltag_detection_t *d;
            zarray_get(found, i, &d);
            if (d->hamming > 1) continue;
            // In the order they're drawn (top left, clockwise). Checked against real frames of drawn tags.
            out[d->id] = {V2{d->p[1][0], d->p[1][1]}, V2{d->p[0][0], d->p[0][1]}, V2{d->p[3][0], d->p[3][1]},
                          V2{d->p[2][0], d->p[2][1]}};
        }
        apriltag_detections_destroy(found);
        return out;
    }

private:
    apriltag_family_t *family_;
    apriltag_detector_t *td_;
};

// Head poses by time, as they were sampled, so a frame can look up where the head was when it was taken.
class PoseLog {
public:
    explicit PoseLog(size_t keep) : keep_(keep) {}   // 0 keeps them all
    void add(uint64_t t, const double m[12]) {
        std::lock_guard<std::mutex> g(mu_);
        Sample s;
        s.t = t;
        std::copy(m, m + 12, s.m);
        log_.push_back(s);
        while (keep_ && log_.size() > keep_) log_.pop_front();
    }
    bool at(double t, double out[12]) {
        std::lock_guard<std::mutex> g(mu_);
        if (log_.size() < 2 || t < log_.front().t || t > log_.back().t) return false;
        const auto it = std::lower_bound(log_.begin(), log_.end(), t, [](const Sample &a, double v) { return a.t < v; });
        const size_t i = std::clamp(size_t(it - log_.begin()), size_t(1), log_.size() - 1);
        const Sample &a = log_[i - 1], &b = log_[i];
        const double f = b.t > a.t ? (t - a.t) / double(b.t - a.t) : 0;
        for (int k = 0; k < 12; ++k) out[k] = (1 - f) * a.m[k] + f * b.m[k];
        // Mixing two rotations shortens them a little; square them up again.
        V3 x{out[0], out[4], out[8]}, y{out[1], out[5], out[9]};
        x = unit(x);
        y = unit(y - x * dot(y, x));
        const V3 z{x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]};
        for (int r = 0; r < 3; ++r) out[r * 4] = x[r], out[r * 4 + 1] = y[r], out[r * 4 + 2] = z[r];
        return true;
    }

private:
    struct Sample {
        uint64_t t;
        double m[12];
    };
    size_t keep_;
    std::mutex mu_;
    std::deque<Sample> log_;
};

class Screens {
public:
    Screens() {
        fd_ = socket(AF_UNIX, SOCK_DGRAM, 0);
        sockaddr_un me{};
        me.sun_family = AF_UNIX;
        bind(fd_, reinterpret_cast<sockaddr *>(&me), sizeof(sa_family_t));   // autobind, for the reply
        timeval tv{1, 0};
        setsockopt(fd_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    }
    ~Screens() { close(fd_); }
    std::string ask(const std::string &cmd) {
        sockaddr_un to{};
        to.sun_family = AF_UNIX;
        const char name[] = "ft_screens";
        std::memcpy(to.sun_path + 1, name, sizeof(name) - 1);
        const socklen_t len = socklen_t(offsetof(sockaddr_un, sun_path) + 1 + sizeof(name) - 1);
        if (sendto(fd_, cmd.data(), cmd.size(), 0, reinterpret_cast<sockaddr *>(&to), len) < 0) return "error send";
        char buf[1024];
        const ssize_t n = recv(fd_, buf, sizeof buf - 1, 0);
        return n > 0 ? std::string(buf, size_t(n)) : "error no reply";
    }

private:
    int fd_;
};

struct Live {
    Display display;
    Solver solver;
    std::mutex mu;        // guards fit and have_fit, which its own thread writes and "lock" reads
    Fit fit;
    bool have_fit = false;
    std::atomic<bool> locked{false};
    explicit Live(const Display &d) : display(d), solver(d) {}
};

std::string status_json(const Live &l, double seconds) {
    std::ostringstream s;
    s.setf(std::ios::fixed);
    s.precision(2);
    s << "{\"panel\":" << l.display.panel << ",\"t\":" << seconds << ",\"locked\":" << (l.locked ? "true" : "false")
      << ",\"sightings\":" << l.solver.sightings();
    if (l.have_fit) {
        const Fit &f = l.fit;
        s << ",\"shown_mm\":" << f.shown_mm << ",\"change_mm\":" << f.change_mm << ",\"rms_px\":" << f.rms_px
          << ",\"frames\":" << f.frames << ",\"spots\":" << f.spots << ",\"solve_ms\":" << f.solve_ms << ",\"distance_m\":" << f.distance_m << ",\"range_mm\":[" << f.head_range_mm[0]
          << "," << f.head_range_mm[1] << "," << f.head_range_mm[2] << "]";
        double m[12];
        panel_matrix(f.pose, m);
        s.precision(5);
        s << ",\"matrix\":[";
        for (int i = 0; i < 12; ++i) s << (i ? "," : "") << m[i];
        s << "]";
    }
    s << "}";
    return s.str();
}

// The side cameras, by sensor: their calibration names, as XRService's log gives them (hands/track/main.cpp).
const char *side_camera(const char *sensor) {
    if (std::strstr(sensor, "4-0036")) return "slam_right";
    if (std::strstr(sensor, "4-0060")) return "slam_left";
    return nullptr;
}

int run(const std::vector<Display> &displays, const std::map<std::string, Camera> &calib) {
    const std::string path = std::string("/run/user/") + std::to_string(getuid()) + "/" + FH_RING_NAME;
    int fd = -1;
    const uint64_t give_up = now_ns() + 20000000000ull;
    struct stat st{};
    for (;;) {
        fd = open(path.c_str(), O_RDONLY);
        if (fd >= 0 && fstat(fd, &st) == 0 && size_t(st.st_size) >= sizeof(fh_ring_hdr_t)) break;
        if (fd >= 0) close(fd);
        if (now_ns() > give_up) {
            std::fprintf(stderr, "ft-align: ft-camd's ring never appeared at %s\n", path.c_str());
            return 1;
        }
        usleep(200000);
    }
    const auto *map = static_cast<const uint8_t *>(mmap(nullptr, size_t(st.st_size), PROT_READ, MAP_SHARED, fd, 0));
    if (map == MAP_FAILED) return 1;
    const auto *hdr = reinterpret_cast<const fh_ring_hdr_t *>(map);
    if (std::memcmp(hdr->magic, FH_RING_MAGIC, 8) != 0 || hdr->version != FH_RING_VERSION) {
        std::fprintf(stderr, "ft-align: %s isn't a ring this version can read\n", path.c_str());
        return 1;
    }
    struct Cam {
        int index;
        const Camera *calib;
        uint64_t last = 0;
    };
    std::vector<Cam> cams;
    for (uint32_t i = 0; i < hdr->ncams; ++i) {
        if (hdr->cams[i].flags != 0) continue;
        const char *name = side_camera(hdr->cams[i].sensor);
        const auto c = name ? calib.find(name) : calib.end();
        if (c != calib.end()) cams.push_back({int(i), &c->second});
    }
    if (cams.empty()) {
        std::fprintf(stderr, "ft-align: no side cameras in the ring\n");
        return 1;
    }

    vr::EVRInitError err = vr::VRInitError_None;
    vr::IVRSystem *sys = vr::VR_Init(&err, vr::VRApplication_Background);
    if (!sys) {
        std::fprintf(stderr, "ft-align: SteamVR: %s\n", vr::VR_GetVRInitErrorAsEnglishDescription(err));
        return 1;
    }
    PoseLog poses(2000);
    std::atomic<bool> stop{false};
    std::thread sampler([&] {
        vr::TrackedDevicePose_t p[vr::k_unMaxTrackedDeviceCount];
        while (!stop) {
            sys->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding, 0, p, vr::k_unMaxTrackedDeviceCount);
            const uint64_t t = now_ns();
            const auto &h = p[vr::k_unTrackedDeviceIndex_Hmd];
            if (h.bPoseIsValid) {
                double m[12];
                for (int r = 0; r < 3; ++r)
                    for (int c = 0; c < 4; ++c) m[r * 4 + c] = h.mDeviceToAbsoluteTracking.m[r][c];
                poses.add(t, m);
            }
            usleep(5000);
        }
    });

    std::deque<Live> live;
    for (const Display &d : displays) live.emplace_back(d);
    const uint64_t started = now_ns();
    std::mutex out_mu;
    const auto report = [&](Live &l) {
        std::lock_guard<std::mutex> g(out_mu);
        std::printf("%s\n", status_json(l, double(now_ns() - started) / 1e9).c_str());
        std::fflush(stdout);
    };

    // A thread per display. A frame can show several displays at once, and looking at one often gives the
    // side cameras a better view of its neighbour, so each fits whenever it has something new.
    std::vector<std::thread> fitters;
    for (Live &l : live)
        fitters.emplace_back([&] {
            Screens screens;
            int seen = 0;
            bool sized = false;
            while (!stop && !l.locked) {
                const uint64_t began = now_ns();
                const int sightings = l.solver.sightings();
                if (sightings == seen) {
                    usleep(20000);
                    continue;
                }
                Fit fit;
                if (l.solver.solve(fit, 100)) {
                    seen = sightings;
                    fit.solve_ms = double(now_ns() - began) / 1e6;
                    {
                        std::lock_guard<std::mutex> g(l.mu);
                        if (l.locked) break;   // locked while fitting: that one stands
                        l.fit = fit, l.have_fit = true;
                    }
                    if (fit.shown_mm < kPlaceBelowMm) {
                        if (!sized) {
                            char c[80];
                            std::snprintf(c, sizeof c, "width %d %.4f", l.display.panel, l.display.metres());
                            screens.ask(c);
                            std::snprintf(c, sizeof c, "curve %d 0", l.display.panel);
                            screens.ask(c);
                            sized = true;
                        }
                        double m[12];
                        panel_matrix(fit.pose, m);
                        std::ostringstream cmd;
                        cmd.setf(std::ios::fixed);
                        cmd.precision(5);
                        cmd << "pose " << l.display.panel;
                        for (double v : m) cmd << ' ' << v;
                        const std::string reply = screens.ask(cmd.str());
                        if (reply.compare(0, 2, "ok") != 0)
                            std::fprintf(stderr, "ft-align: panel %d: %s\n", l.display.panel, reply.c_str());
                    }
                    report(l);
                }
                const uint64_t spent = now_ns() - began;
                if (spent < kFitEveryNs) usleep(useconds_t((kFitEveryNs - spent) / 1000));
            }
        });

    Detector detector;
    std::vector<uint8_t> image;
    std::string input;
    bool done = false;
    int rc = 0;
    while (!done) {
        // Commands: lock N, quit. End of input means quit.
        pollfd pfd{0, POLLIN, 0};
        if (poll(&pfd, 1, 0) > 0) {
            char buf[256];
            const ssize_t n = read(0, buf, sizeof buf);
            if (n <= 0) {
                done = true;
            } else {
                input.append(buf, size_t(n));
                for (size_t at; (at = input.find('\n')) != std::string::npos; input.erase(0, at + 1)) {
                    const std::string line = input.substr(0, at);
                    int panel;
                    if (line == "quit") done = true;
                    else if (std::sscanf(line.c_str(), "lock %d", &panel) == 1)
                        for (Live &l : live)
                            if (l.display.panel == panel) {
                                bool ok;
                                {
                                    std::lock_guard<std::mutex> g(l.mu);
                                    ok = l.have_fit;
                                    if (ok) l.locked = true;
                                }
                                if (ok) report(l);
                            }
                }
            }
        }
        if (std::all_of(live.begin(), live.end(), [](const Live &l) { return bool(l.locked); })) break;

        // The newest frame of each side camera that hasn't been looked at.
        bool any = false;
        for (Cam &c : cams) {
            const fh_ring_cam_t &rc_cam = hdr->cams[c.index];
            const uint64_t n = __atomic_load_n(&rc_cam.latest, __ATOMIC_ACQUIRE);
            if (n == 0 || n == c.last) continue;
            const uint8_t *slot = map + rc_cam.slot_offset + (n % rc_cam.nslots) * rc_cam.slot_bytes;
            const auto *meta = reinterpret_cast<const fh_ring_slot_t *>(slot);
            const uint64_t seq = __atomic_load_n(&meta->seq, __ATOMIC_ACQUIRE);
            if (seq != 2 * n + 2) continue;
            image.resize(size_t(rc_cam.stride) * rc_cam.height);
            std::memcpy(image.data(), slot + sizeof(fh_ring_slot_t), image.size());
            const uint64_t dqbuf = meta->dqbuf_ns;
            if (__atomic_load_n(&meta->seq, __ATOMIC_ACQUIRE) != seq) continue;
            c.last = n;
            any = true;
            double head[12];
            bool have = false;
            for (int tries = 0; tries < 8 && !have; ++tries) {
                have = poses.at(double(dqbuf) - kPoseOffsetNs, head);
                if (!have) usleep(5000);
            }
            if (!have) continue;
            const auto seen = detector.detect(image.data(), int(rc_cam.width), int(rc_cam.height), int(rc_cam.stride));
            if (seen.empty()) continue;
            for (Live &l : live)
                if (!l.locked) l.solver.add(*c.calib, head, seen);
        }
        if (!any) usleep(5000);
    }
    stop = true;
    for (std::thread &t : fitters) t.join();
    sampler.join();
    vr::VR_Shutdown();
    return rc;
}

bool read_pgm(const std::string &path, std::vector<uint8_t> &img, int &w, int &h) {
    std::ifstream f(path, std::ios::binary);
    std::string magic;
    int maxv;
    if (!(f >> magic >> w >> h >> maxv) || magic != "P5") return false;
    f.get();
    img.resize(size_t(w) * h);
    f.read(reinterpret_cast<char *>(img.data()), std::streamsize(img.size()));
    return bool(f);
}

// A capture from align/prototype's tools, run through the same detector and solver as live.
int replay(const std::string &dir, const std::vector<Display> &displays, const std::map<std::string, Camera> &calib) {
    Json::Value idx;
    {
        std::ifstream f(dir + "/index.json");
        Json::CharReaderBuilder b;
        std::string err;
        if (!f || !Json::parseFromStream(b, f, &idx, &err)) {
            std::fprintf(stderr, "ft-align: %s/index.json: %s\n", dir.c_str(), err.c_str());
            return 1;
        }
    }
    PoseLog poses(0);
    {
        std::ifstream f(dir + "/poses.csv");
        std::string line;
        while (std::getline(f, line)) {
            std::stringstream s(line);
            std::string cell;
            double m[12];
            uint64_t t = 0;
            int k = 0;
            while (k < 14 && std::getline(s, cell, ',')) {
                if (k == 0) t = std::strtoull(cell.c_str(), nullptr, 10);
                else if (k >= 2) m[k - 2] = std::atof(cell.c_str());
                ++k;
            }
            if (k == 14) poses.add(t, m);
        }
    }
    std::vector<Json::Value> frames;
    for (const auto &f : idx["frames"])
        if (f["cam"].asInt() < 2) frames.push_back(f);
    std::sort(frames.begin(), frames.end(),
              [](const Json::Value &a, const Json::Value &b) { return a["dqbuf_ns"].asUInt64() < b["dqbuf_ns"].asUInt64(); });
    const Camera &right = calib.at("slam_right"), &left = calib.at("slam_left");
    std::deque<Live> live;
    for (const Display &d : displays) live.emplace_back(d);
    Detector detector;
    std::vector<uint8_t> image;
    double fit_ms = 0;
    int fits = 0;
    int w, h, with_tags = 0, every = std::max(1, int(frames.size()) / 8), count = 0;
    const uint64_t t0 = now_ns();
    for (const Json::Value &f : frames) {
        ++count;
        double head[12];
        if (!read_pgm(dir + "/" + f["file"].asString(), image, w, h)) continue;
        if (!poses.at(double(f["dqbuf_ns"].asUInt64()) - kPoseOffsetNs, head)) continue;
        const auto seen = detector.detect(image.data(), w, h, w);
        if (!seen.empty()) ++with_tags;
        for (Live &l : live) {
            l.solver.add(f["cam"].asInt() == 0 ? right : left, head, seen);
            const uint64_t began = now_ns();
            if (count % every == 0 && l.solver.solve(l.fit, 100)) {
                fit_ms += double(now_ns() - began) / 1e6, ++fits;
                l.have_fit = true;
                std::printf("%s\n", status_json(l, double(count)).c_str());
            }
        }
    }
    const double seconds = double(now_ns() - t0) / 1e9;
    std::fprintf(stderr, "%d frames, %d with tags, %.1f ms a frame, %.1f ms a fit\n", count, with_tags,
                 (seconds * 1000 - fit_ms) / std::max(count, 1), fit_ms / std::max(fits, 1));
    for (Live &l : live)
        if (l.solver.solve(l.fit, 400)) {
            l.have_fit = true;
            std::printf("FINAL %s\n", status_json(l, double(count)).c_str());
        }
    return 0;
}

}  // namespace

int main(int argc, char **argv) {
    const std::string mode = argc > 1 ? argv[1] : "";
    std::vector<Display> displays;
    std::string err;
    std::map<std::string, Camera> calib;
    if (mode == "detect" && argc == 3) {   // one image's tags, to check the detector
        std::vector<uint8_t> img;
        int w, h;
        if (!read_pgm(argv[2], img, w, h)) return 1;
        Detector det;
        for (const auto &[id, c] : det.detect(img.data(), w, h, w))
            std::printf("%d %.1f %.1f  %.1f %.1f  %.1f %.1f  %.1f %.1f\n", id, c[0][0], c[0][1], c[1][0], c[1][1], c[2][0], c[2][1], c[3][0], c[3][1]);
        return 0;
    }
    if (!((mode == "run" && argc == 3) || (mode == "replay" && argc == 4))) {
        std::fprintf(stderr, "usage: ft-align run SPEC.json | ft-align replay DIR SPEC.json\n");
        return 2;
    }
    if (!load_spec(argv[argc - 1], displays, err) || !load_calibration(calib, err)) {
        std::fprintf(stderr, "ft-align: %s\n", err.c_str());
        return 1;
    }
    return mode == "run" ? run(displays, calib) : replay(argv[2], displays, calib);
}
