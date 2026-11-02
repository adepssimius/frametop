// Measures a panel's real surface: rays fired from in front of it. Usage: ft-probe KEY px py pz  xx xy xz  yx yy yz  zx zy zz  half_width
#include <openvr.h>
#include <cstdio>
#include <cstdlib>
int main(int argc, char **argv) {
    if (argc != 15) return 2;
    vr::EVRInitError err = vr::VRInitError_None;
    vr::VR_Init(&err, vr::VRApplication_Background);
    if (err != vr::VRInitError_None) { fprintf(stderr, "VR_Init %d\n", err); return 1; }
    vr::VROverlayHandle_t o = 0;
    if (vr::VROverlay()->FindOverlay(argv[1], &o) != vr::VROverlayError_None) { fprintf(stderr, "no overlay %s\n", argv[1]); return 1; }
    double v[13]; for (int i = 0; i < 13; i++) v[i] = atof(argv[2 + i]);
    double *P = v, *X = v + 3, *Z = v + 9, hw = v[12];
    for (int k = -20; k <= 20; k++) {
        double u = k / 20.0 * hw * 1.02;
        vr::VROverlayIntersectionParams_t in{}; vr::VROverlayIntersectionResults_t out{};
        in.eOrigin = vr::TrackingUniverseStanding;
        for (int i = 0; i < 3; i++) {
            in.vSource.v[i] = float(P[i] + X[i] * u + Z[i] * 1.5);
            in.vDirection.v[i] = float(-Z[i]);
        }
        if (vr::VROverlay()->ComputeOverlayIntersection(o, &in, &out))
            printf("%+.4f hit %.5f %.5f %.5f normal %.5f %.5f %.5f uv %.4f %.4f dist %.5f\n", u, out.vPoint.v[0], out.vPoint.v[1], out.vPoint.v[2], out.vNormal.v[0], out.vNormal.v[1], out.vNormal.v[2], out.vUVs.v[0], out.vUVs.v[1], out.fDistance);
        else printf("%+.4f miss\n", u);
    }
    vr::VR_Shutdown();
    return 0;
}
