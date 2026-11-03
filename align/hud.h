// A small panel on each monitor while it's being aligned: its figure, what would help, and Lock and Stop. It sits
// in the gap between the markers, and only in VR, so the cameras never see it. Main thread only.
#pragma once

#include "solver.h"

#include <openvr.h>

#include <cstdint>
#include <string>
#include <vector>

class Hud {
public:
    enum Click { None, Lock, Stop };
    explicit Hud(int panel);
    ~Hud();
    // What it says: the figure, in green if good, and a line under it.
    void set_text(bool good, const std::string &figure, const std::string &hint);
    // Centres it on the screen, a little toward the viewer, sized from the screen's height.
    void place(const Rigid &pose, double height_m);
    void hide();
    Click poll();

private:
    void draw();
    vr::VROverlayHandle_t overlay_ = vr::k_ulOverlayHandleInvalid;
    std::vector<uint8_t> px_;
    bool good_ = false, shown_ = false, dirty_ = true, have_text_ = false;
    std::string figure_, hint_;
    int hover_ = 0;   // the Click under a pointer
};
