// Logs the headset's pose in SteamVR's standing universe, with CLOCK_MONOTONIC times, as CSV:
// mono_ns,valid,m00,m01,m02,m03,m10,...,m23   Usage: ft-poselog OUT.csv SECONDS
#include <openvr.h>

#include <time.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>

static uint64_t mono_ns() {
    timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return uint64_t(ts.tv_sec) * 1000000000ull + ts.tv_nsec;
}

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    vr::EVRInitError err = vr::VRInitError_None;
    vr::IVRSystem *sys = vr::VR_Init(&err, vr::VRApplication_Background);
    if (!sys) {
        fprintf(stderr, "VR_Init: %s\n", vr::VR_GetVRInitErrorAsEnglishDescription(err));
        return 1;
    }
    FILE *f = fopen(argv[1], "w");
    if (!f) return 1;
    const uint64_t end = mono_ns() + uint64_t(atof(argv[2]) * 1e9);
    unsigned rows = 0, valid = 0;
    vr::TrackedDevicePose_t poses[vr::k_unMaxTrackedDeviceCount];
    while (mono_ns() < end) {
        sys->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding, 0, poses, vr::k_unMaxTrackedDeviceCount);
        const vr::TrackedDevicePose_t &p = poses[vr::k_unTrackedDeviceIndex_Hmd];
        const uint64_t now = mono_ns();
        fprintf(f, "%llu,%d", (unsigned long long)now, p.bPoseIsValid ? 1 : 0);
        for (int r = 0; r < 3; r++)
            for (int c = 0; c < 4; c++) fprintf(f, ",%.6f", p.mDeviceToAbsoluteTracking.m[r][c]);
        fputc('\n', f);
        rows++;
        valid += p.bPoseIsValid;
        usleep(5000);
    }
    fclose(f);
    vr::VR_Shutdown();
    printf("poses %u valid %u\n", rows, valid);
    return 0;
}
