"""VTracer subprocess worker. Ported from Artboard AI's subprocess isolation pattern."""
import sys
from pathlib import Path

def main():
    if len(sys.argv)!=4:raise SystemExit(2)
    import vtracer
    src,dst,colors=sys.argv[1:]
    vtracer.convert_image_to_svg_py(str(Path(src)),str(Path(dst)),
                                    colormode='color',hierarchical='stacked',mode='spline',
                                    filter_speckle=4,color_precision=6,
                                    layer_difference=16,corner_threshold=60,
                                    length_threshold=4,max_iterations=10,
                                    splice_threshold=45,path_precision=3)
if __name__=='__main__':main()
