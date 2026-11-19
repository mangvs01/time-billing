import sys; from PIL import Image
# crop.py in out y0 y1 [x0 x1]
im=Image.open(sys.argv[1]); y0,y1=int(sys.argv[3]),int(sys.argv[4]); x0,x1=(int(sys.argv[5]),int(sys.argv[6])) if len(sys.argv)>6 else (0,im.width)
im.crop((x0,y0,x1,min(y1,im.height))).save(sys.argv[2])
