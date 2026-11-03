// See hud.h. Text as on the screens' keyboard (screens/keyboard.cpp): Noto Sans through stb_truetype, and textures
// through screens/overlaytex, because SetOverlayRaw runs out after 200 calls.
#include "hud.h"

#include "../screens/overlaytex.h"

#define STB_TRUETYPE_IMPLEMENTATION
#include "stb_truetype.h"

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <cmath>
#include <cstddef>
#include <cstdio>
#include <cstring>

namespace {

constexpr int kW = 512, kH = 256;
constexpr double kWidthOfHeight = 0.72;   // of the screen's height: the gap between the tags is about 0.74
constexpr double kInFront = 0.004;        // metres in front of the panel
struct Box { int x0, y0, x1, y1; };
constexpr Box kLock{24, 164, 246, 240}, kStop{266, 164, 488, 240};

std::vector<unsigned char> g_font_data;
stbtt_fontinfo g_font;
bool g_font_tried = false, g_font_ok = false;

void load_font() {
    if (g_font_tried) return;
    g_font_tried = true;
    std::string path;
    if (FILE *p = popen("fc-match -f '%{file}' 'Noto Sans' 2>/dev/null", "r")) {
        char buf[512];
        if (std::fgets(buf, sizeof buf, p)) path = buf;
        pclose(p);
    }
    if (path.empty()) path = "/usr/share/fonts/google-noto-vf/NotoSans[wght].ttf";
    if (FILE *f = std::fopen(path.c_str(), "rb")) {
        std::fseek(f, 0, SEEK_END);
        g_font_data.resize(size_t(std::ftell(f)));
        std::fseek(f, 0, SEEK_SET);
        g_font_ok = std::fread(g_font_data.data(), 1, g_font_data.size(), f) == g_font_data.size() &&
                    stbtt_InitFont(&g_font, g_font_data.data(), stbtt_GetFontOffsetForIndex(g_font_data.data(), 0));
        std::fclose(f);
    }
    if (!g_font_ok) std::fprintf(stderr, "ft-align: no font (%s)\n", path.c_str());
}

void fill(std::vector<uint8_t> &px, Box b, uint8_t r, uint8_t g, uint8_t bl, uint8_t a) {
    for (int y = b.y0; y < b.y1; ++y)
        for (int x = b.x0; x < b.x1; ++x) {
            uint8_t *p = &px[(size_t(y) * kW + x) * 4];
            p[0] = r, p[1] = g, p[2] = bl, p[3] = a;
        }
}

// ASCII text centred on (cx, cy), shrunk if it wouldn't fit the panel.
void text(std::vector<uint8_t> &px, const std::string &s, int size, int cx, int cy, const uint8_t colour[3]) {
    if (!g_font_ok || s.empty()) return;
    float scale = stbtt_ScaleForPixelHeight(&g_font, float(size));
    const auto width_at = [&](float k) {
        int w = 0, adv, lsb;
        for (unsigned char c : s) stbtt_GetCodepointHMetrics(&g_font, c, &adv, &lsb), w += int(std::lround(adv * k));
        return w;
    };
    if (width_at(scale) > kW - 24) scale *= float(kW - 24) / float(width_at(scale));
    int ascent, descent, gap;
    stbtt_GetFontVMetrics(&g_font, &ascent, &descent, &gap);
    int x = cx - width_at(scale) / 2;
    const int baseline = cy + int(std::lround((ascent + descent) * scale / 2));
    for (unsigned char c : s) {
        int w, h, xoff, yoff, adv, lsb;
        unsigned char *b = stbtt_GetCodepointBitmap(&g_font, 0, scale, c, &w, &h, &xoff, &yoff);
        for (int gy = 0; b && gy < h; ++gy)
            for (int gx = 0; gx < w; ++gx) {
                const int qx = x + xoff + gx, qy = baseline + yoff + gy;
                if (qx < 0 || qy < 0 || qx >= kW || qy >= kH) continue;
                const double a = b[size_t(gy) * w + gx] / 255.0;
                uint8_t *p = &px[(size_t(qy) * kW + qx) * 4];
                for (int i = 0; i < 3; ++i) p[i] = uint8_t(std::lround(p[i] + (colour[i] - p[i]) * a));
            }
        if (b) stbtt_FreeBitmap(b, nullptr);
        stbtt_GetCodepointHMetrics(&g_font, c, &adv, &lsb);
        x += int(std::lround(adv * scale));
    }
}

int under(double x, double y) {
    const auto in = [&](Box b) { return x >= b.x0 && x < b.x1 && y >= b.y0 && y < b.y1; };
    return in(kLock) ? Hud::Lock : in(kStop) ? Hud::Stop : Hud::None;
}

// The pointer helper reads SteamVR's list of panels only every 20 s, so it's told at once, as ft-screens does.
void announce(const std::string &key) {
    const int fd = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    if (fd < 0) return;
    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    const char name[] = "ft_pointer_helper";
    std::memcpy(addr.sun_path + 1, name, sizeof name - 1);
    const std::string msg = "overlay " + key;
    sendto(fd, msg.data(), msg.size(), MSG_DONTWAIT, reinterpret_cast<sockaddr *>(&addr),
           socklen_t(offsetof(sockaddr_un, sun_path) + 1 + sizeof name - 1));
    close(fd);
}

}  // namespace

Hud::Hud(int panel) : px_(size_t(kW) * kH * 4) {
    load_font();
    const std::string key = "frametop.align." + std::to_string(panel);
    if (vr::VROverlay()->CreateOverlay(key.c_str(), "Frametop monitor alignment", &overlay_) != vr::VROverlayError_None) {
        std::fprintf(stderr, "ft-align: no panel for %d\n", panel);
        overlay_ = vr::k_ulOverlayHandleInvalid;
        return;
    }
    vr::VROverlay()->SetOverlayInputMethod(overlay_, vr::VROverlayInputMethod_Mouse);
    vr::HmdVector2_t scale{{float(kW), float(kH)}};
    vr::VROverlay()->SetOverlayMouseScale(overlay_, &scale);
    vr::VROverlay()->SetOverlaySortOrder(overlay_, 15);   // over the screens and their controls, as the keyboard is
    vr::VROverlay()->SetOverlayFlag(overlay_, vr::VROverlayFlags_MakeOverlaysInteractiveIfVisible, true);
    announce(key);
}

Hud::~Hud() {
    if (overlay_ == vr::k_ulOverlayHandleInvalid) return;
    overlaytex::Forget(overlay_);
    vr::VROverlay()->DestroyOverlay(overlay_);
}

void Hud::set_text(bool good, const std::string &figure, const std::string &hint) {
    if (have_text_ && good == good_ && figure == figure_ && hint == hint_) return;
    good_ = good, figure_ = figure, hint_ = hint, have_text_ = true;
    dirty_ = true;
}

void Hud::draw() {
    static const uint8_t white[3] = {235, 235, 235}, soft[3] = {190, 195, 200}, green[3] = {120, 225, 140};
    fill(px_, {0, 0, kW, kH}, 22, 24, 28, 240);
    text(px_, figure_, 60, kW / 2, 48, good_ ? green : white);
    text(px_, hint_, 30, kW / 2, 118, soft);
    const auto button = [&](Box b, int which, const char *label) {
        const uint8_t v = hover_ == which ? 92 : 58;
        fill(px_, b, v, v, uint8_t(v + 6), 255);
        text(px_, label, 38, (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2, white);
    };
    button(kLock, Lock, "Lock");
    button(kStop, Stop, "Stop");
    overlaytex::Set(overlay_, px_.data(), kW, kH);
    dirty_ = false;
}

void Hud::place(const Rigid &pose, double height_m) {
    if (overlay_ == vr::k_ulOverlayHandleInvalid || !have_text_) return;
    double m[12];
    panel_matrix(pose, m);
    vr::HmdMatrix34_t t;
    for (int r = 0; r < 3; ++r)
        for (int c = 0; c < 4; ++c) t.m[r][c] = float(m[r * 4 + c] + (c == 3 ? m[r * 4 + 2] * kInFront : 0));
    vr::VROverlay()->SetOverlayTransformAbsolute(overlay_, vr::TrackingUniverseStanding, &t);
    vr::VROverlay()->SetOverlayWidthInMeters(overlay_, float(height_m * kWidthOfHeight));
    if (dirty_) draw();
    if (!shown_) vr::VROverlay()->ShowOverlay(overlay_), shown_ = true;
}

void Hud::hide() {
    if (overlay_ == vr::k_ulOverlayHandleInvalid || !shown_) return;
    vr::VROverlay()->HideOverlay(overlay_);
    shown_ = false;
}

Hud::Click Hud::poll() {
    Click click = None;
    if (overlay_ == vr::k_ulOverlayHandleInvalid) return click;
    vr::VREvent_t ev;
    while (vr::VROverlay()->PollNextOverlayEvent(overlay_, &ev, sizeof ev)) {
        const double x = ev.data.mouse.x, y = kH - ev.data.mouse.y;   // OpenVR's mouse origin is bottom left
        if (ev.eventType == vr::VREvent_MouseMove) {
            const int now = under(x, y);
            if (now != hover_) hover_ = now, dirty_ = true;
        } else if (ev.eventType == vr::VREvent_MouseButtonDown && ev.data.mouse.button == vr::VRMouseButton_Left) {
            click = Click(under(x, y));
        }
    }
    return click;
}
