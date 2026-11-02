"""Makes a 2560x1440 white image with four AprilTags (36h11) and writes where their corners are.
Usage: make_marker.py OUT.png OUT.json [TAG_PX]"""
import json
import sys

import cv2
import numpy as np

out_png, out_json = sys.argv[1], sys.argv[2]
tag_px = int(sys.argv[3]) if len(sys.argv) > 3 else 500
W, H = 2560, 1440
MARGIN = 80
d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
img = np.full((H, W), 255, np.uint8)
places = {0: (MARGIN, MARGIN), 1: (W - MARGIN - tag_px, MARGIN),
          2: (MARGIN, H - MARGIN - tag_px), 3: (W - MARGIN - tag_px, H - MARGIN - tag_px)}
corners = {}
for tag_id, (x, y) in places.items():
    img[y:y + tag_px, x:x + tag_px] = cv2.aruco.generateImageMarker(d, tag_id, tag_px)
    # OpenCV's corner order: top left, top right, bottom right, bottom left
    corners[tag_id] = [[x, y], [x + tag_px, y], [x + tag_px, y + tag_px], [x, y + tag_px]]
cv2.imwrite(out_png, img)
json.dump(dict(width=W, height=H, tag_px=tag_px, corners=corners), open(out_json, 'w'))
print('wrote', out_png, 'tag', tag_px, 'px')
