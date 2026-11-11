"""Conservative local edge diagnostics. Scores are risk indicators, not visual approval."""
import hashlib
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt

VERSION = '2.3.0'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def composite(image, background):
    base = Image.new('RGBA', image.size, background)
    base.alpha_composite(image.convert('RGBA'))
    return base.convert('RGB')


def features(image, width=3):
    arr = np.asarray(image.convert('RGBA'))
    a = arr[:, :, 3]
    binary = (a > 127).astype(np.uint8)
    distance = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    core = (a >= 250) & (distance > width*2+2)
    if not core.any():
        return None
    _, nearest = distance_transform_edt(~core, return_indices=True)
    inside = arr[nearest[0], nearest[1], :3].astype(np.float32)
    rgb = arr[:, :, :3].astype(np.float32)
    delta = (inside-rgb) @ np.array([.2126, .7152, .0722])
    color_distance = np.max(np.abs(inside-rgb), axis=2)
    edge = (a > 24) & (distance <= width) & (a < 255)
    # Include opaque boundary rims without treating every dark pixel as contamination.
    edge |= (a >= 255) & (distance <= max(1, width/2))
    suspect = edge & (np.abs(delta) > 22) & (color_distance > 28)
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    thin = cv2.dilate(((binary > 0) & (opened == 0)).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    return dict(arr=arr, alpha=a, distance=distance, core=core, nearest_rgb=inside,
                delta=delta, edge=edge, suspect=suspect, thin=thin)


def analyze(image, review_regions=None):
    im = image.convert('RGBA')
    a = np.asarray(im.getchannel('A'))
    bbox = im.getchannel('A').getbbox()
    f = features(im)
    flags = []
    metrics = dict(alpha_min=int(a.min()), alpha_max=int(a.max()), bbox=bbox,
                   size=list(im.size), nonzero_alpha_pixels=int(np.count_nonzero(a)))
    if bbox is None:
        flags.append('empty_foreground')
    if a.min() != 0:
        flags.append('no_transparent_background')
    if f is None:
        flags.append('no_confident_opaque_interior')
        metrics.update(edge_pixels=0, suspect_pixels=0, dark_rim_pixels=0,
                       light_rim_pixels=0, rim_risk_ratio=0., rim_severity=0.)
        regions = []
    else:
        edge_count = int(f['edge'].sum())
        suspected = int(f['suspect'].sum())
        dark = int((f['suspect'] & (f['delta'] > 0)).sum())
        light = suspected-dark
        ratio = suspected/max(1, edge_count)
        metrics.update(edge_pixels=edge_count, suspect_pixels=suspected,
                       dark_rim_pixels=dark, light_rim_pixels=light,
                       rim_risk_ratio=round(ratio, 6), thin_detail_pixels=int(f['thin'].sum()),
                       rim_severity=float(np.abs(f['delta'])[f['suspect']].sum()/max(1,edge_count)))
        if dark >= 18 and dark/max(1, edge_count) > .025:
            flags.append('suspected_dark_rim')
        if light >= 18 and light/max(1, edge_count) > .025:
            flags.append('suspected_light_rim')
        count, _, stats, _ = cv2.connectedComponentsWithStats(f['suspect'].astype(np.uint8), 8)
        regions = [dict(box=s[:4].tolist(), pixels=int(s[4])) for s in stats[1:] if s[4] >= 4]
        regions = sorted(regions, key=lambda x:-x['pixels'])[:8]
    n, _, stats, _ = cv2.connectedComponentsWithStats((a > 127).astype(np.uint8), 8)
    components = sorted((int(s[4]) for s in stats[1:]), reverse=True)
    detached = [s for s in components[1:] if s >= 8]
    metrics['detached_components'] = detached
    if detached:
        flags.append('suspected_detached_detail_or_background')
    return dict(technical_pass=bool(bbox and im.size == (800, 800) and a.min() == 0 and a.max() > 200),
                edge_status='suspected' if flags else 'no_numeric_alert',
                visual_status='pending', flags=flags, metrics=metrics, regions=regions,
                review_regions=review_regions or [],
                limitation='Heuristics can flag genuine dark edges or miss attached background; visual review is required.')


def repair(image, round_number, output_scale, protected=None):
    """Operate on full-resolution candidate; never globally erode or delete components."""
    before = np.asarray(image.convert('RGBA')).copy()
    width = max(2, min(12, round(2/max(.01, output_scale))))
    f = features(image, width=width)
    if f is None:
        return image.copy(), dict(accepted=False, reason='No opaque interior')
    protect = f['thin'].copy()
    if protected is not None:
        if protected.size != image.size:
            raise ValueError('保护蒙版必须与原图尺寸相同')
        protect |= np.asarray(protected.convert('L')) > 0
    result = before.copy()
    selected = f['suspect'] & ~protect
    # Both rounds change soft-edge RGB only. Explicit masks are the only alpha edits.
    band = selected & (before[:, :, 3] < 250) & (before[:, :, 3] > 0)
    limit = 16 if round_number == 1 else 24
    correction = np.clip(f['nearest_rgb'][band]-before[band,:3].astype(float), -limit, limit)
    result[band,:3] = np.clip(np.rint(before[band,:3]+correction),0,255).astype(np.uint8)
    result[protect] = before[protect]
    core = f['core']
    core_unchanged = bool(np.array_equal(result[core], before[core]))
    detail_unchanged = bool(np.array_equal(result[protect], before[protect]))
    old_area = int(np.count_nonzero(before[:, :, 3] > 127))
    loss = int(np.count_nonzero((before[:, :, 3] > 127) & (result[:, :, 3] <= 127)))
    alpha_unchanged = bool(np.array_equal(result[:,:,3],before[:,:,3]))
    modified = int(np.count_nonzero(np.any(result != before,axis=2)))
    guard = core_unchanged and detail_unchanged and alpha_unchanged and modified > 0
    return Image.fromarray(result), dict(accepted=guard, round=round_number,
        method='bounded_edge_color_only',max_channel_delta=limit,alpha_unchanged=alpha_unchanged,
        core_unchanged=core_unchanged, protected_details_unchanged=detail_unchanged,
        foreground_pixels_lost=loss, foreground_loss_ratio=loss/max(1,old_area),
        modified_pixels=modified,
        note='Area and pixel guards do not prove semantic correctness; requires visual review.')


def diagnostic_boxes(image, report):
    """Explicit inspection areas first, then numerical risks and contour fallback."""
    centers=[]
    for left,top,right,bottom in report.get('review_regions',[]):
        centers.append(((left+right)//2,(top+bottom)//2))
    for region in report['regions']:
        x,y,w,h=region['box'];centers.append((x+w//2,y+h//2))
    box=image.getchannel('A').getbbox() or (0,0,800,800)
    centers.extend([((box[0]+box[2])//2,box[1]+90),
                    (box[0]+70,(box[1]+box[3])//2),
                    (box[2]-70,(box[1]+box[3])//2)])
    boxes=[]
    for cx,cy in centers:
        x=max(0,min(480,cx-160));y=max(0,min(480,cy-160))
        if all(abs(x-other[0])+abs(y-other[1])>=120 for other in boxes):
            boxes.append((x,y,x+320,y+320))
        if len(boxes)==4:break
    return boxes


def diagnostics(image, report, font):
    """Four overview backgrounds; identical native-pixel white/gray/black local views."""
    small = image.copy(); small.thumbnail((320, 320))
    boxes=diagnostic_boxes(image,report)
    canvas = Image.new('RGB', (1280, 370+len(boxes)*354), (242,244,247))
    d = ImageDraw.Draw(canvas)
    backgrounds = [('白底', 'white'), ('灰底', (160,160,160,255)), ('黑底','black')]
    for col, (label, color) in enumerate(backgrounds):
        canvas.paste(composite(small, color), (col*320, 30))
        d.text((col*320+10, 4), label, font=font, fill='black')
    checker = Image.new('RGBA', small.size, 'white'); cd = ImageDraw.Draw(checker)
    for y in range(0, small.height, 16):
        for x in range(0, small.width, 16):
            if (x//16+y//16)%2: cd.rectangle((x,y,x+15,y+15),fill=(215,215,215,255))
    checker.alpha_composite(small)
    canvas.paste(checker.convert('RGB'),(960,30));d.text((970,4),'透明棋盘格',font=font,fill='black')
    marked=composite(image,'white'); md=ImageDraw.Draw(marked)
    for i,region in enumerate(report['regions'][:4],1):
        x,y,w,h=region['box'];md.rectangle((x,y,x+w,y+h),outline='red',width=2)
    for box in report.get('review_regions',[]):md.rectangle(tuple(box),outline=(240,130,0),width=2)
    marked.thumbnail((320,320));canvas.paste(marked,(0,400))
    d.text((10,374),'红：疑似风险；橙：指定检查区',font=font,fill='black')
    backgrounds=[('白底','white'),('灰底',(80,80,80,255)),('黑底','black')]
    for row,box in enumerate(boxes):
        top=370+row*354
        if row:
            d.text((10,top+40),f'局部{row+1} 坐标',font=font,fill='black')
            d.text((10,top+70),str(box),font=font,fill='black')
        for column,(label,color) in enumerate(backgrounds,1):
            crop=composite(image.crop(box),color)
            canvas.paste(crop,(column*320,top+30))
            d.text((column*320+8,top+4),f'局部{row+1} {label} · 100%',font=font,fill='black')
    return canvas
