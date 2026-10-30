"""Artboard AI's SSIM visual-difference method, adapted to intrinsic AssetsX asset dimensions.

Derived from nafiulnahid17/artboardai-engine/artboard_engine/fidelity.py
commit file SHA 386f908c. This is a preview-fidelity metric, NOT semantic or print proof.
"""
from io import BytesIO
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
import cairosvg


def compare_preview(reference:Image.Image,svg:bytes,output_dir:Path)->dict:
    w,h=reference.size
    scale=min(1,768/max(w,h))
    w,h=max(2,round(w*scale)),max(2,round(h*scale))
    actual=Image.open(BytesIO(cairosvg.svg2png(bytestring=svg,output_width=w,output_height=h))).convert('RGBA')
    expected=reference.convert('RGBA').resize((w,h),Image.Resampling.LANCZOS)
    def white(im):
        p=Image.new('RGBA',(w,h),'white');p.alpha_composite(im)
        return np.asarray(p.convert('RGB'))
    a=white(actual);b=white(expected)
    x=cv2.cvtColor(a,cv2.COLOR_RGB2GRAY).astype('float64')
    y=cv2.cvtColor(b,cv2.COLOR_RGB2GRAY).astype('float64')
    mx=cv2.GaussianBlur(x,(11,11),1.5);my=cv2.GaussianBlur(y,(11,11),1.5)
    vx=cv2.GaussianBlur(x*x,(11,11),1.5)-mx*mx
    vy=cv2.GaussianBlur(y*y,(11,11),1.5)-my*my
    covariance=cv2.GaussianBlur(x*y,(11,11),1.5)-mx*my
    c1,c2=(.01*255)**2,(.03*255)**2
    ssim=((2*mx*my+c1)*(2*covariance+c2))/((mx*mx+my*my+c1)*(vx+vy+c2))
    diff=np.abs(a.astype('float64')-b.astype('float64')).mean(axis=2)
    heat=np.zeros((h,w,3),dtype=np.uint8)
    heat[:,:,0]=np.minimum(diff*5,255).astype('uint8')
    heat[:,:,1]=np.maximum(255-diff*5,0).astype('uint8')
    Image.fromarray(heat,'RGB').save(output_dir/'vector_difference_heatmap.png')
    canvas=Image.new('RGB',(w*2,h),'white')
    canvas.paste(Image.fromarray(b,'RGB'),(0,0))
    canvas.paste(Image.fromarray(a,'RGB'),(w,0))
    canvas.save(output_dir/'modified_vs_vector_preview.png')
    score=float(np.clip(ssim.mean(),-1,1))
    return {'grayscale_ssim':round(score,5),'mean_rgb_difference_0_255':round(float(diff.mean()),3),
            'review_flag':score<.95,'comparison_resolution_px':[w,h],
            'heatmap':'vector_difference_heatmap.png','comparison':'modified_vs_vector_preview.png',
            'requires_operator_confirmation':True,
            'note':'SSIM comparison against modified raster preview; does not establish font, trademark, geometry, or CMYK print correctness.'}
