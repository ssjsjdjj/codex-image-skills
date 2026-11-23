"""Prepare identity-bound review data. Reads images; never edits image pixels."""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image

Image.MAX_IMAGE_PIXELS=500_000_000
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source',required=True)
parser.add_argument('--candidate',required=True)
parser.add_argument('--output',required=True)
parser.add_argument('--size',nargs=2,type=int)
args=parser.parse_args()
target=Path(args.output)
if target.exists(): raise FileExistsError(target)
with Image.open(args.source) as source:
    if source.mode!='RGB': raise ValueError('This helper expects an opaque RGB source. Preserve transparency through the original SKC workflow.')
    size=args.size or [source.width*2,source.height*2]
if min(size)<=0: raise ValueError('Output dimensions must be positive.')
profile={
 'schema':2,
 'source_sha256':hashlib.file_digest(open(args.source,'rb'),'sha256').hexdigest(),
 'candidate_sha256':hashlib.file_digest(open(args.candidate,'rb'),'sha256').hexdigest(),
 'reference_size':size,'output_size':size,
 'candidate_review':{'status':'pending','notes':''},
 'ai_opacity':0,'feather_px':0,'ai_regions':[],'protected_regions':[],
 'zipper':{'enabled':False},
 'instructions':'The executing agent must inspect source/candidate/reference, locate actual material polygons and record observations. Approved status is a review record, not an automatic assessment. Do not ask the user to fill technical fields.'
}
target.write_text(json.dumps(profile,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(str(target))
