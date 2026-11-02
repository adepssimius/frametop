import cv2,sys
import numpy as np
W,H=2560,1440; S=160
def grid(col,bg,out):
    im=np.zeros((H,W,4),np.uint8); im[...]=bg
    for x in range(0,W+1,S):
        cv2.line(im,(min(x,W-1),0),(min(x,W-1),H-1),col,2 if x%(S*4) else 5)
    for y in range(0,H+1,S):
        cv2.line(im,(0,min(y,H-1)),(W-1,min(y,H-1)),col,2 if y%(S*4) else 5)
    cv2.rectangle(im,(0,0),(W-1,H-1),col,10)
    cv2.line(im,(W//2-120,H//2),(W//2+120,H//2),col,9); cv2.line(im,(W//2,H//2-120),(W//2,H//2+120),col,9)
    cv2.imwrite(out,im)
grid((255,0,255,255),(0,0,0,0),sys.argv[1])
grid((0,255,0,255),(0,0,0,255),sys.argv[2])
