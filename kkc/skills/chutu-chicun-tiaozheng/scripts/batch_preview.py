"""Read-only preview contact sheets, twenty numbered candidates per page."""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps
from validate_candidate import _font


def save_target_preview(output,path,job):
    """A display JPEG only; never becomes the PSD or final PNG pixel source."""
    path=Path(path)
    if path.exists() or path.is_symlink():raise FileExistsError('目标预览已存在，不覆盖')
    image=output.convert('RGBA');selected=str(job.get('format','jpg')).lower()
    background=Image.new('RGBA',image.size,'white');policy='white'
    if selected=='png' and image.getchannel('A').getextrema()[0]<255:
        draw=ImageDraw.Draw(background);policy='checkerboard_preview_only'
        for top in range(0,image.height,16):
            for left in range(0,image.width,16):
                if (left//16+top//16)%2:draw.rectangle((left,top,left+15,top+15),fill='#cccccc')
    Image.alpha_composite(background,image).convert('RGB').save(path,format='JPEG',quality=94,
        **({'icc_profile':output.info['icc_profile']} if output.info.get('icc_profile') else {}))
    return policy


def contact_sheets(items,directory,size,*,page_size=20):
    if type(page_size) is not int or not 1<=page_size<=20:raise ValueError('总览每页数量应为1—20')
    directory=Path(directory);paths=[]
    for start in range(0,len(items),page_size):
        page=items[start:start+page_size];columns=min(4,len(page));rows=math.ceil(len(page)/columns)
        sheet=Image.new('RGB',(columns*320,60+rows*230),'#eeeeee');draw=ImageDraw.Draw(sheet)
        draw.text((16,12),f'{size}  {start+1}—{start+len(page)} / {len(items)}',font=_font(24),fill='#202020')
        for offset,item in enumerate(page):
            left=(offset%columns)*320;top=60+(offset//columns)*230
            with Image.open(item['preview']) as opened:
                thumbnail=ImageOps.contain(opened.convert('RGB'),(308,185),Image.Resampling.LANCZOS)
                sheet.paste(thumbnail,(left+(320-thumbnail.width)//2,top+32+(185-thumbnail.height)//2))
            draw.text((left+8,top+3),f'第{item["number"]}张',font=_font(21),fill='#202020')
        path=directory/f'overview-{start//page_size+1:02d}.jpg'
        if path.exists() or path.is_symlink():raise FileExistsError('总览文件已存在，不覆盖')
        sheet.save(path,format='JPEG',quality=92);paths.append(str(path))
    return paths
