"""The live monitor-alignment solver: rays from tag corners, a fixed-size rigid fit, and an error estimate."""
import importlib.util
import json
import os

import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation as Rot

HERE = os.path.dirname(os.path.abspath(__file__))
OFF_NS = 16e6       # head pose time relative to the frame's dequeue time, from the second test
PX = 318.0          # rough focal length, so residuals read as pixels
INFLATE = 1.0       # frames aren't independent; set from replay.py
FLOOR_MM = 0.0      # systematic error the fit can't see; set from replay.py


def load_calib():
    os.environ['FRAME_JOB_DEVICE_ROOT'] = HERE + '/root'
    sp = importlib.util.spec_from_file_location('calib', HERE + '/calib.py')
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m.load()


NAMES = {0: 'slam_right', 1: 'slam_left'}


def make_detector():
    p = cv2.aruco.DetectorParameters()
    p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    p.cornerRefinementWinSize = 3
    return cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11), p)


class Poses:
    """Head poses by CLOCK_MONOTONIC time, from ft-poselog's CSV."""

    def __init__(self):
        self.t, self.m = [], []

    def add_rows(self, rows):
        for r in rows:
            self.t.append(r[0])
            self.m.append(r[2:])

    def at(self, t):
        if len(self.t) < 2 or t > self.t[-1] or t < self.t[0]:
            return None
        i = int(np.clip(np.searchsorted(self.t, t), 1, len(self.t) - 1))
        a = (t - self.t[i - 1]) / (self.t[i] - self.t[i - 1])
        T = np.eye(4)
        T[:3, :4] = ((1 - a) * self.m[i - 1] + a * self.m[i]).reshape(3, 4)
        U, _, Vt = np.linalg.svd(T[:3, :3])
        T[:3, :3] = U @ Vt
        return T


class Solver:
    def __init__(self, cal, marker, pitch, width=2560, height=1440):
        self.cal, self.pitch = cal, pitch
        self.W, self.H = width, height
        self.tag = {int(k): np.array([[x - width / 2, y - height / 2, 0.] for x, y in v])
                    for k, v in marker['corners'].items()}
        self.obs = []
        self.q = None
        self.corners_prev = None
        self.CORN = np.array([[-width / 2, -height / 2, 0], [width / 2, -height / 2, 0],
                              [width / 2, height / 2, 0], [-width / 2, height / 2, 0]], float)

    def add(self, cam, head, tags):
        tags = {i: uv for i, uv in tags.items() if i in self.tag}
        if not tags:
            return
        c = self.cal[NAMES[cam]]
        uv = np.vstack([tags[i] for i in tags])
        self.obs.append(dict(cam=cam, head=head, uv=uv, m=np.vstack([self.tag[i] for i in tags]),
                             o=head[:3, :3] @ c.origin + head[:3, 3], d=c.rays(uv) @ head[:3, :3].T, n=len(uv)))

    def _seed(self):
        best = max(self.obs[-60:], key=lambda x: x['n'])
        c = self.cal[NAMES[best['cam']]]
        r = c.unproject(best['uv'])
        nn = r[:, :2] / r[:, 2:3]
        ok, rv, tv = cv2.solvePnP(best['m'] * self.pitch, nn, np.eye(3), None, flags=cv2.SOLVEPNP_SQPNP)
        Rc, _ = cv2.Rodrigues(rv)
        H = best['head']
        return np.r_[Rot.from_matrix(H[:3, :3] @ c.R @ Rc).as_rotvec(), H[:3, :3] @ (c.R @ tv.ravel() + c.origin) + H[:3, 3]]

    def corners(self, q):
        return Rot.from_rotvec(q[:3]).apply(self.CORN * self.pitch) + q[3:6]

    def solve(self, max_frames=160):
        """Returns a dict with the fit and its error estimate, or None without enough to go on."""
        fr = [x for x in self.obs if x['n'] >= 4]
        if len(fr) < 3:
            return None
        if len(fr) > max_frames:
            fr = [fr[i] for i in np.linspace(0, len(fr) - 1, max_frames).astype(int)]
        O = np.vstack([np.repeat(x['o'][None], x['n'], 0) for x in fr])
        D = np.vstack([x['d'] for x in fr])
        M = np.vstack([x['m'] for x in fr]) * self.pitch

        def res(q):
            v = Rot.from_rotvec(q[:3]).apply(M) + q[3:6] - O
            v /= np.linalg.norm(v, axis=1, keepdims=True)
            return np.cross(v, D).ravel() * PX

        q0 = self.q if self.q is not None else self._seed()
        s = least_squares(res, q0, loss='soft_l1', f_scale=1.0, x_scale=.01, max_nfev=25)
        q = s.x
        r = res(q)
        keep = np.abs(r) < 3 * max(np.median(np.abs(r)) * 1.5, 0.3)
        J = s.jac
        sigma2 = float(np.mean(r[keep] ** 2)) if keep.any() else float(np.mean(r ** 2))
        try:
            cov = np.linalg.inv(J.T @ J) * sigma2
        except np.linalg.LinAlgError:
            return None
        # The spread of each screen corner that this covariance implies.
        e = 1e-5
        C0 = self.corners(q)
        sd = 0.0
        for k in range(4):
            Jc = np.zeros((3, 6))
            for a in range(6):
                dq = np.zeros(6)
                dq[a] = e
                Jc[:, a] = (self.corners(q + dq)[k] - C0[k]) / e
            sd = max(sd, np.sqrt(np.trace(Jc @ cov @ Jc.T)))
        change = 0.0 if self.corners_prev is None else float(np.max(np.linalg.norm(C0 - self.corners_prev, axis=1)))
        self.corners_prev = C0
        self.q = q
        pos = np.array([x['head'][:3, 3] for x in fr])
        Rm = Rot.from_rotvec(q[:3]).as_matrix()
        return dict(q=q, sd_mm=sd * 1000, change_mm=change * 1000, frames=len(fr), rms=float(np.sqrt(sigma2)),
                    range_mm=np.ptp(pos @ Rm, axis=0) * 1000, dist=float(np.mean(np.linalg.norm(pos - q[3:6], axis=1))))

    def overlay_matrix(self, q):
        Rm = Rot.from_rotvec(q[:3]).as_matrix()
        return np.c_[Rm[:, 0], -Rm[:, 1], -Rm[:, 2], q[3:6]]
