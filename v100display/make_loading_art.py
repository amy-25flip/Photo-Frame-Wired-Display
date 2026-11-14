# SPDX-License-Identifier: GPL-2.0-or-later
"""Code-drawn native-resolution startup artwork; no runtime image dependency."""
from pathlib import Path
import sys
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
import c444

def art():
    h,w=600,1024
    y,x=np.mgrid[:h,:w];glow=np.exp(-(((x-512)/290)**2+((y-240)/210)**2))
    rgb=np.stack([9+glow*13,13+glow*25,27+glow*45],axis=-1).astype(np.uint8)
    def text(s,y,scale,color,thick=1):
        font=cv2.FONT_HERSHEY_SIMPLEX;size=cv2.getTextSize(s,font,scale,thick)[0]
        cv2.putText(rgb,s,((w-size[0])//2,y),font,scale,color,thick,cv2.LINE_AA)
    rng=np.random.default_rng(100)
    for xx,yy,r in zip(rng.integers(80,945,50),rng.integers(65,440,50),rng.integers(1,3,50)):
        if abs(int(xx)-512)>130 or abs(int(yy)-230)>120:cv2.circle(rgb,(int(xx),int(yy)),int(r),(56,76,103),-1)
    # A miniature window becoming a portal, with a friendly pixel companion.
    cv2.rectangle(rgb,(401,123),(623,302),(86,216,222),2,cv2.LINE_AA)
    cv2.line(rgb,(401,153),(623,153),(86,216,222),1,cv2.LINE_AA)
    for xx in (414,425,436):cv2.circle(rgb,(xx,138),2,(86,216,222),-1)
    cv2.ellipse(rgb,(512,322),(143,22),0,0,360,(42,70,97),2,cv2.LINE_AA)
    mask=['01100000110','01110001110','01111111110','11111111111','11111111111','11001110011','11001110011','11111111111','01110101110','00111111100','00110001100']
    unit=10;ox=457;oy=178
    for row,line in enumerate(mask):
        for col,c in enumerate(line):
            if c=='1':cv2.rectangle(rgb,(ox+col*unit,oy+row*unit),(ox+(col+1)*unit-1,oy+(row+1)*unit-1),(134,229,217),-1)
    for xx,yy in ((642,174),(370,267),(659,293)):
        cv2.rectangle(rgb,(xx,yy),(xx+7,yy+7),(160,136,227),-1)
    text('P I X E L   P O R T A L',409,0.94,(226,238,246),2)
    text('A little frame. A whole new window.',449,0.55,(133,158,180))
    for i in range(5):cv2.circle(rgb,(488+i*12,493),2,(86+i*12,163+i*10,184+i*8),-1)
    text('Connecting your desktop',537,0.43,(105,137,160))
    return rgb

if __name__=='__main__':
    dest=Path(sys.argv[1]);dest.mkdir(parents=True,exist_ok=True)
    rgb=art();cv2.imwrite(str(dest/'loading.png'),cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR))
    packed=c444.encode(rgb,dither=True)
    (dest/'loading.c444').write_bytes(packed)
    preview=c444.decode_ref(packed,1024*600).reshape(600,1024)
    (dest/'loading.rgb565').write_bytes(preview.astype('<u2').tobytes())
    rgb2=np.stack([((preview>>11)&31)*255//31,((preview>>5)&63)*255//63,(preview&31)*255//31],axis=-1).astype(np.uint8)
    cv2.imwrite(str(dest/'loading-panel-preview.png'),cv2.cvtColor(rgb2,cv2.COLOR_RGB2BGR))
    print('saved native 1024x600 artwork and',len(packed),'packed bytes')
