bl_info = {
    'name': 'Print & Pin · Poster Print', 'author': 'G_ni', 'version': (1, 81, 0),
    'blender': (5, 2, 0), 'location': '3D View > Sidebar > Poster Print',
    'description': 'Print & Pin, part 1: cut image sheets, age the paper, frame photos and print them as poster textures with exact UVs.',
    'category': 'Object',
}
import bpy
import bpy.utils.previews
import sys
import math
import time
from time import perf_counter as PERF
import os
import json
import uuid
import re
import shutil
import hashlib
import tempfile
import numpy as np
ADDON_DIR=os.path.dirname(os.path.abspath(__file__))
BUILTIN_PAPER_DIR=os.path.join(ADDON_DIR,'paper')   # Paper textures shipped with the addon by default
from bpy.props import StringProperty, IntProperty, FloatProperty, FloatVectorProperty, BoolProperty, EnumProperty, CollectionProperty, PointerProperty
from .i18n_ko import _KO

# ---------------------------------------------------------------- Language (English / 한국어)
# The UI language is an add-on preference (default English), shared by Poster Print and Poster Pin in
# <Blender config>/print_pin_language.json. Panel, editor and message text switch right away; labels and
# tooltips that Blender stores at registration (operator names, property names) follow after a restart.
import re as _i18n_re
_I18N={'lang':None,'cache':{},'tpl':None}
def _i18n_file():
    try:return os.path.join(bpy.utils.user_resource('CONFIG'),'print_pin_language.json')
    except Exception:return ''
def _i18n_lang():
    if _I18N['lang'] is None:
        lang='EN'
        try:
            with open(_i18n_file(),encoding='utf-8') as f:lang=json.load(f).get('lang','EN')
        except Exception:pass
        _I18N['lang']=lang if lang in ('EN','KO') else 'EN'
    return _I18N['lang']
def _i18n_set(lang):
    _I18N['lang']=lang;_I18N['cache'].clear()
    try:
        p=_i18n_file();os.makedirs(os.path.dirname(p),exist_ok=True)
        with open(p,'w',encoding='utf-8') as f:json.dump({'lang':lang},f)
    except Exception:pass
    for mod in ('poster_atlas','poster_scatter'):   # the other add-on reads the same file: reset its copy too
        m=sys.modules.get(mod)
        if m is not None and getattr(m,'_I18N',None) is not None and m._I18N is not _I18N:
            m._I18N['lang']=lang;m._I18N['cache'].clear()
    try:
        for w in bpy.context.window_manager.windows:
            for a in w.screen.areas:a.tag_redraw()
    except Exception:pass
_I18N_SPEC=_i18n_re.compile(r'%%|%[-+ 0#]*\d*(?:\.\d+)?[diouxXeEfFgGs]')
def _i18n_templates():
    if _I18N['tpl'] is None:
        tpl=[]
        for en,ko in _KO.items():
            if '%' not in en or not _I18N_SPEC.search(en.replace('%%','')):continue
            parts=[];pos=0
            for m in _I18N_SPEC.finditer(en):
                parts.append(_i18n_re.escape(en[pos:m.start()]));t=m.group()
                if t=='%%':parts.append('%')
                elif t[-1] in 'dioux':parts.append(r'(-?\d+)')
                elif t[-1] in 'X':
                    w=_i18n_re.search(r'(\d+)X$',t);parts.append(r'([0-9A-Fa-f]{%s})'%w.group(1) if w else r'([0-9A-Fa-f]+)')
                elif t[-1]=='s':parts.append(r'(.*?)')
                else:parts.append(r'(-?[0-9.eE+\-]+|inf|nan)')
                pos=m.end()
            parts.append(_i18n_re.escape(en[pos:]))
            try:tpl.append((len(en),_i18n_re.compile(''.join(parts)+r'\Z',_i18n_re.S),ko,en in _I18N_TR_ARGS))
            except _i18n_re.error:pass
        tpl.sort(key=lambda t:-t[0]);_I18N['tpl']=tpl
    return _I18N['tpl']
_I18N_SEPS=('  ·  ','  |  ',' · ',' | ')
_I18N_TR_ARGS={'Eyedropper (%s): click a poster or a color cell · Esc = Cancel','%s set with eyedropper · #%02X%02X%02X',
    '%s on %d image(s)','Look: %s · %d image(s)','Surface: %s · %d image(s)','Turned off %s','Applied %s','Removed %s.',
    'Cleared %s effects','%s has no effects to clear','Previewing: %s · %d posters','Previewing: %s · on #%s (Esc cancels)','%d selected: applied [%s] · pick another effect to stack on top.',
    'Paint · %s — drag over a poster  |  [ ] brush size  |  right-click to stop','Scale %s with mouse','Changed to %s · poster sizes kept%s · Ctrl+Z to undo',
    '%s ×%d','Surface · %s','%s %d','%s  ·  %d','Added %d image(s) to the %s list','Size %d%%  ·  move left / right  ·  Ctrl 5%% steps  ·  R rotate  ·  %s  ·  Esc cancel',
    'Rotate %.0f°  ·  Ctrl 15° steps  ·  S size  ·  %s  ·  Esc cancel','Move  ·  keep holding and press S size / R rotate  ·  %s',
    '%s  [angle %.0f° · scale %d%%%s]  %s','Layer %d: placed %d poster%s %s','Layer %d · %s','%s|%d','%s  %d×%d',
    'Make %d-Cut  ·  %s card  (%d selected)','Photo strip %d×%d on a %s card (%.0f×%.0f mm) from %d photo(s)%s · originals unchecked in the list',
    'Too many cells for a %s card.','%d images · one %s sheet (~%d A4)','Not all current posters fit on the %s canvas · remove a few or reduce their size.',
    'Auto %d · Manual %d%s%s · %.2fs','Packed %d selected into the free space · others stay put%s · Ctrl+Z to undo','Green inset %d px%s',
    'Photo strip %d×%d','%d × %d px  |  Rotation %d°  |  %s','Applied to %d selected: %s','= %d posters%s','Paper Crumple · %s','Custom (pattern %d)'}
def _i18n_tr(s,depth=0):
    k=_KO.get(s)
    if k is not None:return k
    st=s.strip()
    if st!=s and st:
        k=_i18n_tr(st,depth+1)
        if k!=st:return s[:len(s)-len(s.lstrip())]+k+s[len(s.rstrip()):]
        return s
    for _,rx,ko,tr_args in _i18n_templates():
        m=rx.match(s)
        if m:
            g=m.groups()
            # values are names of the user's data (collections, objects) unless the message only ever gets UI words
            return _i18n_re.sub(r'\{(\d+)\}',lambda mm:(_i18n_tr(g[int(mm.group(1))],depth+1) if tr_args else g[int(mm.group(1))]) if int(mm.group(1))<len(g) else '',ko)
    if depth<4:
        for sep in _I18N_SEPS:
            if sep in s:
                parts=s.split(sep);out=[_i18n_tr(p,depth+1) for p in parts]
                if out!=parts:return sep.join(out)
    return s
def _T(s):
    """English UI text -> current language (English when the preference is English)."""
    if not isinstance(s,str) or not s or _i18n_lang()!='KO':return s
    c=_I18N['cache'];r=c.get(s)
    if r is None:
        try:r=_i18n_tr(s)
        except Exception:r=s
        if len(c)>20000:c.clear()
        c[s]=r
    return r
_I18N_KEEP={}
def _T_items(items):
    """Translate the name / description of EnumProperty items (identifiers stay English)."""
    if callable(items):
        fn=items
        def cb(self,context):
            res=fn(self,context)
            if _i18n_lang()!='KO' or not res:return res
            out=[tuple((_T(v) if i in (1,2) and isinstance(v,str) else v) for i,v in enumerate(it)) if isinstance(it,tuple) and len(it)>=3 else it for it in res]
            _I18N_KEEP[id(fn)]=out   # Blender needs the strings kept alive
            return out
        return cb
    try:return [tuple((_T(v) if i in (1,2) and isinstance(v,str) else v) for i,v in enumerate(it)) if isinstance(it,(tuple,list)) and len(it)>=3 else it for it in items]
    except TypeError:return items
def _i18n_lang_changed(self,context):_i18n_set(self.language)

from bpy_extras.io_utils import ImportHelper
from mathutils import Vector

CUT_EDITORS=[]
PANEL_OPEN={'layout':True,'effects':True,'sec:Text':False}   # fold state (Text starts closed) of the editor's side-panel sections (kept between sessions)
SELECTION_DRAGS=[]
SELECTION_TIMER=None
LIST_ROWS={}
SELECTION_BATCH=False
PREVIEW_ICONS=None
POSTER_FORMATS={'A4':(210.,297.),'A3':(297.,420.),'Sticky Note':(75.,75.)}
# Picture tab formats: card width, height and white border (side, top, bottom) in mm. Instant films have the thick bottom.
PHOTO_FORMAT_ALIASES={'Polaroid':'Instant Classic','Instax Mini':'Instant Mini','Instax Square':'Instant Square','Instax Wide':'Instant Wide'}   # Old (brand) names in saved data


class _PhotoFormats(dict):   # Looks up old saved names too; lists only the generic names
    def __getitem__(self,k):return dict.__getitem__(self,PHOTO_FORMAT_ALIASES.get(k,k))
    def __contains__(self,k):return dict.__contains__(self,PHOTO_FORMAT_ALIASES.get(k,k))


PHOTO_FORMATS=_PhotoFormats({'Instant Classic':(88.,107.,(4.5,6.5,21.5)),'Instant Mini':(54.,86.,(4.,6.5,17.5)),'Instant Square':(72.,86.,(5.,6.5,17.5)),
               'Instant Wide':(108.,86.,(4.5,6.5,17.5)),'Print 4×6':(102.,152.,(4.,4.,4.)),'Print 5×7':(127.,178.,(5.,5.,5.))})
KEEP=object()   # 'leave as is' marker
# Printed photo surface (Principled BSDF): photo paper is a dielectric, so Metallic stays 0; the shine comes from low roughness.
# Values are (photo area roughness, white border roughness, metallic).
PHOTO_FINISHES={'MATTE':('Matte',(.62,.55,0.)),'SATIN':('Satin',(.45,.5,0.)),'SILK':('Silk',(.35,.45,0.)),'GLOSSY':('Glossy',(.18,.42,0.))}   # same names as Paper, least shiny first
# Paper surface (Paper tab): how much light the printed paper reflects. Plain paper is matte (0.85 = the default, no layer).
PAPER_FINISHES={'MATTE':('Matte',.85),'SATIN':('Satin',.55),'SILK':('Silk',.4),'GLOSSY':('Glossy',.25)}


def strip_card(cols,rows):
    """Real photo-booth print for a cols×rows strip: one column = 2×6 inch strip, wider grids = 4×6 inch
    (turned to 6×4 when there are more columns than rows). Returns width mm, height mm, label."""
    if cols==1 and rows>=3:return 50.8,152.4,'2×6 in'
    if cols>rows:return 152.4,101.6,'6×4 in'
    return 101.6,152.4,'4×6 in'
LEGACY_FORMATS={'포스트잇':'Sticky Note'}   # format key used by older versions
EDIT_MODES=[('SCALE','Scale','Adjusts width and height independently. The photo ratio may change.'),
            ('FIT','Keep Ratio','Scales while keeping the original ratio of the whole photo.'),
            ('CROP','Crop','Fills the frame; move the photo inside to choose what gets cropped.')]
LAYOUT_DIRECTIONS=[('↖',-1,1),('↑',0,1),('↗',1,1),
                   ('←',-1,0),('Center',0,0),('→',1,0),
                   ('↙',-1,-1),('↓',0,-1),('↘',1,-1)]


def ui_theme():
    # Reads Blender's own theme so the editor looks like native UI and follows theme changes.
    t=bpy.context.preferences.themes[0];ui=t.user_interface
    def c4(v,a=1.):
        v=tuple(v);return v if len(v)==4 else v+(a,)
    def w(name):
        wc=getattr(ui,name)
        return {'inner':c4(wc.inner),'sel':c4(wc.inner_sel),'item':c4(wc.item),'outline':c4(wc.outline),
                'text':c4(wc.text),'text_sel':c4(wc.text_sel),'round':float(getattr(wc,'roundness',.4))}
    T={k:w('wcol_'+k) for k in ('tool','radio','numslider','text','regular')}
    try:back=c4(t.image_editor.space.back)
    except Exception:back=(.19,.19,.19,1)
    try:head=c4(t.view_3d.space.header);head=head[:3]+(1.,)
    except Exception:head=(.19,.19,.19,1)
    try:sel,act=c4(t.view_3d.object_selected),c4(t.view_3d.object_active)
    except Exception:sel,act=(.93,.34,0,1),(1,.63,.16,1)
    T.update(back=back,header=head,obj_sel=sel,obj_act=act,dim=T['tool']['text'][:3]+(.62,),accent=T['radio']['sel'])
    return T


def shade(col,d):return tuple(min(1.,max(0.,v+d)) for v in col[:3])+(col[3] if len(col)>3 else 1.,)


def rrect_fan(x0,y0,x1,y1,r,seg=4,corners=(True,True,True,True)):
    # Triangle fan of a rounded rectangle. corners = (bottom-right, top-right, top-left, bottom-left);
    # a False corner stays square so aligned buttons sit flush, like Blender's align=True rows.
    r=max(0.,min(r,(x1-x0)/2,(y1-y0)/2))
    pts=[((x0+x1)/2,(y0+y1)/2)]
    for (cx,cy,a0,sx,sy),on in zip(((x1,y0,-90,-1,1),(x1,y1,0,-1,-1),(x0,y1,90,1,-1),(x0,y0,180,1,1)),corners):
        rc=r if (on and r>=.5) else 0.
        ccx,ccy=cx+sx*rc,cy+sy*rc
        for k in range(seg+1):
            a=math.radians(a0+90*k/seg);pts.append((ccx+rc*math.cos(a),ccy+rc*math.sin(a)))
    pts.append(pts[1]);return pts

def rotated_path(path,turns):
    path=bpy.path.abspath(path);turns=int(turns)%4
    if not turns:return path
    stat=os.stat(path)
    key=hashlib.sha256((path+'|'+str(stat.st_mtime_ns)+'|'+str(stat.st_size)+'|'+str(turns)).encode()).hexdigest()
    folder=os.path.join(tempfile.gettempdir(),'poster_atlas_rotation_cache')
    cached=os.path.join(folder,key+'.png')
    if not os.path.isfile(cached):
        os.makedirs(folder,exist_ok=True)
        # Blender pixels are bottom-up: positive rot90 is visually clockwise.
        pixels=np.ascontiguousarray(np.rot90(read_pixels(path),turns,axes=(0,1)))
        temporary=os.path.join(folder,key+'_'+uuid.uuid4().hex+'.png')
        im=save_atlas(temporary,pixels,False)
        try:os.replace(temporary,cached)
        finally:
            bpy.data.images.remove(im)
            if os.path.exists(temporary):os.remove(temporary)
    return cached

def file_path(item):
    return rotated_path(item.path,item.quarter_turns)

def rotate_item(settings,step):
    if not settings.files:return
    item=settings.files[max(0,min(settings.active,len(settings.files)-1))]
    turns=(item.quarter_turns+step)%4
    rotated_path(item.path,turns)  # Validate/cache first; keep the old state on failure.
    item.quarter_turns=turns
    for editor in list(CUT_EDITORS):
        if editor.preview_only:editor.preview_step(0)
        elif editor.layout_mode:editor.refresh_layout_sources()


def selection_button_held():
    # A native checkbox can consume its release before the modal sees it.
    # On Windows, also check physical button state so selection cannot run on.
    if os.name=='nt':
        import ctypes
        user32=ctypes.windll.user32
        key=2 if user32.GetSystemMetrics(23) else 1
        return bool(user32.GetAsyncKeyState(key)&0x8000)
    return None


def preview_icon(path):
    global PREVIEW_ICONS
    path=bpy.path.abspath(path)
    try:
        stat=os.stat(path);key=path+'|'+str(stat.st_mtime_ns)+'|'+str(stat.st_size)
        if PREVIEW_ICONS is None:PREVIEW_ICONS=bpy.utils.previews.new()
        if key not in PREVIEW_ICONS:
            # Only visited images are loaded; cap memory for large libraries.
            while len(PREVIEW_ICONS)>=24:del PREVIEW_ICONS[next(iter(PREVIEW_ICONS))]
            PREVIEW_ICONS.load(key,path,'IMAGE')
        return PREVIEW_ICONS[key].icon_id
    except (OSError,RuntimeError,KeyError):return 0


def cut_grid(w,h,cols,rows):
    if w<cols*2 or h<rows*2:raise ValueError('Too many divisions for the image size.')
    return [[round(c*w/cols),h-round((r+1)*h/rows),round((c+1)*w/cols),h-round(r*h/rows)] for r in range(rows) for c in range(cols)]


def chroma_mask(px):
    """Chroma-key green (background) pixels. Greens inside the artwork, like dark green or lime, are kept."""
    r,g,b=px[...,0],px[...,1],px[...,2]
    return (g>.55)&(g-np.maximum(r,b)>.28)&(r<.6)&(b<.6)


def shadow_mask(px,bg):
    """Soft drop shadows drawn on the green background: darker, greenish, low-saturation pixels next to the green,
    only within a thin band from it. Dark or neutral artwork (black posters, gray borders) is never touched."""
    rgb=px[...,:3];r,g,b=rgb[...,0],rgb[...,1],rgb[...,2]
    lum=rgb.mean(-1);sat=rgb.max(-1)-rgb.min(-1);gd=g-np.maximum(r,b)
    cand=(gd>.03)&(gd<.28)&(sat<.3)&(lum>.06)&(lum<.55)&~bg
    band=max(4,int(min(px.shape[:2])*.03))
    m=bg.copy()
    for _ in range(band):   # grow from the green background into connected shadow pixels, at most a thin band
        nb=np.zeros_like(m);nb[1:]|=m[:-1];nb[:-1]|=m[1:];nb[:,1:]|=m[:,:-1];nb[:,:-1]|=m[:,1:]
        new=nb&cand&~m
        if not new.any():break
        m|=new
    return m&~bg


def background_mask(px,shadows=False):
    """Green background, plus drop shadows on it when 'Remove Shadows' is on."""
    bg=chroma_mask(px)
    return bg|shadow_mask(px,bg) if shadows and bg.any() else bg


def chroma_regions(px,min_frac=.002,shadows=False):
    """Find artwork blobs on a green background as a list of [x0,y0,x1,y1] (bottom-left origin). Ordered top->bottom, left->right."""
    h,w=px.shape[:2];k=max(1,int(math.ceil(max(w,h)/1200)))
    small=~background_mask(px[::k,::k],shadows);sh,sw=small.shape
    parent=[];boxes=[]
    def find(a):
        while parent[a]!=a:parent[a]=parent[parent[a]];a=parent[a]
        return a
    prev=[]
    for y in range(sh):
        row=small[y];d=np.diff(np.concatenate(([0],row.view(np.int8),[0])))
        starts=np.flatnonzero(d==1);ends=np.flatnonzero(d==-1);cur=[]
        for a,b in zip(starts,ends):
            lab=len(parent);parent.append(lab);boxes.append([a,y,b,y+1,(b-a)])
            for pa,pb,pl in prev:
                if pa<b and a<pb:   # Merge if touching a blob on the row above
                    ra,rb=find(lab),find(pl)
                    if ra!=rb:parent[ra]=rb
            cur.append((a,b,lab))
        prev=cur
    merged={}
    for i,(a,y,b,y1,n) in enumerate(boxes):
        r=find(i);m=merged.get(r)
        if m is None:merged[r]=[a,y,b,y1,n]
        else:m[0]=min(m[0],a);m[1]=min(m[1],y);m[2]=max(m[2],b);m[3]=max(m[3],y1);m[4]+=n
    keep=[m for m in merged.values() if m[4]>=min_frac*sh*sw]
    full=~background_mask(px,shadows);rects=[]
    for a,y,b,y1,_ in keep:   # Fit the border exactly at the original resolution
        x0=max(0,a*k-k);x1=min(w,b*k+k);y0=max(0,y*k-k);y1=min(h,y1*k+k)
        sub=full[y0:y1,x0:x1];cols=np.flatnonzero(sub.any(0));rows=np.flatnonzero(sub.any(1))
        if len(cols)<2 or len(rows)<2:continue
        rects.append([int(x0+cols[0]),int(y0+rows[0]),int(x0+cols[-1])+1,int(y0+rows[-1])+1])
    if not rects:return []
    hmed=sorted(r[3]-r[1] for r in rects)[len(rects)//2]
    rects.sort(key=lambda r:(-round((r[1]+r[3])/2/max(hmed*.6,1)),r[0]))   # Row by row from the top
    return rects


def chroma_fit(px,rects,shadows=False):
    """For each defined cell, remove the green background and shrink to fit the artwork. Cells that are all green are dropped."""
    full=~background_mask(px,shadows);out=[]
    for x0,y0,x1,y1 in rects:
        sub=full[int(y0):int(y1),int(x0):int(x1)]
        cols=np.flatnonzero(sub.any(0));rows=np.flatnonzero(sub.any(1))
        if len(cols)<2 or len(rows)<2:continue
        out.append([int(x0)+int(cols[0]),int(y0)+int(rows[0]),int(x0)+int(cols[-1])+1,int(y0)+int(rows[-1])+1])
    return out


def chroma_inset(rects,n):
    """Shrink each box by n pixels on every side (keeps at least 4 px)."""
    n=int(n or 0)
    if n<=0:return [list(r) for r in rects]
    out=[]
    for x0,y0,x1,y1 in rects:
        k=min(n,max(0,(x1-x0-4)//2),max(0,(y1-y0-4)//2));out.append([x0+k,y0+k,x1-k,y1-k])
    return out


def cut_drag(rect,handle,dx,dy,w,h):
    x0,y0,x1,y1=rect;dx=round(dx);dy=round(dy)
    if handle=='MOVE':
        dx=max(-x0,min(w-x1,dx));dy=max(-y0,min(h-y1,dy))
        return [x0+dx,y0+dy,x1+dx,y1+dy]
    if 'W' in handle:x0=max(0,min(x1-2,x0+dx))
    if 'E' in handle:x1=min(w,max(x0+2,x1+dx))
    if 'S' in handle:y0=max(0,min(y1-2,y0+dy))
    if 'N' in handle:y1=min(h,max(y0+2,y1+dy))
    return [x0,y0,x1,y1]


def layout_drag(rect,handle,dx,dy,w,h,margin=4):
    if handle=='MOVE':
        a,b,c,d=rect
        dx=max(margin-a,min(w-margin-c,round(dx)))
        dy=max(margin-b,min(h-margin-d,round(dy)))
        return [a+dx,b+dy,c+dx,d+dy]
    a,b,c,d=rect;rw=c-a;rh=d-b;ratio=rw/rh
    hx=-1 if 'W' in handle else 1 if 'E' in handle else 0
    hy=-1 if 'S' in handle else 1 if 'N' in handle else 0
    ax=c if hx<0 else a if hx>0 else (a+c)/2
    ay=d if hy<0 else b if hy>0 else (b+d)/2
    proposed=rw+hx*dx if hx and (not hy or abs(dx/rw)>=abs(dy/rh)) else (rh+hy*dy)*ratio
    mx=ax-margin if hx<0 else w-margin-ax if hx>0 else 2*min(ax-margin,w-margin-ax)
    my=ay-margin if hy<0 else h-margin-ay if hy>0 else 2*min(ay-margin,h-margin-ay)
    nw=max(2,min(max(2,proposed),mx,my*ratio));nh=nw/ratio
    x0=ax-nw if hx<0 else ax if hx>0 else ax-nw/2
    y0=ay-nh if hy<0 else ay if hy>0 else ay-nh/2
    return [round(x0),round(y0),round(x0+nw),round(y0+nh)]


def initial_layout(s,sizes):
    if not sizes:return []
    res=int(s.resolution);pad=max(4,round(4*res/2048));gap=2*pad+2
    available=res-2*pad;n=len(sizes)
    normalized=[(w/max(w,h),h/max(w,h)) for w,h in sizes]
    best=None
    # All images share one long-edge length regardless of source resolution.
    # Maximize that common size, never enlarge one image to consume a blank cell.
    for columns in range(1,n+1):
        groups=[list(range(i,min(i+columns,n))) for i in range(0,n,columns)]
        heights=[max(normalized[i][1] for i in ids) for ids in groups]
        length=min((available-gap*(len(groups)-1))/sum(heights),
                   min((available-gap*(len(ids)-1))/sum(normalized[i][0] for i in ids) for ids in groups))
        if length<2:continue
        height=length*sum(heights)+gap*(len(groups)-1)
        y=(res+height)/2;rects=[None]*n
        for ids,row_height in zip(groups,heights):
            row_width=length*sum(normalized[i][0] for i in ids)+gap*(len(ids)-1)
            x=(res-row_width)/2
            for i in ids:
                w,h=(v*length for v in normalized[i]);top=y-(row_height*length-h)/2
                rects[i]=[math.floor(x+1e-6),math.floor(top-h+1e-6),math.floor(x+w+1e-6),math.floor(top+1e-6)]
                x+=w+gap
            y-=row_height*length+gap
        if any(min(r[2]-r[0],r[3]-r[1])<2 for r in rects):continue
        if best is None or length>best[0]:best=(length,rects)
    if best is None:raise ValueError('Too many images or the ratio is too long. Please use fewer images at once.')
    return best[1]


def layout_conflicts(rects,pad):
    bad=set()
    for i,(a,b,c,d) in enumerate(rects):
        for j in range(i):
            e,f,g,h=rects[j]
            if a-pad<g+pad and c+pad>e-pad and b-pad<h+pad and d+pad>f-pad:bad.update((i,j))
    return bad


def layout_density(s):
    w,h=dimensions(s)
    return min((2048/3-8)/w,(2048/2-8)/h)

def rotate_uv(u,v,turns):
    return [(u,v),(v,1-u),(1-u,1-v),(1-v,u)][turns%4]

def rotated_crop(crop,turn):
    a,b,c,d=crop
    points=[rotate_uv(u,v,turn) for u,v in ((a,b),(c,b),(c,d),(a,d))]
    return [min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)]

def crop_frame_drag(rect,crop,turn,handle,dx,dy,width,height,pad):
    # The image stays fixed while its frame edges move, including after packing rotation.
    a,b,c,d=rect;l,t,r,u=rotated_crop(crop,turn)
    sw=(c-a)/(r-l);sh=(d-b)/(u-t);sx=a-l*sw;sy=b-t*sh
    moved=cut_drag(rect,handle,dx,dy,width,height)
    moved=[max(pad,math.ceil(sx-1e-7),moved[0]),max(pad,math.ceil(sy-1e-7),moved[1]),
           min(width-pad,math.floor(sx+sw+1e-7),moved[2]),min(height-pad,math.floor(sy+sh+1e-7),moved[3])]
    if moved[2]-moved[0]<2 or moved[3]-moved[1]<2:return list(rect),list(crop)
    oriented=[(moved[0]-sx)/sw,(moved[1]-sy)/sh,(moved[2]-sx)/sw,(moved[3]-sy)/sh]
    return moved,[max(0.,min(1.,v)) for v in rotated_crop(oriented,-turn)]

def centered_layout_rect(rect,rw,rh,res,pad):
    if rw>res-2*pad or rh>res-2*pad:
        raise ValueError('That size is larger than the canvas. Please increase the output resolution.')
    a,b,c,d=rect
    x=max(pad,min(res-pad-rw,round((a+c-rw)/2)))
    y=max(pad,min(res-pad-rh,round((b+d-rh)/2)))
    return [x,y,x+rw,y+rh]

def preset_layout_rect(rect,image_size,preset,density,res,pad,turns=0,exact=False):
    iw,ih=image_size;mw,mh=POSTER_FORMATS[LEGACY_FORMATS.get(preset,preset)] if isinstance(preset,str) else preset
    if isinstance(preset,str) and preset in {'A3','A4'} and iw>ih:mw,mh=mh,mw
    if min(mw,mh)<=0:raise ValueError('Width and height must be greater than 0.')
    factor=min(mw/iw,mh/ih);physical=[mw,mh] if exact else [iw*factor,ih*factor]
    rw,rh=[max(2,round(v*density)) for v in physical]
    if turns%2:rw,rh=rh,rw
    return centered_layout_rect(rect,rw,rh,res,pad),physical

def cover_crop(image_size,frame_size,previous=(0.,0.,1.,1.)):
    """Fill an exact frame without stretching; retain the previous focal point."""
    iw,ih=image_size;fw,fh=frame_size
    scale=max(fw/iw,fh/ih);w=min(1.,fw/(iw*scale));h=min(1.,fh/(ih*scale))
    a,b,c,d=previous
    x=max(0.,min(1-w,(a+c-w)/2));y=max(0.,min(1-h,(b+d-h)/2))
    return [x,y,x+w,y+h]

def crop_map(crop,base,inverse=False):
    a,b,c,d=base;w=c-a;h=d-b
    if inverse:return [(crop[0]-a)/w,(crop[1]-b)/h,(crop[2]-a)/w,(crop[3]-b)/h]
    return [a+crop[0]*w,b+crop[1]*h,a+crop[2]*w,b+crop[3]*h]

def crop_size(size,crop):return (size[0]*(crop[2]-crop[0]),size[1]*(crop[3]-crop[1]))

def vacant_layout_rect(rect,others,res,pad,gap=None):
    """Find a nearby free slot without moving or scaling any existing image."""
    rw,rh=rect[2]-rect[0],rect[3]-rect[1];maxx=res-pad-rw;maxy=res-pad-rh
    if maxx<pad or maxy<pad:return None
    gap=max(0,2*pad+2 if gap is None else gap)
    px=max(pad,min(maxx,rect[0]));py=max(pad,min(maxy,rect[1]))
    ys={pad,maxy,py}
    for a,b,c,d in others:ys.update((max(pad,min(maxy,b-gap-rh)),max(pad,min(maxy,d+gap))))
    best=None
    for y in ys:
        intervals=sorted((a-gap-rw,c+gap) for a,b,c,d in others if y<d+gap and y+rh>b-gap)
        left=pad
        for lo,hi in intervals+[(maxx,maxx)]:
            right=min(maxx,lo)
            if left<=right:
                x=max(left,min(right,px));score=(x-px)**2+(y-py)**2
                candidate=(score,y,x)
                if best is None or candidate<best:best=candidate
            left=max(left,hi)
            if left>maxx:break
    return None if best is None else [best[2],best[1],best[2]+rw,best[1]+rh]

def pack_layout(sizes,res,pad,gap,rotate=False):
    """Keep sizes and fit everything (MaxRects, many orders and rules, then shuffled tries) and center the block.
    Returns rects, or with rotate=True (rects, rotated indices) allowing 90° turns. None if no arrangement was found."""
    avail=res-2*pad
    if not sizes:return ([],set()) if rotate else []
    if any(min(w,h)>avail or (not rotate and (w>avail or h>avail)) for w,h in sizes):return None
    out=pack_search(sizes,avail,gap,rotate)
    if not out:return None
    x0=min(o[0] for o in out);y0=min(o[1] for o in out);x1=max(o[0]+o[2] for o in out);y1=max(o[1]+o[3] for o in out)
    dx=pad+(avail-(x1-x0))//2-x0;dy=pad+(avail-(y1-y0))//2-y0
    rects=[[x+dx,y+dy,x+dx+w,y+dy+h] for x,y,w,h,r in out]
    return (rects,{i for i,o in enumerate(out) if o[4]}) if rotate else rects


def _carve(free,x,y,w,h):
    """Remove box (x,y,w,h) from the MaxRects free list."""
    nf=[]
    for fx,fy,fw,fh in free:
        if x>=fx+fw or x+w<=fx or y>=fy+fh or y+h<=fy:nf.append((fx,fy,fw,fh));continue
        if x>fx:nf.append((fx,fy,x-fx,fh))
        if x+w<fx+fw:nf.append((x+w,fy,fx+fw-x-w,fh))
        if y>fy:nf.append((fx,fy,fw,y-fy))
        if y+h<fy+fh:nf.append((fx,y+h,fw,fy+fh-y-h))
    return [r for k,r in enumerate(nf) if not any(k!=j and r[0]>=o[0] and r[1]>=o[1] and r[0]+r[2]<=o[0]+o[2] and r[1]+r[3]<=o[1]+o[3] and (r!=o or j<k) for j,o in enumerate(nf))]


def pack_search(sizes,avail,gap,rot_ok,budget=2.,obstacles=None):
    """Try MaxRects with 5 orders x 4 rules, then shuffled orders until the time budget runs out. [(x,y,w,h,rotated)] or None."""
    free0=None
    if obstacles:   # images that stay where they are: their space (plus the spacing) is taken out first
        free0=[(0,0,avail+gap,avail+gap)]
        for x,y,w,h in obstacles:free0=_carve(free0,x,y,w+gap,h+gap)
    import random,time
    n=range(len(sizes))
    orders=[sorted(n,key=lambda i:(-sizes[i][0]*sizes[i][1],i)),sorted(n,key=lambda i:(-max(sizes[i]),-min(sizes[i]),i)),
            sorted(n,key=lambda i:(-(sizes[i][0]+sizes[i][1]),i)),sorted(n,key=lambda i:(-sizes[i][1],-sizes[i][0],i)),
            sorted(n,key=lambda i:(-sizes[i][0],-sizes[i][1],i))]
    rules=('BSSF','BAF','BLSF','BL')
    for o in orders:
        for r in rules:
            out=_maxrects(sizes,o,avail,gap,r,rot_ok,free0)
            if out:return out
    rng=random.Random(len(sizes));t0=time.time();k=0
    while time.time()-t0<budget:
        base=orders[k%len(orders)];pos={v:j for j,v in enumerate(base)}
        o=sorted(base,key=lambda v:pos[v]+rng.gauss(0,2.5))
        out=_maxrects(sizes,o,avail,gap,rules[k%4],rot_ok,free0);k+=1
        if out:return out
    return None


def _maxrects(sizes,order,avail,gap,rule,rot_ok=True,free0=None):
    """One MaxRects attempt. Each box may be rotated 90°. Returns None on failure."""
    free=list(free0) if free0 else [(0,0,avail+gap,avail+gap)];out=[None]*len(sizes)
    for i in order:
        best=None
        for rot in ((0,1) if rot_ok else (0,)):
            w,h=(sizes[i][1],sizes[i][0]) if rot else sizes[i]
            w+=gap;h+=gap
            for fx,fy,fw,fh in free:
                if w<=fw and h<=fh:
                    if rule=='BSSF':key=(min(fw-w,fh-h),max(fw-w,fh-h),rot)
                    elif rule=='BLSF':key=(max(fw-w,fh-h),min(fw-w,fh-h),rot)
                    elif rule=='BAF':key=(fw*fh-w*h,min(fw-w,fh-h),rot)
                    else:key=(fy+h,fx,rot)
                    if best is None or key<best[0]:best=(key,fx,fy,w,h,rot)
        if best is None:return None
        _,x,y,w,h,rot=best;out[i]=(x,y,w-gap,h-gap,rot)
        nf=[]
        for fx,fy,fw,fh in free:
            if x>=fx+fw or x+w<=fx or y>=fy+fh or y+h<=fy:nf.append((fx,fy,fw,fh));continue
            if x>fx:nf.append((fx,fy,x-fx,fh))
            if x+w<fx+fw:nf.append((x+w,fy,fx+fw-x-w,fh))
            if y>fy:nf.append((fx,fy,fw,y-fy))
            if y+h<fy+fh:nf.append((fx,y+h,fw,fy+fh-y-h))
        free=[r for k,r in enumerate(nf) if not any(k!=j and r[0]>=o[0] and r[1]>=o[1] and r[0]+r[2]<=o[0]+o[2] and r[1]+r[3]<=o[1]+o[3] and (r!=o or j<k) for j,o in enumerate(nf))]
    return out


def pack_rotatable(sizes,avail,gap):
    """Run MaxRects with several orders/rules and return the first successful layout: [(x,y,w,h,rotated)]."""
    n=range(len(sizes))
    orders=[sorted(n,key=lambda i:(-sizes[i][0]*sizes[i][1],i)),
            sorted(n,key=lambda i:(-max(sizes[i]),-min(sizes[i]),i)),
            sorted(n,key=lambda i:(-(sizes[i][0]+sizes[i][1]),i)),
            sorted(n,key=lambda i:(-sizes[i][1],-sizes[i][0],i)),
            sorted(n,key=lambda i:(-sizes[i][0],-sizes[i][1],i))]
    for order in orders:
        for rule in ('BSSF','BAF','BL'):
            out=_maxrects(sizes,order,avail,gap,rule)
            if out:return out
    return None


def optimal_fill_layout(rects,res,pad,gap):
    """Scale everything up by the same factor as far as possible while keeping relative sizes, allowing 90° rotation only inside the texture, to fill the canvas.
    Returns: (new rects, set of rotated indices, scale) or None."""
    base=[(c-a,d-b) for a,b,c,d in rects]
    if not base:return None
    avail=res-2*pad;gap=max(0,int(gap))
    total=sum(w*h for w,h in base)
    hi=min(math.sqrt(avail*avail/total),avail/max(min(w,h) for w,h in base))*1.001;lo=0.;best=None
    def attempt(k):
        sizes=[(max(2,round(w*k)),max(2,round(h*k))) for w,h in base]
        if any(min(s)>avail for s in sizes):return None
        out=pack_rotatable(sizes,avail,gap)
        return (k,out) if out else None
    for _ in range(26):
        mid=(lo+hi)/2;got=attempt(mid)
        if got:lo=mid;best=got
        else:hi=mid
        if hi-lo<1e-4:break
    if best is None:return None
    k,out=best
    x0=min(o[0] for o in out);y0=min(o[1] for o in out);x1=max(o[0]+o[2] for o in out);y1=max(o[1]+o[3] for o in out)
    dx=pad+(avail-(x1-x0))//2-x0;dy=pad+(avail-(y1-y0))//2-y0
    new=[[x+dx,y+dy,x+dx+w,y+dy+h] for x,y,w,h,r in out]
    return new,{i for i,o in enumerate(out) if o[4]},k


def convert_layout_resolution(rects,turns,old_res,new_res,gap):
    """When switching output resolution (2K<->4K), keep poster sizes (px = mm × density) and only move the layout.
    If the current layout fits as is, center it; otherwise re-pack allowing rotation inside the texture.
    Returns: (rects, turns, repacked) or None (does not fit at all)."""
    pad=max(4,round(4*new_res/2048));avail=new_res-2*pad
    turns=list(turns) if turns else [0]*len(rects)
    if not rects:return [],turns,False
    x0=min(r[0] for r in rects);y0=min(r[1] for r in rects);x1=max(r[2] for r in rects);y1=max(r[3] for r in rects)
    if x1-x0<=avail and y1-y0<=avail:
        dx=pad+(avail-(x1-x0))//2-x0;dy=pad+(avail-(y1-y0))//2-y0
        return [[a+dx,b+dy,c+dx,d+dy] for a,b,c,d in rects],turns,False
    sizes=[(c-a,d-b) for a,b,c,d in rects]
    out=pack_rotatable(sizes,avail,max(0,int(gap or 0)))
    if not out:return None
    x0=min(o[0] for o in out);y0=min(o[1] for o in out);x1=max(o[0]+o[2] for o in out);y1=max(o[1]+o[3] for o in out)
    dx=pad+(avail-(x1-x0))//2-x0;dy=pad+(avail-(y1-y0))//2-y0
    new=[[x+dx,y+dy,x+dx+w,y+dy+h] for x,y,w,h,r in out]
    return new,[(t+1)%4 if o[4] else t for t,o in zip(turns,out)],True


def move_layout_group(rects,horizontal,vertical,width,height,pad,gap=None,selected=None):
    """Compact each rectangle along the requested axes, retaining size/order."""
    if not rects:return []
    selected=set(range(len(rects))) if selected is None else set(selected)
    if not selected:return [list(r) for r in rects]
    left=min(rects[i][0] for i in selected);right=max(rects[i][2] for i in selected)
    bottom=min(rects[i][1] for i in selected);top=max(rects[i][3] for i in selected)
    if horizontal==vertical==0:
        dx=round((width-left-right)/2);dy=round((height-bottom-top)/2)
        moved=[[a+dx,b+dy,c+dx,d+dy] if i in selected else [a,b,c,d] for i,(a,b,c,d) in enumerate(rects)]
        for i in selected:
            for j in set(range(len(rects)))-selected:
                if layout_conflicts([moved[i],moved[j]],max(0,gap or 0)/2):raise ValueError('Overlaps an unselected image. Please move in another direction.')
        return moved
    gap=max(0,2*pad if gap is None else round(gap))
    moved=[list(r) for r in rects]
    def compact(axis,direction,limit):
        perpendicular=1-axis;placed=[]
        order=sorted(selected,key=lambda i:(moved[i][axis] if direction<0 else -moved[i][axis+2],i))
        for i in order:
            r=moved[i];length=r[axis+2]-r[axis]
            position=pad if direction<0 else limit-pad-length
            frozen=[j for j in range(len(moved)) if j not in selected and (moved[j][axis]<r[axis+2] if direction<0 else moved[j][axis+2]>r[axis])]
            for j in placed+frozen:
                other=moved[j]
                # Spacing belongs to the movement axis. Increasing it must not
                # turn a separate row/column into a blocker across that axis.
                if r[perpendicular]<other[perpendicular+2] and r[perpendicular+2]>other[perpendicular]:
                    position=max(position,other[axis+2]+gap) if direction<0 else min(position,other[axis]-gap-length)
            if position<pad or position+length>limit-pad:
                raise ValueError('Not enough space to gather at the given spacing. Reduce the spacing or the image size.')
            r[axis]=position;r[axis+2]=position+length;placed.append(i)
    for _ in range(len(rects)+2 if horizontal and vertical else 1):
        before=[list(r) for r in moved]
        if horizontal:compact(0,horizontal,width)
        if vertical:compact(1,vertical,height)
        if before==moved:break
    return moved


def remove_earlier_cuts(s,sheet,keep_folder):
    """Take pieces of an earlier cut of the same sheet out of the texture list (files stay on disk). Returns how many."""
    want=os.path.normcase(os.path.abspath(bpy.path.abspath(sheet)));src={};rows=[]
    for k,f in enumerate(s.files):
        d=os.path.dirname(os.path.abspath(bpy.path.abspath(f.path)))
        if not os.path.basename(d).startswith('Cut_') or os.path.normcase(d)==os.path.normcase(keep_folder):continue
        if d not in src:
            try:
                with open(os.path.join(d,'cut_regions.json'),encoding='utf-8') as fh:src[d]=os.path.normcase(os.path.abspath(json.load(fh).get('source','')))
            except (OSError,ValueError):src[d]=None
        if src[d]==want:rows.append(k)
    for k in reversed(rows):s.files.remove(k)
    if rows:s.active=max(0,min(s.active,len(s.files)-1))
    return len(rows)


def export_cuts(path,rects,parent,source_name=None,key_green=False,shadows=False):
    parent=os.path.abspath(bpy.path.abspath(parent))
    if not os.path.isdir(parent):os.makedirs(parent,exist_ok=True)
    token=uuid.uuid4().hex[:10];folder=os.path.join(parent,'Cut_'+token);os.makedirs(folder)
    paths=[]
    try:
        pixels=read_pixels(path);h,w=pixels.shape[:2]
        name=os.path.splitext(os.path.basename(source_name or path))[0][:80]
        for i,rect in enumerate(rects):
            x0,y0,x1,y1=map(int,rect)
            if not (0<=x0<x1<=w and 0<=y0<y1<=h):raise ValueError('The cut region is outside the image bounds.')
            out=os.path.join(folder,'%s_%03d.png'%(name,i+1))
            piece=pixels[y0:y1,x0:x1].copy()
            if key_green:   # Chroma-key green becomes transparent; reduce green spill at the edges
                m=background_mask(piece,shadows);piece[m,3]=0.
                g=piece[...,1];cap=np.maximum(piece[...,0],piece[...,2])+.06
                spill=(~m)&(g>cap);piece[spill,1]=cap[spill]
            im=save_atlas(out,piece,False)
            bpy.data.images.remove(im);paths.append(out)
        with open(os.path.join(folder,'cut_regions.json'),'w',encoding='utf-8') as f:
            json.dump({'source':path,'original_size':[w,h],'coordinate_origin':'bottom_left','rectangles':rects,'files':[os.path.basename(p) for p in paths]},f,ensure_ascii=False,indent=2)
        return paths,folder
    except Exception:
        if os.path.dirname(folder)==parent and os.path.basename(folder)=='Cut_'+token:shutil.rmtree(folder)
        raise


class PA_OT_cut(bpy.types.Operator):
    bl_idname='poster_atlas.cut';bl_label=_T('Cut Images by Dragging')
    bl_description=_T('Opens the selected image large to adjust cut boxes. Applying saves individual PNGs and adds them to the list.')
    bl_options={'UNDO'}
    preview_only:BoolProperty(default=False,options={'HIDDEN','SKIP_SAVE'})
    layout_mode:BoolProperty(default=False,options={'HIDDEN','SKIP_SAVE'})

    @classmethod
    def poll(cls,context):
        s=context.scene.poster_atlas
        return bool(context.area and context.area.type=='VIEW_3D' and (len(s.files) or len(s.cut_files)))

    def invoke(self,context,event):
        s=context.scene.poster_atlas
        if CUT_EDITORS:
            self.report({'WARNING'},_T('Please close the open cut editor first.'));return {'CANCELLED'}
        if self.layout_mode:return self.invoke_layout(context,event)
        if not self.preview_only and not (s.cut_output_dir.strip() or s.output_dir.strip()):
            self.report({'ERROR'},_T('Please choose a folder for cut PNGs under Image Cutting.'));return {'CANCELLED'}
        self.from_cut=not self.preview_only   # Cutting comes from the [Images to Cut] list, large view from the texture list
        pool=s.cut_files if self.from_cut else s.files
        if not len(pool):
            self.report({'ERROR'},_T('Please add images to cut in the [Images to Cut] tab first.' if self.from_cut else 'Please add images.'));return {'CANCELLED'}
        self.source_index=max(0,min(s.cut_active if self.from_cut else s.active,len(pool)-1))
        self.im=None;self.handler=None
        try:
            self.path=file_path(pool[self.source_index])
            self.im=bpy.data.images.load(self.path,check_existing=False);self.w,self.h=self.im.size[:]
            if self.w<1 or self.h<1:raise ValueError('Cannot read the image.')
            self.rects=[] if self.preview_only else cut_grid(self.w,self.h,s.cut_columns,s.cut_rows)
            import gpu
            self.texture=editor_texture(self.im)
        except Exception as exc:
            if self.im:bpy.data.images.remove(self.im)
            self.report({'ERROR'},_T(str(exc)));return {'CANCELLED'}
        self.area=context.area;self.region=next(r for r in self.area.regions if r.type=='WINDOW')
        self.win=context.window;self.workspace=context.workspace;self.settings=s
        self.zoom=1.;self.pan=[0.,0.];self.selected=0;self.drag=None;self.panning=None;self.space_pan=False;self.history=[];self.closed=False
        self.handler=bpy.types.SpaceView3D.draw_handler_add(self.draw_overlay,(),'WINDOW','POST_PIXEL')
        CUT_EDITORS.append(self)
        context.window_manager.modal_handler_add(self)
        self.workspace.status_text_set('Image preview: Wheel = Zoom / Middle button = Pan / ← → = Previous·Next / Enter or Esc = Close' if self.preview_only else 'Poster cutting: Drag corners·edges = Resize / Drag inside = Move / Wheel = Zoom / Middle button = Pan / Enter = Apply / Esc = Cancel')
        self.area.tag_redraw();return {'RUNNING_MODAL'}

    def invoke_layout(self,context,event):
        import gpu
        s=context.scene.poster_atlas
        PANEL_OPEN['sec:Text']=False   # Text starts closed every time the editor opens
        try:self.paths=[file_path(f) for f in build_files(s)]
        except Exception as exc:self.report({'ERROR'},_T(str(exc)));return {'CANCELLED'}
        if not self.paths:
            self.report({'ERROR'},_T('Please check images to use or select all images.'));return {'CANCELLED'}
        self.images=[];self.textures=[];self.im=None;self.texture=None;self.handler=None;self.closed=False
        try:
            for path in self.paths:
                im=bpy.data.images.load(path,check_existing=False);self.images.append(im)
                if min(im.size)<1:raise ValueError('Cannot read the image: '+os.path.basename(path))
                self.textures.append(editor_texture(im,EDITOR_MAX_SIDE))
            self.w=self.h=int(s.resolution);self.pad=max(4,round(4*self.w/2048))
            self.sizes=[tuple(im.size) for im in self.images]
            self.rects=initial_layout(s,self.sizes)
            self.physical_sizes=[None]*len(self.rects)
            self.layout_rotations=[0]*len(self.rects)
            self.crops=[[0.,0.,1.,1.] for _ in self.rects]
            self.applied_crops=[[0.,0.,1.,1.] for _ in self.rects]
            self.effects=[None]*len(self.rects)
            try:
                saved=json.loads(s.layout_plan)
                # If reopened after changing resolution in the panel, keep the previous layout and move it over
                if saved.get('paths')==self.paths and saved.get('resolution')!=self.w and len(saved.get('rects',[]))==len(self.paths):
                    conv=convert_layout_resolution(saved['rects'],saved.get('rotations') or [0]*len(self.paths),saved['resolution'],self.w,s.layout_gap)
                    if conv:saved['rects'],saved['rotations'],_=conv;saved['resolution']=self.w
                if saved['paths']==self.paths and saved['resolution']==self.w and len(saved['rects'])==len(self.paths):
                    if all(len(r)==4 and self.pad<=r[0]<r[2]<=self.w-self.pad and self.pad<=r[1]<r[3]<=self.h-self.pad for r in saved['rects']):
                        self.rects=saved['rects']
                        physical=saved.get('physical_sizes',[])
                        if len(physical)==len(self.rects):self.physical_sizes=physical
                        rotations=saved.get('rotations',[])
                        if len(rotations)==len(self.rects) and all(type(v)==int and 0<=v<4 for v in rotations):self.layout_rotations=rotations
                        crops=saved.get('crops',[])
                        if len(crops)==len(self.rects) and all(len(c)==4 and 0<=c[0]<c[2]<=1 and 0<=c[1]<c[3]<=1 for c in crops):self.crops=crops
                        applied=saved.get('applied_crops',[])
                        if len(applied)==len(self.rects) and all(len(c)==4 and 0<=c[0]<c[2]<=1 and 0<=c[1]<c[3]<=1 for c in applied):self.applied_crops=applied
                        effects=saved.get('effects',[])
                        if len(effects)==len(self.rects):self.effects=[fx_clean(f) if f else None for f in effects]
            except (ValueError,KeyError,TypeError):pass
        except Exception as exc:
            self.textures.clear()
            for im in self.images:bpy.data.images.remove(im)
            self.report({'ERROR'},_T(str(exc)));return {'CANCELLED'}
        self.area=context.area;self.region=next(r for r in self.area.regions if r.type=='WINDOW')
        self.win=context.window;self.workspace=context.workspace;self.settings=s
        self.zoom=1.;self.pan=[0.,0.];self.selected=0;self.drag=None;self.panning=None;self.space_pan=False;self.history=[]
        self.selection={0} if self.rects else set();self.marquee=None;self.box_select=False;self.group_drag=None
        self.fx_previews={};self.fx_src={};self.fx_preview_on=True;self.fx_jitter=True;self.fx_clipboard=None
        self.paper_snap={k:getattr(s,k) for k in PAPER_KEYS};s.paper_auto=False   # Paper crumple is off by default
        self.fx_pending=None;self.fx_focus=None;self.list_snap=self.list_snapshot()   # for Ctrl+Z of image-list changes
        self.handler=bpy.types.SpaceView3D.draw_handler_add(self.draw_overlay,(),'WINDOW','POST_PIXEL')
        CUT_EDITORS.append(self);context.window_manager.modal_handler_add(self)
        self.workspace.status_text_set('Texture layout: Space + Left drag or Middle drag = Pan / Wheel = Zoom / Home = Frame all / Ctrl Z = Undo / Enter = Build / Esc = Close editor')
        self.area.tag_redraw();return {'RUNNING_MODAL'}

    def layout_spec(self):
        return {'paths':self.paths,'rects':[list(r) for r in self.rects],'resolution':self.w,
                'physical_sizes':getattr(self,'physical_sizes',[None]*len(self.rects)),
                'crops':getattr(self,'crops',[[0.,0.,1.,1.] for _ in self.rects]),
                'applied_crops':getattr(self,'applied_crops',[[0.,0.,1.,1.] for _ in self.rects]),
                'rotations':getattr(self,'layout_rotations',[0]*len(self.rects)),
                'effects':[dict(f) if f else None for f in getattr(self,'effects',[None]*len(self.rects))]}

    def remember_layout(self):
        self.fx_last=None   # a new undo step = the last effect is locked in
        self.history.append({'rects':[list(r) for r in self.rects],
                             'edit_mode':self.settings.edit_mode,
                             'selection':sorted(getattr(self,'selection',{self.selected})),
                             'applied_crops':[list(c) for c in getattr(self,'applied_crops',[[0.,0.,1.,1.] for _ in self.rects])],
                             'crops':[list(c) for c in getattr(self,'crops',[[0.,0.,1.,1.] for _ in self.rects])],
                             'physical_sizes':[list(v) if v else None for v in self.physical_sizes],
                             'rotations':list(getattr(self,'layout_rotations',[0]*len(self.rects))),
                             'effects':[dict(f) if f else None for f in getattr(self,'effects',[None]*len(self.rects))],
                             # Ctrl+Z also restores the effect being chosen, sticky-note random colors and paper crumple settings
                             'pending':self._pending_copy(),'pool':self.settings.postit_pool,
                             'paper':{k:getattr(self.settings,k) for k in PAPER_KEYS}})
        self.history=self.history[-40:]

    def _pending_copy(self):
        p=getattr(self,'fx_pending',None)
        if not p:return None
        return {k:(list(v) if isinstance(v,list) else dict(v) if isinstance(v,dict) else v) for k,v in p.items() if k not in ('cache','_tset')}

    def set_preset(self,preset,photo=None,per_image=None,label_=None,keep_photo=False):
        """Paper preset (A4 · A3 · Sticky Note) or, with photo=, a Picture format: exact card size, photo cropped
        (never stretched) to fill it, plus the format's white border and the current look."""
        selection=sorted(i for i in getattr(self,'selection',{self.selected}) if 0<=i<len(self.rects))
        if not selection:return
        mode=self.settings.edit_mode;prepared={}
        crops=getattr(self,'crops',[[0.,0.,1.,1.] for _ in self.rects])
        bases=getattr(self,'applied_crops',[[0.,0.,1.,1.] for _ in self.rects])
        turns=getattr(self,'layout_rotations',[0]*len(self.rects))
        # Compute the entire batch before changing anything; each image retains
        # its own source ratio, committed crop, and atlas-only rotation.
        if photo:   # remember each picture's own size before its first card, so Format · Off can give it back
            if not hasattr(self,'photo_orig'):self.photo_orig={}
            for i in selection:
                if not self.photo_get(i):self.photo_orig[self.paths[i]]={'mm':self.physical_sizes[i],'crop':list(crops[i]),'rect':list(self.rects[i])}
        if per_image:selection=[i for i in selection if i in per_image]
        elif hasattr(self,'rand_base'):   # a new preset / size becomes the new base for Random Size
            for i in selection:self.rand_base.pop(self.paths[i],None)
        for i in selection:
            base=bases[i];size=crop_size(self.sizes[i],base);p_=per_image[i] if per_image else preset
            if photo:
                mw,mh,_=PHOTO_FORMATS[photo]
                if photo.startswith('Print') and size[0]>size[1]:mw,mh=mh,mw   # prints turn with the photo, instant cards don't
                p_=(mw,mh)
            rect,physical=preset_layout_rect(self.rects[i],size,p_,
                layout_density(self.settings),self.w,self.pad,turns[i],exact=bool(photo) or mode!='FIT')
            crop=crop_map(cover_crop(size,physical,crop_map(crops[i],base,True)),base) if mode=='CROP' else list(base)   # photo cards: Scale / Keep Ratio keep the whole photo (fitted in the card window)
            prepared[i]=[rect,physical,crop]
        # Resized selections replace their old footprints together. Only the
        # unselected images and already placed new footprints reserve space.
        chosen=set(selection);occupied=[r for j,r in enumerate(self.rects) if j not in chosen]
        order=sorted(selection,key=lambda i:-(prepared[i][0][2]-prepared[i][0][0])*(prepared[i][0][3]-prepared[i][0][1]))
        crowded=0
        for i in order:
            rect=prepared[i][0]
            free=vacant_layout_rect(rect,occupied,self.w,self.pad,self.settings.layout_gap)
            if free is not None:prepared[i][0]=free
            else:crowded+=1
            occupied.append(prepared[i][0])
        self.remember_layout()
        self.crops=[list(c) for c in crops]
        for i,(rect,physical,crop) in prepared.items():
            self.rects[i]=rect;self.physical_sizes[i]=physical;self.crops[i]=crop
        if photo:self.photo_set(selection,fmt=photo)
        elif not keep_photo:   # Paper size on a photo card: keep the card, border in proportion, now a custom-size card
            for i in [i for i in selection if (self.photo_get(i) or {}).get('frame')]:
                fm=list((self.photo_get(i) or {}).get('frame_m') or []);ph=self.physical_sizes[i] if i<len(self.physical_sizes) else None
                if fm and ph:self.photo_set([i],fmt=None,margins=[v*min(ph) for v in fm])
        self.drag=None;self.group_drag=None;self.area.tag_redraw()
        label=label_ or photo or (preset if isinstance(preset,str) else 'Custom size')
        message='Applied to %d selected: %s'%(len(selection),label)
        if crowded:message+=' · %d lack free space: please adjust the overlap.'%crowded
        self.report({'WARNING'} if crowded else {'INFO'},_T(message))

    def random_sizes(self):
        """Random Size: every selected image gets its own size within ± random_size_pct of its base size (ratio kept).
        The base is the size it had before the first Random Size, so repeated clicks reshuffle instead of drifting."""
        import random as _rnd
        selection=sorted(i for i in getattr(self,'selection',{self.selected}) if 0<=i<len(self.rects))
        if not selection:self.report({'WARNING'},_T('Select images first · A selects all'));return
        if not hasattr(self,'rand_base'):self.rand_base={}
        dens=layout_density(self.settings);turns=getattr(self,'layout_rotations',[0]*len(self.rects));pct=self.settings.random_size_pct/100.
        targets={}
        for i in selection:
            key=self.paths[i];b=self.rand_base.get(key)
            if b is None:
                ph=self.physical_sizes[i] if i<len(self.physical_sizes) else None
                if ph:b=list(ph)
                else:
                    a,b0,c,d=self.rects[i];w_,h_=(c-a)/dens,(d-b0)/dens
                    b=[h_,w_] if turns[i]%2 else [w_,h_]
                self.rand_base[key]=b
            k=1+_rnd.uniform(-pct,pct);targets[i]=(b[0]*k,b[1]*k)
        self.set_preset(None,per_image=targets,label_='Random Size ±%d%%'%self.settings.random_size_pct)

    def snap_move(self,rect,dx,dy,scale,locked=False):
        """Snap (B while moving): the moved image (or block) sticks its edges to other images' edges -
        side by side at the Spacing distance, or lined up with them - and to the canvas border. Corners = both axes snapped."""
        base=list(self.group_drag.values()) if self.group_drag else [rect];moving=set(self.group_drag) if self.group_drag else {self.selected}
        x0=min(r[0] for r in base);y0=min(r[1] for r in base);x1=max(r[2] for r in base);y1=max(r[3] for r in base);bw,bh=x1-x0,y1-y0
        g=self.settings.layout_gap;thr=12./max(scale,1e-6);others=[r for j,r in enumerate(self.rects) if j not in moving]
        def best(pos,size,lo_i,hi_i,lim):
            cands=[(self.pad,None),(lim-self.pad-size,None)]
            for r in others:
                a,b=r[lo_i],r[hi_i]
                cands+=[(b+g,b),(a-g-size,a),(a,a),(b-size,b)]   # beside (gap) / lined up
            got=min(cands,key=lambda c:abs(c[0]-pos))
            return got if abs(got[0]-pos)<=thr else None
        gs=[]
        if not (locked and dx==0.):
            bx=best(x0+dx,bw,0,2,self.w)
            if bx:dx=bx[0]-x0;gs.append(('X',bx[1] if bx[1] is not None else bx[0]))
        if not (locked and dy==0.):
            by=best(y0+dy,bh,1,3,self.h)
            if by:dy=by[0]-y0;gs.append(('Y',by[1] if by[1] is not None else by[0]))
        self.snap_guides=gs;return dx,dy

    def copy_size_selected(self):
        """Copy Size: every other selected image takes the active image's size (mm). Edit Mode decides how a different ratio fits."""
        sel=sorted(i for i in getattr(self,'selection',{self.selected}) if 0<=i<len(self.rects))
        src=self.selected
        if not 0<=src<len(self.rects) or len([i for i in sel if i!=src])<1:
            self.report({'WARNING'},_T('Click the image whose size you want, then Shift+click the images to change (or A for all), then Copy Size'));return
        dens=layout_density(self.settings);turns=getattr(self,'layout_rotations',[0]*len(self.rects))
        ph=self.physical_sizes[src] if src<len(self.physical_sizes) else None
        if ph:w_,h_=ph
        else:
            a,b,c,d=self.rects[src];w_,h_=(c-a)/dens,(d-b)/dens
            if turns[src]%2:w_,h_=h_,w_
        targets={i:(w_,h_) for i in sel if i!=src}
        for i in targets:
            if hasattr(self,'rand_base'):self.rand_base.pop(self.paths[i],None)
        self.set_preset(None,per_image=targets,label_='Copy Size of #%d (%.0f × %.0f mm)'%(src+1,w_,h_))

    def size_reset_selected(self):
        """Layout header · Reset: the selected images go back to their starting size (as when first laid out).
        Effects, photo cards (border kept in proportion) and crops stay. Ctrl+Z undoes it."""
        sel=sorted(i for i in getattr(self,'selection',{self.selected}) if 0<=i<len(self.rects))
        if not sel:self.report({'WARNING'},_T('Select images first · A selects all'));return
        turns=getattr(self,'layout_rotations',[0]*len(self.rects))
        sizes=[(size[0]*(c[2]-c[0]),size[1]*(c[3]-c[1])) for size,c in zip(self.sizes,self.crops)]
        oriented=[sz[::-1] if t%2 else sz for sz,t in zip(sizes,turns)]
        base=initial_layout(self.settings,oriented);den=layout_density(self.settings);targets={}
        for i in sel:
            a,b,c,d=base[i];w_,h_=(c-a)/den,(d-b)/den
            targets[i]=(h_,w_) if turns[i]%2 else (w_,h_)
            if hasattr(self,'rand_base'):self.rand_base.pop(self.paths[i],None)
        self.set_preset(None,per_image=targets,label_='Reset size')

    def scale_selected(self,sel,k):
        """S: every selected image k times its current size (ratio kept); then re-packed like a preset."""
        dens=layout_density(self.settings);turns=getattr(self,'layout_rotations',[0]*len(self.rects));targets={}
        # Photo cards scale too: border kept in proportion, the card becomes a custom size (no fixed format)
        cards={i:list((self.photo_get(i) or {}).get('frame_m') or []) for i in sel if (self.photo_get(i) or {}).get('frame')}
        for i in sel:
            ph=self.physical_sizes[i] if i<len(self.physical_sizes) else None
            if ph:b=list(ph)
            else:
                a,b0,c,d=self.rects[i];w_,h_=(c-a)/dens,(d-b0)/dens
                b=[h_,w_] if turns[i]%2 else [w_,h_]
            targets[i]=(b[0]*k,b[1]*k)
            if hasattr(self,'rand_base'):self.rand_base.pop(self.paths[i],None)   # The new size is the new base for Random Size
        sel_old=getattr(self,'selection',None);self.selection=set(sel)
        try:self.set_preset(None,per_image=targets,label_='Scale %d%%'%round(k*100)+(' · %d photo card%s now custom size'%(len(cards),'' if len(cards)==1 else 's') if cards else ''),keep_photo=True)
        finally:
            if sel_old is not None:self.selection=sel_old
        for i,fm in cards.items():   # Same border share of the (new) card's short side, saved as a custom border
            ph=self.physical_sizes[i] if i<len(self.physical_sizes) else None
            if ph and fm:self.photo_set([i],fmt=None,margins=[v*min(ph) for v in fm])

    def photo_aspect(self,i):
        """Width/height of image i as shown (applied crop + layout rotation): Keep Ratio uses it inside the card window."""
        try:
            w_,h_=crop_size(self.sizes[i],getattr(self,'applied_crops',[[0.,0.,1.,1.]]*len(self.rects))[i])
            if getattr(self,'layout_rotations',[0]*len(self.rects))[i]%2:w_,h_=h_,w_
            return float(w_)/max(float(h_),1e-6)
        except Exception:return None

    def photo_get(self,i):
        """Values of image i's Picture layer (format, border, look), or None."""
        if not (0<=i<len(self.effects)) or not self.effects[i]:return None
        for l in fx_layers(self.effects[i]):
            if l['id'] in ('PHOTO','POLAROID'):
                v=dict(l['values'])
                if l['id']=='POLAROID':v.setdefault('photo_fmt','Instant Classic')
                return v
        return None

    def photo_set(self,indices,fmt=KEEP,look=KEEP,frame=KEEP,margins=KEEP,finish=KEEP,caption=KEEP,look_k=KEEP):
        """Change the Picture layer of these images. KEEP leaves that part as it is. look=None = no look,
        frame=False = no border, margins = custom border (side, top, bottom) in mm, finish = (photo roughness,
        border roughness, metallic). Other effects stay; the layer goes away when nothing is left."""
        for i in indices:
            f=self.effects[i];cur=self.photo_get(i) or {}
            fmt_=cur.get('photo_fmt') if fmt is KEEP else fmt
            if look is KEEP:   # a format only changes the card: the photo's colors stay until a Look is picked
                look_=(cur.get('pol_style','CLASSIC') if cur.get('polaroid') else None) if cur else None
            else:look_=look
            if frame is KEEP:frame_=bool(cur.get('frame')) if cur else (bool(fmt_) and getattr(self,'photo_frame_last',True))
            else:frame_=bool(frame)
            if finish is KEEP:fin=(cur.get('p_rough'),cur.get('f_rough'),cur.get('p_metal')) if cur.get('p_rough') is not None else None
            else:fin=finish
            if fin is None and (look_ or frame_):   # a new card keeps the Surface the image already had (Matte if none)
                sv_=fx_clean(f).get('s_rough') if f else None
                fin=PHOTO_FINISHES[next((k for k,(_,v) in PAPER_FINISHES.items() if sv_ is not None and abs(v-sv_)<1e-4),'MATTE')][1]
            cap_=(cur.get('caption',''),cur.get('cap_font','INK'),cur.get('cap_ink','BLACK')) if caption is KEEP else caption   # (text, font, ink)
            layers=[l for l in fx_layers(f) if l['id'] not in ('PHOTO','POLAROID')]
            if look_ or frame_ or fin is not None:
                card=self.physical_sizes[i] if i<len(self.physical_sizes) and self.physical_sizes[i] else None
                short=min(card) if card else None
                if margins is not KEEP and margins is not None and short:m=[max(0.,v)/short for v in margins];custom=True
                elif fmt is KEEP and cur.get('frame_custom') and cur.get('frame_m'):m=list(cur['frame_m']);custom=True
                elif fmt_ in PHOTO_FORMATS:mw,mh,mm=PHOTO_FORMATS[fmt_];m=[v/min(mw,mh) for v in mm];custom=False
                else:m=[.045,.045,.045];custom=False   # plain even white border
                name='Photo'+(' · '+fmt_ if fmt_ else '')+(' · '+dict(POL_STYLE_NAMES)[look_] if look_ else '')
                k_=float(look_k) if look_k is not KEEP else (float(cur.get('polaroid')) if cur.get('polaroid') else LOOK_K[FX_START_LOOK])
                layers.append({'id':'PHOTO','name':name,'count':1,'values':{'polaroid':k_ if look_ else 0.,'pol_style':look_ or 'CLASSIC',
                               'frame':1. if frame_ else 0.,'frame_m':m if frame_ else None,'frame_custom':custom,'photo_fmt':fmt_,
                               'p_rough':float(fin[0]),'f_rough':float(fin[1]),'p_metal':float(fin[2]),
                               'caption':cap_[0] if frame_ else '','cap_font':cap_[1],'cap_ink':cap_[2],
                               'photo_fit':self.settings.edit_mode if (fmt is not KEEP or not cur.get('photo_fit')) else cur.get('photo_fit'),'src_aspect':self.photo_aspect(i)}})
            g=fx_flatten(layers,f)
            if g and not g['seed']:g['seed']=fx_seed(g,self.paths[i])
            self.effects[i]=g
        self.fx_clear_previews(set(indices))

    def build_where_lines(self):
        """[(kind, text, group)] for the Finish area: the destination, then each group and where it ends up."""
        st=self.settings
        try:
            prev=st.last_collection if st.update_previous else None
            act_=getattr(bpy.context.view_layer,'active_layer_collection',None)
            key=(len(bpy.data.collections),tuple((f.group,f.selected) for f in st.files),act_.collection.name if act_ else '',prev.name if prev else '',st.batch_name)
            if getattr(self,'_where_key',None)==key:return self._where
            if prev is not None:
                par=next((p for p in bpy.data.collections if prev.name in p.children and not p.get('poster_groups_root') and not p.get('poster_shared_group')),None)
                dest,base=(par.name if par else 'Scene'),prev.name
            else:
                d=build_destination(bpy.context)
                dest=d.name if d else 'Scene Collection'
                base=st.batch_name.strip() or batch_names(batch_number(None),batch_groups(st))[0]
            out=[('main','Goes into:  %s  ›  %s'%(dest,base),'')]
            cnt={}
            for f in build_files(st):
                g=f.group.strip()
                if g:cnt[g]=cnt.get(g,0)+1
            gl=batch_groups(st)
            for g in gl[:4]:
                uc=user_group_collection(g)
                out.append(('group',('%s · %d  →  %s'%(g,cnt[g],uc.name)) if uc else '%s · %d'%(g,cnt[g]),g))
            if len(gl)>4:out.append(('dim','… %d more groups'%(len(gl)-4),''))
        except Exception:out=[]
        self._where_key=key if 'key' in locals() else None;self._where=out
        return out

    def look_state(self):
        """(look style or None, strength) of the poster shown in the panel."""
        ph=self.photo_get(self.selected) if self.rects else None
        if ph and ph.get('polaroid'):return ph.get('pol_style','CLASSIC'),float(ph['polaroid'])
        return None,0.

    def look_targets(self):
        return [i for i in self.fx_targets() if 0<=i<len(self.rects)]

    def fx_on(self,pid):
        """Is this effect on the selected posters (applied, or being previewed)?"""
        p=getattr(self,'fx_pending',None)
        if p and p['id']==pid:return True
        return any(l['id']==pid for i in (self.fx_targets() if self.rects else []) if 0<=i<len(self.effects) for l in fx_layers(self.effects[i]))

    def surface_key(self,i):
        """What Surface shows for image i on both tabs: the photo card's finish if it has one, else the paper's."""
        ph=self.photo_get(i) or {}
        if ph.get('p_rough') is not None:
            fv=(ph['p_rough'],ph.get('f_rough') or ph['p_rough'],ph.get('p_metal') or 0.)
            return next((k for k,(_,v) in PHOTO_FINISHES.items() if max(abs(a-b) for a,b in zip(v,fv))<1e-4),'CUSTOM')
        sv=fx_clean(self.effects[i] if 0<=i<len(self.effects) else None).get('s_rough')
        if sv is None:return 'MATTE'
        return next((k for k,(_,v) in PAPER_FINISHES.items() if abs(v-sv)<1e-4),'CUSTOM')

    def surface_set(self,indices,k):
        """Surface button (either tab): photo cards get the photo finish, other images the paper one. One value per image."""
        photos=[i for i in indices if self.photo_get(i)];papers=[i for i in indices if i not in photos]
        if photos:self.photo_set(photos,finish=PHOTO_FINISHES[k][1]);self.paper_surface_set(photos,None)
        if papers:self.paper_surface_set(papers,PAPER_FINISHES[k][1])

    def paper_surface_set(self,indices,rough):
        """Paper tab Surface: roughness of the whole printed sheet (Matte 0.85 = plain paper = no layer)."""
        for i in indices:
            f=self.effects[i];layers=[l for l in fx_layers(f) if l['id']!='SURFACE']
            if rough is not None and abs(float(rough)-PAPER_FINISHES['MATTE'][1])>1e-4:
                nm=next((t for t,v in PAPER_FINISHES.values() if abs(v-rough)<1e-4),'Custom')
                layers.append({'id':'SURFACE','name':'Surface · %s'%nm,'count':1,'values':{'s_rough':float(rough)}})
            g=fx_flatten(layers,f)
            if g and not g['seed']:g['seed']=fx_seed(g,self.paths[i])
            self.effects[i]=g
        self.fx_clear_previews(set(indices))

    def photo_off(self,indices):
        """Format · Off: take the picture treatment away completely (card size, border, look, surface)
        and give the image back its own size and crop."""
        idx=[i for i in indices if self.photo_get(i)]
        if not idx:self.report({'INFO'},_T('The selected images have no Picture settings.'));return
        self.remember_layout();orig=getattr(self,'photo_orig',{});den=layout_density(self.settings)
        self.photo_set(idx,fmt=None,look=None,frame=False,finish=None)
        for i in idx:
            o=orig.get(self.paths[i]);a,b,c,d=self.rects[i];cx,cy=(a+c)/2,(b+d)/2
            if o and o.get('rect'):
                ow,oh=o['rect'][2]-o['rect'][0],o['rect'][3]-o['rect'][1];self.physical_sizes[i]=o.get('mm');self.crops[i]=list(o['crop'])
            else:   # no record: the image's own ratio, as long as the card's long side
                bw,bh=crop_size(self.sizes[i],self.applied_crops[i]);L=max(c-a,d-b);k=L/max(bw,bh,1)
                ow,oh=max(2,round(bw*k)),max(2,round(bh*k));self.physical_sizes[i]=[ow/den,oh/den];self.crops[i]=list(self.applied_crops[i])
            rect=centered_layout_rect([int(cx),int(cy),int(cx),int(cy)],int(ow),int(oh),self.w,self.pad)
            free=vacant_layout_rect(rect,[r for j,r in enumerate(self.rects) if j!=i],self.w,self.pad,self.settings.layout_gap)
            self.rects[i]=free if free is not None else rect
            orig.pop(self.paths[i],None)
        self.fx_clear_previews(set(idx));self.area.tag_redraw()
        self.report({'INFO'},_T('Picture removed from %d image(s) · back to their own size'%len(idx)))

    def discard_session_strips(self):
        """Close without Build: photo strips made in this session go away like every other edit — their list
        entries are removed, the photos they used are checked again and the generated PNGs are deleted."""
        strips=getattr(self,'session_strips',[])
        if not strips:return
        norm=lambda q:os.path.normcase(os.path.abspath(q))
        try:
            files=self.settings.files
            for rec in reversed(strips):
                for k in reversed(range(len(files))):
                    if norm(files[k].path)==norm(rec['path']):files.remove(k)
                src={norm(q) for q in rec['sources']}
                for f in files:
                    try:
                        if norm(file_path(f)) in src:f.selected=True
                    except Exception:pass
                try:os.remove(rec['path'])
                except OSError:pass
            self.settings.active=max(0,min(self.settings.active,len(files)-1))
        except ReferenceError:pass
        self.session_strips=[]

    def photo_border_mm(self,i):
        """Current border of image i in mm (side, top, bottom), from its card size."""
        ph=self.photo_get(i) or {};card=self.physical_sizes[i] if i<len(self.physical_sizes) and self.physical_sizes[i] else None
        m=ph.get('frame_m') or (PHOTO_FORMATS[ph['photo_fmt']][2] and [v/min(PHOTO_FORMATS[ph['photo_fmt']][:2]) for v in PHOTO_FORMATS[ph['photo_fmt']][2]] if ph.get('photo_fmt') in PHOTO_FORMATS else [.045,.045,.045])
        return [v*min(card) for v in m] if card else [4.,4.,4.]

    def make_strip(self):
        """Photo booth strip: the selected photos (in reading order, top-left first) fill a cols×rows grid on one card.
        Saved as a new PNG that replaces them in the layout; the originals stay in the list, just unchecked."""
        st=self.settings;cols,rows=int(st.strip_cols),int(st.strip_rows)
        idx=[i for i in getattr(self,'selection',{self.selected}) if 0<=i<len(self.rects)]
        if not idx:self.report({'WARNING'},_T('Select the photos for the strip first · A selects all'));return
        hs=sorted(self.rects[i][3]-self.rects[i][1] for i in idx);band=max(1.,hs[len(hs)//2]*.6)
        idx.sort(key=lambda i:(-round((self.rects[i][1]+self.rects[i][3])/2/band),self.rects[i][0]))   # top row first, then left to right
        n=cols*rows;Wc,Hc,label=strip_card(cols,rows)
        # Real print sizes (inch photo paper as in Korean four-cut booths); cells share what is left after the border
        m,g,top=3.5,2.6,4.;foot=14. if cols==1 else 18.
        cw_mm=(Wc-2*m-(cols-1)*g)/cols;avail=Hc-top-foot-(rows-1)*g
        stag=.15 if (st.strip_stagger and cols>1) else 0.   # staggered: every other column sits a little lower (room for a logo)
        ch_mm=avail/(rows+stag);drop=ch_mm*stag
        if cw_mm<5 or ch_mm<5:self.report({'WARNING'},_T('Too many cells for a %s card.'%label));return
        W_mm,H_mm=Wc,Hc;den=max(8.,min(24.,900./cw_mm))   # px/mm: about 900 px per cell, at most 24 px/mm
        Wp,Hp=int(round(W_mm*den)),int(round(H_mm*den));cwp=int(round(cw_mm*den));chp=int(round(ch_mm*den))
        frame=np.array((.06,.06,.065) if st.strip_frame=='BLACK' else (.955,.95,.94),np.float32)
        card=np.empty((Hp,Wp,4),np.float32);card[:,:,:3]=frame;card[:,:,3]=1.
        for k in range(n):
            i=idx[k%len(idx)];im=self.images[i];w,h=im.size
            c=self.crops[i] if i<len(getattr(self,'crops',[])) else [0.,0.,1.,1.]
            turn=self.layout_rotations[i] if i<len(getattr(self,'layout_rotations',[])) else 0
            fx_=self.fx_effective(i)
            if fx_active(fx_):   # the photo's effects (paper, crumple, color, damage …) go into its cell, as it looks on the canvas
                a_,b_,c2_,d_=self.rects[i];rw_,rh_=c2_-a_,d_-b_;kk_=max(cwp,chp)*1.25/max(rw_,rh_,1)
                pw_,ph_=max(2,round(rw_*kk_)),max(2,round(rh_*kk_))
                f_=fx_clean(fx_);f_['seed']=fx_seed(f_,self.paths[i]);caption_ensure(f_,pw_ if turn%2 else ph_)
                px=fx_preview_pixels(self.fx_source(i),list(c),turn,pw_,ph_,st.background,f_,layout_density(st)*kk_,fx_resources(st),paper_info(st,f_.get('paper')))
            else:
                px=np.empty(w*h*4,np.float32);im.pixels.foreach_get(px);px=px.reshape(h,w,4)
                x0,x1=int(c[0]*w),max(int(c[0]*w)+1,int(round(c[2]*w)));y0,y1=int(c[1]*h),max(int(c[1]*h)+1,int(round(c[3]*h)))
                px=px[y0:y1,x0:x1]
                if turn:px=np.ascontiguousarray(np.rot90(px,turn,axes=(0,1)))
            rgb=px[:,:,:3]*px[:,:,3:4]+frame*(1-px[:,:,3:4])
            cell=pol_cover(rgb,cwp,chp)
            r_,c_=divmod(k,cols)   # row 0 = top of the strip
            x=int(round((m+c_*(cw_mm+g))*den));ytop=int(round((top+r_*(ch_mm+g)+drop*(c_%2))*den));y=min(Hp-ytop-chp,Hp-chp);y=max(0,y)   # pixel rows start at the bottom
            card[y:y+chp,x:x+cwp,:3]=cell
        first=self.paths[idx[0]];folder=os.path.join(os.path.dirname(first),'Photo Strips');os.makedirs(folder,exist_ok=True)
        out=os.path.join(folder,'Strip_%dx%d_%s.png'%(cols,rows,uuid.uuid4().hex[:8]))
        bpy.data.images.remove(save_atlas(out,card,False))
        old_rect=list(self.rects[idx[0]]);norm=lambda q:os.path.normcase(os.path.abspath(q));gone={norm(self.paths[i]) for i in idx}
        for f in st.files:
            if f.selected:
                try:
                    if norm(file_path(f)) in gone:f.selected=False
                except Exception:pass
        nf=st.files.add();nf.path=out;nf.selected=True
        if not hasattr(self,'session_strips'):self.session_strips=[]
        self.session_strips.append({'path':out,'sources':[self.paths[i] for i in idx]})   # undone when the editor closes without Build
        self.refresh_layout_sources()
        j=next((k for k,q in enumerate(self.paths) if norm(q)==norm(out)),None)
        if j is not None:   # real card size, placed where the first photo was
            dl=layout_density(st);rw,rh=max(2,round(W_mm*dl)),max(2,round(H_mm*dl))
            rect=centered_layout_rect(old_rect,rw,rh,self.w,self.pad)
            free=vacant_layout_rect(rect,[r for k,r in enumerate(self.rects) if k!=j],self.w,self.pad,st.layout_gap)
            self.rects[j]=free if free is not None else rect;self.physical_sizes[j]=[W_mm,H_mm]
            self.selected=j;self.selection={j}
        self.area.tag_redraw()
        extra=' · %d photo(s) reused to fill %d cells'%(n-len(idx),n) if len(idx)<n else (' · %d not used'%(len(idx)-n) if len(idx)>n else '')
        self.report({'INFO'},_T('Photo strip %d×%d on a %s card (%.0f×%.0f mm) from %d photo(s)%s · originals unchecked in the list'%(cols,rows,label,W_mm,H_mm,min(len(idx),n),extra)))

    def move_group(self,horizontal,vertical):
        if not self.rects:return
        selection=getattr(self,'selection',{self.selected})
        if not selection and not horizontal==vertical==0:   # Pack works on every image, no selection needed
            self.report({'WARNING'},_T('Select images to move. Press A to select all.'));return
        if horizontal==vertical==0 and selection and len([i for i in selection if 0<=i<len(self.rects)])<len(self.rects):
            return self.pack_selected(sorted(i for i in selection if 0<=i<len(self.rects)))
        if horizontal==vertical==0:   # Center: keep sizes, re-pack largest first without gaps and center
            sizes_=[(c-a,d-b) for a,b,c,d in self.rects]
            packed=pack_layout(sizes_,self.w,self.pad,self.settings.layout_gap)
            if packed:
                self.remember_layout();self.rects=packed;self.drag=None;self.area.tag_redraw()
                self.report({'INFO'},_T('Re-packed %d images without changing size · Ctrl+Z to undo'%len(packed)));return
            got=pack_layout(sizes_,self.w,self.pad,self.settings.layout_gap,rotate=True)   # last resort: turn some 90° inside the texture (the poster on the wall is unchanged)
            if got:
                rects_,rot_=got;self.remember_layout()
                for i in rot_:self.layout_rotations[i]=(self.layout_rotations[i]+1)%4
                self.rects=rects_;self.drag=None;self.fx_clear_previews(set(rot_));self.area.tag_redraw()
                self.report({'INFO'},_T('Re-packed %d images without changing size · %d turned 90° inside the texture only · Ctrl+Z to undo'%(len(rects_),len(rot_))));return
            self.report({'WARNING'},_T('Not enough room for everything, could not re-pack · reduce sizes or remove a few images.'))
        moved=move_layout_group(self.rects,horizontal,vertical,self.w,self.h,self.pad,self.settings.layout_gap,selection)
        if moved!=self.rects:
            self.remember_layout();self.rects=moved;self.drag=None
            self.area.tag_redraw()
        self.report({'INFO'},_T('Centered %d selected'%len(selection) if horizontal==vertical==0 else 'Moved %d selected · spacing %d px'%(len(selection),self.settings.layout_gap)))

    def pack_selected(self,sel):
        """Pack with some images selected: only those move, into the free space around the others (spacing kept). Sizes unchanged."""
        g=self.settings.layout_gap;avail=self.w-2*self.pad;lo,hi=self.pad,self.w-self.pad
        fixed=[r for j,r in enumerate(self.rects) if j not in sel and r[2]>lo and r[0]<hi and r[3]>lo and r[1]<hi]   # ones parked outside are ignored
        obst=[(max(a,lo)-self.pad,max(b,lo)-self.pad,min(c,hi)-max(a,lo),min(d,hi)-max(b,lo)) for a,b,c,d in fixed]
        sizes=[(self.rects[i][2]-self.rects[i][0],self.rects[i][3]-self.rects[i][1]) for i in sel]
        for rot in (False,True):
            if any((min(w,h) if rot else max(w,h))>avail for w,h in sizes):continue
            out=pack_search(sizes,avail,g,rot,budget=1.5,obstacles=obst)
            if not out:continue
            self.remember_layout();turned=set()
            for i,(x,y,w,h,r) in zip(sel,out):
                self.rects[i]=[x+self.pad,y+self.pad,x+self.pad+w,y+self.pad+h]
                if r:self.layout_rotations[i]=(self.layout_rotations[i]+1)%4;turned.add(i)
            if turned:self.fx_clear_previews(turned)
            self.drag=None;self.area.tag_redraw()
            self.report({'INFO'},_T('Packed %d selected into the free space · others stay put%s · Ctrl+Z to undo'%(len(sel),' · %d turned 90° in the texture only'%len(turned) if turned else '')));return
        self.report({'WARNING'},_T('Not enough free space for the %d selected · make room, select more, or press A then Pack for everything'%len(sel)))

    def change_resolution(self,res):
        """Change the texture size (2K / 4K / custom) while editing the layout: keep poster sizes and layout, change only the canvas."""
        res=int(res)
        if res==self.w:return
        got=convert_layout_resolution(self.rects,self.layout_rotations,self.w,res,self.settings.layout_gap)
        if got is None:
            self.report({'WARNING'},_T('Not all current posters fit on the %s canvas · remove a few or reduce their size.'%(res_label(res))));return
        rects,turns,repacked=got
        self.remember_layout();self.history[-1]['resolution']=self.w
        self.w=self.h=res;self.pad=max(4,round(4*res/2048))
        self.rects=rects;self.layout_rotations=turns;set_resolution(self.settings,res)
        try:self.fx_clear_previews()
        except Exception:pass
        self.drag=None;self.group_drag=None;self.zoom=1.;self.pan=[0.,0.];self.area.tag_redraw()
        self.report({'INFO'},_T('Changed to %s · poster sizes kept%s · Ctrl+Z to undo'%(res_label(res),' · re-packed to fit' if repacked else '')))

    def optimize_selected(self,sel):
        """Optimal with some images selected: only those grow (same factor, ratios kept, 90° turns inside the texture
        allowed) as far as the free space around the unselected ones allows. The others don't move."""
        g=max(0,int(self.settings.layout_gap));avail=self.w-2*self.pad;lo_,hi_=self.pad,self.w-self.pad
        fixed=[r for j,r in enumerate(self.rects) if j not in sel and r[2]>lo_ and r[0]<hi_ and r[3]>lo_ and r[1]<hi_]   # parked outside = ignored
        obst=[(max(a,lo_)-self.pad,max(b,lo_)-self.pad,min(c,hi_)-max(a,lo_),min(d,hi_)-max(b,lo_)) for a,b,c,d in fixed]
        base=[(self.rects[i][2]-self.rects[i][0],self.rects[i][3]-self.rects[i][1]) for i in sel]
        free=avail*avail-sum((w+g)*(h+g) for _,_,w,h in obst)
        if free<=0:self.report({'WARNING'},_T('No free space left around the other images'));return
        tot=sum((w+g)*(h+g) for w,h in base)
        hi=min(math.sqrt(free/max(tot,1)),avail/max(1,min(min(w,h) for w,h in base)))*1.001;lo=0.;best=None
        def attempt(k):
            sizes=[(max(2,round(w*k)),max(2,round(h*k))) for w,h in base]
            if any(min(s_)>avail for s_ in sizes):return None
            out=pack_search(sizes,avail,g,True,budget=0.,obstacles=obst)
            return (k,out) if out else None
        for _ in range(24):
            mid=(lo+hi)/2;got=attempt(mid)
            if got:lo=mid;best=got
            else:hi=mid
            if hi-lo<1e-3:break
        if best is None:self.report({'WARNING'},_T('The selected images don\'t fit in the free space · make room or select fewer'));return
        k,out=best;den=layout_density(self.settings);self.remember_layout();turned=set()
        for i,(x,y,w,h,r) in zip(sel,out):
            if r:self.layout_rotations[i]=(self.layout_rotations[i]+1)%4;turned.add(i)
            self.rects[i]=[x+self.pad,y+self.pad,x+self.pad+w,y+self.pad+h]
            if self.physical_sizes[i] is not None:
                rw,rh=w,h
                if self.layout_rotations[i]%2:rw,rh=rh,rw
                self.physical_sizes[i]=[rw/den,rh/den]
        if turned:self.fx_clear_previews(turned)
        self.drag=None;self.group_drag=None;self.area.tag_redraw()
        self.report({'INFO'},_T('Optimal for %d selected: ×%.2f · %d turned · others stay put · Ctrl+Z to undo'%(len(sel),k,len(turned))))

    def optimize_layout(self):
        """Optimal layout: keep ratios · scale up by the same factor · 90° rotation only inside the texture."""
        if not self.rects:return
        sel_=sorted(i for i in getattr(self,'selection',()) if 0<=i<len(self.rects))
        if sel_ and len(sel_)<len(self.rects):return self.optimize_selected(sel_)   # only the selected ones (A = all)
        before=sum((c-a)*(d-b) for a,b,c,d in self.rects)/float((self.w-2*self.pad)**2)
        got=optimal_fill_layout(self.rects,self.w,self.pad,self.settings.layout_gap)
        if not got:
            self.report({'WARNING'},_T('Could not find an optimal layout · try reducing the spacing.'));return
        rects,rotated,k=got;den=layout_density(self.settings)
        self.remember_layout()
        for i,r in enumerate(rects):
            if i in rotated:self.layout_rotations[i]=(self.layout_rotations[i]+1)%4
            self.rects[i]=r
            if self.physical_sizes[i] is not None:
                rw,rh=r[2]-r[0],r[3]-r[1]
                if self.layout_rotations[i]%2:rw,rh=rh,rw
                self.physical_sizes[i]=[rw/den,rh/den]
        after=sum((c-a)*(d-b) for a,b,c,d in self.rects)/float((self.w-2*self.pad)**2)
        self.drag=None;self.group_drag=None;self.area.tag_redraw()
        self.report({'INFO'},_T('Optimal layout: ×%.2f scale · %d rotated · usage %d%% → %d%% · Ctrl+Z to undo'%(k,len(rotated),round(before*100),round(after*100))))

    def reset_crop(self,remember=True):
        if not self.rects:return
        i=self.selected;a,b,c,d=self.rects[i];turn=self.layout_rotations[i]
        base=self.applied_crops[i];size=crop_size(self.sizes[i],base)
        iw,ih=size[::-1] if turn%2 else size
        factor=min((c-a)/iw,(d-b)/ih)
        if remember:self.remember_layout()
        self.rects[i]=centered_layout_rect(self.rects[i],max(2,round(iw*factor)),max(2,round(ih*factor)),self.w,self.pad)
        self.crops[i]=list(base);self.physical_sizes[i]=None;self.area.tag_redraw()

    def apply_crop(self):
        if not self.rects or not getattr(self,'selection',{self.selected}):return
        self.remember_layout()
        self.applied_crops[self.selected]=list(self.crops[self.selected])
        self.settings.edit_mode='FIT';self.drag=None;self.area.tag_redraw()
        self.report({'INFO'},_T('Crop applied · sizes are now based on the cropped photo.'))

    def set_edit_mode(self,mode):
        if mode not in {'CROP','FIT','SCALE'}:return
        self.remember_layout()
        if self.rects and getattr(self,'selection',{self.selected}):
            i=self.selected
            if mode=='FIT':self.reset_crop(remember=False)
            elif mode=='SCALE':self.crops[i]=list(self.applied_crops[i])
            elif self.settings.edit_mode!='CROP':
                a,b,c,d=self.rects[i];frame=(c-a,d-b)
                if self.layout_rotations[i]%2:frame=frame[::-1]
                base=self.applied_crops[i]
                self.crops[i]=crop_map(cover_crop(crop_size(self.sizes[i],base),frame,crop_map(self.crops[i],base,True)),base)
        self.settings.edit_mode=mode;self.drag=None;self.area.tag_redraw()

    def zoom_crop(self,factor):
        if not self.rects or not getattr(self,'selection',{self.selected}):return
        i=self.selected;base=self.applied_crops[i];a,b,c,d=crop_map(self.crops[i],base,True);w=c-a;h=d-b
        factor=max(.01,min(factor,1/w,1/h));nw=w*factor;nh=h*factor
        size=crop_size(self.sizes[i],base)
        if min(nw*size[0],nh*size[1])<2:return
        x=max(0.,min(1-nw,(a+c-nw)/2));y=max(0.,min(1-nh,(b+d-nh)/2))
        self.remember_layout();self.crops[i]=crop_map([x,y,x+nw,y+nh],base);self.area.tag_redraw()

    def rotate_layout_image(self,step):
        if not self.rects or not getattr(self,'selection',{self.selected}):return
        sel=sorted(j for j in self.selection if 0<=j<len(self.rects))
        if len(sel)>1:return self.rotate_layout_group(sel,step)
        i=self.selected;a,b,c,d=self.rects[i]
        rw,rh=(d-b,c-a) if step%2 else (c-a,d-b)
        rect=centered_layout_rect(self.rects[i],rw,rh,self.w,self.pad)
        free=vacant_layout_rect(rect,[r for j,r in enumerate(self.rects) if j!=i],self.w,self.pad,self.settings.layout_gap)
        self.remember_layout()
        self.rects[i]=free if free is not None else rect
        self.layout_rotations[i]=(self.layout_rotations[i]+step)%4
        self.drag=None;self.area.tag_redraw()

    def sync_list_pick(self):
        """The image clicked on the canvas becomes the blue row in the sidebar list (names are no longer selectable)."""
        sel=frozenset(i for i in getattr(self,'selection',()) if 0<=i<len(self.rects))
        key=(sel,self.selected if sel else -1)
        if key==getattr(self,'_pick_sync',None):return
        first=not hasattr(self,'_pick_sync');self._pick_sync=key
        if first:return   # opening the editor: leave the list as it is until something is picked on the canvas
        want={self.paths[i] for i in sel};s=self.settings
        act=self.paths[self.selected] if sel and 0<=self.selected<len(self.paths) else None
        for k,f in enumerate(s.files):
            fp=file_path(f)
            if f.picked:f.picked=False
            if act and fp==act and s.active!=k:s.active=k;s.no_row=False
        self.area.tag_redraw()

    def rotate_layout_group(self,sel,step):
        """Several selected: turn the whole block 90° around its center (positions and every image together), like rotating the sheet."""
        rs=[self.rects[j] for j in sel]
        x0=min(r[0] for r in rs);y0=min(r[1] for r in rs);x1=max(r[2] for r in rs);y1=max(r[3] for r in rs)
        cx=(x0+x1)/2;cy=(y0+y1)/2;new={}
        for j in sel:
            a,b,c,d=self.rects[j]
            if step>0:n=[cx+(b-cy),cy-(c-cx),cx+(d-cy),cy-(a-cx)]   # clockwise: (x,y) -> (y,-x) around the center
            else:n=[cx-(d-cy),cy+(a-cx),cx-(b-cy),cy+(c-cx)]       # counter-clockwise
            new[j]=[math.floor(v) for v in n]
        nx0=min(r[0] for r in new.values());ny0=min(r[1] for r in new.values());nx1=max(r[2] for r in new.values());ny1=max(r[3] for r in new.values())
        lo,hi=self.pad,self.w-self.pad
        if nx1-nx0>hi-lo or ny1-ny0>hi-lo:
            self.report({'WARNING'},_T('The turned block is too big for the texture · turn fewer images, or reduce sizes.'));return
        dx=max(lo-nx0,min(0,hi-nx1));dy=max(lo-ny0,min(0,hi-ny1))   # keep it on the canvas
        for j in new:new[j]=[new[j][0]+dx,new[j][1]+dy,new[j][2]+dx,new[j][3]+dy]
        g=self.settings.layout_gap;others=[r for j,r in enumerate(self.rects) if j not in new]
        hit=any(a<C+g and A<c+g and b<D+g and B<d+g for a,b,c,d in new.values() for A,B,C,D in others)
        self.remember_layout()
        for j in sel:self.rects[j]=new[j];self.layout_rotations[j]=(self.layout_rotations[j]+step)%4
        self.drag=None;self.group_drag=None;self.fx_clear_previews(set(sel));self.area.tag_redraw()
        self.report({'WARNING'} if hit else {'INFO'},_T(('Turned %d images as one block %s 90°'%(len(sel),'right' if step>0 else 'left'))+(' · it now overlaps other images: press Pack' if hit else ' · Ctrl+Z to undo')))

    # ---- Effects panel layout -------------------------------------------------------
    def fx_layout(self,right,f):
        rh=self.region.height;self.fx_preview_on=True   # effects are always shown as they are
        pw=min(248*f,max(208*f,right*.24));x0=right-pw;x1=right
        self.fx_panel=(x0,0,x1,rh-self.hdr());W=[];pad=8*f;xx=x0+pad;ww=pw-2*pad
        H=20*f;G=3*f;xr=x1-pad
        # ---- Finish (whole editor): Build / Close, pinned to the very bottom
        self.dest_lines=self.build_where_lines()   # where Build puts things: shown right above the Build button
        bh=24*f;self.fin_area=(x0,0,x1,8*f+bh+24*f+len(self.dest_lines)*15*f+(4*f if self.dest_lines else 0)+(6*f if self.dest_lines else 0))
        ym_=self.fin_area[3]-16*f-15*f   # 'Goes into … › name': click it to rename the batch
        self.batch_name_button=(xx,ym_-4*f,xr,ym_+14*f) if self.dest_lines else (-99,-99,-99,-99)
        cw=ww*.34
        self.apply_button=(xx,8*f,xr-cw-12*f,8*f+bh)
        self.cancel_button=(xr-cw,8*f,xr,8*f+bh)
        fin_h=self.fin_area[3]
        # ---- Effect apply (only the chosen effect), just above Finish
        foot_h=fin_h;self.fx_foot=(x0,fin_h,x1,foot_h)   # no separate apply step: effects apply on click
        # ---- Layout tools, pinned to the top
        bx=xx;bwid=xr-bx
        ytop=rh-self.hdr()-30*f
        def lrow():
            nonlocal ytop
            ytop-=H;r=ytop;ytop-=G;return r
        def lab(text,x0_=None,adv=True):   # Blender style: label on its own line above the controls
            nonlocal ytop
            self.bar_labels.append((text,(xx if x0_ is None else x0_,ytop-15*f,xr,ytop)))
            if adv:ytop-=17*f
        def sec(name):   # foldable section title: click it to hide / show its buttons (remembered)
            nonlocal ytop
            on=PANEL_OPEN.get('sec:'+name,True);bd=(xx,ytop-16*f,xr,ytop+1*f)
            self.sec_heads.append((bd,name));self.bar_labels.append((('▾  ' if on else '▸  ')+name,(xx,ytop-15*f,xr,ytop)))
            ytop-=17*f;return on
        Z=(-99,-99,-99,-99);self.sec_heads=[]
        self.bar_labels=[];self.preset_buttons=[];names=list(POSTER_FORMATS);self.random_size_button=Z;self.copy_size_button=Z
        self.photo_fmt_buttons=[];self.photo_border_buttons=[];self.photo_look_buttons=[];self.strip_buttons=[];self.photo_finish_buttons=[];self.caption_buttons=[];self.paper_finish_buttons=[]
        self.res_buttons=[];self.bg_buttons=[];self.group_buttons=[];self.mode_buttons=[];self.move_buttons=[];self.layout_rotate_buttons=[];self.text_buttons=[];self.tab_buttons=[]
        self.custom_size_button=self.gap_button=self.crop_apply_button=self.optimize_button=self.pack_button=Z
        def grid(items,cols):
            out=[];c=(bwid-(cols-1)*G)/cols
            for k in range(0,len(items),cols):
                r=lrow()
                for j,it in enumerate(items[k:k+cols]):out.append(((bx+j*(c+G),r,bx+j*(c+G)+c,r+H),it))
            return out
        if PANEL_OPEN['layout']:
            if sec('Output'):   # first: applies to the whole sheet
                r=lrow();c=(bwid-2*G)/3
                self.res_buttons=[((bx+j*(c+G),r,bx+j*(c+G)+c,r+H),r_) for j,r_ in enumerate((2048,4096,'CUSTOM'))]
                r=lrow()
                self.bg_buttons=[((bx+j*(c+G),r,bx+j*(c+G)+c,r+H),k_) for j,k_ in enumerate(('WHITE','BLACK','TRANSPARENT'))]
                r=lrow();self.gap_button=(bx,r,xr,r+H)   # gap between images on the sheet
            ytop-=5*f
            r=lrow();half=(bwid-G)/2   # Paper (posters, notes) / Picture (photo prints, instant films)
            self.tab_buttons=[((bx,r,bx+half,r+H),'PAPER'),((bx+half+G,r,xr,r+H),'PICTURE')]
            def edit_mode_rows():
                nonlocal ytop
                ytop-=5*f
                if not sec('Edit Mode'):return
                r=lrow();c=(bwid-2*G)/3
                self.mode_buttons=[((bx+j*(c+G),r,bx+j*(c+G)+c,r+H),mode,text) for j,(mode,text,_) in enumerate(EDIT_MODES)]
                if self.settings.edit_mode=='CROP':r=lrow();self.crop_apply_button=(bx,r,xr,r+H)   # only needed while cropping
            def arrange_rows():   # one row: Left 90° · Right 90° · Pack · Optimal
                nonlocal ytop
                ytop-=5*f
                if not sec('Arrange'):return
                c4=(xr-bx-3*G)/4
                r=lrow();self.layout_rotate_buttons=[((bx,r,bx+c4,r+H),-1),((bx+c4+G,r,bx+2*c4+G,r+H),1)]
                self.pack_button=(bx+2*(c4+G),r,bx+3*c4+2*G,r+H);self.optimize_button=(bx+3*(c4+G),r,xr,r+H)
            # Order: Size -> Edit Mode -> Arrange, then what the picture is and how it looks
            ytop-=5*f
            pic_=self.settings.layout_tab=='PICTURE'
            if sec('Size'):   # Paper: Scale|Keep Ratio|Crop · presets · exact size · Random|Copy
                half=(bwid-G)/2   # Picture: formats (+ Photo Strip settings) · border · Scale|Keep Ratio|Crop · exact size · Random|Copy
                def mode_row():
                    r=lrow();c=(bwid-2*G)/3
                    self.mode_buttons=[((bx+j*(c+G),r,bx+j*(c+G)+c,r+H),mode,text) for j,(mode,text,_) in enumerate(EDIT_MODES)]
                    if self.settings.edit_mode=='CROP':r=lrow();self.crop_apply_button=(bx,r,xr,r+H)   # only needed while cropping
                if pic_:
                    mode_row();ytop-=2*f
                    self.photo_fmt_buttons=grid(list(PHOTO_FORMATS)+['STRIP','OFF'],4)   # Photo Strip is one of the formats: click it for its settings
                    if getattr(self,'strip_open',False):   # photo-booth 4 / 6 cut settings, right under the formats
                        ytop-=2*f
                        self.strip_buttons=grid([('L',1,3),('L',1,4),('L',2,2),('L',2,3),('L',3,2)],5)
                        self.strip_buttons+=grid([('C-',),('CV',),('C+',),('R-',),('RV',),('R+',)],6)
                        self.strip_buttons+=grid([('FR','WHITE'),('FR','BLACK'),('STAG',)],3)
                        ytop-=3*f;self.strip_buttons+=grid([('MAKE',)],1);ytop-=8*f   # the action button stands apart from the settings and from the rows below
                    ytop-=2*f;self.photo_border_buttons=grid(['FRAME','NONE','CUSTOM'],3)   # Border belongs to the format
                else:
                    mode_row();ytop-=2*f;self.preset_buttons=grid(names,3)
                r=lrow();self.random_size_button=(bx,r,bx+half,r+H);self.copy_size_button=(bx+half+G,r,xr,r+H)
                r=lrow();self.custom_size_button=(bx,r,xr,r+H)   # the exact size last
            arrange_rows()   # rotation / pack below the size
            if self.settings.layout_tab!='PICTURE':   # Paper: how shiny the printed paper is (like Picture's Print Finish)
                ytop-=5*f
                if sec('Surface'):self.paper_finish_buttons=grid(['MATTE','SATIN','SILK','GLOSSY','CUSTOM'],5)   # least shiny first, same as Picture
            if self.settings.layout_tab=='PICTURE':   # (formats are part of Size)
                ytop-=5*f
                if sec('Surface'):self.photo_finish_buttons=grid(['MATTE','SATIN','SILK','GLOSSY','CUSTOM'],5)   # same buttons as Paper's Surface
            ytop-=8*f
        self.lay_head=(x0,rh-self.hdr()-26*f,x1,rh-self.hdr()-2*f)
        # ---- Text (above Effects): write on the selected image
        ytop-=2*f
        if sec('Text'):
            r=lrow();half=(bwid-G)/2
            self.text_buttons=[((bx,r,bx+half,r+H),'ADD'),((bx+half+G,r,xr,r+H),'DEL')]
            self.text_buttons+=grid([('F',k) for k in TEXT_FONTS]+['MORE'],3)
            self.text_buttons+=grid([('W',n) for n in range(len(TEXT_WEIGHTS))],3)
            self.text_buttons+=grid([('I',k) for k in TEXT_INKS],4)
            self.text_buttons+=grid(['LS-','LSV','LS+'],3)
        # Group: pinned at the very bottom of the panel, right above 'Goes into' / Build (the effects scroll above it)
        keep_y=ytop;gn_=self.group_names()
        open_=PANEL_OPEN.get('sec:Group',True)
        blk=17*f+((1+(len(gn_)+1+2)//3)*(H+G) if open_ else 0)+6*f
        ytop=fin_h+blk
        if sec('Group'):   # how many groups (− / +), then one button per group; they act on the posters selected on the canvas
            self.group_buttons=grid([('GC-',),('GCV',),('GC+',),('GREN',)],4)
            self.group_buttons+=grid([('G',g) for g in gn_]+[('NONE',)],3)
        foot_h=fin_h+blk+4*f;self.fx_foot=(x0,fin_h,x1,fin_h)
        ytop=keep_y
        ytop-=8*f
        self.lay_sep=ytop;self.fx_title_y=ytop-20*f
        self.fx_head=(x0,ytop-26*f,x1,ytop-2*f)
        top=ytop-28*f;self.fx_view=(x0,foot_h,x1,top)
        y=top+getattr(self,'fx_scroll',0.)
        def row(n,h,gap=3*f):
            nonlocal y
            y-=h;cells=[(xx+j*(ww+gap)/n,y,xx+(j+1)*(ww+gap)/n-gap,y+h) for j in range(n)];y-=gap;return cells
        def head(text):
            nonlocal y
            y-=15*f;W.append(('head',(xx,y,x1,y+18*f),text,text));y-=4*f
        def title_off(text,kind,key):   # section title on the left, its Off at the right end (same width everywhere)
            nonlocal y
            y-=3*f;c4=row(4,18*f,3*f)
            W.append(('label',(c4[0][0],c4[0][1]-2*f,c4[2][2],c4[0][3]),text,text));W.append((kind,c4[3],key,'Off'))
        pc=paper_choices(self.settings)
        y-=4*f
        jc_=row(3,18*f);W.append(('button',(jc_[0][0],jc_[0][1],jc_[1][2],jc_[0][3]),'JITTER','Vary per sheet'))   # checkbox
        W.append(('button',jc_[2],'ALL_OFF','All Off'))   # every effect off on the selected posters (card, surface, text stay)
        pic_=self.settings.layout_tab=='PICTURE'
        if pic_:   # Picture: the film looks are the effects (paper effects, damage, paper / ink colors don't apply to photos)
            lk_,lkk_=self.look_state()
            cells=[c for _ in range(2) for c in row(3,20*f)]
            for c,k in zip(cells,['CLASSIC','EXPIRED','FADED','BW','WARM','COOL']):
                W.append(('look',c,k,{'FADED':'Sun Faded','CLASSIC':'Classic','WARM':'Warm','COOL':'Cool'}.get(k,dict(POL_STYLE_NAMES).get(k,k))))
            title_off('Strength','button','LOOK_OFF')
            cells=row(4,20*f,3*f)
            for c,(k,(t,_)) in zip(cells,FX_AMOUNTS.items()):W.append(('lamt',c,k,t))
            if lk_ and (getattr(self,'look_custom',False) or not any(abs(lkk_-v)<1e-3 for v in LOOK_K.values())):
                W.append(('lslider',row(1,20*f,4*f)[0],'look_k','Strength'))
        # Two groups: paper & look (surface only) / damage (cuts the paper: its outline and shadow change too)
        btns=[] if pic_ else ([('PAPER_FOCUS','Paper Crumple')] if pc else [])+[('PRESET:'+k,name) for k,name,_ in FX_PRESETS if k not in FX_DAMAGE_KEYS and k!='POSTIT']   # Sticky Note sits with the paper colors
        cells=[c for _ in range((len(btns)+2)//3) for c in row(3,20*f)]   # as many rows of 3 as there are effects
        for c,(k,name) in zip(cells,btns):W.append(('button',c,k,name))
        if not pic_:y-=3*f;W.append(('label',(xx,y-14*f,x1,y),'Damage','Damage'));y-=15*f
        btns=[] if pic_ else [('PRESET:'+k,name) for k,name,_ in FX_PRESETS if k in FX_DAMAGE_KEYS]
        cells=[c for _ in range((len(btns)+2)//3) for c in row(3,20*f)]
        for c,(k,name) in zip(cells,btns):W.append(('button',c,k,name))
        pv_=getattr(self,'fx_pending',None)
        if pic_:pass   # (Strength for the looks is above)
        elif pv_ and pv_['id']=='PAPER':   # Paper Crumple has its own strength: Light / Medium / Heavy, or Custom with 3 sliders
            title_off('Strength','fxoff','OFF')
            cells=row(4,20*f,3*f)
            for c,(k,t) in zip(cells,[(k,t) for k,t,_ in PAPER_PRESETS]+[('CUSTOM','Custom')]):W.append(('ppm',c,k,t))
            if pv_['mode']=='CUSTOM':
                for key in ('paper_strength','paper_tile_mm','paper_ao'):W.append(('ppslider',row(1,20*f,4*f)[0],key,PAPER_SLIDERS[key][0]))
        else:
            title_off('Strength','fxoff','OFF')   # strength of the previewed / next effect
            cells=row(4,20*f,3*f)
            for c,(k,(t,_)) in zip(cells,FX_AMOUNTS.items()):W.append(('amt',c,k,t))
            if getattr(self,'fx_amount','LOW')=='CUSTOM' and pv_ and pv_['id'].startswith('PRESET:'):   # one Custom = all the dials at once (only while previewing)
                W.append(('amtslider',row(1,20*f,4*f)[0],'amount_v','Strength'))
                if fx_preset_uses(getattr(self,'fx_pending',None),'size'):W.append(('amtslider',row(1,20*f,4*f)[0],'scale_v','Pattern Size'))
        pp=getattr(self,'fx_pending',None)
        if pp and pp['id']=='PAPER':   # Paper crumple pattern (strength row is above)
            cells=row(5,20*f,3*f);W.append(('plabel',cells[0],'SEED','Seed'))
            W.append(('ppv',cells[1],'V-','◀'));W.append(('plabel',cells[2],'SEEDV','%d'%pp['vals'].get('seed',1)))
            W.append(('ppv',cells[3],'V+','▶'));W.append(('ppv',cells[4],'VR','Random'))
        elif getattr(self,'fx_focus',None)=='PAPER' and pc:
            W.append(('label',(xx,y-14*f,x1,y),'Crumple','Crumple'));y-=15*f
            for c,(k,t) in zip(row(5,20*f,3*f),[('NONE','None')]+[(k,t) for k,t,_ in PAPER_PRESETS]+[('CUSTOM','Custom')]):W.append(('ppreset',c,k,t))
            if self.paper_mode()=='CUSTOM':
                for key in PAPER_SLIDERS:W.append(('pslider',row(1,20*f,4*f)[0],key,PAPER_SLIDERS[key][0]))
                nv=len([1 for k,v,t in pc if k==self.settings.paper_set]) or 1
                cells=row(nv+1,20*f,3*f);W.append(('plabel',cells[0],'PV','Pattern #'))
                for c,v in zip(cells[1:],range(nv)):W.append(('pvar',c,v,'%d'%(v+1)))
        elif pp and pp['id'].startswith('PRESET:'):   # Amount of the chosen preset
            if pp['id']=='PRESET:POSTIT':pass   # its colors are shown under the Sticky Note button (Paper color section)
            elif fx_preset_uses(pp,'seed'):   # Seed only where it moves something (not lines / grid / fade)
                cells=row(5,20*f,3*f)
                W.append(('plabel',cells[0],'SEED','Seed'))
                W.append(('pseed',cells[1],'S-','◀'));W.append(('plabel',cells[2],'SEEDV','%d'%pp['token']))
                W.append(('pseed',cells[3],'S+','▶'));W.append(('pseed',cells[4],'SR','Random'))
        y-=2*f
        pv2_=getattr(self,'fx_pending',None)
        if False and pv2_ and (pv2_['id'].startswith('PRESET:') or pv2_['id']=='PAPER'):   # 'Previewing …' line hidden (the user sees effects as applied)
            pt_=self.pend_targets()
            if pt_ and not set(pt_)&set(self.fx_targets() if self.rects else ()):   # the preview sits on other posters than the ones selected now
                W.append(('help',(xx,y-14*f,x1,y),'select','Previewing: %s · on #%s (Esc cancels)'%(pv2_['name'],', '.join(str(i+1) for i in pt_[:4])+('…' if len(pt_)>4 else ''))));y-=15*f
            else:W.append(('help',(xx,y-14*f,x1,y),'select','Previewing: %s · %d posters'%(pv2_['name'],len(pt_))));y-=15*f
            y-=2*f
        y-=4*f
        # Colors: paper / ink (+ Sticky Note) are always here, whatever else is open
        for label_,sw,grays,key in (() if pic_ else (('Paper color (light areas)',FX_PAPER_SWATCHES,FX_PAPER_GRAYS,'tint'),('Ink color (dark areas)',FX_INK_SWATCHES,FX_INK_GRAYS,'ink'))):
            title_off(label_,'button','COLOROFF:'+key)   # Off = back to the poster's own color (was the 'Original' cell)
            sw_=[c for c in sw if c is not None]
            gr_=[c for k,c in enumerate(grays) if k!=len(grays)//2+1]   # one middle tone less, so Pick gets the same width as Custom
            n_=max(len(sw_),len(gr_))+2
            cells=row(n_,20*f,3*f)
            for c,col in zip(cells,sw_):W.append(('swatch',c,key,col))
            W.append(('button',(cells[len(sw_)][0],cells[-1][1],cells[-1][2],cells[-1][3]),'PICK:'+key,'Custom'))   # Custom fills the rest of the row
            gcells=row(n_,20*f,3*f)
            for c,col in zip(gcells,gr_):W.append(('swatch',c,key,col))   # same column grid as the color row above
            W.append(('button',(gcells[len(gr_)][0],gcells[-1][1],gcells[-1][2],gcells[-1][3]),'DROP:'+key,'Pick'))   # eyedropper (as wide as Custom)
            if key=='tint':   # Sticky Note: a colored note paper, so it lives with the paper colors
                y-=2*f;W.append(('button',row(1,20*f,3*f)[0],'PRESET:POSTIT','Sticky Note'))   # lit = on; press again to take it off
                pp=getattr(self,'fx_pending',None)
                if pp and pp['id']=='PRESET:POSTIT':   # note colors (no pattern size / seed)
                    cells=row(len(POSTIT_COLORS)+1,20*f,3*f);W.append(('plabel',cells[0],'PC','Color'))
                    for c,(k,(t,col)) in zip(cells[1:],POSTIT_COLORS.items()):W.append(('pcol',c,k,t))
                    if pp.get('color','Y')=='RANDOM':
                        pool=postit_pool(self.settings)
                        W.append(('label',(xx,y-14*f,x1,y),'POOL','%d random colors'%len(pool)));y-=15*f   # Eyedropper uses the E key, no button
                        for j in range(0,len(pool),6):
                            for c,(n,col) in zip(row(6,20*f,3*f),list(enumerate(pool))[j:j+6]):W.append(('ppool',c,n,col))
                        for c,(k,t) in zip(row(5,20*f,3*f),[('ADD','+ Add'),('DEL','− Remove'),('PICK','Pick Color'),('EYEDROP','Eyedropper'),('SHUFFLE','Reshuffle')]):W.append(('ppbtn',c,k,t))
                y-=4*f
        # (Details sliders removed at the user's request: effects + colors + tools cover it)
        if getattr(self,'fx_tab','COLOR')!='COLOR':self.fx_tab='COLOR'
        y-=6*f;W.append(('sep',(xx,y,x1,y+1),'',''));y-=5*f
        cur=self.effects[self.selected] if self.rects else None
        layers=fx_layers(cur)
        cells=row(2,20*f);clip=getattr(self,'fx_clipboard',None)
        for c,(k,t) in zip(cells,[('COPY','Copy Effects of #%d'%(self.selected+1) if self.rects else 'Copy Effects'),
                                   ('PASTE','Paste Effects to #%d'%(getattr(self,'fx_clip_from',0)+1) if clip else 'Paste (empty)')]):W.append(('button',c,k,t))
        # Tools (hand painting) last, with its own Reset
        y-=6*f;W.append(('sep',(xx,y,x1,y+1),'',''));y-=5*f
        import blf
        title_off('Tools','button','TOOL_OFF')   # stops painting (back to selecting posters)
        cells=row(2,20*f,3*f)+row(2,20*f,3*f)+row(2,20*f,3*f)
        for c,(k,t) in zip(cells,FX_TOOLS[1:]):W.append(('brush',c,k,t))
        tool=self.fx_draft_get().get('brush','select')
        # Description of the chosen tool (wrapped)
        blf.size(0,round(11*f));lines=[];cur=''
        for word in FX_TOOL_HELP[tool].split(' '):
            test=(cur+' '+word).strip()
            if cur and blf.dimensions(0,_T(test))[0]>ww-6*f:lines.append(cur);cur=word
            else:cur=test
        if cur:lines.append(cur)
        y-=4*f   # (tool descriptions removed from the panel: they are in the tooltips/docs)
        if tool in ('tear','peel','wear','protect','erase'):
            W.append(('label',(xx,y-14*f,x1,y),'Brush Tip','Brush Tip'));y-=15*f
            cells=row(len(FX_BRUSH_TIPS),20*f,3*f)
            for c,(k,t) in zip(cells,FX_BRUSH_TIPS):W.append(('tip',c,k,t))
            cells=row(len(FX_BRUSH_POWER),20*f,3*f)
            for c,(t,v) in zip(cells,FX_BRUSH_POWER):W.append(('power',c,v,t))
            for key in ('brush_size','brush_strength')+(('tear_rim',) if tool=='tear' else ()):
                W.append(('slider',row(1,20*f,4*f)[0],key,FX_SLIDERS[key][0]))
        n_sel=len(self.fx_targets()) if self.rects else 0

        bottom=y-getattr(self,'fx_scroll',0.)
        self.fx_scroll_max=max(0.,foot_h+10*f-bottom)
        self.fx_scroll=max(0.,min(getattr(self,'fx_scroll',0.),self.fx_scroll_max))
        if not PANEL_OPEN['effects']:   # folded: keep only the Apply Effect / Discard footer
            W=[w for w in W if w[1][3]<=foot_h+1];self.fx_scroll=0.;self.fx_scroll_max=0.
        self.fx_widgets=W
        return x0

    def fx_draft_get(self):
        # The color cells / sliders show the selected poster's real values: re-read whenever it or its effects change
        # (not while an effect is being previewed: the preview reads from here)
        key=(self.selected,id(self.effects[self.selected])) if self.rects and 0<=self.selected<len(self.effects) else None
        d=getattr(self,'fx_draft',None)
        if d is None or (not getattr(self,'fx_pending',None) and getattr(self,'_draft_key',None)!=key):
            brush={k:d[k] for k in ('brush_size','brush_strength','brush','tip','tear_rim') if k in d} if d else {}
            self.fx_draft=fx_clean(self.effects[self.selected] if self.rects else None)
            self.fx_draft.update(brush_size=25.,brush_strength=.6,brush='select',tip='soft',tear_rim=FX_TEAR_RIM);self.fx_draft.update(brush)
            self._draft_key=key
        return self.fx_draft

    def fx_load_draft(self):
        brush={k:self.fx_draft[k] for k in ('brush_size','brush_strength','brush','tip','tear_rim')} if getattr(self,'fx_draft',None) else {}
        self.fx_draft=None;d=self.fx_draft_get();d.update(brush)

    def fx_pending_values(self,i):
        p=self.fx_pending
        if p['id']=='PAPER':
            v=p['vals'];return {'paper':{'set':p['set'],'seed':int(v.get('seed',1)),'strength':float(v['paper_strength']),'tile':float(v['paper_tile_mm']),'ao':float(v['paper_ao'])}}
        if p['id'].startswith('TAB:'):
            d=self.fx_draft_get();keys=p.get('keys')   # only what was changed (the rest of the draft may be stale)
            return {k:d[k] for k in FX_TAB_KEYS[p['id'][4:]] if keys is None or k in keys}
        if i not in p['cache']:
            key=p['id'][7:];rng=np.random.default_rng((p['token']*1000003+i)&0xffffffff)
            v=fx_from_preset(key,rng,self.fx_jitter and len(self.pend_targets())>1)
            keys=next(vals for k,_,vals in FX_PRESETS if k==key)
            p['cache'][i]={k:v[k] for k in keys if k in FX_VALUE_KEYS}
            amt=self.pend_mult('amount');c_=p['cache'][i]
            if 'stain' in c_:c_['stain']=float(min(3.,c_['stain']*amt))   # coffee ring may go past 1 (darker)
            for k in ('fade','yellow','wear','peel','holes','fray'):
                if k in c_:c_[k]=float(min(1.,c_[k]*amt))
            for k in ('kraft','lined','grid','water','linen','edgetone'):   # paper kinds: Strong may go past 1
                if k in c_:c_[k]=float(min(2.,c_[k]*amt))
            if 'sat' in c_:c_['sat']=float(1-(1-c_['sat'])*amt)
            sc=self.pend_mult('scale')*self.poster_scale(i)
            for k,base in (('hole_size',400.),('wear_edge',15.),('fray_depth',5.)):
                if k in c_ or (k=='hole_size' and ('peel' in c_ or 'holes' in c_)) or (k=='wear_edge' and 'wear' in c_) or (k=='fray_depth' and 'fray' in c_):
                    c_[k]=float(c_.get(k,base)*sc)
            if any(k in c_ for k in ('wear','peel','holes','fray')):c_['pattern']=float(sc)
            elif any(k in c_ for k in FX_PAPER_KIND_KEYS):   # Paper grain / line spacing: real size, only Pattern Size changes it; each paper kind keeps its own
                for k in FX_PAPER_KIND_KEYS:
                    if k in c_:c_['ps_'+k]=float(self.pend_mult('scale'))   # Paper grain / line spacing: real size, only Pattern Size changes it (not the poster size)
            # Seed buttons: each effect group gets its own seed from the Seed value (each poster its own variation)
            if any(k in c_ for k in ('wear','peel','holes','fray')):c_['dmg_seed']=int(p['token'])*1009+int(i)+1
            if any(k in c_ for k in ('kraft','water','linen','edgetone')):c_['paper_seed']=int(p['token'])*1013+int(i)+1
            if key=='COFFEE':   # Coffee ring: Seed moves it (each poster its own spot), Pattern Size changes the mug size
                c_['stain_seed']=int(p['token'])*1009+int(i)+1;c_['stain_size']=float(self.pend_mult('scale'))
            if key=='POSTIT':
                ck=p.get('color','Y')
                if ck=='RANDOM':   # Random: cycle through shuffled colors so neighboring sheets don't match
                    cols=postit_pool(self.settings);order=np.random.default_rng(p['token']).permutation(len(cols))
                    tg=self.pend_targets();pos=tg.index(i) if i in tg else i
                    p['cache'][i]['tint']=cols[order[pos%len(cols)]]
                else:p['cache'][i]['tint']=POSTIT_COLORS[ck][1]
        return p['cache'][i]

    def postit_pool_button(self,key):
        p=getattr(self,'fx_pending',None);st=self.settings
        if not p or p['id']!='PRESET:POSTIT':return
        pool=postit_pool(st);sel=max(0,min(p.get('pool_sel',0),len(pool)-1))
        if key=='ADD' and len(pool)<6:   # Up to 6, fill in the preset sticky-note colors in order
            missing=[c for c in POSTIT_PRESET6 if all(max(abs(a-b) for a,b in zip(c,q))>1e-3 for q in pool)]
            pool.append(tuple(missing[0] if missing else POSTIT_PRESET6[len(pool)%6]));p['pool_sel']=len(pool)-1
            set_postit_pool(st,pool);p['cache']={};self.area.tag_redraw()
            self.report({'INFO'},_T('Sticky note color added (%d/6) · change it with [Change Color].'%len(pool)));return
        if key=='ADD':   # From the 7th: add one more of the picked color and open the color picker right away (closing it = same color = more weight)
            pool.append(pool[sel]);p['pool_sel']=len(pool)-1;set_postit_pool(st,pool);p['cache']={}
            self.eyedrop_start();return
        if key=='DEL':
            if len(pool)<=1:self.report({'WARNING'},_T('At least one color is required.'));return
            pool.pop(sel);p['pool_sel']=max(0,min(sel,len(pool)-1))
        elif key=='PICK':bpy.ops.poster_atlas.fx_pick_color('INVOKE_DEFAULT',target='pool');return
        elif key=='EYEDROP':
            if getattr(self,'eyedrop',None):self.eyedrop_end();return   # Press again to turn off
            self.eyedrop_start();return
        elif key=='SHUFFLE':p['token']=int(np.random.default_rng().integers(1,10000))
        set_postit_pool(st,pool);p['cache']={};self.area.tag_redraw()

    def eyedrop_pick(self,x,y):
        """Color under x,y: the value if it is a panel color cell, the source image color if it is a poster. None otherwise."""
        def inside(r):return r[0]<=x<=r[2] and r[1]<=y<=r[3]
        for kind_,bounds_,key_,text_ in getattr(self,'fx_widgets',[]):
            if not inside(bounds_):continue
            if kind_ in ('swatch','ppool') and isinstance(text_,(tuple,list)):return tuple(text_[:3])
            if kind_=='pcol' and POSTIT_COLORS.get(key_,('',None))[1]:return POSTIT_COLORS[key_][1]
        i_=self.rect_hit(x,y)
        return None if i_ is None else self.sample_source_color(i_,x,y)

    def sample_source_color(self,i,x,y):
        ox,oy,sc=self.view();cx,cy=(x-ox)/sc,(y-oy)/sc
        a,b,c,d=self.rects[i]
        u=min(1.,max(0.,(cx-a)/max(1,c-a)));v=min(1.,max(0.,(cy-b)/max(1,d-b)))
        su,sv=rotate_uv(u,v,(-self.layout_rotations[i])%4)
        cr=self.crops[i];su=cr[0]+su*(cr[2]-cr[0]);sv=cr[1]+sv*(cr[3]-cr[1])
        im=self.images[i];w,h=im.size;px=min(w-1,max(0,int(su*w)));py=min(h-1,max(0,int(sv*h)))
        k=(py*w+px)*4;c=list(im.pixels[k:k+4])
        return None if c[3]<.5 else c[:3]   # transparent: nothing visible to take

    def eyedrop_start(self,target='pool'):
        """Eyedropper: the cursor becomes a dropper; clicking a poster or a color cell takes that color. Right click = color wheel, Esc = cancel.
        target: 'pool' = sticky-note random color, 'tint' / 'ink' = Color Adjust paper / ink color of the selected posters."""
        self.eyedrop=target
        try:self.win.cursor_modal_set('EYEDROPPER')
        except Exception:pass
        what={'tint':'paper color','ink':'ink color'}.get(target,'sticky note color')
        self.report({'INFO'},_T('Eyedropper (%s): click a poster or a color cell · Esc = Cancel'%what))
        self.area.tag_redraw()

    def eyedrop_end(self):
        self.eyedrop=None
        try:self.win.cursor_modal_restore()
        except Exception:pass
        self.area.tag_redraw()

    def eyedrop_apply(self,col):
        """Addon's own eyedropper: Blender's built-in eyedropper cannot read this editor (overlay) and returns gray."""
        t=getattr(self,'eyedrop',None)
        if not t:return
        if col is None:   # transparent spot: keep the dropper on
            self.report({'WARNING'},_T('Nothing visible there (transparent) · click on the image or a color cell'));return
        self.eyedrop_end()
        col=tuple(max(0.,min(1.,float(c))) for c in col[:3])
        if t in ('tint','ink'):   # same as clicking a color cell: applies to the selected posters (one undo step)
            self.fx_draft_get()[t]=col;self.fx_touch('TAB:COLOR',FX_TAB_NAMES['COLOR'],(t,));self.fx_commit(quiet=True)
            self.report({'INFO'},_T('%s set with eyedropper · #%02X%02X%02X'%(('Paper color' if t=='tint' else 'Ink color'),*tuple(round(c*255) for c in col))));self.area.tag_redraw();return
        self.remember_layout()
        if t=='pool':
            st=self.settings;pool=postit_pool(st);p=getattr(self,'fx_pending',None) or {}
            sel=max(0,min(p.get('pool_sel',0),len(pool)-1));pool[sel]=col;set_postit_pool(st,pool)
            if p:p['cache']={}
        self.report({'INFO'},_T('Color set with eyedropper · #%02X%02X%02X'%tuple(round(c*255) for c in col)));self.area.tag_redraw()

    def poster_scale(self,i):
        """Pattern size basis: a 300mm long side counts as 1; larger posters get larger patterns."""
        a,b,c,d=self.rects[i];mm=max(c-a,d-b)/max(layout_density(self.settings),1e-6)
        return max(.5,min(4.,mm/300.))

    def pend_mult(self,which):
        p=self.fx_pending;table=FX_AMOUNTS if which=='amount' else FX_SCALES;k=p.get(which,'LOW')
        if k=='CUSTOM':return float(p.get(which+'_v',1.))
        ov=FX_STRONG_OVERRIDES.get(p.get('id',''),{}).get(p.get('amount'))   # some effects have their own Light / Medium / Strong (tuned by eye)
        if ov and which in ov:return float(ov[which])
        return table[k][1]

    def fx_set_amount(self,kind,key):
        p=getattr(self,'fx_pending',None)
        if not p or not p['id'].startswith('PRESET:'):return
        which='amount' if kind=='pamt' else 'scale'
        if key=='CUSTOM' and p.get(which)!='CUSTOM':p[which+'_v']=self.pend_mult(which)   # Continue adjusting from the current value
        p[which]=key;p['cache']={};self.area.tag_redraw()

    def fx_seed_step(self,key):
        p=getattr(self,'fx_pending',None)
        if not p or not p['id'].startswith('PRESET:'):return
        if key=='SR':p['token']=int(np.random.default_rng().integers(1,10000))
        else:p['token']=max(1,min(9999,p['token']+(1 if key=='S+' else -1)))
        p['cache']={};self.area.tag_redraw()

    def fx_effective(self,i):
        """Committed effects + (if the image is selected) the effect being chosen."""
        memo=getattr(self,'_fx_memo',None)
        if memo is not None and i in memo:return memo[i]
        fx=self.effects[i];p=getattr(self,'fx_pending',None)
        if not p or i not in self.pend_set():
            if memo is not None:memo[i]=fx
            return fx
        vals=self.fx_pending_values(i);name=p['name'];n=1
        old=[l for l in fx_layers(fx) if l['id']==p['id']]
        if old and (p['id'].startswith('PRESET:') or p['id']=='PAPER') and not p.get('edit'):
            n=int(old[-1].get('count',1))+1;vals=fx_stack(old[-1]['values'],vals);name='%s ×%d'%(p['name'],n)
        elif old and p['id'].startswith('TAB:'):
            L_=fx_layers(fx);pos_=max(k for k,l in enumerate(L_) if l['id']==p['id'])
            later_={k for l in L_[pos_+1:] for k in l['values']}
            vals=dict({k:v for k,v in L_[pos_]['values'].items() if k not in later_},**vals)
        layers=[l for l in fx_layers(fx) if l['id']!=p['id']]+[{'id':p['id'],'name':name,'values':vals,'count':n}]
        f=fx_flatten(layers,fx)
        if f and not f['seed']:f['seed']=fx_seed(f,self.paths[i])
        if memo is not None:memo[i]=f
        return f

    def fx_touch(self,pid,name,keys):
        """Start (or continue) an adjust layer of a tab that changes only these keys."""
        d0=self.fx_draft_get();saved={k:d0[k] for kk in keys for k in FX_TOUCH.get(kk,(kk,)) if k in d0}
        self.fx_set_pending(pid,name)   # may apply the previewed preset first (the draft is then re-read): keep the new values
        self.fx_draft_get().update(saved)
        p=getattr(self,'fx_pending',None)
        if p is not None:
            ks=set(p.get('keys') or ())
            for k in keys:ks.update(FX_TOUCH.get(k,(k,)))
            p['keys']=ks;p['cache']={}

    def fx_set_pending(self,pid,name):
        cur=getattr(self,'fx_pending',None)
        stacking=bool(cur) and cur['id']==pid   # same effect clicked again while previewing = add one more on top
        if cur and (cur['id']!=pid or pid.startswith('PRESET:')):   # keep the previous addition; same preset again stacks on top
            amt=(cur.get('amount'),cur.get('amount_v'),cur.get('scale'),cur.get('scale_v')) if cur['id']==pid else None
            self.fx_commit(quiet=True)
            if cur['id'].startswith('PRESET:') or cur['id']=='PAPER':self.toast('Applied %s'%cur['name'])
            cur=None
        else:amt=None
        if not cur:
            self.fx_pending={'id':pid,'name':name,'cache':{},'token':int(np.random.default_rng().integers(1,10000)),'amount':getattr(self,'fx_amount','LOW'),'amount_v':getattr(self,'fx_amount_v',1.)}
            mem=getattr(self,'fx_memory',{}).get(pid)
            tg=self.fx_targets()
            on_tg=any(l['id']==pid for i in tg if 0<=i<len(self.effects) for l in fx_layers(self.effects[i]))
            if mem and pid.startswith('PRESET:') and on_tg:   # re-opening an effect these posters already have: its own Strength / Custom sliders / seed / color
                self.fx_amount=mem.get('amount') or self.fx_amount;self.fx_amount_v=mem.get('amount_v',1.);self.fx_scale_v=mem.get('scale_v',1.)
                if mem.get('color'):self.fx_pending['color']=mem['color']
            elif pid.startswith('PRESET:'):   # new on these posters: always the default strength (Medium), not another poster's Custom
                self.fx_amount=FX_START_AMOUNT;self.fx_amount_v=1.;self.fx_scale_v=1.;self.fx_pending['amount']=FX_START_AMOUNT;self.fx_pending['amount_v']=1.
                if mem and mem.get('color'):self.fx_pending['color']=mem['color']   # (a picked color is a choice, not a strength: keep it)
            if pid.startswith('PRESET:') and not stacking and on_tg:
                self.fx_pending['edit']=True   # already on these posters: re-open it with its settings (replaces, no stacking)
                if mem and mem.get('token'):self.fx_pending['token']=mem['token']
            if pid.startswith('PRESET:'):self.fx_adjust_last()   # apply Strength (and Custom sliders) to the preview
            if False:
                for k_,v_ in zip(('amount','amount_v','scale','scale_v'),amt):
                    if v_ is not None:self.fx_pending[k_]=v_
        # Bind the preview to the selection at the moment of choosing -> clicking other posters to look around won't change the target
        if self.fx_pending:self.fx_pending['targets']=list(self.fx_targets())
        self.area.tag_redraw()

    def pend_rebind(self):
        """Rebind the target of the effect being chosen to the current selection (when re-picking color/amount or selecting all)."""
        p=getattr(self,'fx_pending',None)
        if not p:return
        new=list(self.fx_targets())
        if new!=list(p.get('targets',[])):p['targets']=new;p['cache']={};p.pop('_tset',None)

    def pend_follow_selection(self):
        """Posters picked on the canvas that the preview isn't on: apply the preview to its own posters first,
        so the panel always shows the selected posters' real state (not another poster's preview)."""
        p=getattr(self,'fx_pending',None)
        sel=set(self.fx_targets()) if self.rects else set()
        moved=sel!=getattr(self,'_fx_last_sel',sel);self._fx_last_sel=sel
        if getattr(self,'slider_drag',None):return
        if p and (p['id']=='PAPER' or p['id'].startswith('PRESET:')) and sel and not sel&self.pend_set():
            name=p['name'];self.fx_commit(quiet=True);self.toast('Applied %s'%name);p=None
        if moved and not p:   # other posters picked: the Strength row starts over at Medium (not the last poster's Custom)
            self.fx_amount=FX_START_AMOUNT;self.fx_amount_v=1.;self.fx_scale_v=1.

    def postit_keep_previous(self):
        """Sticky Note color clicked while a different note is selected: apply the color the previous notes got, then re-open Sticky Note on the new selection."""
        p=getattr(self,'fx_pending',None)
        if not p or p['id']!='PRESET:POSTIT':return
        old=list(p.get('targets') or []);new=list(self.fx_targets())
        if not old or not new or old==new:return
        name=p['name'];self.fx_commit(quiet=True);self.fx_set_pending('PRESET:POSTIT',name)

    def pend_targets(self):
        p=getattr(self,'fx_pending',None)
        if not p:return []
        return [i for i in p.get('targets',self.fx_targets()) if 0<=i<len(self.rects)]

    def pend_set(self):
        p=getattr(self,'fx_pending',None)
        if not p:return frozenset()
        key=(len(self.rects),id(p.get('targets')))
        c=p.get('_tset')
        if not c or c[0]!=key:c=p['_tset']=(key,frozenset(self.pend_targets()))
        return c[1]

    def fx_commit(self,quiet=False):
        p=getattr(self,'fx_pending',None)
        if p and (p['id'].startswith('PRESET:') or p['id']=='PAPER'):   # remember this effect's settings for next time
            if not hasattr(self,'fx_memory'):self.fx_memory={}
            if p['id']=='PAPER':self.fx_memory['PAPER']={'mode':p.get('mode'),'vals':dict(p.get('vals') or {}),'set':p.get('set')}
            else:self.fx_memory[p['id']]={'amount':getattr(self,'fx_amount','LOW'),'amount_v':getattr(self,'fx_amount_v',1.),
                                          'scale_v':getattr(self,'fx_scale_v',1.),'token':p.get('token'),'color':p.get('color')}
        if quiet:   # automatic: keep the just-added effect, no messages, painting untouched
            idx=self.pend_targets() if p else []
            if idx:
                before={i:(dict(self.effects[i]) if self.effects[i] else None) for i in idx}
                vals={i:self.fx_effective(i) for i in idx};self.set_effects(idx,lambda i:vals[i])
                if p['id'].startswith('PRESET:'):   # Strength changes now re-tune this addition (Adjust Last)
                    self.fx_last={'targets':sorted(idx),'before':before,'pending':dict(p,cache={}),'n':len(self.effects)}
            self.fx_pending=None;return
        if getattr(self,'paint_session',None) is not None:
            n=self.paint_session_end(True);self.fx_set_tool('select')
            if not p:self.report({'INFO'},_T('Applied paint to %d images.'%n if n else 'Nothing painted; paint mode ended.'));return
        if not p:self.report({'WARNING'},_T('Choose an effect above first. Apply after checking the preview.'));return
        idx=self.pend_targets()
        if not idx:self.report({'WARNING'},_T('Select images to apply effects to. Press A to select all.'));return
        vals={i:self.fx_effective(i) for i in idx}
        self.set_effects(idx,lambda i:vals[i]);self.fx_pending=None
        self.report({'INFO'},_T('%d selected: applied [%s] · pick another effect to stack on top.'%(len(idx),p['name'])))

    def fx_remove_layer(self,lid):
        if lid.startswith('PAINT:') or lid.startswith('CUT:'):
            def strip(i):
                f=fx_clean(self.effects[i]);p=f['paint'] or {};masks=paint_masks(p);cuts=list(p.get('cuts') or [])
                if lid.startswith('PAINT:'):masks.pop(lid[6:],None)
                else:
                    k=int(lid[4:])
                    if 0<=k<len(cuts):cuts.pop(k)
                gh,gw=(next(iter(masks.values())).shape if masks else (p.get('h',8),p.get('w',8)))
                f['paint']=paint_pack(masks,gw,gh,p.get('rim',FX_TEAR_RIM),cuts);return f if fx_active(f) else None
            if lid.startswith('CUT:'):idx=[self.selected] if self.rects else []   # Cut only on visible images
            else:idx=[i for i in self.fx_targets() if self.effects[i] and lid[6:] in paint_masks(fx_clean(self.effects[i])['paint'])]
            if idx:self.set_effects(idx,strip);self.report({'INFO'},_T('Removed %s.'%(FX_PAINT_NAMES.get(lid[6:],'Cut'))))
            return
        if lid=='PAINT':
            idx=[i for i in self.fx_targets() if self.effects[i] and fx_has_paint(fx_clean(self.effects[i]))]
            def make(i):
                f=fx_clean(self.effects[i]);f['paint']=None;return f if fx_active(f) else None
        else:
            idx=[i for i in self.fx_targets() if any(l['id']==lid for l in fx_layers(self.effects[i]))]
            def make(i):return fx_flatten([l for l in fx_layers(self.effects[i]) if l['id']!=lid],self.effects[i])
        if idx:self.set_effects(idx,make);self.report({'INFO'},_T('Removed one effect layer from %d selected.'%len(idx)))

    # ---- Hand painting -----------------------------------------------------------
    # Paint, cuts and texts are stored on the upright card (effects are made upright, then the card turns with the image).
    # On an image turned 90° in the texture, canvas positions are converted to / from the card.
    def card_uv(self,i,u,v):
        return rotate_uv(u,v,(-self.layout_rotations[i])%4)

    def rect_uv(self,i,u,v):
        return rotate_uv(u,v,self.layout_rotations[i]%4)

    def card_px(self,i):
        """Upright card size in canvas pixels (width, height)."""
        a,b,c,d=self.rects[i];return ((d-b),(c-a)) if self.layout_rotations[i]%2 else ((c-a),(d-b))

    def paint_grid(self,i):
        den=layout_density(self.settings);cw_,ch_=self.card_px(i);wmm,hmm=cw_/den,ch_/den
        k=min(1.,256/max(wmm/2,hmm/2,1));return max(8,round(wmm/2*k)),max(8,round(hmm/2*k))

    def remove_selected_from_layout(self):
        """Del: remove the selected images from the layout and uncheck them in the list."""
        idx=sorted(i for i in getattr(self,'selection',set()) if 0<=i<len(self.paths))
        if not idx:self.report({'WARNING'},_T('Select images to remove first.'));return
        if len(idx)>=len(self.paths):self.report({'WARNING'},_T('You cannot remove all of them. Keep at least one.'));return
        norm=lambda p:os.path.normcase(os.path.abspath(p))
        gone={norm(self.paths[i]):i for i in idx};items=[]
        for k,f in enumerate(self.settings.files):
            if not f.selected:continue
            try:p=norm(file_path(f))
            except Exception:continue
            if p in gone:items.append(k)
        # Remember position/effects/crop of removed images so Ctrl+Z can restore them
        keep={self.paths[i]:{'rect':list(self.rects[i]),'mm':self.physical_sizes[i],'turn':self.layout_rotations[i],'crop':list(self.crops[i]),
                             'applied':list(self.applied_crops[i]),'fx':self.effects[i]} for i in idx}
        undo={'kind':'REMOVE','files':[self.settings.files[k].path for k in items],'keep':keep,'selection':sorted(self.selection),'selected':self.selected}
        history=list(self.history)
        for k in items:self.settings.files[k].selected=False
        self.selection=set()
        try:self.refresh_layout_sources()
        except Exception as exc:self.report({'ERROR'},_T(str(exc)));return
        self.history=(history+[undo])[-40:]
        self.area.tag_redraw()
        self.report({'INFO'},_T('Removed %d from the layout (%s) · Ctrl+Z to undo.'%(len(items),', '.join(os.path.basename(p) for p in keep))))

    def renumber_selected(self):
        """W: swap the numbers of 2 selected images; with 3 or more, number them by where they sit (top row first, left to right).
        Built posters are named in number order, so Scatter (By Number on a rail) hangs them in this order. Ctrl+Z undoes it."""
        global SELECTION_BATCH
        sel=sorted(i for i in getattr(self,'selection',set()) if 0<=i<len(self.paths))
        if len(sel)<2:self.report({'WARNING'},_T('Select 2 images to swap their numbers · or 3+ to number them by position (top row first, left to right).'));return
        if len(sel)==2:order=[sel[1],sel[0]]
        else:
            cy=lambda i:(self.rects[i][1]+self.rects[i][3])*.5
            hs=sorted(self.rects[i][3]-self.rects[i][1] for i in sel);tol=max(1.,hs[len(hs)//2]*.5);rows=[]
            for i in sorted(sel,key=lambda i:-cy(i)):   # top row first (y goes up)
                if rows and abs(rows[-1][0]-cy(i))<=tol:rows[-1][1].append(i)
                else:rows.append([cy(i),[i]])
            order=[i for _,g in rows for i in sorted(g,key=lambda i:self.rects[i][0])]
        if order==sel:self.report({'INFO'},_T('Already numbered in that order.'));return
        s=self.settings;slots=[k for k,f in enumerate(s.files) if f.selected]
        if len(slots)!=len(self.paths):self.report({'WARNING'},_T('The image list is out of sync with the layout · try again.'));return
        data=[(s.files[slots[i]].path,s.files[slots[i]].quarter_turns,s.files[slots[i]].picked,s.files[slots[i]].group) for i in order]
        SELECTION_BATCH=True
        try:
            for j,(pth,qt,pk,gp) in enumerate(data):   # slot sel[j] now holds image order[j]
                f=s.files[slots[sel[j]]];f.path=pth;f.quarter_turns=qt;f.group=gp
                if f.picked!=pk:f.picked=pk
        finally:SELECTION_BATCH=False
        try:self.refresh_layout_sources()
        except Exception as exc:self.report({'ERROR'},_T(str(exc)));return
        if len(sel)==2:self.report({'INFO'},_T('Swapped numbers #%d and #%d · Ctrl+Z to undo.'%(sel[0]+1,sel[1]+1)))
        else:self.report({'INFO'},_T('Numbered %d images by position (#%s) · Ctrl+Z to undo.'%(len(sel),', #'.join(str(i+1) for i in sel))))

    def undo_list(self,state):
        """Ctrl+Z for an image-list change: the old list comes back (entries, order, checks) and the images
        return to the places and effects they had. Files are never deleted, so nothing is lost."""
        s=self.settings;self._list_restoring=True
        cur={f.path:f.group for f in s.files}   # groups belong to the image: keep the ones it has now (Group… isn't part of the list undo)
        try:
            s.files.clear()
            for entry in state['files']:
                path,turns,sel=entry[:3]
                f=s.files.add();f.path=path;f.quarter_turns=turns;f.selected=sel
                f.group=cur.get(path,entry[3] if len(entry)>3 else '')
            s.active=max(0,min(s.active,len(s.files)-1))
            self.refresh_layout_sources(placed=state['keep'])
        except Exception as exc:self.report({'ERROR'},_T(str(exc)));return
        finally:self._list_restoring=False
        for i,p in enumerate(self.paths):
            k=state['keep'].get(p)
            if not k:continue
            self.rects[i]=list(k['rect']);self.physical_sizes[i]=k['mm'];self.layout_rotations[i]=k['turn']
            self.crops[i]=list(k['crop']);self.applied_crops[i]=list(k['applied']);self.effects[i]=k['fx']
        self.fx_clear_previews();self.selection={i for i in state.get('selection',[]) if i<len(self.paths)} or {0}
        self.selected=min(state.get('selected',0),max(0,len(self.paths)-1))
        self.area.tag_redraw();self.report({'INFO'},_T('Image list restored (%d images).'%len(state['files'])))

    def undo_remove(self,state):
        """Restore images removed with Del to their original position and effects, re-checking them in the list."""
        history=list(self.history);want=set(state['files'])
        for f in self.settings.files:
            if f.path in want:f.selected=True
        try:self.refresh_layout_sources(placed=state['keep'])
        except Exception as exc:self.report({'ERROR'},_T(str(exc)));return
        self.history=history
        back=set()
        for i,p in enumerate(self.paths):
            k=state['keep'].get(p)
            if not k:continue
            self.rects[i]=list(k['rect']);self.physical_sizes[i]=k['mm'];self.layout_rotations[i]=k['turn']
            self.crops[i]=list(k['crop']);self.applied_crops[i]=list(k['applied']);self.effects[i]=k['fx'];back.add(i)
        self.fx_clear_previews(back);self.selection=back
        if back:self.selected=min(back)
        self.report({'INFO'},_T('Restored %d removed images.'%len(back)))

    def rect_hit(self,x,y):
        ox,oy,scale=self.view();px,py=(x-ox)/scale,(y-oy)/scale
        return next((i for i in range(len(self.rects)-1,-1,-1) if self.rects[i][0]<=px<=self.rects[i][2] and self.rects[i][1]<=py<=self.rects[i][3]),None)

    def paint_focus(self,i):
        # Select the painted image right away so it shows in the list on the right
        if i not in getattr(self,'selection',set()):self.selection={i}
        self.selected=i
        if not self.fx_preview_on:self.fx_preview_on=True

    def paint_begin(self,x,y):
        d=self.fx_draft_get()
        if d.get('brush')=='cut':
            self.cut_drag=[x,y,x,y];self.area.tag_redraw();return
        hit=self.rect_hit(x,y)
        if hit is None:return
        self.remember_layout();self.paint_focus(hit);f=fx_clean(self.effects[hit]);p=f['paint'] or {}
        gw,gh=self.paint_grid(hit);old=paint_masks(p)
        bufs={ch:(paint_upsample(old[ch],gw,gh) if ch in old else np.zeros((gh,gw),np.float32)) for ch in FX_PAINT_CHANNELS}
        self.stroke={'i':hit,'bufs':bufs,'base':{k:v.copy() for k,v in bufs.items()},'acc':np.zeros((gh,gw),np.float32),'last':None,'t':0.}
        self.stroke_marks=[];self.paint_move(x,y)

    def paint_store(self,i,bufs):
        f=fx_clean(self.effects[i]);p=f['paint'] or {};gh,gw=bufs['tear'].shape
        f['paint']=paint_pack(bufs,gw,gh,self.fx_draft_get().get('tear_rim',FX_TEAR_RIM),p.get('cuts'))
        if not f['seed']:f['seed']=fx_seed(f,self.paths[i])
        # Keep the last preview on screen while the new one computes (clearing it here made the
        # canvas flash back to the original image every 0.25 s during a stroke).
        self.effects[i]=f if fx_active(f) else None
        if getattr(self,'paint_session',None) is not None:self.paint_session['touched'].add(i)

    def cut_poly(self,i,cut):
        """Cut preview: polygon of the side that will disappear (screen coordinates)."""
        ox,oy,scale=self.view();a,b,c,d=self.rects[i];W_,H_=self.card_px(i)
        x0,y0,x1,y1,side=cut
        def sd(u,v):return ((u-x0)*W_*(y1-y0)*H_-(v-y0)*H_*(x1-x0)*W_)
        pts=[(0,0),(1,0),(1,1),(0,1)];out=[]
        for k in range(4):
            p,q=pts[k],pts[(k+1)%4];sp,sq=sd(*p)*side,sd(*q)*side
            if sp>0:out.append(p)
            if (sp>0)!=(sq>0) and sp!=sq:
                t=sp/(sp-sq);out.append((p[0]+(q[0]-p[0])*t,p[1]+(q[1]-p[1])*t))
        return [(ox+(a+ru*(c-a))*scale,oy+(b+rv*(d-b))*scale) for ru,rv in (self.rect_uv(i,u,v) for u,v in out)]

    def cut_target(self):
        """Poster the drawn line cuts and (u0,v0,u1,v1,side). The poster under the line midpoint wins."""
        x0,y0,x1,y1=self.cut_drag
        if math.hypot(x1-x0,y1-y0)<6:return None,None
        i=next((j for j in (self.rect_hit((x0+x1)/2,(y0+y1)/2),self.rect_hit(x0,y0),self.rect_hit(x1,y1)) if j is not None),None)
        if i is None:return None,None
        ox,oy,scale=self.view();a,b,c,d=self.rects[i]
        p0=self.card_uv(i,((x0-ox)/scale-a)/(c-a),((y0-oy)/scale-b)/(d-b));p1=self.card_uv(i,((x1-ox)/scale-a)/(c-a),((y1-oy)/scale-b)/(d-b))
        cw_,ch_=self.card_px(i);cut=[p0[0],p0[1],p1[0],p1[1]];cut.append(cut_side(cut,cw_/max(ch_,1)))
        return i,cut

    def cut_end(self):
        i,cut=self.cut_target();self.cut_drag=None
        if i is None:self.area.tag_redraw();return
        self.remember_layout();self.paint_focus(i)
        f=fx_clean(self.effects[i]);p=f['paint'] or {};masks=paint_masks(p)
        gh,gw=(next(iter(masks.values())).shape if masks else self.paint_grid(i)[::-1])
        f['paint']=paint_pack(masks,gw,gh,p.get('rim',FX_TEAR_RIM),list(p.get('cuts') or [])+[cut])
        if not f['seed']:f['seed']=fx_seed(f,self.paths[i])
        self.effects[i]=f;self.area.tag_redraw()   # Keep the old preview until the new one is ready (no flash to the original)
        if getattr(self,'paint_session',None) is not None:self.paint_session['touched'].add(i)
        self.report({'INFO'},_T('Cut #%d · undo it with × in the list on the right.'%(i+1)))

    def paint_move(self,x,y):
        st=self.stroke;i=st['i'];d=self.fx_draft_get()
        ox,oy,scale=self.view();px,py=(x-ox)/scale,(y-oy)/scale
        a,b,c,e_=self.rects[i];den=layout_density(self.settings);cw_,ch_=self.card_px(i)
        gh,gw=st['bufs']['tear'].shape;rad_mm=d['brush_size']/2;cell=(cw_/den)/gw
        u,v=self.card_uv(i,(px-a)/(c-a),(py-b)/(e_-b))   # position on the upright card
        last=st['last'];pts=[(u,v)]
        if last:
            dist=math.hypot((u-last[0])*cw_,(v-last[1])*ch_)/den;n=max(1,int(dist/(rad_mm*.3)))
            pts=[(last[0]+(u-last[0])*k/n,last[1]+(v-last[1])*k/n) for k in range(1,n+1)]
        st['last']=(u,v)
        yy,xx=np.mgrid[0:gh,0:gw].astype(np.float32)
        sign=-1. if d['brush']=='erase' else 1.;chans=FX_PAINT_CHANNELS if d['brush']=='erase' else (d['brush'],)
        tool_col=FX_TOOL_COLORS.get(d['brush'],(1,.85,.2))
        tip=d.get('tip','soft');hole=fx_resources(self.settings).get('hole') if tip=='noise' else None
        rng=np.random.default_rng()
        for uu,vv in pts:
            r_=rad_mm/cell;dd=((xx+.5-uu*gw)**2+(yy+.5-vv*gh)**2)/max(r_*r_,1e-6)
            if tip=='hard':shape=np.clip((1-np.sqrt(dd))*6,0,1)
            elif tip=='spray':shape=(np.clip(1-dd,0,1)>0)*(rng.random(dd.shape)<.14)*2.2
            else:shape=np.clip(1-dd,0,1)**2
            if hole is not None:   # Noise brush: blotchy along the tear pattern
                nn=fx_sample(hole,(xx+.5)*cell/220.+.17*i,(yy+.5)*cell/220.+.41*i);shape=shape*np.clip((nn-.3)*2.5,0,1)*1.6
            # Overlaps within one stroke don't darken (max); a new stroke adds
            st['acc']=np.maximum(st['acc'],np.clip(shape,0,1))
            for ch in chans:st['bufs'][ch]=np.clip(st['base'][ch]+st['acc']*d['brush_strength']*1.5*sign,0,1)
            sr=rad_mm*den*scale;ru_,rv_=self.rect_uv(i,uu,vv)
            self.stroke_marks.append((ox+(a+ru_*(c-a))*scale,oy+(b+rv_*(e_-b))*scale,sr,tool_col+(.35,)))
        import time
        if time.time()-st.get('t',0.)>.25:   # Show the result live while painting
            st['t']=time.time();self.paint_store(i,st['bufs']);self.stroke_marks=self.stroke_marks[-6:]
        self.area.tag_redraw()

    def paint_end(self):
        st=self.stroke;self.stroke=None
        self.paint_store(st['i'],st['bufs']);self.stroke_marks=[];self.area.tag_redraw()

    def paint_session_start(self):
        if getattr(self,'paint_session',None) is None:
            self.paint_session={'effects':[dict(f) if f else None for f in self.effects],'paths':list(self.paths),'history':len(self.history),'touched':set()}

    def paint_session_end(self,keep):
        ps=getattr(self,'paint_session',None);self.paint_session=None
        if ps is None:return 0
        if not keep and ps['paths']==self.paths:
            self.effects=ps['effects'];self.history=self.history[:ps['history']];self.fx_clear_previews(set(ps['touched']))
        return len(ps['touched'])

    def fx_set_tool(self,tool):
        d=self.fx_draft_get();d['brush']=tool;self.painting_on=tool!='select'
        if self.painting_on:self.paint_session_start()
        self.stroke=None;self.cut_drag=None
        self.area.tag_redraw()

    def fx_set_rim(self):
        rim=self.fx_draft_get()['tear_rim'];idx=[i for i in self.fx_targets() if self.effects[i] and 'tear' in paint_masks(fx_clean(self.effects[i])['paint'])]
        for i in idx:
            f=fx_clean(self.effects[i]);f['paint']=dict(f['paint'],rim=float(rim));self.effects[i]=f
        self.fx_clear_previews(set(idx))

    def toast(self,msg):
        import time
        self.report({'INFO'},_T(msg));self.fx_toast=(msg,time.time());self.area.tag_redraw()
        area=self.area
        def _clear():
            try:area.tag_redraw()
            except ReferenceError:pass
            return None
        bpy.app.timers.register(_clear,first_interval=4.1)

    def paper_mode(self):
        s=self.settings
        if not s.paper_auto:return 'NONE'
        if getattr(self,'paper_custom',False):return 'CUSTOM'
        return paper_preset_match(s)

    def paper_pick(self,key):
        s=self.settings
        if key=='NONE':s.paper_auto=False;self.paper_custom=False
        elif key=='CUSTOM':
            s.paper_auto=True;self.paper_custom=True
            names=sorted(paper_sets(paper_folder(s))) if paper_folder(s) else []
            if names and s.paper_set not in names:s.paper_set=names[0]
        else:
            vals=next(v for k,t,v in PAPER_PRESETS if k==key);names=sorted(paper_sets(paper_folder(s))) if paper_folder(s) else []
            if names and s.paper_set not in names:s.paper_set=names[0]
            for a,b in vals.items():setattr(s,a,b)
            s.paper_auto=True;self.paper_custom=False
        self.paper_sync();self.area.tag_redraw()

    def paper_sync(self):
        """(unused) Paper crumple is added to the material only on [Build]."""
        return
        try:
            if not paper_targets(bpy.context,'ALL'):return
            bpy.ops.poster_atlas.paper_apply(scope='ALL',remove=not self.settings.paper_auto)
        except Exception as exc:print('poster_atlas paper sync',exc)

    def paper_button(self,key):
        st=self.settings
        if key=='PAPER_PREVIEW':self.paper_preview=not getattr(self,'paper_preview',True)
        elif key in ('VAR-','VAR+'):
            folder=paper_folder(st);n=len(paper_sets(folder).get(st.paper_set,{})) if folder else 0
            if n:st.paper_variant=(min(st.paper_variant,n-1)+(1 if key=='VAR+' else -1))%n
        self.area.tag_redraw()

    def paper_pend_mode(self,key):
        p=getattr(self,'fx_pending',None)
        if not p or p['id']!='PAPER':return
        if key!='CUSTOM':
            sd=p['vals'].get('seed',1);p['vals']=dict(next(v for k,t,v in PAPER_PRESETS if k==key));p['vals']['seed']=sd
        p['mode']=key;self.area.tag_redraw()

    def paper_pend_seed(self,key):
        p=getattr(self,'fx_pending',None)
        if not p or p['id']!='PAPER':return
        cur=int(p['vals'].get('seed',1))
        if key=='VR':cur=int(np.random.default_rng().integers(1,10000))
        else:cur=max(1,min(9999,cur+(1 if key=='V+' else -1)))
        p['vals']['seed']=cur;self.area.tag_redraw()

    def fx_turn_off(self):
        """Strength · Off: removes the effect being shown from the selected posters; turning it on again starts from defaults."""
        p=getattr(self,'fx_pending',None)
        if not p or not (p['id'].startswith('PRESET:') or p['id']=='PAPER'):
            self.toast('Pick an effect first, then Off removes it');return
        pid,name=p['id'],p['name']
        sel_=set(self.fx_targets());others=[i for i in (p.get('targets') or []) if i not in sel_ and 0<=i<len(self.rects)]
        if others:   # previewed on more posters than are selected now: the others keep it, only the selected ones lose it
            p['targets']=others;p.pop('_tset',None);self.fx_commit(quiet=True)
        applied=any(l['id']==pid for i in self.fx_targets() if 0<=i<len(self.effects) for l in fx_layers(self.effects[i]))
        if not applied:self.remember_layout()   # undo step for a preview-only Off
        self.fx_pending=None
        if applied:self.fx_remove_layer(pid)
        getattr(self,'fx_memory',{}).pop(pid,None)
        if pid.startswith('PRESET:'):self.fx_amount='LOW';self.fx_amount_v=1.;self.fx_scale_v=1.   # next time it starts from defaults
        self.toast('Turned off %s'%name);self.area.tag_redraw()

    def fx_adjust_last(self):
        """Strength buttons / slider re-tune the effect being previewed (live on the canvas)."""
        p=getattr(self,'fx_pending',None)
        if not p and not getattr(self,'_adj_reopen',False):
            # Nothing previewed (the effect was already applied): re-open the last applied preset of the selected
            # poster, keep the Strength / Custom values just set, and re-tune it live.
            lay=[l for l in fx_layers(self.effects[self.selected]) if l['id'].startswith('PRESET:')] if 0<=self.selected<len(self.effects) and self.effects[self.selected] else []
            if lay:
                keep=(getattr(self,'fx_amount','LOW'),getattr(self,'fx_amount_v',1.),getattr(self,'fx_scale_v',1.))
                pid=lay[-1]['id'];nm=next((n for k,n,_ in FX_PRESETS if 'PRESET:'+k==pid),pid[7:])
                self._adj_reopen=True
                try:self.fx_set_pending(pid,nm)
                finally:self._adj_reopen=False
                self.fx_amount,self.fx_amount_v,self.fx_scale_v=keep;p=getattr(self,'fx_pending',None)
                if p:
                    p['edit']=True;v_=lay[-1].get('values') or {}   # keep the applied pattern (seed) instead of a new random one
                    for sk,mul in (('dmg_seed',1009),('stain_seed',1009),('paper_seed',1013)):
                        if v_.get(sk):p['token']=max(1,int((int(v_[sk])-self.selected-1)//mul));break
        if not p or not p['id'].startswith('PRESET:'):return False
        custom=getattr(self,'fx_amount','LOW')=='CUSTOM'
        p['amount']=getattr(self,'fx_amount','LOW');p['amount_v']=getattr(self,'fx_amount_v',1.)
        p['scale']='CUSTOM' if custom else 'LOW';p['scale_v']=getattr(self,'fx_scale_v',1.);p['cache']={};self._fx_memo=None
        self.area.tag_redraw();return True

    def fx_slider_set(self,key,bounds,x):
        if key.startswith('L:'):   # film look strength (Custom)
            t=max(0.,min(1.,(x-bounds[0])/max(1.,bounds[2]-bounds[0])))
            idx_=[i for i in self.look_targets() if (self.photo_get(i) or {}).get('polaroid')]
            if idx_:self.photo_set(idx_,look_k=max(.02,1.5*t))
            self.area.tag_redraw();return
        if key.startswith('A:'):   # Custom strength / pattern size of the previewed effect
            _,lo,hi,_=PEND_SLIDERS[key[2:]];t=max(0.,min(1.,(x-bounds[0])/max(1.,bounds[2]-bounds[0])))
            setattr(self,'fx_'+key[2:],lo+(hi-lo)*t);self.fx_adjust_last();self.area.tag_redraw();return
        if key.startswith('Q:'):
            p=getattr(self,'fx_pending',None)
            if p and p['id']=='PAPER':
                _,lo,hi,_=PAPER_SLIDERS[key[2:]];t=max(0.,min(1.,(x-bounds[0])/max(1.,bounds[2]-bounds[0])))
                p['vals'][key[2:]]=lo+(hi-lo)*t
            self.area.tag_redraw();return
        if key.startswith('D:'):
            p=getattr(self,'fx_pending',None)
            if p:
                _,lo,hi,_=PEND_SLIDERS[key[2:]];t=max(0.,min(1.,(x-bounds[0])/max(1.,bounds[2]-bounds[0])))
                p[key[2:]]=lo+(hi-lo)*t;p['cache']={}
            self.area.tag_redraw();return
        if key.startswith('P:'):
            _,lo,hi,_=PAPER_SLIDERS[key[2:]];t=max(0.,min(1.,(x-bounds[0])/max(1.,bounds[2]-bounds[0])))
            setattr(self.settings,key[2:],lo+(hi-lo)*t);self.area.tag_redraw();return
        _,lo,hi,_=FX_SLIDERS[key];t=max(0.,min(1.,(x-bounds[0])/max(1.,bounds[2]-bounds[0])))
        self.fx_draft_get()[key]=lo+(hi-lo)*t;self.area.tag_redraw()

    # ---- Effects -------------------------------------------------------------
    def fx_clear_previews(self,indices=None):
        for i in list(getattr(self,'fx_previews',{}).keys()):
            if indices is None or i in indices:
                _,im,_=self.fx_previews.pop(i)
                if im is None:continue
                try:bpy.data.images.remove(im)
                except (ReferenceError,RuntimeError):pass

    def fx_targets(self):
        idx=sorted(i for i in getattr(self,'selection',{self.selected}) if 0<=i<len(self.rects))
        # If nothing is selected, target the image shown in the panel (the number shown in the list)
        if not idx and 0<=self.selected<len(self.rects):idx=[self.selected]
        return idx

    # ---- Text tool: type on an image, S size · R rotate · drag/G move, Alt+Enter new line --------------
    # The text being edited floats above the image (drawn live) and goes back into the image's effects when done.
    def text_screen(self,i):
        ox,oy,sc=self.view();a,b,c,d=self.rects[i];return ox+a*sc,oy+b*sc,ox+c*sc,oy+d*sc

    def text_frame(self,i,it):
        """Screen center, screen px per raster px, cos, sin and block layout of one text."""
        X0,Y0,X1,Y1=self.text_screen(i);t_=self.layout_rotations[i]%4
        L=text_layout(it.get('t') or '',it.get('font') or 'INK',it.get('ls',1.))
        ru,rv=self.rect_uv(i,float(it.get('x',.5)),float(it.get('y',.5)))
        k=float(it.get('h',.08))*((X1-X0) if t_%2 else (Y1-Y0))/TEXT_S;ang=math.radians(float(it.get('ang',0.))-90.*t_)   # the card turns clockwise with the image
        return (X0+ru*(X1-X0),Y0+rv*(Y1-Y0)),k,math.cos(ang),math.sin(ang),L

    def text_move_to(self,i,it,ru,rv):
        """Place a text at a canvas position given as uv on the image's rect."""
        it['x'],it['y']=self.card_uv(i,min(1.,max(0.,ru)),min(1.,max(0.,rv)))

    def text_corners(self,i,it,pad=6):
        (cx,cy),k,c,s,L=self.text_frame(i,it);hw=L[0]*k/2+pad;hh=L[1]*k/2+pad
        return [(cx+c*x-s*y,cy+s*x+c*y) for x,y in ((-hw,-hh),(hw,-hh),(hw,hh),(-hw,hh))]

    def text_local(self,i,it,x,y):
        (cx,cy),k,c,s,L=self.text_frame(i,it);dx,dy=x-cx,y-cy
        return (c*dx+s*dy),(-s*dx+c*dy),k,L

    def text_inside(self,i,it,x,y,pad=6):
        lx,ly,k,L=self.text_local(i,it,x,y)
        return abs(lx)<=L[0]*k/2+pad and abs(ly)<=L[1]*k/2+pad

    def text_hit(self,x,y,only_selected=True):
        """(image, index) of the text under the mouse, topmost first."""
        sel=getattr(self,'selection',{self.selected})
        for i in [self.selected]+[j for j in range(len(self.rects)-1,-1,-1) if j!=self.selected]:
            if not 0<=i<len(self.rects) or (only_selected and i not in sel) or not self.effects[i]:continue
            items=fx_clean(self.effects[i])['texts']
            for n in range(len(items)-1,-1,-1):
                if (items[n].get('t') or '').strip() and self.text_inside(i,items[n],x,y):return i,n
        return None

    def text_caret_at(self,i,it,x,y):
        import blf
        lx,ly,k,(W,H,lh,lines,widths)=self.text_local(i,it,x,y)
        if k<=0:return len(it['t'])
        j=max(0,min(len(lines)-1,int((H/2-ly/k)//max(lh,1.))));px_=lx/k+W/2
        fid=text_font_id(it.get('font') or 'INK');blf.disable(fid,blf.ROTATION);blf.size(fid,TEXT_S);l=lines[j]
        col=min(range(len(l)+1),key=lambda n:abs(blf.dimensions(fid,_T(l[:n]))[0]-px_) if n else abs(px_))
        return sum(len(q)+1 for q in lines[:j])+col

    def text_new(self):
        idx=self.fx_targets()
        if not self.rects or not idx:self.toast('Select an image first, then press Add Text');return
        self.text_drop()
        i=self.selected if self.selected in idx else idx[0]
        it={'t':'','font':getattr(self,'text_font','INK'),'ink':getattr(self,'text_ink','BLACK'),'x':.5,'y':.5,
            'h':getattr(self,'text_h',.08),'ang':0.,'ls':getattr(self,'text_ls',1.),'wt':getattr(self,'text_wt',0)}
        self.text_edit={'i':i,'n':None,'item':it,'orig':None,'typing':True,'car':0,'mode':None,'saved':False}
        self.selection={i};self.selected=i;self.area.tag_redraw()

    def text_lift(self,i,n,typing=False):
        """Take a text out of the image so it can be edited live (Ctrl+Z goes back to before the edit)."""
        self.text_drop();self.remember_layout()
        f=fx_clean(self.effects[i]);it=f['texts'].pop(n)
        self.effects[i]=f if fx_active(f) else None
        self.text_edit={'i':i,'n':n,'item':dict(it),'orig':dict(it),'typing':typing,'car':len(it.get('t') or ''),'mode':None,'saved':True}
        self.text_font=it.get('font') or 'INK';self.text_ink=it.get('ink') or 'BLACK';self.text_wt=int(it.get('wt',0) or 0);self.area.tag_redraw()

    def text_drop(self,cancel=False):
        """Put the floating text back into its image (cancel = as it was before the edit)."""
        te=getattr(self,'text_edit',None)
        if not te:return
        self.text_edit=None;i=te['i'];self.area.tag_redraw()
        it=te['orig'] if cancel else te['item']
        if not 0<=i<len(self.rects) or not it or not (it.get('t') or '').strip():return
        if not te.get('saved'):self.remember_layout()
        f=fx_clean(self.effects[i]);n=te['n']
        if n is None or n>len(f['texts']):f['texts'].append(dict(it))
        else:f['texts'].insert(n,dict(it))
        if not f['seed']:f['seed']=fx_seed(f,self.paths[i])
        self.effects[i]=f

    def text_transform(self,x,y,event):
        te=self.text_edit;it=te['item'];st=te['start'];md=te['mode'];x0,y0=te['m0']
        X0,Y0,X1,Y1=self.text_screen(te['i'])
        if md in ('MOVE','DRAG'):
            if event.shift:   # Shift: straight along X or Y only
                if abs(x-x0)>=abs(y-y0):y=y0
                else:x=x0
            ru0,rv0=self.rect_uv(te['i'],st['x'],st['y'])
            self.text_move_to(te['i'],it,ru0+(x-x0)/max(X1-X0,1.),rv0+(y-y0)/max(Y1-Y0,1.))
        elif md=='SCALE':
            fac=max(1.,min(1.5,bpy.context.preferences.system.ui_scale))
            k=2.**((x-x0)/(250.*fac)*(.2 if event.shift else 1.))
            if event.ctrl:k=round(k/.05)*.05
            it['h']=max(.004,min(2.,st['h']*k))
        elif md=='SCALEH':   # corner handle: size follows the distance from the center
            ru0,rv0=self.rect_uv(te['i'],st['x'],st['y']);cx=X0+ru0*(X1-X0);cy=Y0+rv0*(Y1-Y0)
            k=math.hypot(x-cx,y-cy)/max(math.hypot(x0-cx,y0-cy),1.)
            if event.ctrl:k=round(k/.05)*.05
            it['h']=max(.004,min(2.,st['h']*k))
        elif md=='ROT':
            ru0,rv0=self.rect_uv(te['i'],st['x'],st['y']);cx=X0+ru0*(X1-X0);cy=Y0+rv0*(Y1-Y0)
            ang=st['ang']+math.degrees(math.atan2(y-cy,x-cx)-math.atan2(y0-cy,x0-cx))
            if event.ctrl:ang=round(ang/15.)*15.
            it['ang']=((ang+180.)%360.)-180.

    def text_handles(self,i,it):
        """Screen points of the rotate knob (above the top edge) and the size square (bottom-right corner)."""
        cn=self.text_corners(i,it,6);(cx,cy),k,c,s,L=self.text_frame(i,it)
        tm=((cn[2][0]+cn[3][0])/2,(cn[2][1]+cn[3][1])/2);f=max(1.,min(1.5,bpy.context.preferences.system.ui_scale))
        return {'ROT':(tm[0]-s*24*f,tm[1]+c*24*f),'SCALEH':cn[1]}

    def text_handle_at(self,i,it,x,y):
        f=max(1.,min(1.5,bpy.context.preferences.system.ui_scale))
        return next((nm for nm,(hx,hy) in self.text_handles(i,it).items() if math.hypot(x-hx,y-hy)<=10*f),None)

    def text_button(self,key):
        te=getattr(self,'text_edit',None);it=te['item'] if te else None
        if key=='ADD':self.text_new()
        elif key=='DEL':
            if te:it['t']='';self.text_drop();self.toast('Text deleted · Ctrl+Z to undo')
            else:self.toast('Click a text on the selected image first')
        elif key[0]=='F':
            self.text_font=key[1]
            if it:it['font']=key[1]
        elif key=='MORE':bpy.ops.poster_atlas.text_font('INVOKE_DEFAULT')
        elif key[0]=='W':
            self.text_wt=key[1]
            if it:it['wt']=key[1]
        elif key[0]=='I':
            self.text_ink=key[1]
            if it:it['ink']=key[1]
        elif key in ('LS-','LS+'):
            v=round(max(.6,min(3.,float(it.get('ls',1.) if it else getattr(self,'text_ls',1.))+(.1 if key=='LS+' else -.1))),2)
            self.text_ls=v
            if it:it['ls']=v
        self.area.tag_redraw()

    def text_modal(self,event,x,y,inside):
        """Keys and mouse while a text floats. Returns None to let the editor handle the event."""
        te=self.text_edit;i=te['i']
        if not 0<=i<len(self.rects):self.text_edit=None;return None
        it=te['item'];tp=event.type;pr=event.value=='PRESS';RM={'RUNNING_MODAL'};self.area.tag_redraw()
        md=te.get('mode')
        if md:   # S size / R rotate / G or drag move
            if tp in {'MOUSEMOVE','INBETWEEN_MOUSEMOVE'}:self.text_transform(x,y,event);return RM
            if (tp=='LEFTMOUSE' and (event.value=='RELEASE' if te.get('held') else pr)) or (pr and tp in {'RET','NUMPAD_ENTER'}):
                if md=='DRAG' and te['typing'] and not te.get('moved') and abs(x-te['m0'][0])<=4 and abs(y-te['m0'][1])<=4:
                    it.update(te['start']);te['car']=self.text_caret_at(i,it,x,y)
                te['mode']=None;te['moved']=False;self.text_h=it['h'];return RM
            if pr and tp in {'S','R','G'} and not event.ctrl and not event.alt:   # switch while holding the click: S size · R rotate · G move
                nm_={'S':'SCALE','R':'ROT','G':'DRAG' if te.get('held') else 'MOVE'}[tp]
                if nm_!=md:te['mode']=nm_;te['start']=dict(it);te['m0']=(x,y);te['moved']=True
                return RM
            if pr and tp in {'ESC','RIGHTMOUSE'}:it.update(te['start']);te['mode']=None;te['moved']=False;return RM
            return RM if tp not in {'WHEELUPMOUSE','WHEELDOWNMOUSE','MIDDLEMOUSE','TIMER'} else None
        if pr and tp in {'UP_ARROW','DOWN_ARROW'} and event.alt:   # line spacing
            it['ls']=round(max(.6,min(3.,float(it.get('ls',1.))+(.1 if tp=='UP_ARROW' else -.1))),2);self.text_ls=it['ls'];return RM
        if tp=='LEFTMOUSE' and event.value in {'PRESS','DOUBLE_CLICK'}:
            if inside(self.fx_panel):return None   # panel buttons (font, pen) work on this text
            hd_=self.text_handle_at(i,it,x,y)
            if hd_:te['mode']=hd_;te['start']=dict(it);te['m0']=(x,y);te['held']=True;return RM   # rotate knob / size corner
            if self.text_inside(i,it,x,y):
                if event.value=='DOUBLE_CLICK':te['typing']=True;te['car']=self.text_caret_at(i,it,x,y);return RM
                te['mode']='DRAG';te['start']=dict(it);te['m0']=(x,y);te['held']=True   # drag moves it, even while typing; a click without moving places the caret
                return RM
            self.text_drop();return None   # click elsewhere: done, the click does its normal job
        if te['typing']:
            if not pr:return None if tp in {'MOUSEMOVE','INBETWEEN_MOUSEMOVE','WHEELUPMOUSE','WHEELDOWNMOUSE','MIDDLEMOUSE','LEFTMOUSE','TIMER'} else RM
            t=it['t'];c_=max(0,min(len(t),int(te.get('car',len(t)))))
            ls_=t.rfind('\n',0,c_)+1;le_=t.find('\n',c_);le_=len(t) if le_<0 else le_
            if tp in {'RET','NUMPAD_ENTER'}:
                if event.alt or event.shift:it['t']=t[:c_]+'\n'+t[c_:];te['car']=c_+1
                else:te['typing']=False
                return RM
            if tp=='ESC':
                te['typing']=False
                if not t.strip():self.text_drop()
                return RM
            if tp=='BACK_SPACE':
                j=c_
                if event.ctrl:
                    while j>0 and t[j-1]==' ':j-=1
                    while j>0 and t[j-1] not in ' \n':j-=1
                else:j=max(0,c_-1)
                it['t']=t[:j]+t[c_:];te['car']=j;return RM
            if tp=='DEL':it['t']=t[:c_]+t[c_+1:];return RM
            if tp=='LEFT_ARROW':te['car']=max(0,c_-1);return RM
            if tp=='RIGHT_ARROW':te['car']=min(len(t),c_+1);return RM
            if tp=='HOME':te['car']=ls_;return RM
            if tp=='END':te['car']=le_;return RM
            if tp in {'UP_ARROW','DOWN_ARROW'}:
                col=c_-ls_
                if tp=='UP_ARROW' and ls_>0:p0=t.rfind('\n',0,ls_-1)+1;te['car']=min(p0+col,ls_-1)
                elif tp=='DOWN_ARROW' and le_<len(t):n1=t.find('\n',le_+1);n1=len(t) if n1<0 else n1;te['car']=min(le_+1+col,n1)
                return RM
            if tp=='V' and event.ctrl:
                clip=(bpy.context.window_manager.clipboard or '').replace('\r\n','\n').replace('\r','\n').replace('\t',' ')
                it['t']=t[:c_]+clip+t[c_:];te['car']=c_+len(clip);return RM
            if tp=='A' and event.ctrl:return RM
            u=event.unicode
            if u and u.isprintable() and not event.ctrl:it['t']=t[:c_]+u+t[c_:];te['car']=c_+len(u)
            return RM
        if pr:   # text picked (not typing)
            if tp in {'S','R','G'} and not event.ctrl and not event.alt:
                te['mode']={'S':'SCALE','R':'ROT','G':'MOVE'}[tp];te['start']=dict(it);te['m0']=(x,y);te['held']=False;return RM
            if tp in {'RET','NUMPAD_ENTER','F2'}:te['typing']=True;te['car']=len(it['t']);return RM
            if tp in {'DEL','BACK_SPACE','X'}:it['t']='';self.text_drop();self.toast('Text deleted · Ctrl+Z to undo');return RM
            if tp=='ESC':self.text_drop();return RM
            if tp in {'LEFT_ARROW','RIGHT_ARROW','UP_ARROW','DOWN_ARROW'}:   # nudge
                X0,Y0,X1,Y1=self.text_screen(i);st_=(10. if event.shift else 2.)
                ru_,rv_=self.rect_uv(i,it['x'],it['y'])   # arrows move it on screen, also on a turned image
                if tp in {'LEFT_ARROW','RIGHT_ARROW'}:ru_+=(st_ if tp=='RIGHT_ARROW' else -st_)/max(X1-X0,1.)
                else:rv_+=(st_ if tp=='UP_ARROW' else -st_)/max(Y1-Y0,1.)
                self.text_move_to(i,it,ru_,rv_)
                return RM
            if tp in {'MOUSEMOVE','INBETWEEN_MOUSEMOVE','WHEELUPMOUSE','WHEELDOWNMOUSE','MIDDLEMOUSE','TIMER','SPACE'} or tp.startswith('EVT_') or tp in {'LEFT_SHIFT','RIGHT_SHIFT','LEFT_CTRL','RIGHT_CTRL','LEFT_ALT','RIGHT_ALT','OSKEY'}:return None
            self.text_drop();return None   # any other key: done with the text, the key does its normal job (A, Ctrl+Z, ...)
        return None

    def text_overlay(self,flat,batch_for_shader,fac):
        """Frames on texts of the selected images, and the floating text drawn live with caret and hints."""
        import gpu,blf
        def lines_(pts,col,w=1.,prim='LINE_LOOP'):
            gpu.state.blend_set('ALPHA');gpu.state.line_width_set(w)
            b=batch_for_shader(flat,prim,{'pos':pts});flat.bind();flat.uniform_float('color',col);b.draw(flat);gpu.state.line_width_set(1.)
        te=getattr(self,'text_edit',None)
        for i in getattr(self,'selection',{self.selected}):
            if 0<=i<len(self.rects) and self.effects[i]:
                for it in text_items(self.effects[i]):lines_(self.text_corners(i,it,3),(1,1,1,.3))
        if not te or not 0<=te['i']<len(self.rects):return
        i=te['i'];it=te['item'];(cx,cy),k,c,s,(W,H,lh,lines,widths)=self.text_frame(i,it)
        fid=text_font_id(it.get('font') or 'INK');col=TEXT_INKS.get(it.get('ink') or 'BLACK',TEXT_INKS['BLACK'])[1]
        def P(lx,ly):lx*=k;ly*=k;return (cx+c*lx-s*ly,cy+s*lx+c*ly)
        if TEXT_S*k>=1:
            gpu.state.blend_set('ALPHA');blf.enable(fid,blf.ROTATION);blf.rotation(fid,math.atan2(s,c))   # screen angle (includes the image's turn)
            blf.size(fid,TEXT_S*k);blf.color(fid,*col,.94)
            rb=TEXT_WEIGHTS[max(0,min(2,int(it.get('wt',0) or 0)))][1]*TEXT_S   # Bold / Heavy: same text drawn around a small circle
            offs=[(0.,0.)]+([(rb*f_*math.cos(a_),rb*f_*math.sin(a_)) for f_ in (.5,1.) for a_ in [n_*math.pi/6 for n_ in range(12)]] if rb>0 else [])
            for j,l in enumerate(lines):
                for ox_,oy_ in offs:
                    if l:blf.position(fid,*P(-W/2+ox_,H/2-TEXT_S-j*lh+oy_),0);blf.draw(fid,_T(l))
            blf.disable(fid,blf.ROTATION)
        typing=te['typing'];md=te.get('mode')
        acc=(1.,.8,.25,1.) if md else (.35,.75,1.,1.) if typing else (1.,1.,1.,.95)
        cn=self.text_corners(i,it,6);lines_(cn,(0,0,0,.55),3.);lines_(cn,acc,1.5)
        if not typing or md:
            hs=self.text_handles(i,it);tm=((cn[2][0]+cn[3][0])/2,(cn[2][1]+cn[3][1])/2)
            lines_([tm,hs['ROT']],acc,1.5,'LINES')
            for nm_,(hx,hy) in hs.items():
                r_=6*fac if nm_=='ROT' else 5*fac
                pts=[(hx+r_*math.cos(a_),hy+r_*math.sin(a_)) for a_ in [n_*math.pi/8 for n_ in range(16)]] if nm_=='ROT' else [(hx-r_,hy-r_),(hx+r_,hy-r_),(hx+r_,hy+r_),(hx-r_,hy+r_)]
                gpu.state.blend_set('ALPHA');b_=batch_for_shader(flat,'TRI_FAN',{'pos':pts});flat.bind();flat.uniform_float('color',acc);b_.draw(flat)
                lines_(pts,(0,0,0,.7),1.)
        if typing:
            t=it['t'];car=max(0,min(len(t),int(te.get('car',len(t)))));j=t.count('\n',0,car);cl=car-(t.rfind('\n',0,car)+1)
            blf.size(fid,TEXT_S);wpx=blf.dimensions(fid,_T(lines[j][:cl]))[0] if cl else 0.
            yb=H/2-TEXT_S-j*lh;lines_([P(-W/2+wpx,yb-.22*TEXT_S),P(-W/2+wpx,yb+.95*TEXT_S)],acc,2.,'LINES')
        fin_='release to apply' if te.get('held') else 'click to apply'
        if md=='SCALE':msg='Size %d%%  ·  move left / right  ·  Ctrl 5%% steps  ·  R rotate  ·  %s  ·  Esc cancel'%(round(it['h']/max(te['start']['h'],1e-6)*100),fin_)
        elif md=='ROT':msg='Rotate %.0f°  ·  Ctrl 15° steps  ·  S size  ·  %s  ·  Esc cancel'%(it['ang'],fin_)
        elif md=='SCALEH':msg='Size %d%%  ·  Ctrl 5%% steps'%round(it['h']/max(te['start']['h'],1e-6)*100)
        elif md:msg='Move  ·  keep holding and press S size / R rotate  ·  %s'%fin_
        elif typing:msg='Type  ·  drag the box to move  ·  Alt+Enter new line  ·  Alt ↑↓ line spacing  ·  Enter done (then S size · R rotate)'
        else:msg='Drag to move  ·  round knob = rotate  ·  corner square = size  ·  S / R / G keys too  ·  Alt ↑↓ line spacing  ·  Enter or double-click edit  ·  Del delete'
        fs=round(12*fac);x_=min(p[0] for p in cn);y_=min(p[1] for p in cn)-18*fac
        blf.size(0,fs);tw=blf.dimensions(0,_T(msg))[0]
        gpu.state.blend_set('ALPHA');b=batch_for_shader(flat,'TRIS',{'pos':[(x_-4,y_-5*fac),(x_+tw+4,y_-5*fac),(x_+tw+4,y_+13*fac),(x_-4,y_+13*fac)]},indices=[(0,1,2),(0,2,3)])
        flat.bind();flat.uniform_float('color',(0,0,0,.7));b.draw(flat)
        blf.position(0,x_,y_,0);blf.color(0,1,.9,.6,1);blf.draw(0,_T(msg))

    def fx_reset_all(self):
        """Effects header · Reset: remove every effect (paper, look, damage, paint) from the selected posters,
        including the Print Finish look (Classic, Warm ...). The photo card itself (format, border, surface) is kept.
        Ctrl+Z brings it back."""
        idx=[i for i in self.fx_targets() if 0<=i<len(self.effects) and self.effects[i]]
        self.fx_pending=None
        if not idx:self.toast('No effects on the selected posters');self.area.tag_redraw();return
        def make(i):   # texts are their own tool (above Effects) and stay
            keep=[]
            for l in fx_layers(self.effects[i]):
                if l['id'] not in ('PHOTO','POLAROID'):continue
                v=dict(l.get('values') or {})
                if not v.get('frame'):continue   # look only, no card border: nothing of the card is left to keep
                v['polaroid']=0.;keep.append(dict(l,values=v,name='Photo'+(' · '+v['photo_fmt'] if v.get('photo_fmt') else '')))
            f=fx_flatten(keep,dict(fx_clean(self.effects[i]),paint=None))
            return f if f and fx_active(f) else None
        self.set_effects(idx,make)
        self.toast('Reset effects on %d poster%s · Ctrl+Z to undo'%(len(idx),'' if len(idx)==1 else 's'))

    def fx_all_off(self):
        """All Off (next to Vary per sheet): every Effects-panel effect leaves the selected posters (paper kinds, looks,
        damage, colors, crumple, paint). The photo card with its look, the Surface and texts are Layout things and stay."""
        idx=[i for i in self.fx_targets() if 0<=i<len(self.effects) and self.effects[i]]
        self.fx_pending=None
        if not idx:self.toast('No effects on the selected posters');self.area.tag_redraw();return
        def make(i):
            keep=[l for l in fx_layers(self.effects[i]) if l['id'] in ('PHOTO','POLAROID','SURFACE')]
            f=fx_flatten(keep,dict(fx_clean(self.effects[i]),paint=None))
            return f if f and fx_active(f) else None
        self.set_effects(idx,make)
        self.toast('All effects off on %d poster%s · Ctrl+Z to undo'%(len(idx),'' if len(idx)==1 else 's'))

    def set_effects(self,indices,make):
        if not indices:
            self.report({'WARNING'},_T('Select images to apply effects to. Press A to select all.'));return
        self.remember_layout()
        for i in indices:self.effects[i]=make(i)
        self.fx_clear_previews(set(indices));self.area.tag_redraw()

    def fx_button(self,key):
        idx=self.fx_targets()
        if key=='EDIT':bpy.ops.poster_atlas.layout_effects('INVOKE_DEFAULT')
        elif key=='COMMIT':self.fx_commit()
        elif key=='CANCEL':
            self.fx_pending=None
            if getattr(self,'paint_session',None) is not None:
                n=self.paint_session_end(False);self.fx_set_tool('select')
                self.report({'INFO'},_T('Discarded paint on %d images.'%n if n else 'Paint mode ended.'))
        elif key=='LOAD':self.fx_load_draft();self.report({'INFO'},_T('Loaded values of #%d.'%(self.selected+1)))
        elif key.startswith('PICK:'):bpy.ops.poster_atlas.fx_pick_color('INVOKE_DEFAULT',target=key[5:])
        elif key.startswith('DROP:'):
            if not idx:self.toast('Select the posters to color first · A selects all')
            elif getattr(self,'eyedrop',None)==key[5:]:self.eyedrop_end()   # press again to turn off
            else:self.eyedrop_start(key[5:])
        elif key=='PAINT_CLEAR':
            def clear(i):
                f=self.effects[i]
                if not f:return None
                f=dict(f);f['paint']=None;return f if fx_active(f) else None
            has=[i for i in idx if self.effects[i] and fx_has_paint(fx_clean(self.effects[i]))]
            if has:self.set_effects(has,clear)
            else:self.report({'INFO'},_T('The selected image has no paint.'))
        elif key=='PAPER_FOCUS':
            p=getattr(self,'fx_pending',None);st=self.settings
            applied=any(l['id']=='PAPER' for i in idx for l in fx_layers(self.effects[i]))
            stacking=bool(p) and p['id']=='PAPER'
            if p:
                self.fx_commit(quiet=True)   # auto-apply the previewed effect; Paper Crumple again stacks
                if p['id'].startswith('PRESET:') or p['id']=='PAPER':self.toast('Applied %s'%p['name'])
            if True:
                names=sorted(paper_sets(paper_folder(st))) if paper_folder(st) else []
                vals=dict(next(v for k,t,v in PAPER_PRESETS if k==FX_START_PAPER));vals['seed']=1   # default strength (FX_START_PAPER)
                self.fx_pending={'id':'PAPER','name':'Paper Crumple','mode':FX_START_PAPER,'set':st.paper_set if st.paper_set in names else (names[0] if names else st.paper_set),
                                 'vals':vals,'cache':{},'token':1,'targets':list(idx)}
                mem=getattr(self,'fx_memory',{}).get('PAPER')
                if mem and applied:   # re-opening crumple these posters have: remembered mode / sliders / seed (new posters start at Medium)
                    self.fx_pending['mode']=mem.get('mode','LIGHT');self.fx_pending['vals']=dict(mem.get('vals') or vals)
                    if mem.get('set'):self.fx_pending['set']=mem['set']
                if applied and not stacking:self.fx_pending['edit']=True   # re-open the applied crumple instead of stacking
            self.fx_focus=None
            if not idx:self.toast('Select posters first · A selects all')
        elif key.startswith('PRESET:'):
            self.fx_focus=None
            p=getattr(self,'fx_pending',None)
            nm=next(n for k,n,_ in FX_PRESETS if k==key[7:])
            on_=key=='PRESET:POSTIT' and ((bool(p) and p['id']==key) or any(l['id']==key for i in idx if 0<=i<len(self.effects) for l in fx_layers(self.effects[i])))
            if not idx:self.toast('Select posters first · A selects all')
            elif on_:   # Sticky Note is on: pressing it again takes it off (it is a paper color, not something to stack)
                if not p or p['id']!=key:self.fx_set_pending(key,nm)
                self.fx_turn_off()
            else:
                self.fx_set_pending(key,nm)   # preview only; picking another effect (or Build) applies it
        elif key=='DETAIL':
            self.fx_detail=not getattr(self,'fx_detail',False)
            if self.fx_tab not in ('COLOR','WEAR','PEEL','FRAY'):self.fx_tab='COLOR'
        elif key=='JITTER':self.fx_jitter=not self.fx_jitter
        elif key=='ALL_OFF':self.fx_all_off()
        elif key.startswith('COLOROFF:'):   # paper / ink color off: the poster's own color again
            k_=key[9:];d_=self.fx_draft_get()
            if d_.get(k_) is None:self.toast('Already the original color')
            else:d_[k_]=None;self.fx_touch('TAB:COLOR',FX_TAB_NAMES['COLOR'],(k_,));self.fx_commit(quiet=True)
        elif key=='LOOK_OFF':   # film look off on the selected photos (card, border, surface stay)
            idx_=[i for i in idx if (self.photo_get(i) or {}).get('polaroid')]
            if idx_:self.remember_layout();self.photo_set(idx_,look=None);self.look_custom=False
            else:self.toast('No look on the selected posters')
        elif key=='TOOL_OFF':   # like every Off: the hand painting (and cuts) leave the selected posters, and the tool stops
            if getattr(self,'paint_session',None) is not None:self.paint_session_end(True)
            self.fx_set_tool('select')
            def clear_(i):
                f_=self.effects[i]
                if not f_:return None
                f_=dict(f_);f_['paint']=None;return f_ if fx_active(f_) else None
            has_=[i for i in idx if 0<=i<len(self.effects) and self.effects[i] and fx_has_paint(fx_clean(self.effects[i]))]
            if has_:self.set_effects(has_,clear_);self.toast('Paint off on %d poster%s · Ctrl+Z to undo'%(len(has_),'' if len(has_)==1 else 's'))
            else:self.toast('Paint tool off')
        elif key=='PREVIEW':self.fx_preview_on=not self.fx_preview_on
        elif key=='CLEAR':
            # Also turn off the effect being chosen (yellow preview) and painting
            had_pend=getattr(self,'fx_pending',None) is not None;self.fx_pending=None;self.fx_focus=None
            if getattr(self,'paint_session',None) is not None:self.paint_session_end(False);had_pend=True
            if getattr(self,'painting_on',False):self.fx_set_tool('select')
            has=[i for i in idx if self.effects[i]];names=lambda L:', '.join('#%d'%(i+1) for i in L) if len(L)<=4 else '%d images'%len(L)
            paper_off=False
            if has:self.set_effects(has,lambda i:None)
            msg=['Turned off the effect being chosen'] if had_pend else []
            if has:msg.append('Cleared %s effects'%names(has))
            if paper_off:msg.append('Turned off paper crumple')
            if not msg:
                msg.append('%s has no effects to clear'%names(idx) if idx else 'Select an image first')
                if self.settings.paper_auto:msg.append('Paper crumple is removed by pressing the checked [Paper Crumple] button again')
            self.toast(' · '.join(msg))
        elif key=='COPY':
            src=self.fx_effective(self.selected) if self.rects else None
            if src and fx_active(src):
                self.fx_clipboard=dict(src);self.fx_clip_from=self.selected
                self.toast('Copied effects of #%d · choose other posters and [Paste]'%(self.selected+1))
            else:self.toast('#%d has no effects to copy (paper crumple is shared by all posters, so no need to copy it)'%(self.selected+1))
        elif key=='PASTE':
            if self.fx_clipboard:
                self.set_effects(idx,lambda i:dict(self.fx_clipboard));self.toast('Pasted effects to %d images from #%d'%(len(idx),getattr(self,'fx_clip_from',0)+1))
            else:self.toast('Choose a poster with effects first and press [Copy Effects]')
        elif key=='RESEED':
            rng=np.random.default_rng()
            def reseed(i):
                f=self.effects[i]
                if not f:return None
                f=dict(f);f['seed']=int(rng.integers(1,2**31-1));return f
            self.set_effects([i for i in idx if self.effects[i]],reseed)
        self.area.tag_redraw()

    def fx_source(self,i):
        path=self.paths[i]
        if path not in self.fx_src:
            im=self.images[i];w,h=im.size[:]
            buf=np.empty(w*h*4,np.float32);im.pixels.foreach_get(buf);data=buf.reshape(h,w,4)
            k=min(1.,1024/max(w,h))
            if k<1:data=resize(data,max(1,round(w*k)),max(1,round(h*k)))
            self.fx_src[path]=data
        return self.fx_src[path]

    def paper_params(self):
        """Paper texture for the canvas preview. None if turned off."""
        s=self.settings;pp=getattr(self,'fx_pending',None)
        if pp and pp['id']=='PAPER':
            on=True;pset=pp['set'];v=pp['vals'];var,stg,tile,ao=v['paper_variant'],v['paper_strength'],v['paper_tile_mm'],v['paper_ao']
        else:
            on=s.paper_auto;pset=s.paper_set;var,stg,tile,ao=s.paper_variant,s.paper_strength,s.paper_tile_mm,s.paper_ao
        key=(s.paper_dir,on,pset,var,getattr(self,'paper_preview',True),round(stg,3),round(tile,1),round(ao,3))
        if getattr(self,'_paper_key',None)==key:return self._paper
        self._paper_key=key;self._paper=None
        if not (on and getattr(self,'paper_preview',True)):return None
        folder=paper_folder(s);sets=paper_sets(folder) if folder and os.path.isdir(folder) else {}
        if pset not in sets:return None
        seeds=sorted(sets[pset]);sd=seeds[min(var,len(seeds)-1)];maps=sets[pset][sd]
        try:pm=paper_preview_maps(s,maps['normal'],maps.get('ambientocclusion'))
        except (OSError,RuntimeError,KeyError):return None
        self._paper={'id':[pset,sd,stg,tile,ao],'maps':pm,'strength':stg,'tile':max(tile,1.),'ao':ao}
        return self._paper

    def fx_preview(self,i,fx=None):
        # Run the same pipeline as building at a small size and show it on the canvas.
        import gpu
        if fx is None:fx=self.fx_effective(i)
        paper=paper_info(self.settings,fx_clean(fx).get('paper')) if fx else None
        if not (self.fx_preview_on and fx_active(fx)):return None
        a,b,c,d=self.rects[i];rw,rh=c-a,d-b
        k=min(1.,480/max(rw,rh,1));pw,ph=max(2,round(rw*k)),max(2,round(rh*k))
        key=json.dumps([fx_key(fx),pw,ph,self.crops[i],self.layout_rotations[i],self.settings.background],sort_keys=True)
        old=self.fx_previews.get(i);stale=old[2] if old else None
        if old and old[0]==key:return old[2]
        jobs=getattr(self,'_fx_jobs',None)
        if jobs is None:self._fx_jobs=jobs={}
        job=jobs.get(i)
        if job:
            # A job for this sheet is still running: keep showing the last preview until it finishes.
            # (While painting, the key changes every 0.25 s; queuing a new job each time used to pile
            # up abandoned work so the preview lagged and flashed back to the original.)
            if not job[1].done():return stale
            jobs.pop(i,None)
            try:px=job[1].result()
            except Exception as exc:print('poster_atlas preview',exc);px=None
            if px is not None:
                self.fx_clear_previews({i});tex=gpu_texture_from_pixels(px);self.fx_previews[i]=(job[0],None,tex)
                if job[0]==key:return tex
                stale=tex   # Slightly outdated result: show it now and compute the latest below
            elif job[0]==key:return stale
        if self.drag or self.group_drag or (getattr(self,'slider_drag',None) and not self.slider_drag[0].startswith('A:')):return stale   # Don't recompute while dragging
        # Compute in the background (several sheets at once) so the screen doesn't freeze
        f=fx_clean(fx);f['seed']=fx_seed(f,self.paths[i]);den=layout_density(self.settings)*k;caption_ensure(f,pw if self.layout_rotations[i]%2 else ph)   # caption text is rasterized here (main thread)
        fut=fx_pool().submit(fx_preview_pixels,self.fx_source(i),list(self.crops[i]),self.layout_rotations[i],pw,ph,
                             self.settings.background,f,den,fx_resources(self.settings),paper)
        jobs[i]=(key,fut)
        return stale

    def group_targets(self):
        """List rows of the images selected on the canvas."""
        want={self.paths[i] for i in getattr(self,'selection',{self.selected}) if 0<=i<len(self.paths)}
        out=[]
        for k,f in enumerate(self.settings.files):
            if not f.selected:continue
            try:
                if file_path(f) in want:out.append(k)
            except Exception:pass
        return out

    def group_names(self):
        """Buttons of the Group section: the groups already used in the list (in list order), then 'Group k' up to
        the chosen number of groups. A used group never disappears, even past the number."""
        n=int(getattr(self.settings,'group_count',2));key=(n,tuple(f.group for f in self.settings.files))
        if getattr(self,'_gn_key',None)!=key:
            out=[]
            for f in self.settings.files:
                g=f.group.strip()
                if g and g not in out:out.append(g)
            k=1
            while len(out)<n:
                if 'Group %d'%k not in out:out.append('Group %d'%k)
                k+=1
            self._gn_key=key;self._gn=out
        return self._gn

    def group_selected(self,name):
        idx=self.group_targets()
        if not idx:self.report({'WARNING'},_T('Click images on the canvas first · A selects all'));return
        for k in idx:self.settings.files[k].group=name
        if name:LAST_GROUP[0]=name
        self.report({'INFO'},_T('%d image%s → %s'%(len(idx),'' if len(idx)==1 else 's',name or 'no group')));self.area.tag_redraw()

    def path_groups(self):
        """{image path in the layout: its group} for the canvas badges (cached until the list changes)."""
        key=tuple((f.path,f.quarter_turns,f.group,f.selected) for f in self.settings.files)
        if getattr(self,'_grp_key',None)!=key:
            out={}
            for f in self.settings.files:
                if f.selected and f.group.strip():
                    try:out[file_path(f)]=f.group.strip()
                    except Exception:pass
            self._grp_key=key;self._grp=out
        return self._grp

    def list_snapshot(self):
        return [(f.path,int(f.quarter_turns),bool(f.selected),f.group) for f in self.settings.files]

    def refresh_layout_sources(self,placed=None):
        """Sync the layout with the checked images. placed = {path: saved spot} for images coming back by Ctrl+Z:
        they return to exactly that spot, so nothing else is moved or re-packed."""
        import gpu
        paths=[file_path(f) for f in build_files(self.settings)]
        snap=getattr(self,'list_snap',None);prev_history=list(getattr(self,'history',[]))
        if paths==self.paths:
            self.list_snap=self.list_snapshot();return
        # The image list changed (removed / cleared / unchecked in the sidebar, or a strip was made):
        # keep the old list and each image's place so Ctrl+Z in the editor puts it all back.
        list_undo=None
        if snap is not None and not getattr(self,'_list_restoring',False):
            list_undo={'kind':'LIST','files':snap,'selection':sorted(getattr(self,'selection',{self.selected})),'selected':self.selected,
                       'keep':{p:{'rect':list(r),'mm':m_,'turn':t_,'crop':list(c_),'applied':list(a_),'fx':x_} for p,r,m_,t_,c_,a_,x_ in
                               zip(self.paths,self.rects,self.physical_sizes,getattr(self,'layout_rotations',[0]*len(self.rects)),
                                   getattr(self,'crops',[[0.,0.,1.,1.]]*len(self.rects)),getattr(self,'applied_crops',[[0.,0.,1.,1.]]*len(self.rects)),
                                   getattr(self,'effects',[None]*len(self.rects)))}}
        # Preserve existing hand-edited rectangles; only new selections seek gaps.
        old={p:(im,tex,list(rect),mm,turn) for p,im,tex,rect,mm,turn in zip(self.paths,self.images,self.textures,self.rects,self.physical_sizes,getattr(self,'layout_rotations',[0]*len(self.rects)))}
        active=self.paths[self.selected] if self.paths else None
        selected_paths={self.paths[i] for i in getattr(self,'selection',{self.selected}) if i<len(self.paths)}
        old_crops=dict(zip(self.paths,getattr(self,'crops',[[0.,0.,1.,1.] for _ in self.paths])))
        old_applied=dict(zip(self.paths,getattr(self,'applied_crops',[[0.,0.,1.,1.] for _ in self.paths])))
        old_fx=dict(zip(self.paths,getattr(self,'effects',[None]*len(self.paths))))
        loaded=[];images=[];textures=[]
        try:
            for path in paths:
                if path in old:im,tex,_,_,_=old[path]
                else:
                    im=bpy.data.images.load(path,check_existing=False);loaded.append(im)
                    if min(im.size)<1:raise ValueError('Cannot read the image: '+os.path.basename(path))
                    tex=editor_texture(im,EDITOR_MAX_SIDE)
                images.append(im);textures.append(tex)
        except Exception:
            textures.clear()
            for im in loaded:bpy.data.images.remove(im)
            raise
        sizes=[tuple(im.size) for im in images]
        rects=[list(old[p][2]) if p in old else None for p in paths]
        physical=[old[p][3] if p in old else None for p in paths]
        rotations=[old[p][4] if p in old else 0 for p in paths]
        added_indices=[];existing=[r for r in rects if r is not None];no_room=False;den=layout_density(self.settings)
        for i,path in enumerate(paths):
            if rects[i] is not None:continue
            back=(placed or {}).get(path)
            if back:   # Ctrl+Z: back to its own spot and size
                rects[i]=list(back['rect']);physical[i]=back['mm'];rotations[i]=back['turn'];continue
            if existing:   # New images get the same size as already placed posters (median of long sides)
                longs=sorted(max(c-a,d-b) for a,b,c,d in existing);L=longs[len(longs)//2]
                iw,ih=sizes[i];k=L/max(iw,ih,1);rw,rh=max(2,round(iw*k)),max(2,round(ih*k))
                proposed=centered_layout_rect([self.w//2,self.h//2,self.w//2,self.h//2],rw,rh,self.w,self.pad);mm=[rw/den,rh/den]
            else:proposed,mm=preset_layout_rect([self.w//2,self.h//2,self.w//2,self.h//2],sizes[i],'A4',den,self.w,self.pad)
            free=vacant_layout_rect(proposed,[r for r in rects if r is not None],self.w,self.pad,self.settings.layout_gap)
            if free is None:no_room=True
            rects[i]=free if free is not None else proposed;physical[i]=mm;added_indices.append(i)
        if no_room:   # If there is no free space, keep sizes and try re-packing everything
            packed=pack_layout([(c-a,d-b) for a,b,c,d in rects],self.w,self.pad,self.settings.layout_gap)
            if packed:rects=packed;self.report({'INFO'},_T('Re-packed everything to fit the new images · Ctrl+Z to undo.'))
            else:self.report({'WARNING'},_T('Not enough room; new images overlap · reduce sizes or remove a few.'))
        removed=[im for p,im in zip(self.paths,self.images) if p not in paths]
        old_paths=list(self.paths)
        self.paths=paths;self.images=images;self.textures=textures;self.sizes=sizes;self.rects=rects
        self.physical_sizes=physical
        self.layout_rotations=rotations
        self.crops=[list(old_crops.get(p,[0.,0.,1.,1.])) for p in paths]
        self.applied_crops=[list(old_applied.get(p,[0.,0.,1.,1.])) for p in paths]
        self.effects=[old_fx.get(p) for p in paths];self.fx_clear_previews()
        # Numbers changed, so re-map the target of the effect being chosen by file (otherwise it hits the wrong poster)
        p_=getattr(self,'fx_pending',None)
        if p_:
            tp={old_paths[i] for i in p_.get('targets',[]) if 0<=i<len(old_paths)}
            p_['targets']=[i for i,pth in enumerate(paths) if pth in tp];p_['cache']={};p_.pop('_tset',None)
        self._fx_jobs={}
        self.selected=added_indices[-1] if added_indices else paths.index(active) if active in paths else 0
        self.selection={i for i,p in enumerate(paths) if p in selected_paths}|set(added_indices)
        # Keep the earlier undo steps: they are undone after this list change (newest first), when the list is back as it was
        self.drag=None;self.history=(prev_history+[list_undo])[-40:] if list_undo else (prev_history if getattr(self,'_list_restoring',False) else [])
        self.list_snap=self.list_snapshot()
        old.clear()
        for im in removed:bpy.data.images.remove(im)
        self.area.tag_redraw()

    def layout_hit(self,x,y):
        rs=[getattr(self,'pack_button',(0,0,0,0)),self.crop_apply_button,self.custom_size_button,self.gap_button,getattr(self,'random_size_button',(0,0,0,0)),getattr(self,'copy_size_button',(0,0,0,0)),getattr(self,'optimize_button',(0,0,0,0)),
            getattr(self,'apply_button',(0,0,0,0)),getattr(self,'cancel_button',(0,0,0,0)),getattr(self,'batch_name_button',(0,0,0,0))]
        rs+=[b[0] for b in self.mode_buttons]+[b[0] for b in getattr(self,'res_buttons',[])]+[b[0] for b in self.layout_rotate_buttons]
        rs+=[b[0] for b in self.move_buttons]+[b[0] for b in self.preset_buttons]+[b[0] for b in getattr(self,'bg_buttons',[])]
        for nm in ('group_buttons','tab_buttons','photo_fmt_buttons','photo_border_buttons','caption_buttons','photo_look_buttons','strip_buttons','photo_finish_buttons','paper_finish_buttons','text_buttons','sec_heads'):rs+=[b[0] for b in getattr(self,nm,[])]
        return any(r[0]<=x<=r[2] and r[1]<=y<=r[3] for r in rs)

    def hdr(self):return round(44*max(1.,min(1.5,bpy.context.preferences.system.ui_scale)))

    def controls(self):
        # WINDOW includes the transparent sidebar/toolbar area. Keep buttons
        # inside the actually visible canvas, not behind those other regions.
        left,right=0,self.region.width
        space=self.area.spaces.active
        for r in self.area.regions:
            if r.width<=1:continue
            if r.type=='UI' and space.show_region_ui:
                right=min(right,max(0,r.x-self.region.x))
            elif r.type=='TOOLS' and space.show_region_toolbar:
                left=max(left,r.x+r.width-self.region.x)
        if right-left<160:left,right=0,self.region.width
        factor=max(1.,min(1.5,bpy.context.preferences.system.ui_scale))
        if self.layout_mode:
            right=self.fx_layout(right,factor)
        margin=14*factor;H=22*factor;G=4*factor;bottom=88*factor
        available=max(120,right-left-2*margin)
        bh=28*factor;aw=min(230*factor,available*.62);cw=min(120*factor,available-aw-2*G)
        x=left+margin;y=10*factor
        if self.layout_mode:bottom=30*factor   # layout tools live in the right panel; only the status line stays here
        else:
            self.apply_button=(x,y,x+aw,y+bh)
            self.cancel_button=(x+aw+2*G,y,x+aw+2*G+cw,y+bh)
            self.bar_labels=[]
        if not self.layout_mode and not self.preview_only:
            # Change cols/rows inside the cut window: [−] value [+]
            gx=self.cancel_button[2]+20*factor;sw=24*factor;vw=70*factor;self.grid_buttons=[];gy_=y+(bh-H)/2
            for kind in ('COL','ROW','INSET'):
                self.grid_buttons.append(((gx,gy_,gx+sw,gy_+H),kind,-1));gx+=sw+2*factor
                self.grid_buttons.append(((gx,gy_,gx+vw,gy_+H),kind,0));gx+=vw+2*factor
                self.grid_buttons.append(((gx,gy_,gx+sw,gy_+H),kind,1));gx+=sw+14*factor
            self.chroma_button=(gx,gy_,gx+140*factor,gy_+H);gx+=140*factor+G
            self.chroma_find_button=(gx,gy_,gx+140*factor,gy_+H);gx+=140*factor+G
            self.shadow_button=(gx,gy_,gx+130*factor,gy_+H);gx+=130*factor+14*factor
            self.remove_button=(gx,gy_,gx+130*factor,gy_+H)
            bottom=y+bh+30*factor
        if self.preview_only:
            bw=min(150*factor,(available-2*G)/3)
            self.apply_button=(x,y,x+bw,y+bh)
            self.rotate_left_button=(x+bw+G,y,x+2*bw+G,y+bh)
            self.rotate_right_button=(x+2*bw+2*G,y,x+3*bw+2*G,y+bh)
            bottom=y+bh+30*factor
        return left,right,bottom,factor

    def cut_remove_selected(self):
        """Image Cutting: remove the selected box. Ctrl+Z brings it back."""
        if not self.rects:self.report({'INFO'},_T('No boxes to remove.'));return
        i=max(0,min(self.selected,len(self.rects)-1))
        self.history.append([list(r) for r in self.rects]);self.history=self.history[-40:]
        del self.rects[i];self.drag=None
        self.selected=max(0,min(i,len(self.rects)-1))
        self.report({'INFO'},_T('Removed box %d · %d left · Ctrl+Z to undo'%(i+1,len(self.rects))))
        self.area.tag_redraw()

    def view(self):
        left,right,bottom,_=self.controls();rh=self.region.height
        available=max(10,right-left-40);height=max(10,rh-self.hdr()-8-bottom-20)
        scale=max(.001,min(available/self.w,height/self.h))*self.zoom
        return left+(right-left-self.w*scale)/2+self.pan[0],bottom+(height-self.h*scale)/2+self.pan[1],scale

    def finish(self,save=False):
        # Layout/effects are saved only when finishing with [Build]. Close editor/Esc discards this session's edits.
        if self.closed:return
        self.closed=True
        try:self.win.cursor_modal_restore()   # hand the cursor back to Blender (eyedropper or editor arrow)
        except Exception:pass
        if self.handler:bpy.types.SpaceView3D.draw_handler_remove(self.handler,'WINDOW');self.handler=None
        if self.layout_mode:
            # Closing the editor clears all edits (layout, effects, paper crumple, sticky-note random colors) -> starts fresh next time.
            # When reopened with [Edit], the layout is read fresh from the batch record.
            try:self.settings.layout_plan='';self.settings.postit_pool=''
            except ReferenceError:pass
            if not save:   # Closing without building also restores the paper crumple settings
                self.discard_session_strips()
                try:
                    for k,v in getattr(self,'paper_snap',{}).items():setattr(self.settings,k,v)
                    if self.settings.layout_tab!='PAPER':self.settings.layout_tab='PAPER'   # next time the editor opens on Paper (the default)
                    if getattr(self,'reedit_restore',None):self.settings.update_previous,self.settings.last_collection=self.reedit_restore
                except ReferenceError:pass
            snap=getattr(self,'reedit_list',None)
            if snap is not None:   # Re-edit session: the batch's images were only in the list while editing; put the list back as it was
                try:restore_file_list(self.settings,snap)
                except ReferenceError:pass
            self.fx_clear_previews();self.fx_src={};self._fx_jobs={}
            self.textures.clear()
            for im in self.images:
                try:bpy.data.images.remove(im)
                except ReferenceError:pass
            self.images.clear()
        self.texture=None
        if self.im:bpy.data.images.remove(self.im);self.im=None
        try:self.workspace.status_text_set(None);self.area.tag_redraw()
        except ReferenceError:pass
        if self in CUT_EDITORS:CUT_EDITORS.remove(self)

    def cancel(self,context):self.finish()

    def draw_overlay(self):
        if self.closed or bpy.context.area!=self.area or bpy.context.region!=self.region:return
        import gpu,blf
        from gpu_extras.batch import batch_for_shader
        gpu.state.blend_set('ALPHA');gpu.state.depth_test_set('NONE')
        flat=gpu.shader.from_builtin('UNIFORM_COLOR')
        def box(x0,y0,x1,y1,color):
            # Text drawing may change GPU blend state between overlay elements.
            gpu.state.blend_set('ALPHA')
            b=batch_for_shader(flat,'TRIS',{'pos':[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]},indices=[(0,1,2),(0,2,3)])
            flat.bind();flat.uniform_float('color',color);b.draw(flat)
        def label(x,y,text,color=(1,1,1,1),size=14):
            blf.position(0,x,y,0);blf.size(0,size);blf.color(0,*color);blf.draw(0,_T(text))
        rw,rh=self.region.width,self.region.height
        self._fx_memo={}
        T=ui_theme();fac_=max(1.,min(1.5,bpy.context.preferences.system.ui_scale))
        mx,my=getattr(self,'_mouse',(-9999,-9999))
        held=getattr(self,'_lmb',False) and selection_button_held() is not False
        def rbox(x0,y0,x1,y1,color,r,corners=(True,True,True,True)):
            gpu.state.blend_set('ALPHA')
            b=batch_for_shader(flat,'TRI_FAN',{'pos':rrect_fan(x0,y0,x1,y1,r,4,corners)})
            flat.bind();flat.uniform_float('color',color);b.draw(flat)
        def hot(bd):return bd[0]<=mx<=bd[2] and bd[1]<=my<=bd[3]
        UIR=[]   # buttons of the group being drawn; touching neighbours merge into one aligned block
        th_,tv_=7*fac_,4.5*fac_
        def joined(bd):
            x0,y0,x1,y1=bd;L=R=U=D=None
            for o in UIR:
                if o==bd:continue
                if abs(o[1]-y0)<1 and abs(o[3]-y1)<1:
                    if -1<=x0-o[2]<=th_:L=o
                    if -1<=o[0]-x1<=th_:R=o
                if abs(o[0]-x0)<1 and abs(o[2]-x1)<1:
                    if -1<=y0-o[3]<=tv_:D=o
                    if -1<=o[1]-y1<=tv_:U=o
            # Neighbours meet halfway and overlap by 1px, so the shared border reads as one thin divider.
            if L:x0=round((L[2]+x0)/2)-1
            if R:x1=round((x1+R[0])/2)
            if D:y0=round((D[3]+y0)/2)-1
            if U:y1=round((y1+U[1])/2)
            return (round(x0),round(y0),round(x1),round(y1)),(not(R or D),not(R or U),not(L or U),not(L or D))
        def widget(bd,style='tool',on=False,primary=False,alert=False,dim=False):
            # Blender-style button: theme colors, rounded corners, 1px outline,
            # lighter on hover, blue while pressed or active.
            w=T[style];(x0,y0,x1,y1),cn=joined(bd);r=w['round']*10*fac_
            h_=hot(bd);p_=h_ and held;lit=on or p_ or primary
            inner=w['sel'] if lit else w['inner']
            if alert and not lit:inner=(.43,.21,.21,1)
            if h_ and not p_:inner=shade(inner,.06)
            if dim and not lit:inner=inner[:3]+(inner[3]*.5,)
            rbox(x0,y0,x1,y1,w['outline'],r,cn);rbox(x0+1,y0+1,x1-1,y1-1,inner,max(0,r-1),cn)
            col=w['text_sel'] if lit else w['text']
            return col[:3]+((.45,) if dim and not lit else (1.,))
        def wtext(bd,text,color,size=12,align='C'):
            fs=round(size*fac_);blf.size(0,fs)
            while blf.dimensions(0,_T(text))[0]>bd[2]-bd[0]-8*fac_ and fs>8:fs-=1;blf.size(0,fs)
            tw,_=blf.dimensions(0,_T(text))
            tx=(bd[0]+bd[2]-tw)/2 if align=='C' else bd[0]+7*fac_
            label(tx,(bd[1]+bd[3])/2-fs*.36,text,color,fs)
        qb={};ql=[]
        def qbox(x0,y0,x1,y1,color):   # Draw later in one pass per color
            qb.setdefault(tuple(color),[]).append((x0,y0,x1,y1))
        def qlabel(x,y,text,color=(1,1,1,1),size=14):ql.append((x,y,text,color,size))
        def flush():
            for color,rects in qb.items():
                pos=[];idx=[]
                for x0,y0,x1,y1 in rects:
                    n=len(pos);pos+=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)];idx+=[(n,n+1,n+2),(n,n+2,n+3)]
                gpu.state.blend_set('ALPHA');b=batch_for_shader(flat,'TRIS',{'pos':pos},indices=idx)
                flat.bind();flat.uniform_float('color',color);b.draw(flat)
            qb.clear()
            for x,y,text,color,size in ql:label(x,y,text,color,size)
            ql.clear()
        box(0,0,rw,rh,shade(T['back'],-.06))
        ox,oy,scale=self.view()
        shader=gpu.shader.from_builtin('IMAGE')
        if self.layout_mode:
            background=self.settings.background
            if background=='TRANSPARENT':
                tile=24.;xstart=max(0,ox);ystart=max(0,oy);xend=min(rw,ox+self.w*scale);yend=min(rh,oy+self.h*scale)
                ckey=(round(ox,1),round(oy,1),round(scale,5),rw,rh)
                if getattr(self,'_checks',(None,))[0]!=ckey:   # Rebuild only when the view moves
                    checks=[([],[]),([],[])]
                    for xx in range(math.floor((xstart-ox)/tile),math.ceil((xend-ox)/tile)):
                        for yy in range(math.floor((ystart-oy)/tile),math.ceil((yend-oy)/tile)):
                            positions,indices=checks[(xx+yy)%2];n=len(positions)
                            a,b=max(xstart,ox+xx*tile),max(ystart,oy+yy*tile);c,d=min(xend,ox+(xx+1)*tile),min(yend,oy+(yy+1)*tile)
                            positions.extend(((a,b),(c,b),(c,d),(a,d)));indices.extend(((n,n+1,n+2),(n,n+2,n+3)))
                    self._checks=(ckey,[batch_for_shader(flat,'TRIS',{'pos':p_},indices=i_) if p_ else None for p_,i_ in checks])
                for gray,batch in zip((.38,.26),self._checks[1]):
                    if batch:flat.bind();flat.uniform_float('color',(gray,gray,gray,1));batch.draw(flat)
            else:box(ox,oy,ox+self.w*scale,oy+self.h*scale,(1,1,1,1) if background=='WHITE' else (0,0,0,1))
            budget=[4];paper_on=False;frame_t0=PERF()
            for i,(texture,(a,b,c,d),turn,crop) in enumerate(zip(self.textures,self.rects,self.layout_rotations,self.crops)):
                ca,cb,cc,cd=crop
                coords=[rotate_uv(u,v,-turn) for u,v in [(0,0),(1,0),(1,1),(0,1)]]
                coords=[(ca+u*(cc-ca),cb+v*(cd-cb)) for u,v in coords]
                fx_i=self.fx_effective(i) if self.fx_preview_on else None
                if self.fx_preview_on and (fx_active(fx_i) or paper_on):
                    cached=self.fx_previews.get(i)
                    try:
                        if budget[0]>0 and (budget[0]==4 or PERF()-frame_t0<.05):   # Keep time spent per frame short
                            nj=len(getattr(self,'_fx_jobs',{}))
                            ftex=self.fx_preview(i,fx_i)
                            if len(getattr(self,'_fx_jobs',{}))>nj:budget[0]-=1   # Count only newly queued computations
                        else:ftex=cached[2] if cached else None;self.area.tag_redraw()
                    except Exception as exc:
                        ftex=None;print('poster_atlas preview',exc)
                    if ftex is not None:
                        texture=ftex;coords=[(0,0),(1,0),(1,1),(0,1)]
                        # Lay a dark wall-like base so holes/tears don't vanish into the background (same transparent area as the build result)
                        box(ox+a*scale,oy+b*scale,ox+c*scale,oy+d*scale,(.2,.2,.23,1));shader.bind()
                batch=batch_for_shader(shader,'TRI_FAN',{'pos':[(ox+a*scale,oy+b*scale),(ox+c*scale,oy+b*scale),(ox+c*scale,oy+d*scale),(ox+a*scale,oy+d*scale)],'texCoord':coords})
                shader.bind();shader.uniform_sampler('image',texture);batch.draw(shader)
        else:
            batch=batch_for_shader(shader,'TRI_FAN',{'pos':[(ox,oy),(ox+self.w*scale,oy),(ox+self.w*scale,oy+self.h*scale),(ox,oy+self.h*scale)],'texCoord':[(0,0),(1,0),(1,1),(0,1)]})
            shader.bind();shader.uniform_sampler('image',self.texture);batch.draw(shader)
        sel_set=getattr(self,'selection',{self.selected}) if self.layout_mode else {self.selected}
        pend=self.pend_set() if self.layout_mode and getattr(self,'fx_pending',None) else frozenset()
        touched=self.paint_session['touched'] if self.layout_mode and getattr(self,'paint_session',None) else ()
        groups_=self.path_groups() if self.layout_mode else {}
        for i,(a,b,c,d) in enumerate(self.rects):
            x0,y0,x1,y1=ox+a*scale,oy+b*scale,ox+c*scale,oy+d*scale
            if x1<0 or y1<0 or x0>rw or y0>rh:continue   # Skip off-screen
            picked=i in sel_set
            color=(T['obj_act'] if i==self.selected else T['obj_sel']) if picked else (.72,.72,.72,.9)
            if self.layout_mode and (a<self.pad or b<self.pad or c>self.w-self.pad or d>self.h-self.pad):color=(1.,.3,.25,1.)   # outside the texture: not built until it comes back
            t_=2 if picked else 1
            qbox(x0,y0,x1,y0+t_,color);qbox(x0,y1-t_,x1,y1,color);qbox(x0,y0,x0+t_,y1,color);qbox(x1-t_,y0,x1,y1,color)
            if self.layout_mode and i in pend:   # poster receiving the effect preview: blue frame hugging the image from outside (an inner frame looked smaller than the image)
                a_=T['accent'];w_=3;X0,Y0,X1,Y1=x0-w_,y0-w_,x1+w_,y1+w_
                qbox(X0,Y0,X1,y0,a_);qbox(X0,y1,X1,Y1,a_);qbox(X0,y0,x0,y1,a_);qbox(x1,y0,X1,y1,a_)
            # Scale number/FX/preview badges to the poster's on-screen size (a dot when zoomed out)
            pw_=x1-x0;has_fx=self.layout_mode and fx_active(self.effects[i]);has_pv=self.layout_mode and i in pend
            if pw_>=70:
                k_=max(.45,min(1.,pw_/160.));bh_=23*k_;fs_=max(8,round(14*k_));ty_=y1-3-bh_+6*k_
                g_=groups_.get(self.paths[i],'') if (self.layout_mode and groups_ and i<len(self.paths)) else ''   # the cut window has no image paths
                tag_=str(i+1);nb_=max(20*k_,(18+9*len(tag_))*k_)
                qbox(x0+3,y1-3-bh_,x0+3+nb_,y1-3,(0,0,0,.8));qlabel(x0+3+5*k_,ty_,tag_,color,fs_)
                bx_=x0+6+nb_
                if g_:   # the group in its color (same as the icon next to the name in the sidebar list)
                    gw_=(14+8.5*len(g_))*k_;gc_=GROUP_COLORS.get(group_color_index(g_),(.4,.4,.4))
                    if bx_+gw_>x1-3:g_=g_[0];gw_=22*k_   # small poster: first letter only
                    qbox(bx_,y1-3-bh_,bx_+gw_,y1-3,(*gc_,.95));qlabel(bx_+6*k_,ty_,g_,(1,1,1,1),fs_);bx_+=gw_+3*k_
                if has_fx:qbox(bx_,y1-3-bh_,bx_+34*k_,y1-3,(.45,.2,.55,.9));qlabel(bx_+5*k_,ty_,'FX',(1,1,1,1),fs_);bx_+=37*k_
                # ('Preview' tag hidden: an effect counts as applied as soon as it is clicked)
                if False and has_pv and bx_+76*k_<=x1-2:qbox(bx_,y1-3-bh_,bx_+76*k_,y1-3,T['accent']);qlabel(bx_+6*k_,ty_,'Preview',(1,1,1,1),fs_)
            else:
                d_=max(4,pw_*.14)
                if has_fx:qbox(x0+3,y1-3-d_,x0+3+d_,y1-3,(.55,.25,.7,.95))
                if has_pv:qbox(x0+5+d_,y1-3-d_,x0+5+2*d_,y1-3,T['accent'])
            if i==self.selected and picked:
                for x,y in [(x0,y0),(x1,y0),(x0,y1),(x1,y1),((x0+x1)/2,y0),((x0+x1)/2,y1),(x0,(y0+y1)/2),(x1,(y0+y1)/2)]:qbox(x-4,y-4,x+4,y+4,color)
        flush();self._fx_memo=None
        if self.layout_mode:
            try:self.text_overlay(flat,batch_for_shader,fac_)
            except Exception as exc:print('poster_atlas text overlay',exc)
        if getattr(self,'_fx_jobs',None):   # If a preview is still computing in the background, redraw shortly
            FX_POKE[0]=self.area
            if not bpy.app.timers.is_registered(fx_poke):bpy.app.timers.register(fx_poke,first_interval=.08)
        left,right,bottom,factor=self.controls()
        if self.layout_mode and self.marquee:
            x0,y0,x1,y1,_,_=self.marquee
            a,c=sorted((ox+x0*scale,ox+x1*scale));b,d=sorted((oy+y0*scale,oy+y1*scale))
            a,c=max(left,a),min(right,c);b,d=max(bottom,b),min(rh-self.hdr(),d)
            if c>a and d>b:
                # An outline leaves the image unobscured on every graphics backend.
                for bounds in ((a-1,b-1,c+1,b+2),(a-1,d-2,c+1,d+1),(a-1,b-1,a+2,d+1),(c-2,b-1,c+1,d+1)):box(*bounds,(.05,.05,.05,1))
                for bounds in ((a,b,c,b+1),(a,d-1,c,d),(a,b,a+1,d),(c-1,b,c,d)):box(*bounds,(.65,.82,1,1))
        title=('Image Preview · %d / %d'%(self.source_index+1,len(self.settings.files))) if self.preview_only else ('Image Cutting · %d'%len(self.rects))
        help_text='Wheel zoom · ← → previous·next · Q left 90° / E right 90° · Home frame all' if self.preview_only else 'Drag boxes · Click a box, Del / X: remove it · Wheel zoom · Middle button pan · Ctrl Z undo · Home frame all'
        if self.layout_mode:
            title='Texture Layout · %d · %d × %d'%(len(self.paths),self.w,self.h)
            help_text='Drag empty space / B: box select · Shift click: add·remove · Shift + drag a handle: keep ratio · A: all · Alt A: none · Del: remove from layout · W: swap numbers (2 selected) / number by position (3+) · Arrow keys: move selection'
        hh=self.hdr();box(0,rh-hh,rw,rh,T['header']);box(0,rh-hh,rw,rh-hh+1,T['tool']['outline'])
        label(left+14*fac_,rh-19*fac_,title,T['tool']['text'][:3]+(1,),size=round(14*fac_))
        label(left+14*fac_,rh-36*fac_,help_text,T['dim'],size=round(11*fac_))
        box(0,0,rw,bottom,T['header']);box(0,bottom-1,rw,bottom,T['tool']['outline'])
        B=[]
        if self.preview_only:
            B+=[(self.apply_button,'Close',dict(primary=True)),(self.rotate_left_button,'Left 90°  (Q)',{}),(self.rotate_right_button,'Right 90°  (E)',{})]
        elif self.layout_mode:
            B+=[(self.apply_button,'Build  ·  Texture + Posters',dict(primary=True)),(self.cancel_button,'Close Editor',{})]
            dl_=getattr(self,'dest_lines',[])
            if dl_ and getattr(self,'batch_name_button',(-99,))[0]>-99:B.append((self.batch_name_button,dl_[0][1]+'   ✎',dict(style='text')))
        else:
            B+=[(self.apply_button,'Apply  ·  Save PNG',dict(primary=True)),(self.cancel_button,'Cancel',{})]
        if not self.layout_mode and not self.preview_only:
            st=self.settings
            for bounds,kind,step in getattr(self,'grid_buttons',[]):
                if step:B.append((bounds,'−' if step<0 else '+',{}))
                elif kind=='INSET':B.append((bounds,'Inset %d px'%st.chroma_inset,dict(style='text')))
                else:B.append((bounds,'%s %d'%('Cols' if kind=='COL' else 'Rows',st.cut_columns if kind=='COL' else st.cut_rows),dict(style='text')))
            if hasattr(self,'chroma_button'):
                cm_=getattr(self,'chroma_mode',None)   # light only the one that was used (both make the green transparent on save)
                B.append((self.chroma_button,'Trim Green to Fit',dict(style='radio',on=cm_=='FIT')))
                B.append((self.chroma_find_button,'Find Cells by Green',dict(style='radio',on=cm_=='FIND')))
                B.append((self.shadow_button,'Remove Shadows',dict(style='radio',on=getattr(self,'shadow_cut',False))))
            if hasattr(self,'remove_button'):
                B.append((self.remove_button,'Remove Box %d  (Del)'%(self.selected+1) if self.rects else 'Remove Box  (Del)',{}))
        if self.layout_mode:
            st=self.settings
            for bounds,name in self.preset_buttons:
                wmm,hmm=POSTER_FORMATS[name]
                B.append((bounds,name if len(name)>3 else '%s  %d×%d'%(name,wmm,hmm),{}))   # size only
            for bounds,k_ in getattr(self,'tab_buttons',[]):B.append((bounds,{'PAPER':'Paper','PICTURE':'Picture'}[k_],dict(style='radio',on=st.layout_tab==k_)))
            ph_=self.photo_get(self.selected) if self.rects else None
            for bounds,k_ in getattr(self,'photo_fmt_buttons',[]):
                if k_=='STRIP':B.append((bounds,'Photo Strip',dict(style='radio',on=getattr(self,'strip_open',False))));continue
                B.append((bounds,'Off' if k_=='OFF' else k_,dict(style='radio',on=(not ph_) if k_=='OFF' else bool(ph_) and ph_.get('photo_fmt')==k_)))
            for bounds,k_ in getattr(self,'photo_border_buttons',[]):
                fr_=bool(ph_.get('frame')) if ph_ else None;cu_=bool(ph_ and ph_.get('frame_custom') and fr_)
                on_={'FRAME':fr_ is True and not cu_,'NONE':fr_ is False,'CUSTOM':cu_}[k_]
                B.append((bounds,{'FRAME':'White Border','NONE':'Borderless','CUSTOM':'Custom…'}[k_],dict(style='radio',on=on_)))
            te_=getattr(self,'text_edit',None);tit_=te_['item'] if te_ else {}
            for bounds,k_ in getattr(self,'text_buttons',[]):
                if k_=='ADD':B.append((bounds,'Add Text  (T)',dict(primary=bool(te_ and te_['typing']))))
                elif k_=='DEL':B.append((bounds,'Delete Text',dict(dim=not te_)))
                elif k_=='LSV':B.append((bounds,'Line ×%.1f'%float(tit_.get('ls',getattr(self,'text_ls',1.))),dict(style='text')))
                elif k_ in ('LS-','LS+'):B.append((bounds,'−' if k_=='LS-' else '+',{}))
                elif k_=='MORE':
                    cf_=tit_.get('font',getattr(self,'text_font','INK'))
                    B.append((bounds,'All Fonts…' if cf_ in TEXT_FONTS else text_font_label(cf_),dict(style='radio',on=cf_ not in TEXT_FONTS)))
                elif k_[0]=='W':B.append((bounds,TEXT_WEIGHTS[k_[1]][0],dict(style='radio',on=int(tit_.get('wt',getattr(self,'text_wt',0)) or 0)==k_[1])))
                elif k_[0]=='F':B.append((bounds,{'INK':'Ink Free','PRINT':'Segoe Print','SCRIPT':'Segoe Script','TYPE':'Typewriter','BOLD':'Arial Black'}[k_[1]],dict(style='radio',on=tit_.get('font',getattr(self,'text_font','INK'))==k_[1])))
                else:B.append((bounds,TEXT_INKS[k_[1]][0],dict(style='radio',on=tit_.get('ink',getattr(self,'text_ink','BLACK'))==k_[1])))
            for bounds,k_ in getattr(self,'caption_buttons',[]):
                cap_=((ph_ or {}).get('caption') or '').replace('\n',' / ')
                B.append((bounds,('Caption  ·  '+(cap_[:28]+('…' if len(cap_)>28 else ''))) if cap_ else 'Caption…',dict(style='radio',on=bool(cap_))))
            sk_=self.surface_key(self.selected) if self.rects and (getattr(self,'paper_finish_buttons',[]) or getattr(self,'photo_finish_buttons',[])) else None
            for bounds,k_ in getattr(self,'paper_finish_buttons',[])+getattr(self,'photo_finish_buttons',[]):   # one Surface, same on both tabs
                B.append((bounds,'Custom…' if k_=='CUSTOM' else PAPER_FINISHES[k_][0],dict(style='radio',on=sk_==k_)))
            nsel_=len([i for i in getattr(self,'selection',{self.selected}) if 0<=i<len(self.rects)])
            for bounds,k_ in getattr(self,'strip_buttons',[]):
                t_=k_[0]
                if t_=='L':B.append((bounds,'%d×%d'%(k_[1],k_[2]),dict(style='radio',on=(st.strip_cols,st.strip_rows)==(k_[1],k_[2]))))
                elif t_ in ('C-','R-'):B.append((bounds,'◀',{}))
                elif t_ in ('C+','R+'):B.append((bounds,'▶',{}))
                elif t_=='CV':B.append((bounds,'%d col'%st.strip_cols,dict(style='text')))
                elif t_=='RV':B.append((bounds,'%d row'%st.strip_rows,dict(style='text')))
                elif t_=='FR':B.append((bounds,k_[1].title(),dict(style='radio',on=st.strip_frame==k_[1])))
                elif t_=='STAG':B.append((bounds,'Stagger',dict(style='radio',on=st.strip_stagger)))
                else:B.append((bounds,'Make %d-Cut  ·  %s card  (%d selected)'%(st.strip_cols*st.strip_rows,strip_card(st.strip_cols,st.strip_rows)[2],nsel_),dict(primary=True)))   # an action: accent color so it reads as a button
            for bounds,k_ in getattr(self,'photo_look_buttons',[]):
                if k_.startswith('FX:'):B.append((bounds,'Sun Faded',dict(style='radio',on=self.fx_on('PRESET:'+k_[3:]))));continue
                lk_=(ph_.get('pol_style') if ph_.get('polaroid') else 'OFF') if ph_ else None
                B.append((bounds,'Off' if k_=='OFF' else dict(POL_STYLE_NAMES)[k_].replace(' 70s','').replace(' Film','').replace(' Sun',''),dict(style='radio',on=lk_==k_)))
            B.append((self.custom_size_button,'%g × %g mm'%(st.custom_width,st.custom_height),dict(style='text')))
            B.append((self.gap_button,'Spacing  %d px'%st.layout_gap,dict(style='text')))
            if getattr(self,'random_size_button',(-99,))[0]>-99:B.append((self.random_size_button,('Random ±%d%%  ·  release'%st.random_size_pct) if getattr(self,'rand_drag',None) else 'Random Size  →',dict(style='radio',on=bool(getattr(self,'rand_drag',None)))))
            if getattr(self,'copy_size_button',(-99,))[0]>-99:B.append((self.copy_size_button,'Copy Size  #%d'%(self.selected+1) if self.rects else 'Copy Size',dict(dim=len(getattr(self,'selection',()))<2)))
            for bounds,mode,text in self.mode_buttons:B.append((bounds,text,dict(style='radio',on=st.edit_mode==mode)))
            B.append((self.crop_apply_button,'Apply Crop',dict(dim=st.edit_mode!='CROP')))
            for bounds,text,h,v in self.move_buttons:B.append((bounds,'•' if text=='Center' else text,{}))
            for bounds,delta in self.layout_rotate_buttons:B.append((bounds,'↺ 90°' if delta<0 else '↻ 90°',{}))
            if getattr(self,'pack_button',None):B.append((self.pack_button,'Pack',{}))
            if getattr(self,'optimize_button',None):B.append((self.optimize_button,'Optimal',{}))
            for bounds,k_ in getattr(self,'bg_buttons',[]):B.append((bounds,{'WHITE':'White','BLACK':'Black','TRANSPARENT':'Alpha'}[k_],dict(style='radio',on=st.background==k_)))
            if getattr(self,'group_buttons',None):
                cur_={st.files[k].group.strip() for k in self.group_targets()}
                for bounds,k_ in self.group_buttons:
                    if k_[0]=='G':B.append((bounds,k_[1],dict(style='radio',on=cur_=={k_[1]})))
                    elif k_[0] in ('GC-','GC+'):B.append((bounds,'−' if k_[0]=='GC-' else '+',{}))
                    elif k_[0]=='GCV':B.append((bounds,'%d group%s'%(st.group_count,'' if st.group_count==1 else 's'),dict(style='text')))
                    elif k_[0]=='GREN':B.append((bounds,'Rename…',dict(dim=not (cur_-{''}))))
                    else:B.append((bounds,'No Group',dict(dim=not (cur_-{''}))))
            for bounds,r in getattr(self,'res_buttons',[]):B.append((bounds,(res_label(self.w) if self.w not in (2048,4096) else 'Custom') if r=='CUSTOM' else res_label(r),dict(style='radio',on=(self.w not in (2048,4096)) if r=='CUSTOM' else r==self.w)))
        def draw_B():
            for txt,bd in getattr(self,'bar_labels',[]):label(bd[0],(bd[1]+bd[3])/2-4*fac_,txt,T['dim'],size=round(11*fac_))
            UIR[:]=[b_ for b_,_,_ in B]
            for bounds,text,kw in B:
                if bounds[2]-bounds[0]<1:continue
                col=widget(bounds,**kw);wtext(bounds,text,col,12 if bounds[3]-bounds[1]>=24*fac_ else 11)
        if not self.layout_mode:draw_B()
        if self.preview_only:
            item=self.settings.files[self.source_index]
            info='%d × %d px  |  Rotation %d°  |  %s'%(self.w,self.h,item.quarter_turns*90,os.path.basename(item.path))
        elif self.rects:
            a,b,c,d=self.rects[self.selected]
            info='Selected #%d  |  %d × %d px  |  You can also save with Enter.'%(self.selected+1,c-a,d-b)
            if self.layout_mode:
                density=layout_density(self.settings)
                turn=self.layout_rotations[self.selected]
                raw=((d-b)/density,(c-a)/density) if turn%2 else ((c-a)/density,(d-b)/density)
                pw,ph=self.physical_sizes[self.selected] or raw
                info='#%d | %d × %d px → %.1f × %.1f mm'%(self.selected+1,c-a,d-b,pw,ph)
                info='%d selected · '%len(self.selection)+info
                if turn:info+=' | Layout-only rotation %d°'%(turn*90)
                if self.settings.edit_mode=='CROP':info+=' | Inside: move photo / Border: crop / Shift wheel: zoom photo'
                elif self.settings.edit_mode=='SCALE':info+=' | Width·height independent'
                else:info+=' | Keep whole photo ratio'
        else:info='No images are checked. Check the images to use in the list.'
        label(left+14*fac_,bottom-20*factor,info,T['dim'][:3]+(.9,),size=round(11*factor))
        if self.layout_mode:
            x0,y0,x1,y1=self.fx_panel;box(x0,y0,x1,y1,T['header']);box(x0,y0,x0+1,y1,T['tool']['outline'])
            d=self.fx_draft_get();cur=fx_clean(self.effects[self.selected]) if self.rects else fx_clean(None)
            pend=getattr(self,'fx_pending',None);applied={l['id'] for i_ in (self.fx_targets() if self.rects else []) if 0<=i_<len(self.effects) for l in fx_layers(self.effects[i_])}
            # an effect being previewed on other posters doesn't light its button for the posters selected now
            pend_here=bool(pend) and bool(self.pend_set() & set(self.fx_targets() if self.rects else ()))
            TXT=T['tool']['text'][:3]+(1,)
            def chevron(cx,cy,open_):
                s=3.5*factor
                pts=[(cx-s,cy+s*.5),(cx,cy-s*.5),(cx+s,cy+s*.5)] if open_ else [(cx-s*.5,cy+s),(cx+s*.5,cy),(cx-s*.5,cy-s)]
                gpu.state.blend_set('ALPHA');gpu.state.line_width_set(1.5*factor)
                bt=batch_for_shader(flat,'LINE_STRIP',{'pos':pts});flat.bind();flat.uniform_float('color',TXT[:3]+(.85,));bt.draw(flat)
                gpu.state.line_width_set(1.)
            for hd,title,op in ((self.lay_head,'Layout  ·  %d × %d'%(self.w,self.h),PANEL_OPEN['layout']),
                                (self.fx_head,'Effects  ·  %d selected'%len(self.fx_targets()),PANEL_OPEN['effects'])):
                hx0,hy0,hx1,hy1=hd
                rbox(hx0+5*factor,hy0,hx1-5*factor,hy1,shade(T['header'],.06 if hot(hd) else .035),4*factor)
                chevron(hx0+16*factor,(hy0+hy1)/2,op)
                label(hx0+28*factor,(hy0+hy1)/2-4.5*factor,title,TXT,size=round(12*factor))
                if hd is self.fx_head or hd is self.lay_head:   # Reset: effects / size of the selected posters
                    rb=(hx1-72*factor,hy0+3*factor,hx1-10*factor,hy1-3*factor)
                    if hd is self.fx_head:self.fx_reset_button=rb
                    else:self.lay_reset_button=rb
                    w_=T['tool'];rbox(*rb,w_['outline'],3*factor);rbox(rb[0]+1,rb[1]+1,rb[2]-1,rb[3]-1,shade(w_['inner'],.08) if hot(rb) else w_['inner'],3*factor)
                    wtext(rb,'Reset',w_['text'] if 'text' in w_ else TXT,round(11*factor),'C')
            def text_in(bounds,text,size=12,color=(1,1,1,1),align='C'):wtext(bounds,text,color,size,align)
            def ring(bounds):rbox(bounds[0]-2,bounds[1]-2,bounds[2]+2,bounds[3]+2,T['accent'],4*factor)
            def swatch(bounds,col):
                rbox(*bounds,T['tool']['outline'],3*factor);rbox(bounds[0]+1,bounds[1]+1,bounds[2]-1,bounds[3]-1,col,2*factor)
            def slider(bounds,t,text,vs):
                w=T['numslider'];r=w['round']*10*factor;inner=shade(w['inner'],.06) if hot(bounds) else w['inner']
                (a0,b0,a1,b1),cn=joined(bounds)
                rbox(a0,b0,a1,b1,w['outline'],r,cn);rbox(a0+1,b0+1,a1-1,b1-1,inner,max(0,r-1),cn)
                fw=(a1-a0-2)*t
                if fw>1:rbox(a0+1,b0+1,a0+1+fw,b1-1,w['item'],max(0,min(r-1,fw/2)),(cn[0] and t>.99,cn[1] and t>.99,cn[2],cn[3]))
                tc=w['text'][:3]+(1,);wtext(bounds,text,tc,11,'L')
                fs=round(11*factor);blf.size(0,fs);tw,_=blf.dimensions(0,_T(vs))
                label(bounds[2]-tw-7*factor,(bounds[1]+bounds[3])/2-fs*.36,vs,tc,fs)
            vx0,vy0,vx1,vy1=self.fx_view;fy1=self.fx_foot[3]
            pp_=pend or {}
            UIR[:]=[bd for kind,bd,key,text in self.fx_widgets if bd[3]>fy1+1 and kind not in ('head','label','help','swatch','sep','ppool','layer')
                    and not (kind=='plabel' and key!='SEEDV') and not (kind=='pcol' and POSTIT_COLORS[key][1])]
            for kind,bounds,key,text in self.fx_widgets:
                if bounds[3]<=fy1+1:continue
                if bounds[1]<vy0-1 or bounds[3]>vy1+1:continue   # Outside the scroll area
                if kind=='head':label(bounds[0],bounds[1]+4*factor,text,TXT,size=round(12*factor));continue
                if kind=='label':label(bounds[0],bounds[1]+4*factor,text,T['dim'],size=round(11*factor));continue
                if kind=='help':label(bounds[0]+2*factor,bounds[1]+3*factor,text,(.62,.78,1,1) if key=='select' else T['dim'][:3]+(.85,),size=round(11*factor));continue
                if kind=='swatch':
                    picked=(d[key] is None and text is None) or (d[key] is not None and text is not None and max(abs(p_-q) for p_,q in zip(d[key],text))<1e-3)
                    if picked:ring(bounds)
                    if text is None:c_=widget(bounds,'tool');text_in(bounds,'Original',10,c_)
                    else:swatch(bounds,tuple(text)+(1,))
                    continue
                if kind=='sep':box(bounds[0],bounds[1],bounds[2]-10*factor,bounds[3],T['tool']['outline']);continue
                if kind=='plabel':
                    if key=='SEEDV':c_=widget(bounds,'text');text_in(bounds,text,11,c_)
                    else:text_in(bounds,text,11,T['dim'][:3]+(.9,),'L')
                    continue
                if kind=='amtslider':
                    _,lo,hi,fmt=PEND_SLIDERS[key];v=float(getattr(self,'fx_'+key,1.));slider(bounds,max(0.,min(1.,(v-lo)/(hi-lo))),text,fmt%v);continue
                if kind=='look':
                    c_=widget(bounds,'radio',on=self.look_state()[0]==key);text_in(bounds,text,11,c_);continue
                if kind=='lamt':
                    lk_,k_=self.look_state()
                    on_=bool(lk_) and ((key=='CUSTOM' and (getattr(self,'look_custom',False) or not any(abs(k_-v)<1e-3 for v in LOOK_K.values()))) or (key in LOOK_K and abs(k_-LOOK_K[key])<1e-3 and not getattr(self,'look_custom',False)))
                    c_=widget(bounds,'radio',on=on_,dim=not lk_);text_in(bounds,text,11,c_);continue
                if kind=='lslider':
                    v=self.look_state()[1];slider(bounds,max(0.,min(1.,v/1.5)),text,'%.2f'%v);continue
                if kind=='button' and key=='LOOK_OFF':
                    c_=widget(bounds,'tool',dim=not self.look_state()[0]);text_in(bounds,text,11,c_);continue
                if kind=='button' and isinstance(key,str) and (key.startswith('COLOROFF:') or key=='TOOL_OFF'):
                    off_=(d.get(key[9:]) is None) if key.startswith('COLOROFF:') else not (getattr(self,'painting_on',False) or (self.rects and 0<=self.selected<len(self.effects) and self.effects[self.selected] and fx_has_paint(fx_clean(self.effects[self.selected]))))
                    c_=widget(bounds,'tool',dim=off_);text_in(bounds,text,11,c_);continue
                if kind in ('fxoff','amt'):   # the Strength row works on the effect being previewed: none = the whole row greyed out, nothing lit
                    live_=bool(pend) and (pend['id'].startswith('PRESET:') or pend['id']=='PAPER')
                    on_=kind=='amt' and live_ and getattr(self,'fx_amount','LOW')==key
                    c_=widget(bounds,'radio' if kind=='amt' else 'tool',on=on_,dim=not live_);text_in(bounds,text,11,c_);continue
                if kind=='ppm':c_=widget(bounds,'radio',on=pp_.get('mode')==key);text_in(bounds,text,11,c_);continue
                if kind in ('ppv','pseed'):c_=widget(bounds,'tool');text_in(bounds,text,11,c_);continue
                if kind=='ppslider':
                    _,lo,hi,fmt=PAPER_SLIDERS[key];v=float((pp_.get('vals') or {}).get(key,lo));slider(bounds,max(0.,min(1.,(v-lo)/(hi-lo))),text,fmt%v);continue
                if kind=='ppool':
                    if pp_.get('pool_sel',0)==key:ring(bounds)
                    swatch(bounds,tuple(text)+(1,));continue
                if kind=='ppbtn':
                    on=key=='EYEDROP' and bool(getattr(self,'eyedrop',None));c_=widget(bounds,'tool',on=on);text_in(bounds,text,10 if key=='EYEDROP' else 11,c_);continue
                if kind=='pcol':
                    on=pp_.get('color','Y')==key;col=POSTIT_COLORS[key][1]
                    if col:
                        if on:ring(bounds)
                        swatch(bounds,tuple(col)+(1,));text_in(bounds,text,11,(0,0,0,1))
                    else:c_=widget(bounds,'radio',on=on);text_in(bounds,text,11,c_)
                    continue
                if kind=='pdslider':
                    _,lo,hi,fmt=PEND_SLIDERS[key];v=float(pp_.get(key,1.));slider(bounds,max(0.,min(1.,(v-lo)/(hi-lo))),text,fmt%v);continue
                if kind in ('pamt','pscl'):
                    on=pp_.get('amount' if kind=='pamt' else 'scale','LOW')==key;c_=widget(bounds,'radio',on=on);text_in(bounds,text,11,c_);continue
                if kind=='ppreset':c_=widget(bounds,'radio',on=self.paper_mode()==key);text_in(bounds,text,11,c_);continue
                if kind=='pvar':c_=widget(bounds,'radio',on=paper_variant_index(self.settings)==key);text_in(bounds,text,11,c_);continue
                if kind=='pset':
                    st=self.settings;on=(key=='NONE' and not st.paper_auto) or (st.paper_auto and key=='%s|%d'%(st.paper_set,paper_variant_index(st)))
                    c_=widget(bounds,'radio',on=on);text_in(bounds,text,11,c_);continue
                if kind=='pbtn':c_=widget(bounds,'radio',on=key=='PAPER_PREVIEW' and getattr(self,'paper_preview',True));text_in(bounds,text,11,c_);continue
                if kind=='pslider':
                    _,lo,hi,fmt=PAPER_SLIDERS[key];v=getattr(self.settings,key);slider(bounds,max(0.,min(1.,(v-lo)/(hi-lo))),text,fmt%v);continue
                if kind=='slider':
                    _,lo,hi,fmt=FX_SLIDERS[key];v=d[key];slider(bounds,max(0.,min(1.,(v-lo)/(hi-lo))),text,fmt%v);continue
                if kind=='layer':
                    lb=(bounds[0],bounds[1],bounds[2]-26*factor,bounds[3]);c_=widget(lb,'text');text_in(lb,'✓  '+text,11,c_,'L')
                    xb=(bounds[2]-24*factor,bounds[1],bounds[2],bounds[3]);c_=widget(xb,'tool',alert=True);text_in(xb,'×',13,c_);continue
                mark=''
                if kind=='tab':on=getattr(self,'fx_tab','COLOR')==key or (bool(pend) and pend['id']=='TAB:'+key)
                elif kind=='brush':on=d.get('brush','select')==key
                elif kind=='tip':on=d.get('tip','soft')==key
                elif kind=='power':on=abs(d['brush_strength']-key)<1e-3
                elif isinstance(key,str) and key.startswith('PRESET:'):
                    on=key in applied or (pend_here and pend['id']==key)
                elif key=='JITTER':   # drawn as a checkbox: [x] Vary per sheet
                    on=self.fx_jitter;sz=bounds[3]-bounds[1]-6*factor;bx0=bounds[0]+2*factor;by0=bounds[1]+3*factor
                    rbox(bx0,by0,bx0+sz,by0+sz,T['tool']['outline'],3*factor)
                    rbox(bx0+1,by0+1,bx0+sz-1,by0+sz-1,T['accent'] if on else T['tool']['inner'],2*factor)
                    if on:text_in((bx0,by0,bx0+sz,by0+sz),'✓',11,(1,1,1,1))
                    text_in((bx0+sz+6*factor,bounds[1],bounds[2],bounds[3]),text,11,TXT,'L');continue
                elif key=='PAPER_FOCUS':
                    on='PAPER' in applied or (pend_here and pend['id']=='PAPER')
                elif key=='PREVIEW':on=self.fx_preview_on
                elif isinstance(key,str) and key.startswith('PICK:'):   # a picked / eyedropped color that is not one of the cells: light up Custom and show it
                    k_=key[5:];v_=d.get(k_)
                    cells_=(FX_PAPER_SWATCHES+FX_PAPER_GRAYS) if k_=='tint' else (FX_INK_SWATCHES+FX_INK_GRAYS)
                    on=v_ is not None and not any(c is not None and max(abs(p_-q) for p_,q in zip(c,v_))<1e-3 for c in cells_)
                    if on:
                        c_=widget(bounds,'radio',on=True);sw_=(bounds[2]-12*factor,bounds[1]+4*factor,bounds[2]-4*factor,bounds[3]-4*factor)
                        text_in((bounds[0],bounds[1],bounds[2]-12*factor,bounds[3]),text,11,c_);swatch(sw_,tuple(v_[:3])+(1,));continue
                else:on=False
                radio=kind in ('tab','brush','tip','power') or key in ('JITTER','PREVIEW','PAPER_FOCUS') or (isinstance(key,str) and key.startswith('PRESET:'))
                c_=widget(bounds,'radio' if radio else 'tool',on=on,alert=key in ('CLEAR','PAINT_CLEAR'))
                text_in(bounds,mark+(text if isinstance(text,str) else ''),11,c_)
            # Fixed bottom cell: commit the chosen effect
            fy0=self.fx_foot[1]
            import time
            tst=getattr(self,'fx_toast',None)
            if tst and time.time()-tst[1]<4.:
                blf.size(0,round(11*factor));words=tst[0].split(' ');lines=[];cur_=''
                for w_ in words:
                    t_=(cur_+' '+w_).strip()
                    if cur_ and blf.dimensions(0,_T(t_))[0]>(x1-x0)-32*factor:lines.append(cur_);cur_=w_
                    else:cur_=t_
                if cur_:lines.append(cur_)
                th=(len(lines)*15+10)*factor
                rbox(x0+6,fy1+6,x1-6,fy1+6+th,shade(T['header'],.1),4*factor);box(x0+6,fy1+8,x0+6+3*factor,fy1+4+th,T['accent'])
                for k_,ln in enumerate(lines):label(x0+16*factor,fy1+6+th-(k_+1)*15*factor,ln,TXT,size=round(11*factor))
            # Finish: builds the whole layout (texture + posters) — kept apart from the per-effect Apply above
            fa=self.fin_area
            box(x0,0,x1,fa[3],shade(T['header'],-.045));box(x0,fa[3]-2,x1,fa[3],T['tool']['outline'])
            label(x0+10*factor,fa[3]-16*factor,'Finish  ·  whole layout',T['dim'],size=round(11*factor))
            fs_=round(11*factor)
            for k_,(kind_,txt_,g_) in enumerate(getattr(self,'dest_lines',[])):   # where the build goes (and each group)
                if kind_=='main':continue   # drawn as the clickable name field (see B)
                yy_=fa[3]-16*factor-(k_+1)*15*factor-6*factor;xg_=x0+18*factor
                if g_:
                    gc_=GROUP_COLORS.get(group_color_index(g_),(.5,.5,.5));box(xg_,yy_+1*factor,xg_+8*factor,yy_+9*factor,(*gc_,1.));xg_+=13*factor
                blf.size(0,fs_);t_=txt_;wmax_=x1-8*factor-xg_
                while len(t_)>2 and blf.dimensions(0,_T(t_))[0]>wmax_:t_=t_[:-2]+'…'
                label(xg_,yy_,t_,TXT if kind_=='main' else T['dim'],size=fs_)
            draw_B()
            # Brush cursor and the stroke being drawn
            tool=d.get('brush','select')
            if getattr(self,'painting_on',False) and getattr(self,'paint_cursor',None) and tool!='cut':
                cx,cy=self.paint_cursor;rad=d['brush_size']/2*layout_density(self.settings)*scale
                pts=[(cx+rad*math.cos(t*math.pi/24),cy+rad*math.sin(t*math.pi/24)) for t in range(49)]
                gpu.state.blend_set('ALPHA');bt=batch_for_shader(flat,'LINE_STRIP',{'pos':pts});flat.bind()
                flat.uniform_float('color',FX_TOOL_COLORS.get(tool,(1,.85,.2))+(1,));bt.draw(flat)
            if getattr(self,'cut_drag',None):
                i,cut=self.cut_target()
                if i is not None:
                    poly=self.cut_poly(i,cut)
                    if len(poly)>=3:
                        gpu.state.blend_set('ALPHA');bt=batch_for_shader(flat,'TRIS',{'pos':poly},indices=[(0,k,k+1) for k in range(1,len(poly)-1)])
                        flat.bind();flat.uniform_float('color',(1,.15,.15,.45));bt.draw(flat)
                x0_,y0_,x1_,y1_=self.cut_drag
                gpu.state.line_width_set(2.);bt=batch_for_shader(flat,'LINES',{'pos':[(x0_,y0_),(x1_,y1_)]});flat.bind()
                flat.uniform_float('color',(1,.25,.2,1));bt.draw(flat);gpu.state.line_width_set(1.)
            if getattr(self,'painting_on',False):   # Band showing painting is in progress
                name=dict(FX_TOOLS).get(tool,'')
                msg='Paint · %s — drag over a poster  |  [ ] brush size  |  right-click to stop'%name if tool!='cut' else 'Cut — draw a straight line across a poster  |  right-click to stop'
                bx1=self.fx_panel[0]-12;by1=self.region.height-self.hdr()-8
                box(12,by1-30*factor,bx1,by1,(.12,.1,.05,.88));box(12,by1-30*factor,16,by1,FX_TOOL_COLORS.get(tool,(1,.85,.2))+(1,))
                label(24,by1-21*factor,msg,(1,.9,.6,1),size=round(13*factor))
            for sx,sy,sr,col in getattr(self,'stroke_marks',[])[-400:]:
                box(sx-sr*.25,sy-sr*.25,sx+sr*.25,sy+sr*.25,col)
        if self.layout_mode and getattr(self,'snap_on',False) and self.drag and self.drag[3]=='MOVE':   # snap guides + badge
            ox_,oy_,sc_=self.view()
            for ax_,v_ in getattr(self,'snap_guides',[]):
                if ax_=='X':box(ox_+v_*sc_-1,oy_,ox_+v_*sc_+1,oy_+self.h*sc_,(.3,.85,1.,.85))
                else:box(ox_,oy_+v_*sc_-1,ox_+self.w*sc_,oy_+v_*sc_+1,(.3,.85,1.,.85))
            label(mx+18*fac_,my-22*fac_,'Snap  ·  B off  ·  Shift straight',(.5,.9,1.,1.),size=round(12*fac_))
        sd_=getattr(self,'scale_drag',None)
        if sd_:   # S scale preview: outlines of the selected images at the new size, around their own centers
            ox_,oy_,sc_=self.view();k_=sd_['k'];t_=max(1.,1.5*fac_)
            for i in sd_['sel']:
                if not 0<=i<len(self.rects):continue
                a,b,c,d=self.rects[i];cx,cy=(a+c)/2,(b+d)/2;hw,hh=(c-a)/2*k_,(d-b)/2*k_
                X0,Y0,X1,Y1=ox_+(cx-hw)*sc_,oy_+(cy-hh)*sc_,ox_+(cx+hw)*sc_,oy_+(cy+hh)*sc_
                col_=(1.,.8,.25,.95)
                box(X0,Y0,X1,Y0+t_,col_);box(X0,Y1-t_,X1,Y1,col_);box(X0,Y0,X0+t_,Y1,col_);box(X1-t_,Y0,X1,Y1,col_)
            msg_='Scale %d%%  ·  move left / right  ·  Ctrl 5%% steps  ·  click or Enter to apply  ·  Esc cancel'%round(k_*100)
            label(mx+18*fac_,my+14*fac_,msg_,(1,.9,.6,1),size=round(13*fac_))
        gpu.state.blend_set('NONE')

    def apply(self):
        if self.layout_mode:
            self.text_drop()
            out_=[i+1 for i,(a,b,c,d) in enumerate(self.rects) if a<self.pad or b<self.pad or c>self.w-self.pad or d>self.h-self.pad]
            if out_:
                self.report({'WARNING'},_T('%d image%s outside the texture (red frame: %s) · move them back in or press Pack, then Build'%(len(out_),'' if len(out_)==1 else 's',', '.join('#%d'%n for n in out_[:8])+(' …' if len(out_)>8 else ''))))
                return {'RUNNING_MODAL'}
            if getattr(self,'fx_pending',None):self.fx_commit(quiet=True)   # the last added effect is part of the build
            self.paint_session_end(True);self.painting_on=False   # paint is applied as you draw
            try:
                self.refresh_layout_sources()
                used_=[f.path for f in build_files(self.settings)]
                with bpy.context.temp_override(window=self.win,area=self.area,region=self.region):build(bpy.context,self.settings,self.layout_spec())
            except Exception as exc:
                self.report({'ERROR'},_T(str(exc)));return {'RUNNING_MODAL'}
            self.settings.update_previous=False   # next Build makes a new batch again (use [Edit] to update one)
            self.finish(save=True)   # a Re-edit session puts the list back as it was before (in finish)
            # Then, with [Remove Built Images from List] on, whatever went into this build leaves the list -
            # also after a Re-edit (images added to the batch during the session are built now)
            n_=remove_built_from_list(self.settings,used_)
            self.report({'INFO'},_T(self.settings.last_result+(' · %d removed from the list'%n_ if n_ else '')));return {'FINISHED'}
        if self.preview_only:
            self.finish();return {'FINISHED'}
        if not self.rects:
            self.report({'WARNING'},_T('No boxes to save · drag a box or use Find Cells by Green, or press Cancel.'));return {'RUNNING_MODAL'}
        try:
            st=self.settings
            src_item=st.cut_files[self.source_index] if getattr(self,'from_cut',False) else st.files[self.source_index]
            paths,folder=export_cuts(self.path,self.rects,st.cut_output_dir or st.output_dir,src_item.path,getattr(self,'chroma_used',False),getattr(self,'shadow_cut',False))
            # Cut pieces are appended to the texture list; the cut sheet leaves the cut list (only sheets still to cut remain, the file is kept)
            replaced=remove_earlier_cuts(st,self.path,folder)   # cutting the same sheet again replaces its earlier pieces (no look-alike duplicates)
            existing={os.path.normcase(bpy.path.abspath(f.path)) for f in st.files};first=len(st.files)
            for p in paths:
                if os.path.normcase(p) not in existing:st.files.add().path=p
            if getattr(self,'from_cut',False) and 0<=self.source_index<len(st.cut_files):
                st.cut_files.remove(self.source_index);st.cut_active=max(0,min(self.source_index,len(st.cut_files)-1))
            st.active=max(0,min(first,len(st.files)-1));st.mode='PACK';st.list_tab='TEXTURE'
            self.settings.last_result='Save %d Cut PNGs'%len(paths);self.settings.last_folder=folder
        except Exception as exc:
            self.report({'ERROR'},_T(str(exc)));return {'RUNNING_MODAL'}
        self.finish();self.report({'INFO'},_T('Saved %d PNGs and added them to the [Texture Images] list'%len(paths)+(' · sheet taken off the cut list' if getattr(self,'from_cut',False) else '')+(' · replaced %d pieces from an earlier cut of this sheet (Ctrl+Z brings them back)'%replaced if replaced else '')));return {'FINISHED'}

    def preview_step(self,step):
        import gpu
        idx=max(0,min(len(self.settings.files)-1,self.source_index+step))
        im=None
        try:
            path=file_path(self.settings.files[idx])
            if idx==self.source_index and path==self.path:return
            im=bpy.data.images.load(path,check_existing=False)
            w,h=im.size[:]
            if min(w,h)<1:raise ValueError('Cannot read the image.')
            texture=editor_texture(im)
        except Exception as exc:
            if im:bpy.data.images.remove(im)
            self.report({'WARNING'},_T(str(exc)));return
        old=self.im;self.texture=texture;self.im=im;bpy.data.images.remove(old)
        self.w=w;self.h=h;self.path=path;self.source_index=idx;self.settings.active=idx
        self.zoom=1.;self.pan=[0.,0.];self.area.tag_redraw()

    def modal(self,context,event):
        self._fx_memo=None   # Draw-only notes are not used for input handling
        if self.closed:return {'CANCELLED'}
        if getattr(self,'settings_popup',False):return {'PASS_THROUGH'}
        if self.area not in list(context.screen.areas):self.finish();return {'CANCELLED'}
        if self.layout_mode:self.sync_list_pick();self.pend_follow_selection()
        ar_=self.area
        if not (ar_.x<=event.mouse_x<ar_.x+ar_.width and ar_.y<=event.mouse_y<ar_.y+ar_.height):
            # Mouse over another area (another 3D view, outliner, ...): let Blender handle it, unless a drag/stroke started here is still going
            te_=getattr(self,'text_edit',None)
            busy=getattr(self,'drag',None) or getattr(self,'panning',None) or getattr(self,'marquee',None) or getattr(self,'group_drag',None) or getattr(self,'slider_drag',None) or getattr(self,'stroke',None) or getattr(self,'cut_drag',None) or getattr(self,'scale_drag',None) or getattr(self,'rand_drag',None) or (te_ and te_.get('mode'))
            if not busy:
                if getattr(self,'_cur_def',None):
                    try:self.win.cursor_modal_restore()
                    except Exception:pass
                    self._cur_def=False
                if event.type in {'Z','Y'} and (event.ctrl or event.oskey) and event.value=='PRESS':   # whole-file undo would pull the images out from under the open editor
                    self.report({'INFO'},_T('Scene Undo is paused while the Layout Editor is open · close the editor first (Ctrl+Z over the editor undoes layout steps)'));return {'RUNNING_MODAL'}
                return {'PASS_THROUGH'}
        x,y=event.mouse_x-self.region.x,event.mouse_y-self.region.y
        left,right,bottom,_=self.controls()
        def inside(r):return r[0]<=x<=r[2] and r[1]<=y<=r[3]
        self._mouse=(x,y)
        if event.type=='LEFTMOUSE':self._lmb=event.value in {'PRESS','DOUBLE_CLICK'}
        if getattr(self,'rand_drag',None):   # Random Size drag in progress (started on the button)
            rd_=self.rand_drag;st_=self.settings
            if event.type in {'MOUSEMOVE','INBETWEEN_MOUSEMOVE'}:
                st_.random_size_pct=max(0,min(60,int(round((x-rd_['x0'])/(4*rd_['f'])))))
                self.area.tag_redraw();return {'RUNNING_MODAL'}
            if event.type=='LEFTMOUSE' and event.value=='RELEASE':
                self.rand_drag=None;pct_=st_.random_size_pct
                if pct_>0:
                    try:self.random_sizes()
                    except Exception as exc:self.report({'ERROR'},_T(str(exc)))
                else:self.report({'INFO'},_T('Random Size · 0% · nothing changed'))
                st_.random_size_pct=0;self.area.tag_redraw();return {'RUNNING_MODAL'}
            if event.type in {'ESC','RIGHTMOUSE'} and event.value=='PRESS':
                self.rand_drag=None;st_.random_size_pct=0;self.report({'INFO'},_T('Random Size cancelled'))
                self.area.tag_redraw();return {'RUNNING_MODAL'}
            return {'RUNNING_MODAL'}
        if getattr(self,'scale_drag',None):   # S: scale every selected image together (ratio kept), left/right mouse travel
            sd_=self.scale_drag
            if event.type in {'MOUSEMOVE','INBETWEEN_MOUSEMOVE'}:
                k_=2.**((x-sd_['x0'])/(250.*sd_['f'])*(.2 if event.shift else 1.))
                if event.ctrl:k_=round(k_/.05)*.05
                sd_['k']=max(.1,min(4.,k_));self.area.tag_redraw();return {'RUNNING_MODAL'}
            if (event.type=='LEFTMOUSE' or event.type in {'RET','NUMPAD_ENTER','S'}) and event.value=='PRESS':
                self.scale_drag=None;k_=sd_['k']
                if abs(k_-1)>1e-3:
                    try:self.scale_selected(sd_['sel'],k_)
                    except Exception as exc:self.report({'ERROR'},_T(str(exc)))
                else:self.report({'INFO'},_T('Scale · 100% · nothing changed'))
                self.area.tag_redraw();return {'RUNNING_MODAL'}
            if event.type in {'ESC','RIGHTMOUSE'} and event.value=='PRESS':
                self.scale_drag=None;self.report({'INFO'},_T('Scale cancelled'));self.area.tag_redraw();return {'RUNNING_MODAL'}
            return {'RUNNING_MODAL'}
        if self.layout_mode and getattr(self,'text_edit',None):
            r_=self.text_modal(event,x,y,inside)
            if r_ is not None:return r_
        if self.layout_mode and event.type=='LEFTMOUSE' and event.value=='DOUBLE_CLICK' and not inside(getattr(self,'fx_panel',(0,0,0,0))):
            th_=self.text_hit(x,y,False)
            if th_:
                self.drag=None;self.group_drag=None;self.marquee=None;self.selection={th_[0]};self.selected=th_[0]
                self.text_lift(*th_,typing=True);self.text_edit['car']=self.text_caret_at(th_[0],self.text_edit['item'],x,y);return {'RUNNING_MODAL'}
        # Keep the normal arrow over the editor. Blender would otherwise keep whatever cursor it last
        # showed (e.g. the sidebar resize arrows), because this modal consumes the mouse-move events.
        if not getattr(self,'eyedrop',None):
            want=left<=x<=(self.fx_panel[2] if self.layout_mode else right) and 0<=y<=self.region.height
            if want!=getattr(self,'_cur_def',None):
                try:
                    if want:self.win.cursor_modal_set('DEFAULT')
                    else:self.win.cursor_modal_restore()
                except Exception:pass
                self._cur_def=want
        else:self._cur_def=None
        if self.layout_mode and event.type=='WINDOW_DEACTIVATE':
            self.marquee=None;self.box_select=False;self.drag=None;self.group_drag=None;self.panning=None;self.space_pan=False
            self.area.tag_redraw();return {'PASS_THROUGH'}
        if self.layout_mode and not self.drag and not self.panning and not self.marquee and not getattr(self,'slider_drag',None) and not getattr(self,'stroke',None) and not getattr(self,'cut_drag',None) and not (event.type=='Z' and event.ctrl):   # The editor takes Ctrl+Z even over the sidebar (prevents Blender-wide undo)
            # Let native list checkboxes and their drag-selection modal receive
            # events in the sidebar while this canvas remains open.
            if any(r.type=='UI' and r.x<=event.mouse_x<r.x+r.width and r.y<=event.mouse_y<r.y+r.height for r in self.area.regions):
                return {'PASS_THROUGH'}
        if event.type=='ESC' and event.value=='PRESS' and getattr(self,'eyedrop',None):
            self.eyedrop_end();self.report({'INFO'},_T('Color change cancelled.'));return {'RUNNING_MODAL'}
        if event.type=='RIGHTMOUSE' and event.value=='PRESS' and getattr(self,'eyedrop',None):
            self.eyedrop_end();bpy.ops.poster_atlas.fx_pick_color('INVOKE_DEFAULT',target='pool');return {'RUNNING_MODAL'}
        if event.type=='ESC' and event.value=='PRESS':
            if self.layout_mode and getattr(self,'fx_pending',None):
                self.fx_pending=None;self.area.tag_redraw();return {'RUNNING_MODAL'}
            if self.layout_mode and getattr(self,'painting_on',False):
                self.fx_set_tool('select');return {'RUNNING_MODAL'}
            if self.layout_mode and (self.marquee or self.box_select):
                if self.marquee:self.selection=set(self.marquee[5])
                self.marquee=None;self.box_select=False;self.area.tag_redraw();return {'RUNNING_MODAL'}
            self.finish();return {'CANCELLED'}
        if event.type in {'RET','NUMPAD_ENTER'} and event.value=='PRESS':return self.apply()
        if event.type=='SPACE':
            self.space_pan=event.value=='PRESS'
            return {'RUNNING_MODAL'}
        if self.layout_mode and event.type=='E' and event.value=='PRESS' and not event.ctrl and not event.alt:
            pp_=getattr(self,'fx_pending',None)
            if pp_ and pp_['id']=='PRESET:POSTIT' and pp_.get('color')=='RANDOM':
                try:col=self.eyedrop_pick(x,y)
                except Exception as exc:col=None;self.report({'ERROR'},_T('Could not read the color: %s'%exc))
                if col:self.eyedrop='pool';self.eyedrop_apply(col)
                else:self.report({'WARNING'},_T('Hover over a poster or color cell and press E.'))
                return {'RUNNING_MODAL'}
        if self.layout_mode and event.type=='T' and event.value=='PRESS' and not event.ctrl and not event.alt:
            self.text_new();return {'RUNNING_MODAL'}
        if self.layout_mode and event.type=='A' and event.value=='PRESS':
            self.selection=set() if getattr(event,'alt',False) else set(range(len(self.rects)))
            if self.selection:self.pend_rebind()
            self.area.tag_redraw();return {'RUNNING_MODAL'}
        if self.layout_mode and event.type=='S' and event.value=='PRESS' and not event.ctrl and not getattr(self,'stroke',None) and not getattr(self,'painting_on',False):
            sel_=sorted(i for i in getattr(self,'selection',{self.selected}) if 0<=i<len(self.rects))
            if not sel_:self.report({'WARNING'},_T('Select images first · A selects all'));return {'RUNNING_MODAL'}
            self.scale_drag={'x0':x,'f':max(1.,min(1.5,bpy.context.preferences.system.ui_scale)),'k':1.,'sel':sel_}
            self.area.tag_redraw();return {'RUNNING_MODAL'}
        if self.layout_mode and event.type=='B' and event.value=='PRESS' and self.drag and self.drag[3]=='MOVE':   # hold B while moving: snap
            if not getattr(self,'snap_on',False):
                self.snap_on=True;self.snap_guides=[]
                self.report({'INFO'},_T('Snap (while B is held) · edges and corners stick to other images at the Spacing distance'))
            self.area.tag_redraw();return {'RUNNING_MODAL'}
        if event.type=='B' and event.value=='RELEASE' and getattr(self,'snap_on',False):   # let go of B: snap off
            self.snap_on=False;self.snap_guides=[];self.area.tag_redraw();return {'RUNNING_MODAL'}
        if event.type=='LEFTMOUSE' and event.value=='RELEASE' and getattr(self,'snap_on',False):self.snap_on=False;self.snap_guides=[]   # the move ends: snap ends too
        if self.layout_mode and event.type=='B' and event.value=='PRESS':
            self.box_select=True;return {'RUNNING_MODAL'}
        if self.layout_mode and event.type=='W' and event.value=='PRESS' and not event.ctrl and not event.alt and not getattr(self,'stroke',None):
            self.renumber_selected();return {'RUNNING_MODAL'}
        if self.layout_mode and event.type in {'DEL','BACK_SPACE'} and event.value=='PRESS' and not getattr(self,'stroke',None):
            self.remove_selected_from_layout();return {'RUNNING_MODAL'}
        if not self.layout_mode and not self.preview_only and event.type in {'DEL','BACK_SPACE','X'} and event.value=='PRESS' and not event.ctrl:
            self.cut_remove_selected();return {'RUNNING_MODAL'}
        if self.preview_only and event.type in {'Q','E'} and event.value=='PRESS':
            try:rotate_item(self.settings,-1 if event.type=='Q' else 1)
            except Exception as exc:self.report({'ERROR'},_T(str(exc)))
        elif self.layout_mode and event.type in {'LEFT_ARROW','RIGHT_ARROW','UP_ARROW','DOWN_ARROW'} and event.value=='PRESS':
            h,v={'LEFT_ARROW':(-1,0),'RIGHT_ARROW':(1,0),'UP_ARROW':(0,1),'DOWN_ARROW':(0,-1)}[event.type]
            try:self.move_group(h,v)
            except Exception as exc:self.report({'ERROR'},_T(str(exc)))
            self.area.tag_redraw();return {'RUNNING_MODAL'}
        elif self.preview_only and event.type in {'LEFT_ARROW','RIGHT_ARROW'} and event.value=='PRESS':
            self.preview_step(-1 if event.type=='LEFT_ARROW' else 1)
        elif event.type=='Z' and event.ctrl and event.value=='PRESS':
            if self.history:
                state=self.history.pop()
                if isinstance(state,dict) and state.get('kind')=='REMOVE':
                    self.undo_remove(state)
                elif isinstance(state,dict) and state.get('kind')=='LIST':
                    self.undo_list(state)
                elif isinstance(state,dict):
                    if state.get('resolution') and state['resolution']!=self.w:
                        self.w=self.h=state['resolution'];self.pad=max(4,round(4*self.w/2048));set_resolution(self.settings,self.w)
                    self.rects=state['rects'];self.physical_sizes=state['physical_sizes']
                    self.layout_rotations=state.get('rotations',[0]*len(self.rects))
                    self.crops=state.get('crops',[[0.,0.,1.,1.] for _ in self.rects])
                    self.applied_crops=state.get('applied_crops',[[0.,0.,1.,1.] for _ in self.rects])
                    self.settings.edit_mode=state.get('edit_mode',self.settings.edit_mode)
                    self.selection=set(state.get('selection',[self.selected]))
                    if 'effects' in state:self.effects=state['effects']
                    if 'pending' in state:
                        pp_=state['pending'];self.fx_pending=dict(pp_,cache={}) if pp_ else None;self.fx_last=None
                        if pp_ and pp_.get('amount'):self.fx_amount=pp_['amount'];self.fx_amount_v=float(pp_.get('amount_v',1.))
                    if 'pool' in state and state['pool']!=self.settings.postit_pool:self.settings.postit_pool=state['pool']
                    for k_,v_ in (state.get('paper') or {}).items():
                        if getattr(self.settings,k_)!=v_:setattr(self.settings,k_,v_)
                    self.fx_clear_previews()
                else:self.rects=state
                self.report({'INFO'},_T('Undone (%d steps left)'%len(self.history)))
            else:self.report({'INFO'},_T('Nothing left to undo.'))
            self.drag=None
        elif event.type=='HOME' and event.value=='PRESS':self.zoom=1.;self.pan=[0.,0.]
        elif self.layout_mode and event.type=='R' and event.value=='PRESS':
            self.remember_layout()
            sizes=[(size[0]*(c[2]-c[0]),size[1]*(c[3]-c[1])) for size,c in zip(self.sizes,self.crops)]
            oriented=[size[::-1] if turn%2 else size for size,turn in zip(sizes,self.layout_rotations)]
            self.rects=initial_layout(self.settings,oriented) if oriented else [];self.drag=None
            self.physical_sizes=[None]*len(self.rects)
        elif event.type in {'WHEELUPMOUSE','WHEELDOWNMOUSE'} and self.layout_mode and inside(getattr(self,'fx_panel',(0,0,0,0))):
            self.fx_scroll=max(0.,min(getattr(self,'fx_scroll_max',0.),getattr(self,'fx_scroll',0.)+(-40 if event.type=='WHEELUPMOUSE' else 40)))
        elif event.type in {'WHEELUPMOUSE','WHEELDOWNMOUSE'}:
            if self.layout_mode and self.settings.edit_mode=='CROP' and getattr(event,'shift',False):
                self.zoom_crop(1/1.1 if event.type=='WHEELUPMOUSE' else 1.1)
                return {'RUNNING_MODAL'}
            ox,oy,scale=self.view();ix,iy=(x-ox)/scale,(y-oy)/scale
            self.zoom=max(.25,min(20,self.zoom*(1.2 if event.type=='WHEELUPMOUSE' else 1/1.2)))
            nx,ny,ns=self.view();self.pan[0]+=x-(nx+ix*ns);self.pan[1]+=y-(ny+iy*ns)
        elif event.type=='RIGHTMOUSE' and event.value=='PRESS' and self.layout_mode and getattr(self,'painting_on',False):
            self.fx_set_tool('select')
        elif event.type=='MIDDLEMOUSE':
            self.panning=(x,y,list(self.pan)) if event.value=='PRESS' else None
        elif event.type=='LEFTMOUSE' and (event.value=='PRESS' or (event.value=='DOUBLE_CLICK' and self.layout_mode)):   # a quick second click counts too (cycling overlapped images)
            if self.space_pan:
                self.panning=(x,y,list(self.pan));return {'RUNNING_MODAL'}
            if getattr(self,'eyedrop',None):   # Eyedropper: panel color cells give their value; elsewhere read the visible color
                col=None
                for w_ in getattr(self,'fx_widgets',[]):
                    kind_,bounds_,key_,text_=w_
                    if not inside(bounds_):continue
                    if kind_ in ('swatch','ppool') and isinstance(text_,(tuple,list)):col=tuple(text_[:3]);break
                    if kind_=='pcol' and POSTIT_COLORS.get(key_,('',None))[1]:col=POSTIT_COLORS[key_][1];break
                if col:self.eyedrop_apply(col)
                else:   # Clicking a poster reads the color at that point from the source image (no framebuffer read)
                    i_=self.rect_hit(x,y)
                    if i_ is None:self.report({'WARNING'},_T('Click a poster or a panel color cell · Esc to cancel'))
                    else:
                        try:self.eyedrop_apply(self.sample_source_color(i_,x,y))
                        except Exception as exc:self.eyedrop_end();self.report({'ERROR'},_T('Could not read the color: %s'%exc))
                return {'RUNNING_MODAL'}
            if inside(getattr(self,'apply_button',(0,0,0,0))):return self.apply()
            if self.layout_mode and inside(getattr(self,'batch_name_button',(-99,-99,-99,-99))):   # rename the batch
                bpy.ops.poster_atlas.batch_rename('INVOKE_DEFAULT');self.panel_press=True;return {'RUNNING_MODAL'}
            if self.layout_mode and inside(getattr(self,'fx_reset_button',(0,0,0,0))):   # Effects header · Reset
                self.fx_reset_all();self.panel_press=True;return {'RUNNING_MODAL'}
            if self.layout_mode and inside(getattr(self,'lay_reset_button',(0,0,0,0))):   # Layout header · Reset size
                try:self.size_reset_selected()
                except Exception as exc:self.report({'ERROR'},_T(str(exc)))
                self.panel_press=True;return {'RUNNING_MODAL'}
            if self.layout_mode:
                for key_,hd_ in (('layout','lay_head'),('effects','fx_head')):
                    if inside(getattr(self,hd_,(0,0,0,0))):
                        PANEL_OPEN[key_]=not PANEL_OPEN[key_];self.panel_press=True;self.area.tag_redraw();return {'RUNNING_MODAL'}
            if self.layout_mode and inside(self.fx_panel) and not self.layout_hit(x,y):
                # Panel buttons don't change poster selection -> remember the selection before the press and restore it
                keep_sel=(set(self.selection),self.selected);self.click_single=None;self.marquee=None;self.panel_press=True
                d=self.fx_draft_get();infoot=inside(self.fx_foot);vx0,vy0,vx1,vy1=self.fx_view
                for kind,bounds,key,text in self.fx_widgets:
                    isfoot=bounds[3]<=self.fx_foot[3]+1
                    if isfoot!=infoot or not inside(bounds) or kind in ('label','head'):continue
                    if not isfoot and not vy0<=y<=vy1:continue
                    try:
                        if kind in ('pcol','ppbtn','pamt','pscl','pseed','ppm','ppv','ppslider','pdslider','pslider','slider','ppreset','pset','pvar','swatch') or (kind=='button' and (key.startswith('PRESET:') or key=='PAPER_FOCUS')):
                            self.remember_layout()   # Choosing effects and changing color/amount are also undoable with Ctrl+Z
                        if kind=='pcol':self.postit_keep_previous()   # Sticky note color picked for another note: keep the previous note's color, then start on the new one
                        if kind in ('pcol','ppool','ppbtn','pamt','pscl','pseed','ppm','ppv','ppslider','pdslider'):self.pend_rebind()
                        if kind=='slider':
                            if event.ctrl:d[key]=FX_DEFAULTS.get(key,{'brush_size':25.,'brush_strength':.6,'tear_rim':FX_TEAR_RIM}.get(key))
                            else:self.fx_slider_set(key,bounds,x);self.slider_drag=(key,bounds)
                            if key in FX_VALUE_KEYS:
                                self.fx_touch('TAB:'+self.fx_tab,FX_TAB_NAMES[self.fx_tab],(key,))
                                if event.ctrl:self.fx_commit(quiet=True)
                            if key=='tear_rim':self.fx_set_rim()
                        elif kind=='tab':
                            self.fx_tab=key   # (painting has its own Tools section now)
                        elif kind=='pslider':self.fx_slider_set('P:'+key,bounds,x);self.slider_drag=('P:'+key,bounds)
                        elif kind=='ppreset':self.paper_pick(key)
                        elif kind in ('pamt','pscl'):self.fx_set_amount(kind,key)
                        elif kind=='pseed':self.fx_seed_step(key)
                        elif kind=='ppm':self.paper_pend_mode(key)
                        elif kind=='ppv':self.paper_pend_seed(key)
                        elif kind=='ppslider':self.fx_slider_set('Q:'+key,bounds,x);self.slider_drag=('Q:'+key,bounds)
                        elif kind=='ppool':
                            pp_=getattr(self,'fx_pending',None)
                            if pp_:pp_['pool_sel']=int(key)
                        elif kind=='ppbtn':self.postit_pool_button(key)
                        elif kind=='pcol':
                            pp_=getattr(self,'fx_pending',None)
                            if pp_:pp_['color']=key;pp_['cache']={}
                        elif kind=='pdslider':self.fx_slider_set('D:'+key,bounds,x);self.slider_drag=('D:'+key,bounds)
                        elif kind=='pvar':self.settings.paper_variant=int(key);self.paper_sync()
                        elif kind=='pset':
                            if key=='NONE':self.settings.paper_auto=False
                            else:
                                ps,pv=key.rsplit('|',1);self.settings.paper_set=ps;self.settings.paper_variant=int(pv);self.settings.paper_auto=True
                            self.paper_sync()
                        elif kind=='pbtn':self.paper_button(key)
                        elif kind=='swatch':d[key]=text;self.fx_touch('TAB:COLOR',FX_TAB_NAMES['COLOR'],(key,));self.fx_commit(quiet=True)
                        elif kind=='look':
                            idx_=self.look_targets()
                            if idx_:self.remember_layout();self.photo_look_last=key;self.photo_set(idx_,look=key);self.look_custom=False
                        elif kind=='lamt':
                            idx_=[i for i in self.look_targets() if (self.photo_get(i) or {}).get('polaroid')]
                            if not idx_:self.toast('Pick a look first (greyed out until then)')
                            elif key=='CUSTOM':self.look_custom=True
                            else:self.remember_layout();self.look_custom=False;self.photo_set(idx_,look_k=LOOK_K[key])
                        elif kind=='lslider':
                            idx_=[i for i in self.look_targets() if (self.photo_get(i) or {}).get('polaroid')]
                            if idx_:self.remember_layout();self.fx_slider_set('L:look_k',bounds,x);self.slider_drag=('L:look_k',bounds)
                        elif kind=='brush':self.fx_set_tool('select' if getattr(self,'painting_on',False) and d.get('brush')==key else key)   # Pressing the same tool again stops
                        elif kind=='tip':d['tip']=key
                        elif kind=='power':d['brush_strength']=key
                        elif kind=='layer':
                            xb0=bounds[2]-24*bpy.context.preferences.system.ui_scale
                            if x>=xb0-4:self.fx_remove_layer(key[4:])
                        elif kind=='fxoff':
                            if key.startswith('OFF:'):   # Off next to one effect (Sticky Note): that effect, even if another one is previewed
                                pid_=key[4:];p_=getattr(self,'fx_pending',None)
                                if not p_ or p_['id']!=pid_:self.fx_set_pending(pid_,next((n for k_,n,_ in FX_PRESETS if 'PRESET:'+k_==pid_),pid_))
                            self.fx_turn_off()
                        elif kind=='amt' and not (getattr(self,'fx_pending',None) and (self.fx_pending['id'].startswith('PRESET:') or self.fx_pending['id']=='PAPER')):
                            self.toast('Pick an effect first (greyed out until then)')   # nothing previewed: the Strength row is off
                        elif kind=='amt':
                            if key=='CUSTOM' and getattr(self,'fx_amount','LOW')!='CUSTOM':   # Custom starts from what is on screen now (no jump)
                                self.fx_amount_v=float(FX_AMOUNTS.get(getattr(self,'fx_amount','LOW'),(0,1.))[1] or 1.);self.fx_scale_v=float(FX_SCALES['LOW'][1])
                            self.fx_amount=key;self.fx_adjust_last()
                        elif kind=='amtslider':
                            if event.ctrl:setattr(self,'fx_'+key,1.);self.fx_adjust_last()
                            else:self.fx_slider_set('A:'+key,bounds,x);self.slider_drag=('A:'+key,bounds)
                        elif kind=='button':self.fx_button(key)
                    except Exception as exc:self.report({'ERROR'},_T(str(exc)))
                    break
                if 0<len(keep_sel[0]) and all(0<=i<len(self.rects) for i in keep_sel[0]):
                    self.selection,self.selected=set(keep_sel[0]),keep_sel[1]
                self.area.tag_redraw();return {'RUNNING_MODAL'}
            if self.layout_mode and getattr(self,'painting_on',False) and self.rects and left<x<right and bottom<y<self.region.height-self.hdr():
                if self.fx_draft_get().get('brush')=='cut' or self.rect_hit(x,y) is not None:
                    self.paint_begin(x,y);return {'RUNNING_MODAL'}
                self.fx_set_tool('select')   # Clicking empty space outside posters stops painting and becomes a normal click
            if self.layout_mode:
                if inside(self.crop_apply_button):
                    if self.settings.edit_mode=='CROP':self.apply_crop()
                    return {'RUNNING_MODAL'}
                for bounds,mode,text in self.mode_buttons:
                    if inside(bounds):self.set_edit_mode(mode);return {'RUNNING_MODAL'}
                if inside(getattr(self,'copy_size_button',(-99,-99,-99,-99))):
                    try:self.copy_size_selected()
                    except Exception as exc:self.report({'ERROR'},_T(str(exc)))
                    self.area.tag_redraw();return {'RUNNING_MODAL'}
                if inside(getattr(self,'random_size_button',(-99,-99,-99,-99))):   # Random Size: press, drag sideways to set ±%, release to apply
                    self.settings.random_size_pct=0
                    self.rand_drag={'x0':x,'f':max(1.,min(1.5,bpy.context.preferences.system.ui_scale))}
                    self.report({'INFO'},_T('Random Size · drag right to raise ±%, release to apply · Esc cancels'))
                    self.area.tag_redraw();return {'RUNNING_MODAL'}
                for bounds,kind in ((self.custom_size_button,'SIZE'),(self.gap_button,'GAP')):
                    if inside(bounds):
                        bpy.ops.poster_atlas.layout_options('INVOKE_DEFAULT',kind=kind)
                        return {'RUNNING_MODAL'}
                for bounds,r in getattr(self,'res_buttons',[]):
                    if inside(bounds):
                        try:bpy.ops.poster_atlas.layout_options('INVOKE_DEFAULT',kind='RES') if r=='CUSTOM' else self.change_resolution(r)
                        except Exception as exc:self.report({'ERROR'},_T(str(exc)))
                        return {'RUNNING_MODAL'}
                for bounds,k_ in getattr(self,'bg_buttons',[]):
                    if inside(bounds):
                        self.settings.background=k_;self.area.tag_redraw();return {'RUNNING_MODAL'}
                for bounds,k_ in getattr(self,'group_buttons',[]):
                    if inside(bounds):
                        st_=self.settings
                        if k_[0] in ('GC-','GC+'):
                            used_=len({f.group.strip() for f in st_.files if f.group.strip()})
                            st_.group_count=max(1,used_ if k_[0]=='GC-' else 0,min(8,st_.group_count+(1 if k_[0]=='GC+' else -1)))
                            if k_[0]=='GC-' and st_.group_count<=used_:self.toast('%d groups are in use · No Group on their posters first'%used_)
                            self.area.tag_redraw()
                        elif k_[0]=='GCV':pass
                        elif k_[0]=='GREN':
                            cur_={st_.files[k].group.strip() for k in self.group_targets()}-{''}
                            if len(cur_)!=1:self.report({'WARNING'},_T('Select posters of one group to rename it'))
                            else:bpy.ops.poster_atlas.group_rename('INVOKE_DEFAULT',old=cur_.pop())
                        else:self.group_selected(k_[1] if k_[0]=='G' else '')
                        return {'RUNNING_MODAL'}
                if inside(getattr(self,'pack_button',(0,0,0,0))):   # Pack: keep sizes and rotation, re-pack every image without gaps
                    try:self.move_group(0,0)
                    except Exception as exc:self.report({'ERROR'},_T(str(exc)))
                    return {'RUNNING_MODAL'}
                if getattr(self,'optimize_button',None) and inside(self.optimize_button):
                    try:self.optimize_layout()
                    except Exception as exc:self.report({'ERROR'},_T(str(exc)))
                    return {'RUNNING_MODAL'}
                for bounds,step in self.layout_rotate_buttons:
                    if inside(bounds):
                        try:self.rotate_layout_image(step)
                        except Exception as exc:self.report({'ERROR'},_T(str(exc)))
                        return {'RUNNING_MODAL'}
                for bounds,text,h,v in self.move_buttons:
                    if inside(bounds):
                        try:self.move_group(h,v)
                        except Exception as exc:self.report({'ERROR'},_T(str(exc)))
                        return {'RUNNING_MODAL'}
                for bounds,preset in self.preset_buttons:
                    if inside(bounds):
                        try:
                            self.set_preset(preset)
                        except Exception as exc:self.report({'ERROR'},_T(str(exc)))
                        return {'RUNNING_MODAL'}
                for bounds,k_ in getattr(self,'tab_buttons',[]):
                    if inside(bounds):self.settings.layout_tab=k_;self.area.tag_redraw();return {'RUNNING_MODAL'}
                for bounds,k_ in getattr(self,'strip_buttons',[]):
                    if not inside(bounds):continue
                    st_=self.settings;t_=k_[0]
                    try:
                        if t_=='L':st_.strip_cols,st_.strip_rows=k_[1],k_[2]
                        elif t_=='C-':st_.strip_cols=max(1,st_.strip_cols-1)
                        elif t_=='C+':st_.strip_cols=min(6,st_.strip_cols+1)
                        elif t_=='R-':st_.strip_rows=max(1,st_.strip_rows-1)
                        elif t_=='R+':st_.strip_rows=min(8,st_.strip_rows+1)
                        elif t_=='FR':st_.strip_frame=k_[1]
                        elif t_=='STAG':st_.strip_stagger=not st_.strip_stagger
                        elif t_=='MAKE':self.make_strip()
                    except Exception as exc:self.report({'ERROR'},_T(str(exc)))
                    self.area.tag_redraw();return {'RUNNING_MODAL'}
                for bounds,k_ in getattr(self,'photo_fmt_buttons',[]):
                    if inside(bounds):
                        try:
                            if k_=='STRIP':self.strip_open=not getattr(self,'strip_open',False);self.area.tag_redraw()   # show / hide the strip settings
                            elif k_=='OFF':self.photo_off([i for i in getattr(self,'selection',{self.selected}) if 0<=i<len(self.rects)])
                            else:self.set_preset(None,photo=k_)
                        except Exception as exc:self.report({'ERROR'},_T(str(exc)))
                        return {'RUNNING_MODAL'}
                for bounds,k_ in getattr(self,'sec_heads',[]):
                    if inside(bounds):
                        PANEL_OPEN['sec:'+k_]=not PANEL_OPEN.get('sec:'+k_,True);self.panel_press=True;self.area.tag_redraw();return {'RUNNING_MODAL'}
                for bounds,k_ in getattr(self,'text_buttons',[]):
                    if inside(bounds):
                        if k_!='LSV':
                            try:self.text_button(k_)
                            except Exception as exc:self.report({'ERROR'},_T(str(exc)))
                        self.panel_press=True;return {'RUNNING_MODAL'}
                for bounds,k_ in getattr(self,'caption_buttons',[]):
                    if inside(bounds):
                        if not [i for i in getattr(self,'selection',{self.selected}) if 0<=i<len(self.rects)]:self.report({'WARNING'},_T('Select images first · A selects all'))
                        else:bpy.ops.poster_atlas.caption('INVOKE_DEFAULT')
                        return {'RUNNING_MODAL'}
                for bounds,k_ in getattr(self,'paper_finish_buttons',[]):
                    if not inside(bounds):continue
                    try:
                        idx=[i for i in getattr(self,'selection',{self.selected}) if 0<=i<len(self.rects)]
                        if not idx:self.report({'WARNING'},_T('Select images first · A selects all'))
                        elif k_=='CUSTOM':bpy.ops.poster_atlas.photo_custom('INVOKE_DEFAULT',kind='FINISH' if self.photo_get(self.selected) else 'PAPER')
                        else:
                            self.remember_layout();self.surface_set(idx,k_)
                            self.report({'INFO'},_T('Surface: %s · %d image(s)'%(PAPER_FINISHES[k_][0],len(idx))))
                            self.area.tag_redraw()
                    except Exception as exc:self.report({'ERROR'},_T(str(exc)))
                    return {'RUNNING_MODAL'}
                for kind_,lst_ in (('border',getattr(self,'photo_border_buttons',[])),('look',getattr(self,'photo_look_buttons',[])),('finish',getattr(self,'photo_finish_buttons',[]))):
                    for bounds,k_ in lst_:
                        if not inside(bounds):continue
                        try:
                            idx=[i for i in getattr(self,'selection',{self.selected}) if 0<=i<len(self.rects)]
                            if not idx:self.report({'WARNING'},_T('Select images first · A selects all'))
                            elif k_.startswith('FX:'):self.remember_layout();self.fx_button('PRESET:'+k_[3:])   # same button as in Effects
                            elif k_=='CUSTOM':bpy.ops.poster_atlas.photo_custom('INVOKE_DEFAULT',kind='BORDER' if kind_=='border' else ('FINISH' if self.photo_get(self.selected) else 'PAPER'))
                            else:
                                self.remember_layout()
                                if kind_=='finish':
                                    self.surface_set(idx,k_)
                                    self.report({'INFO'},_T('Surface: %s · %d image(s)'%(PHOTO_FINISHES[k_][0],len(idx))))
                                elif kind_=='border':
                                    self.photo_frame_last=k_=='FRAME';self.photo_set(idx,frame=k_=='FRAME')
                                    self.report({'INFO'},_T('%s on %d image(s)'%('White border' if k_=='FRAME' else 'Borderless',len(idx))))
                                else:
                                    lk=None if k_=='OFF' else k_
                                    if lk:self.photo_look_last=lk
                                    self.photo_set(idx,look=lk)
                                    self.report({'INFO'},_T('Look: %s · %d image(s)'%(dict(POL_STYLE_NAMES).get(k_,'Off'),len(idx))))
                                self.area.tag_redraw()
                        except Exception as exc:self.report({'ERROR'},_T(str(exc)))
                        return {'RUNNING_MODAL'}
            if not self.layout_mode and not self.preview_only and inside(getattr(self,'remove_button',(0,0,0,0))):
                self.cut_remove_selected();return {'RUNNING_MODAL'}
            if not self.layout_mode and not self.preview_only and inside(getattr(self,'shadow_button',(0,0,0,0))):
                self.shadow_cut=not getattr(self,'shadow_cut',False)
                self.report({'INFO'},_T('Remove Shadows on · gray or dark-green shadows touching the green background are removed too (Trim / Find / save)' if self.shadow_cut else 'Remove Shadows off'))
                self.area.tag_redraw();return {'RUNNING_MODAL'}
            chroma_hit='FIT' if inside(getattr(self,'chroma_button',(0,0,0,0))) else 'FIND' if inside(getattr(self,'chroma_find_button',(0,0,0,0))) else None
            if not self.layout_mode and not self.preview_only and chroma_hit:
                try:
                    px=read_pixels(self.path)
                    sh_=getattr(self,'shadow_cut',False);found=chroma_fit(px,self.rects,sh_) if chroma_hit=='FIT' else chroma_regions(px,shadows=sh_)
                    found=chroma_inset(found,self.settings.chroma_inset)   # a few extra pixels in from every edge (green fringe)
                    if not found:self.report({'WARNING'},_T('No green (chroma-key) background found.' if chroma_hit=='FIND' else 'No non-green artwork inside the cells.'))
                    else:
                        self.history.append([list(r) for r in self.rects]);self.history=self.history[-40:]
                        before=len(self.rects);self.rects=found;self.selected=0;self.drag=None;self.chroma_used=True;self.chroma_mode=chroma_hit
                        msg=('Trimmed green from %d cells'%len(found)+(' (excluded %d all-green cells)'%(before-len(found)) if before>len(found) else '')) if chroma_hit=='FIT' else 'Found %d on the green background'%len(found)
                        self.report({'INFO'},_T(msg+' · green becomes transparent when saving · Ctrl+Z to undo'))
                except Exception as exc:self.report({'ERROR'},_T(str(exc)))
                self.area.tag_redraw();return {'RUNNING_MODAL'}
            if not self.layout_mode and not self.preview_only:
                hitg=next(((kind,step) for bounds,kind,step in getattr(self,'grid_buttons',[]) if step and inside(bounds)),None)
                if hitg:
                    st=self.settings;kind,step=hitg
                    if kind=='INSET':   # Inset: change the extra trim; boxes found by green follow right away
                        nv=max(0,min(60,st.chroma_inset+step))
                        if nv!=st.chroma_inset and getattr(self,'chroma_used',False) and self.rects:
                            self.history.append([list(r) for r in self.rects]);self.history=self.history[-40:]
                            d_=nv-st.chroma_inset;self.rects=[r for r in (chroma_inset([r],d_) if d_>0 else [[max(0,r[0]+d_),max(0,r[1]+d_),min(self.w,r[2]-d_),min(self.h,r[3]-d_)]] for r in self.rects) for r in r]
                        st.chroma_inset=nv;self.report({'INFO'},_T('Green inset %d px%s'%(nv,'' if getattr(self,'chroma_used',False) else ' · used by Trim Green / Find Cells')))
                        self.area.tag_redraw();return {'RUNNING_MODAL'}
                    if kind=='COL':st.cut_columns=max(1,min(32,st.cut_columns+step))
                    else:st.cut_rows=max(1,min(32,st.cut_rows+step))
                    self.history.append([list(r) for r in self.rects]);self.history=self.history[-40:]
                    self.rects=cut_grid(self.w,self.h,st.cut_columns,st.cut_rows);self.selected=0;self.drag=None
                    self.report({'INFO'},_T('Re-split into %d cols × %d rows = %d · Ctrl+Z to undo.'%(st.cut_columns,st.cut_rows,len(self.rects))))
                    self.area.tag_redraw();return {'RUNNING_MODAL'}
            if self.preview_only:
                step=-1 if inside(self.rotate_left_button) else 1 if inside(self.rotate_right_button) else 0
                if step:
                    try:rotate_item(self.settings,step)
                    except Exception as exc:self.report({'ERROR'},_T(str(exc)))
            if not self.preview_only and inside(getattr(self,'cancel_button',(0,0,0,0))):
                if self.layout_mode:self.report({'INFO'},_T('Editor closed · unbuilt changes were not saved.'))
                self.finish();return {'CANCELLED'}
            if not self.preview_only and self.rects and left<x<right and bottom<y<self.region.height-self.hdr():
                ox,oy,scale=self.view();px,py=(x-ox)/scale,(y-oy)/scale;tolerance=9/scale
                if self.layout_mode and self.box_select:
                    self.marquee=(px,py,px,py,'REMOVE' if getattr(event,'alt',False) else 'ADD' if getattr(event,'shift',False) else 'SET',set(self.selection))
                    self.box_select=False;return {'RUNNING_MODAL'}
                if self.layout_mode and not getattr(event,'shift',False) and not getattr(event,'alt',False):
                    th_=self.text_hit(x,y)
                    if th_:
                        self.text_lift(*th_);te_=self.text_edit;te_['mode']='DRAG';te_['start']=dict(te_['item']);te_['m0']=(x,y)
                        return {'RUNNING_MODAL'}
                order=[self.selected]+[i for i in range(len(self.rects)-1,-1,-1) if i!=self.selected]
                if self.layout_mode and 0<=self.selected<len(self.rects):
                    # Overlapping images: the first click picks the smallest one under the mouse, clicking again on the
                    # same spot picks the next one (like Blender). The active image's resize handles keep priority.
                    under=[i for i in range(len(self.rects)-1,-1,-1) if self.rects[i][0]<=px<=self.rects[i][2] and self.rects[i][1]<=py<=self.rects[i][3]]
                    a,b,c,d=self.rects[self.selected]
                    on_sel_edge=self.selected in self.selection and a-tolerance<=px<=c+tolerance and b-tolerance<=py<=d+tolerance and (abs(px-a)<=tolerance or abs(px-c)<=tolerance or abs(py-b)<=tolerance or abs(py-d)<=tolerance)
                    if len(under)>1 and not on_sel_edge:
                        under.sort(key=lambda i:((self.rects[i][2]-self.rects[i][0])*(self.rects[i][3]-self.rects[i][1]),-i))
                        lc=getattr(self,'last_pick',None)
                        if lc and abs(lc[0]-x)<=5 and abs(lc[1]-y)<=5 and lc[2] in under:first=under[(under.index(lc[2])+1)%len(under)]
                        else:first=under[0]
                        order=[first]+[i for i in order if i!=first]
                hit=False
                for i in order:
                    a,b,c,d=self.rects[i]
                    if a-tolerance<=px<=c+tolerance and b-tolerance<=py<=d+tolerance:
                        hit=True
                        if self.layout_mode:
                            if getattr(event,'alt',False):
                                self.selection.discard(i);self.area.tag_redraw();return {'RUNNING_MODAL'}
                            on_handle=i==self.selected and i in self.selection and (abs(px-a)<=tolerance or abs(px-c)<=tolerance or abs(py-b)<=tolerance or abs(py-d)<=tolerance)
                            if getattr(event,'shift',False) and not on_handle:   # Shift on the active image's border = ratio-locked resize, not selection
                                if i in self.selection:self.selection.remove(i)
                                else:self.selection.add(i);self.selected=i
                                self.area.tag_redraw();return {'RUNNING_MODAL'}
                            if i not in self.selection:self.selection={i};self.click_single=None
                            else:self.click_single=(i,x,y) if len(self.selection)>1 else None   # If it didn't move on release, select only this
                        handle=('W' if abs(px-a)<=tolerance else 'E' if abs(px-c)<=tolerance else '')+('S' if abs(py-b)<=tolerance else 'N' if abs(py-d)<=tolerance else '')
                        self.selected=i
                        if self.layout_mode:self.remember_layout()
                        else:self.history.append([list(r) for r in self.rects]);self.history=self.history[-40:]
                        if self.layout_mode:self.drag_crop=list(self.crops[i])
                        if self.layout_mode:
                            self.group_drag={j:list(self.rects[j]) for j in self.selection} if len(self.selection)>1 and not handle else None
                        self.drag=(px,py,list(self.rects[i]),handle or 'MOVE');break
                self.last_pick=(x,y,self.selected) if hit else None
                if self.layout_mode and not hit:
                    self.marquee=(px,py,px,py,'REMOVE' if getattr(event,'alt',False) else 'ADD' if getattr(event,'shift',False) else 'SET',set(self.selection))
                    if self.marquee[4]=='SET':self.selection=set()
        elif event.type=='LEFTMOUSE' and event.value=='RELEASE':
            cs=getattr(self,'click_single',None);self.click_single=None
            if getattr(self,'panel_press',False):cs=None;self.panel_press=False   # Clicks on the panel don't touch poster selection
            if self.layout_mode and cs and abs(x-cs[1])<=4 and abs(y-cs[2])<=4:
                # Clicking one of several selected sheets selects just that one
                if self.drag:
                    sx_,sy_,rect,handle=self.drag
                    if self.group_drag:
                        for j,r in self.group_drag.items():self.rects[j]=list(r)
                    self.rects[cs[0]]=list(rect)
                    if self.history:self.history.pop()
                self.selection={cs[0]};self.selected=cs[0]
            if self.layout_mode:
                if getattr(self,'slider_drag',None) and self.slider_drag[0]=='tear_rim':self.fx_set_rim()
                if getattr(self,'slider_drag',None) and self.slider_drag[0].startswith('P:'):self.paper_sync()
                if getattr(self,'slider_drag',None) and (getattr(self,'fx_pending',None) or {}).get('id','').startswith('TAB:'):self.fx_commit(quiet=True)   # slider value applies on release
                self.slider_drag=None
                if getattr(self,'stroke',None):self.paint_end()
                if getattr(self,'cut_drag',None):self.cut_end()
            if self.layout_mode:self.marquee=None;self.group_drag=None;self.snap_guides=[]
            self.drag=None;self.panning=None
        elif event.type=='MOUSEMOVE' and self.layout_mode and getattr(self,'slider_drag',None):
            key,bounds=self.slider_drag
            if selection_button_held() is False:   # If the release happened outside the panel and the signal was missed, finish here
                if key=='tear_rim':self.fx_set_rim()
                elif key.startswith('P:'):self.paper_sync()
                self.slider_drag=None
            else:self.fx_slider_set(key,bounds,x)
        elif event.type=='MOUSEMOVE' and self.layout_mode and getattr(self,'painting_on',False) and not self.panning:
            self.paint_cursor=(x,y)
            if getattr(self,'stroke',None):self.paint_move(x,y)
            if getattr(self,'cut_drag',None):self.cut_drag[2:]=[x,y]
        elif self.layout_mode and getattr(self,'painting_on',False) and event.type in {'LEFT_BRACKET','RIGHT_BRACKET'} and event.value=='PRESS':
            d=self.fx_draft_get();d['brush_size']=max(2.,min(150.,d['brush_size']*(1/1.2 if event.type=='LEFT_BRACKET' else 1.2)))
        elif event.type=='MOUSEMOVE':
            if self.layout_mode and self.marquee:
                ox,oy,scale=self.view();a,b,_,_,mode,previous=self.marquee;px,py=(x-ox)/scale,(y-oy)/scale
                self.marquee=(a,b,px,py,mode,previous);l,r=sorted((a,px));bottom,top=sorted((b,py))
                hits={i for i,(x0,y0,x1,y1) in enumerate(self.rects) if x0<r and x1>l and y0<top and y1>bottom}
                self.selection=previous|hits if mode=='ADD' else previous-hits if mode=='REMOVE' else hits
                if self.selection and self.selected not in self.selection:self.selected=min(self.selection)
            elif self.panning:
                sx,sy,pan=self.panning;self.pan=[pan[0]+x-sx,pan[1]+y-sy]
            elif self.drag:
                ox,oy,scale=self.view();sx,sy,rect,handle=self.drag
                if self.layout_mode:
                    dx,dy=(x-ox)/scale-sx,(y-oy)/scale-sy
                    if handle=='MOVE' and event.shift:   # Shift while moving: straight along X or Y only (the larger movement wins)
                        if abs(dx)>=abs(dy):dy=0.
                        else:dx=0.
                    self.snap_guides=[]
                    if handle=='MOVE' and getattr(self,'snap_on',False) and (self.group_drag or self.settings.edit_mode!='CROP'):
                        dx,dy=self.snap_move(rect,dx,dy,scale,event.shift)
                    if self.group_drag:
                        rs=list(self.group_drag.values())
                        dx=round(dx);dy=round(dy)   # free move: images may sit outside the texture while arranging (Build asks to bring them back)
                        for j,(a,b,c,d) in self.group_drag.items():self.rects[j]=[a+dx,b+dy,c+dx,d+dy]
                        self.area.tag_redraw();return {'RUNNING_MODAL'}
                    if self.settings.edit_mode=='CROP':
                        base=self.applied_crops[self.selected]
                        crop=crop_map(self.drag_crop,base,True);turn=self.layout_rotations[self.selected]
                        if handle=='MOVE':
                            l,b,r,t=rotated_crop(crop,turn);cw,ch=r-l,t-b
                            l=max(0.,min(1-cw,l-dx*cw/(rect[2]-rect[0])))
                            b=max(0.,min(1-ch,b-dy*ch/(rect[3]-rect[1])))
                            self.crops[self.selected]=crop_map(rotated_crop([l,b,l+cw,b+ch],-turn),base);updated=list(rect)
                        else:
                            if event.shift:   # Shift: keep the frame ratio while resizing (move the dragged edges to the ratio-locked size)
                                lk=layout_drag(rect,handle,dx,dy,self.w,self.h,self.pad)
                                dx=(lk[0]-rect[0]) if 'W' in handle else (lk[2]-rect[2]) if 'E' in handle else 0
                                dy=(lk[1]-rect[1]) if 'S' in handle else (lk[3]-rect[3]) if 'N' in handle else 0
                            updated,edited=crop_frame_drag(rect,crop,turn,handle,dx,dy,self.w,self.h,self.pad)
                            self.crops[self.selected]=crop_map(edited,base)
                    elif self.settings.edit_mode=='SCALE':
                        if handle=='MOVE':updated=[rect[0]+round(dx),rect[1]+round(dy),rect[2]+round(dx),rect[3]+round(dy)]   # free move
                        elif event.shift:updated=layout_drag(rect,handle,dx,dy,self.w,self.h,self.pad)   # Shift: keep ratio
                        else:
                            updated=cut_drag([v-self.pad for v in rect],handle,dx,dy,self.w-2*self.pad,self.h-2*self.pad)
                            updated=[v+self.pad for v in updated]
                    elif handle=='MOVE':updated=[rect[0]+round(dx),rect[1]+round(dy),rect[2]+round(dx),rect[3]+round(dy)]   # free move
                    else:updated=layout_drag(rect,handle,dx,dy,self.w,self.h,self.pad)
                    self.rects[self.selected]=updated
                    if handle!='MOVE' and (updated[2]-updated[0],updated[3]-updated[1])!=(rect[2]-rect[0],rect[3]-rect[1]):self.physical_sizes[self.selected]=None
                else:self.rects[self.selected]=cut_drag(rect,handle,(x-ox)/scale-sx,(y-oy)/scale-sy,self.w,self.h)
        self.area.tag_redraw();return {'RUNNING_MODAL'}

EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp', '.tga', '.exr'}


def dimensions(s):
    # One fixed scale reference; image rectangles control individual poster size.
    return 210,297


def grid_for(count, ratio):
    # Explicit A4 templates preserve the agreed 2K/6 and 4K/24 layouts.
    if count == 6:return 3, 2
    if count == 24:return 6, 4
    candidates = []
    for cols in range(1, count + 1):
        rows = math.ceil(count / cols)
        scale = min(1 / (cols * ratio), 1 / rows)
        candidates.append((count * ratio * scale * scale, -(cols * rows-count), cols, rows))
    return max(candidates)[2:]


def build_files(s):
    return [f for f in s.files if f.selected]


def atlas_layout(s):
    if s.mode=='SPLIT' or s.capacity=='CUSTOM':
        return s.columns*s.rows,s.columns,s.rows
    count=max(1,len(build_files(s))) if s.capacity=='AUTO' else int(s.capacity)
    cols,rows=grid_for(count,dimensions(s)[0]/dimensions(s)[1])
    return count,cols,rows


def poster_size(s,iw,ih,cols,rows):
    basew,baseh=dimensions(s)
    # Fixed reference: 2048 px / 3 columns x 2 rows / portrait A4.
    density=min(2048/(3*basew),2048/(2*baseh))
    factor=min(int(s.resolution)/cols/iw,int(s.resolution)/rows/ih)/density
    return iw*factor,ih*factor


def read_pixels(path):
    im = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = im.size[:]
        if w < 1 or h < 1:raise ValueError('Cannot read the image: ' + os.path.basename(path))
        data = np.empty(w*h*4, dtype=np.float32)
        im.pixels.foreach_get(data)
        return data.reshape(h, w, 4)
    finally:
        bpy.data.images.remove(im)


def shrink_box(data, w, h):
    """Before shrinking a lot, average whole pixel cells first: plain bilinear only reads 4 pixels per output pixel,
    so a big image squeezed small turns jagged and grainy. Returns data at most ~2x the target size."""
    sh, sw = data.shape[:2]
    k = int(min(sw/max(w,1), sh/max(h,1))/1.5)
    if k < 2:return data
    hh, ww = sh//k*k, sw//k*k
    return data[:hh,:ww].reshape(hh//k,k,ww//k,k,data.shape[2]).mean((1,3),dtype=np.float32)


def resize(data, w, h):
    # Bilinear interpolation in bounded row chunks; no third-party package needed.
    sh, sw = data.shape[:2]
    if (sw, sh) == (w, h):return data.copy()
    data = shrink_box(data, w, h); sh, sw = data.shape[:2]
    xs = np.clip((np.arange(w)+.5)*sw/w-.5, 0, sw-1)
    x0 = xs.astype(np.int32); x1 = np.minimum(x0+1, sw-1)
    fx = (xs-x0).astype(np.float32)[None, :, None]
    out = np.empty((h, w, 4), dtype=np.float32)
    for row in range(0, h, 128):
        ys = np.clip((np.arange(row, min(row+128,h))+.5)*sh/h-.5, 0, sh-1)
        y0=ys.astype(np.int32); y1=np.minimum(y0+1,sh-1)
        fy=(ys-y0).astype(np.float32)[:,None,None]
        a=data[y0[:,None],x0[None,:]]*(1-fx)+data[y0[:,None],x1[None,:]]*fx
        b=data[y1[:,None],x0[None,:]]*(1-fx)+data[y1[:,None],x1[None,:]]*fx
        out[row:row+len(ys)]=a*(1-fy)+b*fy
    return out


def on_paper(data, w, h, crop=False):
    # Composite transparent inputs over paper white before interpolation.
    data=data.copy()
    data[:,:,:3]=data[:,:,:3]*data[:,:,3:4]+1-data[:,:,3:4]
    data[:,:,3]=1
    sh,sw=data.shape[:2]
    if crop:
        if sw/sh>w/h:
            cw=max(1,round(sh*w/h));x=(sw-cw)//2;data=data[:,x:x+cw]
        else:
            ch=max(1,round(sw*h/w));y=(sh-ch)//2;data=data[y:y+ch]
        return resize(data,w,h)
    scale=min(w/sw,h/sh)
    nw,nh=max(1,round(sw*scale)),max(1,round(sh*scale))
    scaled=resize(data,nw,nh)
    if crop:
        x=(nw-w)//2;y=(nh-h)//2
        return scaled[y:y+h,x:x+w].copy()
    out=np.ones((h,w,4),np.float32)
    x=(w-nw)//2;y=(h-nh)//2
    out[y:y+nh,x:x+nw]=scaled
    return out


def save_atlas(path, data, packed):
    h,w=data.shape[:2]
    im=bpy.data.images.new(os.path.splitext(os.path.basename(path))[0], width=w,height=h,alpha=True)
    try:
        im.colorspace_settings.name='sRGB'
        im.pixels.foreach_set(np.ascontiguousarray(data).ravel())
        im.filepath_raw=path;im.file_format='PNG';im.save()
        if packed:im.pack()
        return im
    except Exception:
        bpy.data.images.remove(im)
        raise


EDITOR_MAX_SIDE=2048


def editor_texture(im,max_side=None,store=None,key=None):
    """GPU texture for drawing the editor. Since it is drawn directly to the screen, sRGB->linear conversion must be blocked
    so it looks the same color as the file (= build result). (8-bit images only, pixel values untouched)
    max_side: screen only, so large images are downscaled before upload (saves GPU memory and load time). No effect on build results.
    store/key: keeps the downscaled pixels for reuse in preview computation."""
    import gpu
    try:
        w,h=im.size[:]
        if im.is_float and not max_side:return gpu.texture.from_image(im)
        px=np.empty(w*h*4,np.float32);im.pixels.foreach_get(px)   # File sRGB values as is
        if max_side and max(w,h)>max_side:
            k=int(math.ceil(max(w,h)/max_side));a=px.reshape(h,w,4)
            hh,ww=h//k*k,w//k*k
            a=a[:hh,:ww].reshape(hh//k,k,ww//k,k,4).mean((1,3),dtype=np.float32)   # Downscale cleanly by cell average
            h,w=a.shape[:2];px=np.ascontiguousarray(a).ravel()
        if store is not None and key is not None:store[key]=px.reshape(h,w,4)
        return gpu.types.GPUTexture((w,h),format='RGBA16F',data=gpu.types.Buffer('FLOAT',w*h*4,px))
    except Exception:
        return gpu.texture.from_image(im)


def atlas_add_normal(mat,nim):
    nt=mat.node_tree;bs=nt.nodes.get('Principled BSDF');uv=next((n for n in nt.nodes if n.type=='UVMAP'),None)
    t=nt.nodes.new('ShaderNodeTexImage');t.image=nim;t.interpolation='Linear';t.extension='EXTEND';t.label='Paper Crumple Normal';t.location=(-300,-220)
    nm_=nt.nodes.new('ShaderNodeNormalMap');nm_.location=(-20,-220)
    if uv:nt.links.new(uv.outputs['UV'],t.inputs['Vector'])
    nt.links.new(t.outputs['Color'],nm_.inputs['Color']);nt.links.new(nm_.outputs['Normal'],bs.inputs['Normal'])


def finish_canvas(records,res,paper_rough=.85):
    """Roughness (R) and metallic (G) per poster: printed photos get their surface (the picture and its white border
    can differ, like a real instant photo), everything else stays paper. None when the atlas has no pictures."""
    jobs=[(r['pixel_rect'],fx_clean(r['effects']),int(r.get('packing_rotation') or 0)//90%4) for r in records if r.get('effects')]
    jobs=[(rc,f,t) for rc,f,t in jobs if f.get('p_rough') is not None or f.get('s_rough') is not None]
    if not jobs:return None
    can=np.empty((res,res,4),np.float32);can[:]=(paper_rough,0.,0.,1.)
    for (x,y,rw,rh),f,t in jobs:
        if f.get('p_rough') is None:   # Paper tab Surface: one roughness over the whole sheet, never metal
            can[y:y+rh,x:x+rw,0]=float(f['s_rough']);can[y:y+rh,x:x+rw,1]=0.;continue
        pr,fr,pm=float(f['p_rough']),float(f.get('f_rough') or f['p_rough']),float(f.get('p_metal') or 0.)
        can[y:y+rh,x:x+rw,0]=pr;can[y:y+rh,x:x+rw,1]=pm
        if f.get('frame'):   # same border sizes as polaroid_card (on the upright card, then turned like the picture)
            uw,uh=(rh,rw) if t%2 else (rw,rh)
            S=min(uw,uh);m=f.get('frame_m') or (.051,.074,.244)
            side=max(1,round(m[0]*S));top=max(1,round(m[1]*S));bottom=int(max(1,min(round(m[2]*S),uh-top-.4*uh)))
            blk=np.empty((uh,uw,2),np.float32);blk[:,:,0]=fr;blk[:,:,1]=0.
            blk[bottom:uh-top,side:uw-side,0]=pr;blk[bottom:uh-top,side:uw-side,1]=pm
            can[y:y+rh,x:x+rw,:2]=np.rot90(blk,t,axes=(0,1))
    return can


def atlas_add_finish(mat,rim):
    """Roughness / metallic map for printed photos (R = roughness, G = metallic)."""
    nt=mat.node_tree;bs=nt.nodes.get('Principled BSDF');uv=next((n for n in nt.nodes if n.type=='UVMAP'),None)
    t=nt.nodes.new('ShaderNodeTexImage');t.image=rim;t.interpolation='Closest';t.extension='EXTEND';t.label='Photo Finish';t.location=(-300,-480)
    sp=nt.nodes.new('ShaderNodeSeparateColor');sp.label='Photo Finish';sp.location=(-20,-480)
    if uv:nt.links.new(uv.outputs['UV'],t.inputs['Vector'])
    nt.links.new(t.outputs['Color'],sp.inputs['Color'])
    paper=next((n for n in nt.nodes if n.type=='GROUP' and n.label in PAPER_NODE_LABELS),None)
    nt.links.new(sp.outputs['Red'],paper.inputs['Roughness'] if paper else bs.inputs['Roughness'])   # with paper crumple, roughness goes through it
    nt.links.new(sp.outputs['Green'],bs.inputs['Metallic'])
    add_photo_coat(mat)


def add_photo_coat(mat):
    """Glossy photo prints get a clear plastic laminate (Principled Coat) on top: paper stays dull,
    the picture area of a glossy print catches light. Driven by the Photo Finish roughness (glossy ~0.18 -> strong
    coat, luster 0.35 and paper 0.85 -> none). Safe to call again."""
    nt=mat.node_tree;bs=nt.nodes.get('Principled BSDF')
    sp=next((n for n in nt.nodes if n.type=='SEPARATE_COLOR' and n.label=='Photo Finish'),None)
    if bs is None or sp is None or 'Coat Weight' not in bs.inputs:return
    mr=next((n for n in nt.nodes if n.label=='Photo Coat'),None)
    if mr is None:
        mr=nt.nodes.new('ShaderNodeMapRange');mr.label='Photo Coat';mr.location=(200,-640);mr.clamp=True
    mr.inputs['From Min'].default_value=.35;mr.inputs['From Max'].default_value=.12
    mr.inputs['To Min'].default_value=0.;mr.inputs['To Max'].default_value=.7
    nt.links.new(sp.outputs['Red'],mr.inputs['Value']);nt.links.new(mr.outputs['Result'],bs.inputs['Coat Weight'])
    bs.inputs['Coat Roughness'].default_value=.04;bs.inputs['Coat IOR'].default_value=1.5


def finish_roughness_socket(mat):
    sp=next((n for n in mat.node_tree.nodes if n.type=='SEPARATE_COLOR' and n.label=='Photo Finish'),None)
    return sp.outputs['Red'] if sp else None


def atlas_material(im):
    mat=bpy.data.materials.new('Poster Material · '+im.name)
    mat.use_nodes=True
    nt=mat.node_tree
    bs=nt.nodes.get('Principled BSDF');bs.label='Paper Surface'
    bs.inputs['Roughness'].default_value=.85
    uv=nt.nodes.new('ShaderNodeUVMap');uv.uv_map='UVMap';uv.label='Per-Poster Image Area';uv.location=(-550,100)
    tex=nt.nodes.new('ShaderNodeTexImage');tex.image=im;tex.interpolation='Linear';tex.extension='EXTEND';tex.label='Poster Atlas Texture';tex.location=(-300,100)
    nt.links.new(uv.outputs['UV'],tex.inputs['Vector']);nt.links.new(tex.outputs['Color'],bs.inputs['Base Color'])
    nt.links.new(tex.outputs['Alpha'],bs.inputs['Alpha'])
    return mat


# ---------------------------------------------------------------------------
# Paper texture (tiling textures baked in Substance layered onto the poster shader)
# Texture naming: <set name>_s<number>_<normal|ambientocclusion|height>.png
# The normal is saved as Substance's default (DirectX, G inverted); G is flipped only in Blender.
# PaperUV = poster local plane coords (m). The shader multiplies by 1000/tile size (mm) to tile at real size.
PAPER_UV='PaperUV'
POSTER_UV='PosterUV'
POSTER_SIZE_UV='PosterSize'
PAPER_NODE_LABEL='Paper Texture'
PAPER_NODE_LABELS=(PAPER_NODE_LABEL,'종이 질감')   # also match nodes made by older (Korean) versions


def shared_dir(folder):
    """Shared data folder inside a paper texture folder ('_shared'; older versions used '_공용')."""
    new=os.path.join(folder,'_shared');old=os.path.join(folder,'_공용')
    return old if not os.path.isdir(new) and os.path.isdir(old) else new
PAPER_MAPS=('normal','ambientocclusion','height')
PAPER_FILE_RE=re.compile(r'^(.+)_s(\d+)_(normal|ambientocclusion|height)\.png$',re.I)
SD_DEFAULT_DIRS=[r'C:\Program Files\Adobe\Adobe Substance 3D Designer',r'C:\Program Files\Allegorithmic\Substance Designer']
_PAPER_ITEMS=[]
_PAPER_CACHE={'key':None,'sets':{}}


FIBER_FILE='edge_fibers.png'
FIBER_PERIOD_MM=60.   # Edge length covered by one horizontal fiber texture


def fiber_texture_array(W=4096,H=256,seed=7):
    # Torn paper edge fibers: x = along the edge (tiling), y = outward (0 = cut line). Value 1 = paper.
    rng=np.random.default_rng(seed);SS=2;w,h=W*SS,H*SS
    img=np.zeros((h,w),np.float32)
    def hairs(n,lmin,lmax,power,sigma,bend_sd,widths,vmin):
        x0=rng.uniform(0,w,n);L=(lmin+(lmax-lmin)*rng.random(n)**power)*h
        a=np.radians(rng.normal(0,sigma,n));bend=rng.normal(0,bend_sd,n)
        wid=rng.choice(widths,n);val=rng.uniform(vmin,1.,n)
        for i in range(n):
            steps=max(2,int(L[i]/0.7));t=np.linspace(0,1,steps)
            ang=a[i]+bend[i]*t
            px=x0[i]+np.cumsum(np.sin(ang))*L[i]/steps;py=np.cumsum(np.cos(ang))*L[i]/steps
            for dxo in range(-(wid[i]//2),wid[i]-wid[i]//2):
                xi=np.round(px+dxo).astype(int)%w;yi=np.clip(np.round(py).astype(int),0,h-1)
                np.maximum.at(img,(yi,xi),val[i])
    hairs(9000,0.,.35,2.2,28,0.,[2,3,3,4],.6)    # Fuzz just outside the cut line
    hairs(800,.35,.95,1.6,22,.35,[2,2,3],.67)    # Long protruding fibers
    xs=np.arange(w);prof=np.zeros(w)
    for f,amp in [(37,.05),(151,.035),(613,.025),(1709,.02)]:
        prof+=amp*np.abs(np.sin(xs/w*2*math.pi*f+rng.random()*2*math.pi))
    prof=(prof*h).astype(int)
    yy=np.arange(h)[:,None];img=np.maximum(img,(yy<=prof[None,:]).astype(np.float32))
    return img.reshape(H,SS,W,SS).mean(axis=(1,3))


EDGE_FILE_RE=re.compile(r'^(.+)_s(\d+)_(mask|height)\.png$',re.I)
EDGE_BAND=(.215,.165)   # Paper_Edge family: paper is on the small-v side, the tear line is at v≈0.17-0.215
EDGE_AMPLITUDE=.045     # Wiggle width of the tear line (relative to texture height)


def _scan_edge_sets(folder):
    out={}
    base=shared_dir(folder)
    if not os.path.isdir(base):return out
    for root,_,files in os.walk(base):
        for f in files:
            m=EDGE_FILE_RE.match(f)
            if m:out.setdefault(m.group(1),{}).setdefault(int(m.group(2)),{})[m.group(3).lower()]=os.path.join(root,f)
    return {k:{sd:mp for sd,mp in v.items() if 'mask' in mp} for k,v in out.items() if any('mask' in mp for mp in v.values())}


HOLE_FILE='hole_noise.png'


def hole_noise_array(N=2048,seed=11,roughness=.56):
    # Build tiling fractal noise (matching Noise Detail 14.7 / Roughness 0.56 from the reference video) via FFT,
    # then remap the value distribution to uniform 0-1 so 'threshold = area fraction'. As a texture, Unreal gets the same shape.
    rng=np.random.default_rng(seed)
    f=np.fft.fftfreq(N)[:,None];g=np.fft.fftfreq(N)[None,:]
    r=np.sqrt(f*f+g*g);r[0,0]=1.
    beta=-math.log2(roughness)
    amp=r**(-(1+beta));amp[r<1.5/N]=0.;amp[r>.45]=0.
    a=np.real(np.fft.ifft2(amp*np.exp(2j*math.pi*rng.random((N,N)))))
    order=a.ravel().argsort();u=np.empty(N*N,np.float32);u[order]=np.linspace(0,1,N*N,dtype=np.float32)
    return u.reshape(N,N)


def hole_noise_cached():
    """Cache the hole noise (2048², about 0.5s via FFT) in a temp folder and read it directly next time."""
    path=os.path.join(tempfile.gettempdir(),'poster_atlas_hole_noise_v1.npy')
    try:
        a=np.load(path)
        if a.shape==(2048,2048) and a.dtype==np.float32:return a
    except (OSError,ValueError):pass
    a=hole_noise_array()
    try:
        tmp=path+'.%s.tmp'%uuid.uuid4().hex[:6];np.save(tmp,a);os.replace(tmp+'.npy' if os.path.exists(tmp+'.npy') else tmp,path)
    except OSError:pass
    return a


def edge_sets(folder):
    out=_scan_edge_sets(folder) if folder else {}
    if not out and not _is_builtin(folder) and os.path.isdir(BUILTIN_PAPER_DIR):out=_scan_edge_sets(BUILTIN_PAPER_DIR)
    return out


def ensure_hole_texture(folder):
    path=os.path.join(shared_dir(folder),HOLE_FILE)
    if not os.path.isfile(path):
        os.makedirs(os.path.dirname(path),exist_ok=True)
        a=hole_noise_array();N=a.shape[0]
        im=bpy.data.images.new('_hole_tmp',N,N,alpha=False,float_buffer=False)
        try:
            px=np.repeat(a[:,:,None],4,axis=2);px[:,:,3]=1.
            im.pixels.foreach_set(np.ascontiguousarray(px,np.float32).ravel())
            im.filepath_raw=path;im.file_format='PNG';im.save()
        finally:bpy.data.images.remove(im)
    return path


def ensure_fiber_texture(folder):
    path=os.path.join(shared_dir(folder),FIBER_FILE)
    if not os.path.isfile(path):
        os.makedirs(os.path.dirname(path),exist_ok=True)
        a=fiber_texture_array();H,W=a.shape
        im=bpy.data.images.new('_fiber_tmp',W,H,alpha=False,float_buffer=False)
        try:
            px=np.repeat(a[:,:,None],4,axis=2);px[:,:,3]=1.
            im.pixels.foreach_set(np.ascontiguousarray(px,np.float32).ravel())
            im.filepath_raw=path;im.file_format='PNG';im.save()
        finally:bpy.data.images.remove(im)
    return path


# ---- Effects baked into textures (layout editor -> build) ----------------------------------------------
# Pixels are the raw Blender image buffer (sRGB-encoded values, row 0 at the bottom). Lengths in mm, density = pixels/mm.
FX_DEFAULTS={'tint':None,'tint_s':1.,'ink':None,'ink_s':1.,'sat':1.,'hue':0.,'fade':0.,'yellow':0.,
             'wear':0.,'wear_edge':15.,'peel':0.,'holes':0.,'hole_rim':.03,'hole_soft':.004,'hole_size':400.,
             'fray':0.,'fray_depth':5.,'fray_corner':.6,'fray_fiber':.8,'seed':0,'presets':[],'paint':None,'layers':[],'pattern':1.,'paper':None,
             'polaroid':0.,'pol_style':'CLASSIC','frame':0.,'frame_m':None,'photo_fmt':None,'frame_custom':False,'p_rough':None,'f_rough':None,'p_metal':None,
             'kraft':0.,'lined':0.,'grid':0.,'stain':0.,'water':0.,'recycled':0.,'laid':0.,'linen':0.,'edgetone':0.,'stain_seed':0,'stain_size':1.,'dmg_seed':0,'paper_seed':0,'caption':'','cap_font':'INK','cap_ink':'BLACK','photo_fit':None,'src_aspect':None,'texts':[],'paper_pattern':None,'ps_kraft':None,'ps_water':None,'ps_linen':None,'ps_lined':None,'ps_grid':None,'ps_edgetone':None,'s_rough':None}   # Paper styles for plain black-on-white pages
FX_TEAR_RIM=2.5   # White cross-section width at tears, mm (paint)
FX_PAINT_CHANNELS=('tear','peel','wear','protect')
FX_PAINT_LEGACY={'holes':'tear'}      # Old data name
FX_TOOLS=[('select','Select'),('tear','Tear Holes'),('peel','Peel Print'),('wear','Fade Color'),('cut','Straight Cut'),('protect','Protect'),('erase','Undo Paint')]
FX_TOOL_HELP={
    'select':'Pick a tool and drag over a poster. Paint shows as a preview and is committed only with [Apply] below. [Cancel] discards it.',
    'tear':'Tears the paper to make holes. Torn edges show a white paper cross-section.',
    'peel':'Peels off only the print, revealing white paper. No holes.',
    'wear':'Fades and blurs color as if scratched.',
    'cut':'Draw a straight line across a poster to cut it cleanly along that line. The smaller side shown in red disappears.',
    'protect':'Preset holes·peeling·wear (torn bill etc.) will not appear where painted. Use it to protect text.',
    'erase':'Does not erase the paper; it reverts areas painted with this tool. Remove cuts with × in the list below.'}
FX_PAINT_NAMES={'tear':'Tear Holes','peel':'Peel Print','wear':'Fade Color','protect':'Protect'}
FX_TOOL_COLORS={'tear':(1.,.35,.25),'peel':(1.,1.,1.),'wear':(.75,.7,.55),'protect':(.3,.6,1.),'erase':(1.,.4,.8),'cut':(1.,.2,.2)}
FX_WHITE=np.array([.94,.93,.90],np.float32)     # Peeled paper / fibers (sRGB)
FX_YELLOW=np.array([1.,.94,.78],np.float32)
FX_GRIME=np.array([.86,.83,.78],np.float32)
FX_EDGE_BAND=(.215,.165);FX_EDGE_AMP=.045
_FX_RES={}


FX_POOL=[None];FX_POKE=[None]


def fx_poke():
    a=FX_POKE[0];FX_POKE[0]=None
    try:
        if a:a.tag_redraw()
    except ReferenceError:pass
    return None


def fx_pool():
    """Workers that compute effect previews in the background (numpy, so they run concurrently)."""
    if FX_POOL[0] is None:
        from concurrent.futures import ThreadPoolExecutor
        FX_POOL[0]=ThreadPoolExecutor(max_workers=max(1,min(6,(os.cpu_count() or 4)-1)))
    return FX_POOL[0]


def fx_preview_pixels(src,crop,turn,pw,ph,background,f,den,res,paper):
    px=layout_pixels(src,crop,turn,pw,ph,background);t=int(turn or 0)%4
    if t:px=np.ascontiguousarray(np.rot90(px,-t,axes=(0,1)))   # turned to pack: the frame / caption / paper are made on the upright card, then the whole card turns
    if fx_active(f):px=apply_effects(px,f,den,res)
    if paper:px=paper_shade(px,paper,den,f['seed'])
    if t:px=np.rot90(px,t,axes=(0,1))
    return np.ascontiguousarray(px,np.float32)


def rot_normal_tex(nt,t):
    """Turn a tangent-space normal map with its card (np.rot90 by t on bottom-up rows): the image and the XY vectors."""
    t=int(t)%4
    if not t:return nt
    out=np.array(np.rot90(nt,t,axes=(0,1)),np.float32);x=out[...,0]*2-1;y=out[...,1]*2-1
    for _ in range(t):x,y=y,-x
    out[...,0]=x*.5+.5;out[...,1]=y*.5+.5;return out


def gpu_texture_from_pixels(px):
    import gpu
    h,w=px.shape[:2];return gpu.types.GPUTexture((w,h),format='RGBA16F',data=gpu.types.Buffer('FLOAT',w*h*4,px.ravel()))


def fx_key(fx):
    """Lightweight key for the preview cache: the paint mask (long string) is hashed."""
    if not fx or not fx.get('paint'):return fx
    f=dict(fx);p=dict(f['paint'])
    for k,v in list(p.items()):
        if isinstance(v,str) and len(v)>64:p[k]=('#',len(v),hash(v))
        elif isinstance(v,dict):p[k]={kk:(('#',len(vv),hash(vv)) if isinstance(vv,str) and len(vv)>64 else vv) for kk,vv in v.items()}
    f['paint']=p;return f


def fx_clean(fx):
    out=dict(FX_DEFAULTS)
    if fx:out.update({k:v for k,v in fx.items() if k in FX_DEFAULTS})
    out['presets']=list(out.get('presets') or [])
    out['layers']=[dict(l) for l in (out.get('layers') or [])]
    out['texts']=[dict(t) for t in (out.get('texts') or [])]
    if out.get('paper_pattern') is None:   # older data: the paper layer's grain size was stored as the shared 'pattern'
        pl=[l for l in out['layers'] if l.get('id') in FX_PAPER_IDS and isinstance(l.get('values'),dict) and ('paper_pattern' in l['values'] or 'pattern' in l['values'])]
        if pl:v=pl[-1]['values'];out['paper_pattern']=v.get('paper_pattern',v.get('pattern'))
    out['photo_fmt']=PHOTO_FORMAT_ALIASES.get(out['photo_fmt'],out['photo_fmt'])
    for l in out['layers']:
        v=l.get('values')
        if isinstance(v,dict) and v.get('photo_fmt') in PHOTO_FORMAT_ALIASES:l['values']=dict(v,photo_fmt=PHOTO_FORMAT_ALIASES[v['photo_fmt']])
    return out


def fx_has_paint(f):
    p=f.get('paint') if f else None
    return bool(p and (any(p.get(c) for c in FX_PAINT_CHANNELS+tuple(FX_PAINT_LEGACY)) or p.get('cuts')))


def paint_masks(p):
    """Paint mask (small grid, 0-1). Old data ('holes', negative = protect) is read under the new name too."""
    out={}
    if not p or not p.get('w'):return out
    for ch in FX_PAINT_CHANNELS+tuple(FX_PAINT_LEGACY):
        m=paint_decode(p,ch)
        if m is None:continue
        if ch!='protect' and m.min()<0:
            neg=np.clip(-m,0,1);out['protect']=np.maximum(out['protect'],neg) if 'protect' in out else neg
        key=FX_PAINT_LEGACY.get(ch,ch);pos=np.clip(m,0,1)
        out[key]=np.maximum(out[key],pos) if key in out else pos
    return {k:v for k,v in out.items() if v.max()>1e-3}


def paint_pack(masks,w,h,rim,cuts):
    """Mask and cut list to storage format. None if empty."""
    p={'w':int(w),'h':int(h),'rim':float(rim)}
    for ch,m in masks.items():
        if ch in FX_PAINT_CHANNELS and m is not None and np.abs(m).max()>1e-3:p[ch]=paint_encode(np.clip(m,0,1))
    if cuts:p['cuts']=[list(map(float,c)) for c in cuts]
    return p if any(k in p for k in FX_PAINT_CHANNELS) or cuts else None


def fx_dilate_dist(mask,steps):
    """Grow outward from mask one cell at a time and record when each is reached (approx. pixel distance). steps+1 if never reached."""
    dist=np.full(mask.shape,steps+1,np.float32);dist[mask]=0;cur=mask.copy()
    for k in range(1,steps+1):
        nxt=cur.copy()
        nxt[1:]|=cur[:-1];nxt[:-1]|=cur[1:];nxt[:,1:]|=cur[:,:-1];nxt[:,:-1]|=cur[:,1:]
        if k%2==0:   # Mix in diagonals so it spreads roundly
            nxt[1:,1:]|=cur[:-1,:-1];nxt[:-1,:-1]|=cur[1:,1:];nxt[1:,:-1]|=cur[:-1,1:];nxt[:-1,1:]|=cur[1:,:-1]
        new=nxt&~cur
        if not new.any():break
        dist[new]=k;cur=nxt
    return dist


def cut_side(cut,aspect):
    """Side that disappears in a straight cut (+1/-1): the one with smaller area."""
    x0,y0,x1,y1=cut[:4];g=(np.arange(32)+.5)/32;X,Y=np.meshgrid(g*aspect,g)
    sd=(X-x0*aspect)*(y1-y0)-(Y-y0)*(x1-x0)*aspect
    return 1. if (sd>0).mean()<=.5 else -1.


def paint_decode(p,ch):
    import base64
    data=p.get(ch) if p else None
    if not data:return None
    return np.frombuffer(base64.b64decode(data),dtype=np.int8).astype(np.float32).reshape(p['h'],p['w'])/127.


def paint_encode(arr):
    import base64
    return base64.b64encode(np.clip(np.round(arr*127),-127,127).astype(np.int8).tobytes()).decode('ascii')


def paint_upsample(m,w,h):
    # Bilinearly upscale the paint mask (small grid) to the effect pixel size. m[row 0] = bottom
    mh,mw=m.shape
    xs=np.clip((np.arange(w)+.5)*mw/w-.5,0,mw-1);ys=np.clip((np.arange(h)+.5)*mh/h-.5,0,mh-1)
    x0=xs.astype(np.int32);y0=ys.astype(np.int32);x1=np.minimum(x0+1,mw-1);y1=np.minimum(y0+1,mh-1)
    fx_=(xs-x0)[None,:];fy=(ys-y0)[:,None]
    return ((m[y0][:,x0]*(1-fx_)+m[y0][:,x1]*fx_)*(1-fy)+(m[y1][:,x0]*(1-fx_)+m[y1][:,x1]*fx_)*fy).astype(np.float32)


def fx_active(fx):
    if not fx:return False
    f=fx_clean(fx)
    if fx_has_paint(f) or text_items(f):return True
    return bool(f['tint'] or f['ink'] or abs(f['sat']-1)>1e-3 or abs(f['hue'])>1e-3 or f.get('paper') or f['polaroid']>1e-3 or f['frame'] or f.get('p_rough') is not None or f.get('s_rough') is not None or
                max(f['fade'],f['yellow'],f['wear'],f['peel'],f['holes'],f['fray'],f.get('kraft',0.),f.get('lined',0.),f.get('grid',0.),f.get('stain',0.),f.get('water',0.),f.get('recycled',0.),f.get('laid',0.),f.get('linen',0.),f.get('edgetone',0.))>1e-3)


def fx_sample(tex,u,v):
    """Wrapping bilinear sample. tex[row=v, col=u]. (read with np.take from a flat array for speed)"""
    H,W=tex.shape[:2]
    flat=tex.reshape(-1) if tex.flags.c_contiguous else np.ascontiguousarray(tex).reshape(-1)
    x=np.asarray(u,np.float32)*np.float32(W)-np.float32(.5);y=np.asarray(v,np.float32)*np.float32(H)-np.float32(.5)
    xf=np.floor(x);yf=np.floor(y);fx_=x-xf;fy=y-yf
    x0=xf.astype(np.int32)%W;y0=yf.astype(np.int32)%H
    x1=x0+1;x1[x1==W]=0;y1=y0+1;y1[y1==H]=0
    r0=y0*W;r1=y1*W
    a_=np.take(flat,r0+x0);b_=np.take(flat,r0+x1);c_=np.take(flat,r1+x0);d_=np.take(flat,r1+x1)
    a_+=(b_-a_)*fx_;c_+=(d_-c_)*fx_;a_+=(c_-a_)*fy
    return a_


def fx_sample_clamped_v(tex,u,v):
    H=tex.shape[0];return fx_sample(tex,u,np.clip(v,.5/H,1-.5/H))


def fx_rng(seed,salt):
    return np.random.default_rng((int(seed)*7919+salt)&0xffffffff)


def fx_damage_field(tex,xm,ym,W_,H_,size,seed):
    """Peel/hole pattern. Each poster looks different: size, direction, stretch, distortion and which edge it tore from are set by seed,
    and finally it is evenly remapped to 0-1 so the 'amount' slider keeps its meaning (area fraction)."""
    q=fx_rng(seed,77).random(16)
    sc=size*(.55+1.3*q[0])                                   # Pattern size
    th=(round(q[1])*.5+(q[1]-.5)*.17)*math.pi;c,s_=math.cos(th),math.sin(th)   # Grain runs roughly horizontal or vertical (±15°), like real paper
    stretch=1.+(.5*q[3] if q[2]<.4 else .2*q[3])             # Slightly elongated at most (1.5×), no long diagonal streaks
    u=(xm*c-ym*s_)/sc;v=(xm*s_+ym*c)/sc*stretch
    warp=.12+.25*q[4]                                         # Gentle twist so blobs aren't round
    wu=fx_sample(tex,u*.35+q[5]*11,v*.35+q[6]*11)-.5;wv=fx_sample(tex,u*.35+q[7]*11+.5,v*.35+q[8]*11+.5)-.5
    big=fx_sample(tex,u+wu*warp+q[9]*13,v+wv*warp+q[10]*13)
    small=fx_sample(tex,u*3.1+q[11]*7,v*3.1+q[12]*7)
    mix=.15+.55*q[13]                                         # Mostly large blobs <-> finely scattered
    n=big*(1-mix)+small*mix
    # Tears usually start at edges/corners: pick 1-2 per poster and bias toward them
    edges=[xm/W_,1-xm/W_,ym/H_,1-ym/H_]
    k1=int(q[14]*4);k2=int(q[15]*4)
    near=np.minimum(edges[k1],edges[k2] if q[2]>.5 else 1.)
    n=n+np.clip(1-near/.45,0,1)**1.5*(.25+.35*q[4])
    o=n.ravel().argsort();out=np.empty(n.size,np.float32);out[o]=np.linspace(0,1,n.size,dtype=np.float32)
    return out.reshape(n.shape)


# ---- Polaroid: instant-photo look + white card frame -------------------------------------------------
POL_STYLES={   # sRGB values. black/white: where pure black/white end up · shadow/high: split-tone tints · vignette<0 = lighter edges
    'CLASSIC':dict(black=(.085,.075,.07),white=(.99,.96,.88),shadow=(-.025,.02,.04),high=(.04,.02,-.045),sat=.86,contrast=0.,vignette=.22,grain=.018,blur=.2,stain=0.,glow=0.,frame=(.955,.948,.925)),
    'EXPIRED':dict(black=(.15,.13,.14),white=(.99,.93,.80),shadow=(-.05,.045,.03),high=(.08,.005,-.06),sat=.62,contrast=-.12,vignette=.38,grain=.028,blur=.32,stain=.3,glow=.6,frame=(.94,.925,.88)),
    'FADED':dict(black=(.25,.23,.21),white=(1.,.975,.90),shadow=(0.,.025,.035),high=(.05,.035,-.03),sat=.52,contrast=-.28,vignette=-.28,grain=.016,blur=.28,stain=0.,glow=0.,frame=(.965,.955,.93)),
    'BW':dict(black=(.075,.07,.065),white=(.97,.955,.93),shadow=(0.,0.,0.),high=(.01,.005,-.01),sat=0.,contrast=.12,vignette=.2,grain=.03,blur=.15,stain=0.,glow=0.,frame=(.955,.95,.94)),
    'WARM':dict(black=(.04,.035,.03),white=(1.,.97,.90),shadow=(.01,0.,-.02),high=(.05,.02,-.04),sat=1.08,contrast=.06,vignette=.12,grain=.015,blur=.1,stain=0.,glow=0.,frame=(.96,.955,.945)),
    'COOL':dict(black=(.04,.05,.055),white=(.97,.99,1.),shadow=(-.03,.02,.04),high=(0.,.015,0.),sat=.95,contrast=.08,vignette=.12,grain=.015,blur=.1,stain=0.,glow=0.,frame=(.96,.96,.955))}
POL_STYLE_NAMES=[('CLASSIC','Classic 70s'),('EXPIRED','Expired'),('FADED','Faded Sun'),('BW','B&W'),('WARM','Warm Film'),('COOL','Cool Film')]


def pol_noise(h,w,cells,rng):
    """Smooth value noise 0-1 with about 'cells' blobs across the long side."""
    gy=max(2,int(round(cells*h/max(h,w)))+2);gx=max(2,int(round(cells*w/max(h,w)))+2)
    g=rng.random((gy,gx)).astype(np.float32)
    ys=np.linspace(0,gy-1.001,h,dtype=np.float32);xs=np.linspace(0,gx-1.001,w,dtype=np.float32)
    y0=ys.astype(np.int32);x0=xs.astype(np.int32);ty=ys-y0;tx=xs-x0;ty=ty*ty*(3-2*ty);tx=tx*tx*(3-2*tx)
    a=g[y0][:,x0];b=g[y0][:,x0+1];c=g[y0+1][:,x0];d=g[y0+1][:,x0+1]
    return (a*(1-tx)+b*tx)*(1-ty)[:,None]+(c*(1-tx)+d*tx)*ty[:,None]


def pol_blur(img,r):
    """Separable box blur, radius r pixels."""
    if r<1:return img
    out=img
    for ax in (0,1):
        c=np.cumsum(np.pad(out,[(r+1,r) if a==ax else (0,0) for a in range(out.ndim)],mode='edge'),axis=ax,dtype=np.float32)
        n=out.shape[ax];out=(np.take(c,np.arange(2*r+1,2*r+1+n),axis=ax)-np.take(c,np.arange(n),axis=ax))/(2*r+1)
    return out


def pol_cover(src,iw,ih):
    """Fill an iw×ih window with src, scaled to cover and centered (bilinear)."""
    h,w=src.shape[:2];sc=max(iw/w,ih/h)
    if sc<1/3:   # big shrink: average cells first (see shrink_box)
        k=int(1/sc/1.5);hh,ww=h//k*k,w//k*k
        src=src[:hh,:ww].reshape(hh//k,k,ww//k,k,src.shape[2]).mean((1,3),dtype=np.float32);h,w=src.shape[:2];sc=max(iw/w,ih/h)
    xs=np.clip((np.arange(iw)+.5)/sc+(w-iw/sc)/2-.5,0,w-1);ys=np.clip((np.arange(ih)+.5)/sc+(h-ih/sc)/2-.5,0,h-1)
    x0=xs.astype(np.int32);y0=ys.astype(np.int32);x1=np.minimum(x0+1,w-1);y1=np.minimum(y0+1,h-1)
    fx_=(xs-x0)[None,:,None];fy=(ys-y0)[:,None,None]
    return ((src[y0][:,x0]*(1-fx_)+src[y0][:,x1]*fx_)*(1-fy)+(src[y1][:,x0]*(1-fx_)+src[y1][:,x1]*fx_)*fy).astype(np.float32)


def polaroid_grade(rgb,st,k,density,seed):
    """Instant-film color: soft, low saturation, lifted blacks, cool shadows / warm highlights, vignette, grain.
    Expired film adds a colored developer haze from the edges (mostly the bottom) and a few chemical spots."""
    h,w=rgb.shape[:2];lum=np.array([.299,.587,.114],np.float32)
    g=pol_blur(rgb,int(round(st['blur']*density)))
    Y=g@lum;g=Y[...,None]+(g-Y[...,None])*st['sat'];g=.5+(g-.5)*(1+st['contrast'])
    Y=np.clip(g@lum,0,1)[...,None]
    g=g+np.array(st['shadow'],np.float32)*(1-Y)**2*2.+np.array(st['high'],np.float32)*Y**2*2.
    bk=np.array(st['black'],np.float32);g=bk+np.clip(g,0,1)*(np.array(st['white'],np.float32)-bk)
    yy,xx=np.mgrid[0:h,0:w].astype(np.float32)
    u=(xx+.5)/w*2-1;v=(yy+.5)/h*2-1;asp=w/h
    d=np.sqrt((u*min(asp,1.))**2+(v*min(1/asp,1.))**2)/math.sqrt(2);vig=np.clip((d-.35)/.65,0,1)**1.5
    if st['vignette']>0:g=g*(1-st['vignette']*vig)[...,None]
    elif st['vignette']<0:g=g+(1-g)*(-st['vignette']*vig)[...,None]
    if st['glow']>0 or st['stain']>0:
        e=np.minimum(np.minimum(xx,w-1-xx),np.minimum(yy,h-1-yy))/density   # mm from the photo edge
        n1=pol_noise(h,w,6,fx_rng(seed,302));n2=pol_noise(h,w,18,fx_rng(seed,303))
        if st['glow']>0:
            band=np.clip(1-(yy/density)/(6.+8*n2),0,1)**1.5   # row 0 = bottom: the developer pod side
            gl=np.clip(np.exp(-e/(1.5+4.5*n1))+band*.6,0,1)*(.55+.45*n2)*st['glow']
            t=np.clip((n2-.3)/.4,0,1)[...,None]
            col=np.array([.55,.80,.82],np.float32)*(1-t)+np.array([.96,.74,.50],np.float32)*t
            g=g+(col-g)*(gl*.6)[...,None]
        if st['stain']>0:
            m=np.clip((pol_noise(h,w,9,fx_rng(seed,304))-(.80-.12*st['stain']))/.10,0,1)**1.5*st['stain']
            g=g+(np.array([.93,.84,.66],np.float32)-g)*(m*.7)[...,None]
    if st['grain']>0:
        r=fx_rng(seed,301);amp=st['grain']*(1-np.abs(np.clip(g@lum,0,1)-.5)*1.1)
        g=g+(r.standard_normal((h,w)).astype(np.float32)*amp)[...,None]+r.standard_normal((h,w,3)).astype(np.float32)*(amp*.3)[...,None]
    return rgb+(np.clip(g,0,1)-rgb)*min(float(k),1.5)


# ---- Caption: handwriting in the instant card's bottom margin -------------------------------------
CAPTION_FONTS={'INK':('Ink Free','Inkfree.ttf'),'PRINT':('Segoe Print','segoepr.ttf'),'SCRIPT':('Segoe Script','segoesc.ttf')}
CAPTION_INKS={'BLACK':('Black Marker',(.07,.07,.09)),'BLUE':('Blue Pen',(.1,.17,.5)),'RED':('Red Marker',(.62,.1,.12))}
_CAPTION_CACHE={}   # (text, font) -> alpha mask (rows bottom-up); filled on the main thread, read by worker threads
_CAPTION_FONT_IDS={}


def caption_font_path(key):
    fn=CAPTION_FONTS.get(key,CAPTION_FONTS['INK'])[1]
    return os.path.join(os.environ.get('WINDIR',r'C:\Windows'),'Fonts',fn)


def caption_mask(text,font):
    """Rasterize the caption once (main thread only: uses the GPU). Returns the cached mask or None."""
    key=(text,font)
    if key in _CAPTION_CACHE:return _CAPTION_CACHE[key]
    if not text.strip():return None
    try:
        import gpu,blf
        from mathutils import Matrix
        path=caption_font_path(font)
        fid=_CAPTION_FONT_IDS.get(path)
        if fid is None:
            fid=blf.load(path) if os.path.isfile(path) else 0;_CAPTION_FONT_IDS[path]=fid
        lines=text.split('\n');S=120;blf.size(fid,S)
        dims=[blf.dimensions(fid,_T(l or ' ')) for l in lines];lh=int(S*1.22)
        W=max(8,int(max(d[0] for d in dims))+S//2);H=lh*len(lines)+S//3
        off=gpu.types.GPUOffScreen(W,H)
        try:
            with off.bind():
                fb=gpu.state.active_framebuffer_get();fb.clear(color=(0.,0.,0.,0.))
                with gpu.matrix.push_pop():
                    gpu.matrix.load_matrix(Matrix.Identity(4));gpu.matrix.load_projection_matrix(Matrix.Identity(4))
                    gpu.matrix.translate((-1.,-1.));gpu.matrix.scale((2./W,2./H))
                    for j,l in enumerate(lines):   # each line slightly offset, like real handwriting
                        blf.position(fid,S//4+(j%2)*S*.12,H-(j+1)*lh+int(S*.28),0);blf.color(fid,1,1,1,1);blf.draw(fid,_T(l))
                buf=fb.read_color(0,0,W,H,4,0,'FLOAT')
        finally:off.free()
        a=np.array(buf,dtype=np.float32).reshape(H,W,4)[...,3]
        ys,xs=np.nonzero(a>.02)
        if len(xs):a=a[max(0,ys.min()-4):ys.max()+5,max(0,xs.min()-4):xs.max()+5]   # trim to the ink
        _CAPTION_CACHE[key]=np.ascontiguousarray(a)
    except Exception as exc:
        print('poster_atlas caption',exc);_CAPTION_CACHE[key]=None
    return _CAPTION_CACHE[key]


def caption_ensure(fx,img_h=None):
    """Call on the main thread before effects run in workers. img_h: height (px) of the image the effects run on,
    so text is rasterized near its final size (never blown up from a small raster)."""
    f=fx_clean(fx) if fx else None
    if f and f.get('frame') and (f.get('caption') or '').strip():caption_mask(f['caption'],f.get('cap_font') or 'INK')
    for it in text_items(f):text_mask(it['t'],it.get('font') or 'INK',it.get('ls',1.),text_raster(it,img_h),it.get('wt',0))


def caption_draw(card,f,w,h,side,bottom,density,seed):
    """Write the caption into the bottom margin (card rows bottom-up): fitted to the margin, slightly tilted and off-center."""
    mask=_CAPTION_CACHE.get(((f.get('caption') or ''),f.get('cap_font') or 'INK'))
    if mask is None or bottom<6:return card
    mh,mw=mask.shape;q=fx_rng(seed,620).random(4)
    bw=w-2*side;s=min(.80*bw/mw,.56*bottom/mh)
    if s<=0:return card
    ang=np.radians((q[0]-.5)*5.)
    cx=w*.5+(q[1]-.5)*bw*.08;cy=bottom*.5+(q[2]-.5)*bottom*.12
    y0=0;y1=bottom;x0=side;x1=w-side
    yy,xx=np.mgrid[y0:y1,x0:x1].astype(np.float32)
    dx=xx-cx;dy=yy-cy;c,s_=np.cos(ang),np.sin(ang)
    u=(c*dx+s_*dy)/s+mw*.5;v=(-s_*dx+c*dy)/s+mh*.5
    P=np.pad(mask,1);u=np.clip(u+1,0,mw+.999);v=np.clip(v+1,0,mh+.999)
    iu=np.minimum(u.astype(np.int32),mw);iv=np.minimum(v.astype(np.int32),mh);fu=u-iu;fv=v-iv
    a=(P[iv,iu]*(1-fu)+P[iv,iu+1]*fu)*(1-fv)+(P[iv+1,iu]*(1-fu)+P[iv+1,iu+1]*fu)*fv
    a=np.clip(a,0,1)*(.86+.1*q[3])   # marker on glossy card: not quite opaque
    ink=np.array(CAPTION_INKS.get(f.get('cap_ink') or 'BLACK',CAPTION_INKS['BLACK'])[1],np.float32)
    reg=card[y0:y1,x0:x1];card[y0:y1,x0:x1]=reg*(1-a[...,None])+ink*a[...,None]
    return card


# ---- Text tool: free text written on any image (layout editor) -------------------------------------
# Each image keeps a list fx['texts'] of {'t' text ('\n' = new line), 'font', 'ink', 'x','y' center (0-1 of the image, y from the bottom),
# 'h' letter size as a fraction of the image height, 'ang' degrees (counter-clockwise), 'ls' line spacing}.
TEXT_FONTS={'INK':('Ink Free','Inkfree.ttf'),'PRINT':('Segoe Print','segoepr.ttf'),'SCRIPT':('Segoe Script','segoesc.ttf'),
            'TYPE':('Typewriter','courbd.ttf'),'BOLD':('Bold Sans','ariblk.ttf')}
TEXT_INKS={'BLACK':('Black',(.07,.07,.09)),'BLUE':('Blue',(.1,.17,.5)),'RED':('Red',(.62,.1,.12)),'WHITE':('White',(.96,.95,.92))}
TEXT_S=120   # raster size of the letters (px) before they are scaled onto the image
_TEXT_DIMS={}


TEXT_WEIGHTS=[('Regular',0.),('Bold',.018),('Heavy',.036)]   # extra stroke thickness (fraction of the letter size) added around every letter
_TEXT_FONT_LIST=[]


def text_font_path(font):
    """Quick fonts by key; any other installed font is stored as its file path."""
    if font in TEXT_FONTS or not font:return os.path.join(os.environ.get('WINDIR',r'C:\Windows'),'Fonts',TEXT_FONTS.get(font or 'INK',TEXT_FONTS['INK'])[1])
    return font


def ttf_name(path):
    """Full font name from a TrueType/OpenType 'name' table (Windows English entry), or None."""
    import struct
    try:
        with open(path,'rb') as fh:
            hd=fh.read(12);n=struct.unpack('>H',hd[4:6])[0];dr=fh.read(16*n)
            ent=next((struct.unpack('>4sIII',dr[16*k:16*k+16]) for k in range(n) if dr[16*k:16*k+4]==b'name'),None)
            if ent is None:return None
            fh.seek(ent[2]);d=fh.read(ent[3])
        off=0
        if True:
            _,cnt,so=struct.unpack('>HHH',d[0:6]);best=None
            for j in range(cnt):
                pid,eid,lid,nid,l_,o_=struct.unpack('>HHHHHH',d[off+6+12*j:off+18+12*j])
                if pid==3 and nid in (4,1) and lid in (0x409,0x412,0x411,0x804,0x404):
                    v=d[off+so+o_:off+so+o_+l_].decode('utf-16-be','ignore')
                    if nid==4:return v
                    best=best or v
            return best
    except Exception:return None
    return None


def text_font_list():
    """Every installed .ttf / .otf font: [(path, name)], sorted by name. Read once."""
    if _TEXT_FONT_LIST:return _TEXT_FONT_LIST
    dirs=[os.path.join(os.environ.get('WINDIR',r'C:\Windows'),'Fonts'),os.path.join(os.environ.get('LOCALAPPDATA',''),'Microsoft','Windows','Fonts')]
    seen={}
    for d in dirs:
        try:names=os.listdir(d)
        except OSError:continue
        for fn in names:
            if not fn.lower().endswith(('.ttf','.otf')):continue
            p=os.path.join(d,fn);nm=ttf_name(p) or os.path.splitext(fn)[0]
            if nm not in seen:seen[nm]=p
    _TEXT_FONT_LIST.extend(sorted(((p,nm) for nm,p in seen.items()),key=lambda v:v[1].lower()))
    return _TEXT_FONT_LIST


def text_font_label(font):
    if font in TEXT_FONTS:return TEXT_FONTS[font][0]
    return next((nm for p,nm in text_font_list() if p==font),os.path.splitext(os.path.basename(font or ''))[0])


def text_font_id(font):
    path=text_font_path(font)
    fid=_CAPTION_FONT_IDS.get(path)
    if fid is None:
        import blf
        fid=blf.load(path) if os.path.isfile(path) else 0;_CAPTION_FONT_IDS[path]=fid
    return fid


def text_layout(t,font,ls):
    """Block layout at TEXT_S (main thread, blf): (W, H, line step, lines, widths). Lines are left aligned."""
    key=(t,font,round(float(ls),3))
    if key in _TEXT_DIMS:return _TEXT_DIMS[key]
    import blf
    fid=text_font_id(font);blf.disable(fid,blf.ROTATION);blf.size(fid,TEXT_S)
    lines=t.split('\n');lh=TEXT_S*1.25*float(ls)
    widths=[blf.dimensions(fid,_T(l))[0] if l else 0. for l in lines]
    out=(max(widths+[TEXT_S*.25]),TEXT_S*1.25+lh*(len(lines)-1),lh,lines,widths)
    if len(_TEXT_DIMS)>400:_TEXT_DIMS.clear()
    _TEXT_DIMS[key]=out;return out


def text_raster(it,img_h):
    """Raster size for a text: the smallest step at or above its letter size in the final image (sharp, never enlarged)."""
    if not img_h:return TEXT_S
    need=float(it.get('h',.08))*float(img_h)
    return next((S for S in (TEXT_S,240,480,960) if S>=need),960)


def text_dilate(m,r):
    """Thicken the letters by r px (rounded octagon steps), keeping soft edges."""
    for k in range(int(r)):
        p=np.pad(m,1);n=np.maximum.reduce([p[1:-1,1:-1],p[:-2,1:-1],p[2:,1:-1],p[1:-1,:-2],p[1:-1,2:]])
        if k%2:n=np.maximum.reduce([n,p[:-2,:-2],p[2:,2:],p[:-2,2:],p[2:,:-2]])
        m=n
    frac=r-int(r)
    if frac>.05:
        p=np.pad(m,1);m=m+(np.maximum.reduce([p[:-2,1:-1],p[2:,1:-1],p[1:-1,:-2],p[1:-1,2:]])-m)*frac
    return np.ascontiguousarray(m)


def text_key(it):
    return ('T',it['t'],it.get('font') or 'INK',round(float(it.get('ls',1.)),3),int(it.get('wt',0) or 0))


def text_mask(t,font,ls,S=TEXT_S,wt=0):
    """Rasterize one text block once at letter size S (main thread only: uses the GPU). Mask center = block center. Cached."""
    key=('T',t,font,round(float(ls),3),int(wt or 0),int(S))
    if key in _CAPTION_CACHE:return _CAPTION_CACHE[key]
    if not t.strip():return None
    try:
        import gpu,blf
        from mathutils import Matrix
        W,H,lh,lines,_=text_layout(t,font,ls);q=S/TEXT_S;W,H,lh=W*q,H*q,lh*q;fid=text_font_id(font);P=int(S*.45)
        Wi=min(16000,int(math.ceil(W))+2*P);Hi=min(16000,int(math.ceil(H))+2*P)
        off=gpu.types.GPUOffScreen(Wi,Hi)
        try:
            with off.bind():
                fb=gpu.state.active_framebuffer_get();fb.clear(color=(0.,0.,0.,0.))
                with gpu.matrix.push_pop():
                    gpu.matrix.load_matrix(Matrix.Identity(4));gpu.matrix.load_projection_matrix(Matrix.Identity(4))
                    gpu.matrix.translate((-1.,-1.));gpu.matrix.scale((2./Wi,2./Hi))
                    blf.disable(fid,blf.ROTATION);blf.size(fid,S)
                    for j,l in enumerate(lines):
                        if l:blf.position(fid,P,P+H-S-j*lh,0);blf.color(fid,1,1,1,1);blf.draw(fid,_T(l))
                buf=fb.read_color(0,0,Wi,Hi,4,0,'FLOAT')
        finally:off.free()
        m=np.ascontiguousarray(np.array(buf,dtype=np.float32).reshape(Hi,Wi,4)[...,3])
        r=TEXT_WEIGHTS[max(0,min(2,int(wt or 0)))][1]*S
        _CAPTION_CACHE[key]=text_dilate(m,r) if r>0 else m
    except Exception as exc:
        print('poster_atlas text',exc);_CAPTION_CACHE[key]=None
    return _CAPTION_CACHE[key]


def text_items(f):
    return [t for t in ((f or {}).get('texts') or []) if (t.get('t') or '').strip()]


def text_draw(rgb,a,f,h,w):
    """Write the image's texts into rgb / alpha (rows bottom-up). Masks must exist (text_mask on the main thread)."""
    for it in text_items(f):
        key=text_key(it);S=text_raster(it,h)
        m=_CAPTION_CACHE.get(key+(S,))
        if m is None:S=TEXT_S;m=_CAPTION_CACHE.get(key+(S,))
        if m is None:continue
        s=float(it.get('h',.08))*h/S   # image px per mask px
        if s<=1e-4:continue
        k=int(1/s) if s<.75 else 1
        if k>1:   # shrink the mask first so small letters stay smooth instead of aliased
            mh_,mw_=(m.shape[0]//k)*k,(m.shape[1]//k)*k
            if mh_<k or mw_<k:continue
            m=m[:mh_,:mw_].reshape(mh_//k,k,mw_//k,k).mean((1,3));s*=k
        mh,mw=m.shape;cx=float(it.get('x',.5))*w;cy=float(it.get('y',.5))*h
        ang=math.radians(float(it.get('ang',0.)));c,sn=math.cos(ang),math.sin(ang)
        hw,hh=mw*s/2,mh*s/2;ex=abs(c)*hw+abs(sn)*hh;ey=abs(sn)*hw+abs(c)*hh
        x0=max(0,int(cx-ex)-1);x1=min(w,int(cx+ex)+2);y0=max(0,int(cy-ey)-1);y1=min(h,int(cy+ey)+2)
        if x1<=x0 or y1<=y0:continue
        yy,xx=np.mgrid[y0:y1,x0:x1].astype(np.float32);dx=xx+.5-cx;dy=yy+.5-cy
        u=(c*dx+sn*dy)/s+mw*.5-.5;v=(-sn*dx+c*dy)/s+mh*.5-.5
        P=np.pad(m,1);u=np.clip(u+1,0,mw+.999);v=np.clip(v+1,0,mh+.999)
        iu=np.minimum(u.astype(np.int32),mw);iv=np.minimum(v.astype(np.int32),mh);fu=u-iu;fv=v-iv
        al=(P[iv,iu]*(1-fu)+P[iv,iu+1]*fu)*(1-fv)+(P[iv+1,iu]*(1-fu)+P[iv+1,iu+1]*fu)*fv
        al=np.clip(al,0,1)*.94   # ink, not quite opaque
        ink=np.array(TEXT_INKS.get(it.get('ink') or 'BLACK',TEXT_INKS['BLACK'])[1],np.float32)
        rgb[y0:y1,x0:x1]=rgb[y0:y1,x0:x1]*(1-al[...,None])+ink*al[...,None]
        a[y0:y1,x0:x1]=np.maximum(a[y0:y1,x0:x1],al)
    return rgb,a


def polaroid_card(px,f,density):
    """px (h,w,4) sRGB, row 0 = bottom. With 'frame' the photo is fitted into a window on a white card
    (thin sides and top, thick bottom like an instant photo); without it only the color look is applied."""
    st=POL_STYLES.get(f.get('pol_style') or 'CLASSIC',POL_STYLES['CLASSIC']);k=float(f.get('polaroid') or 0.)
    seed=int(f.get('seed') or 1);h,w=px.shape[:2];out=px.copy()
    if not f.get('frame'):
        if k>0:out[:,:,:3]=polaroid_grade(px[:,:,:3],st,k,density,seed)
        return out
    S=min(w,h);m=f.get('frame_m') or (.051,.074,.244)   # border (side, top, bottom) as a fraction of the short side
    side=max(1,round(m[0]*S));top=max(1,round(m[1]*S))
    bottom=int(max(1,min(round(m[2]*S),h-top-.4*h)));iw=max(2,w-2*side);ih=max(2,h-top-bottom)
    fc=np.array(st['frame'],np.float32)
    src=px[:,:,:3]*px[:,:,3:4]+fc*(1-px[:,:,3:4])   # transparent parts of the picture show the card color
    fit=f.get('photo_fit') or 'CROP'   # Edit Mode when the format was set: Scale = whole photo stretched, Keep Ratio = whole photo fitted, Crop = fill
    if fit=='CROP':photo=pol_cover(src,iw,ih)
    else:
        s4=np.concatenate([src,np.ones(src.shape[:2]+(1,),np.float32)],-1)
        if fit=='SCALE':photo=resize(s4,iw,ih)[:,:,:3]
        else:   # Keep Ratio: the photo (with its own ratio) centered in the window, card color around it
            ar=float(f.get('src_aspect') or (src.shape[1]/max(src.shape[0],1)))
            fw,fh=(iw,max(1,round(iw/ar))) if iw/ih<ar else (max(1,round(ih*ar)),ih)
            photo=np.empty((ih,iw,3),np.float32);photo[:]=fc
            ox_=(iw-fw)//2;oy_=(ih-fh)//2;photo[oy_:oy_+fh,ox_:ox_+fw]=resize(s4,fw,fh)[:,:,:3]
    if k>0:photo=polaroid_grade(photo,st,k,density,seed)
    card=np.empty((h,w,3),np.float32);card[:]=fc
    card*=(1+(pol_noise(h,w,10,fx_rng(seed,310))-.5)*.025)[...,None]   # faint paper mottle
    yy,xx=np.mgrid[0:h,0:w].astype(np.float32)
    dx=np.maximum(np.maximum(side-xx,xx-(w-side-1)),0);dy=np.maximum(np.maximum(bottom-yy,yy-(h-top-1)),0)
    card*=(1-.06*np.exp(-np.sqrt(dx*dx+dy*dy)/density/.6))[...,None]   # soft shade around the window
    card[bottom:bottom+ih,side:side+iw]=photo
    win=card[bottom:bottom+ih,side:side+iw];rim=max(1,int(round(.18*density)))
    for j in range(min(rim,ih//2,iw//2)):   # darker emulsion line hugging the window edge
        t=.22*(1-j/rim);win[j,:]*=1-t;win[-1-j,:]*=1-t;win[:,j]*=1-t;win[:,-1-j]*=1-t
    if (f.get('caption') or '').strip():card=caption_draw(card,f,w,h,side,bottom,density,seed)
    out[:,:,:3]=np.clip(card,0,1);out[:,:,3]=1.
    return out


# Real paper scans: detail maps (gray, 0.5 = flat) in <add-on>/paper_scans, made from generated 4K scans.
# key: (file, physical size of one tile in mm, strength)
PAPER_SCAN_DIR=os.path.join(os.path.dirname(os.path.abspath(__file__)),'paper_scans')
PAPER_SCANS={'kraft':('kraft_detail.png',150.,.30),'water':('watercolor_detail.png',150.,.30),'linen':('linen_detail.png',150.,.26)}


def load_paper_scans():
    out={}
    for k,(fn,_,_) in PAPER_SCANS.items():
        pth=os.path.join(PAPER_SCAN_DIR,fn)
        if os.path.isfile(pth):
            try:out[k]=_fx_load_gray(pth)
            except (OSError,RuntimeError):pass
    return out


def scan_mip(scan,tile_px):
    """Shrink a paper scan (2×2 averages) toward the poster's pixel rate: a weave finer than the pixels would
    otherwise alias into repeating blotches (moire) instead of reading as an even texture."""
    while scan.shape[0]*.5>=tile_px*.8 and scan.shape[0]%2==0 and scan.shape[1]%2==0 and scan.shape[0]>=32:
        scan=.25*(scan[0::2,0::2]+scan[1::2,0::2]+scan[0::2,1::2]+scan[1::2,1::2])
    return np.ascontiguousarray(scan,np.float32)


def paper_styles(rgb,paper_w,f,xm,ym,W_,H_,density,tex,seed,scans=None):
    """Turn a plain white page into notebook / kraft / grid paper, with an optional coffee ring.
    Lines, grid and kraft only touch the paper (bright pixels), so black writing stays on top."""
    yt=H_-ym   # mm from the top edge
    rng=fx_rng(seed,7)
    def line(d,width):   # anti-aliased line of `width` mm at distance d mm
        return np.clip((width*.5-d)*density+.5,0,1)
    def tint(m,col,k):   # multiply toward col by mask m
        return rgb*(1-(m*k)[...,None]*(1-np.array(col,np.float32)))
    def noise(scale_mm,ox,oy):
        if tex is not None:return fx_sample(tex,xm/scale_mm+ox,ym/scale_mm+oy)
        return np.full(xm.shape,.5,np.float32)
    pw=paper_w[...,0]
    def psz(k):   # Pattern Size of one paper kind (older data: one shared paper size)
        return float(np.clip(f.get('ps_'+k) or f.get('paper_pattern') or f.get('pattern',1.) or 1.,.2,5.))
    def grain(m,amount):   # material only: light/dark variation, mostly on the paper, a little through the ink
        return rgb*(1+(m*amount*(.5+.5*pw)))[...,None]
    for key_,(fname_,size_mm,amp_) in PAPER_SCANS.items():   # Real paper scans (high-passed, seamless): texture only, colors stay
        kk=min(2.,f.get(key_,0.))
        scan=(scans or {}).get(key_)
        if kk<=1e-3 or scan is None:continue
        q=fx_rng(seed,sum(map(ord,key_))).random(3)   # own offset and turn per poster, so the same paper never lines up twice
        ang=q[2]*2*np.pi if key_ in ('kraft','water') else (np.pi*.5 if q[2]>.5 else 0.)   # laid / linen keep their line direction
        c,s_=np.cos(ang),np.sin(ang)
        psc=psz(key_);u=(xm*c-yt*s_)/(size_mm*psc)+q[0];v_=(xm*s_+yt*c)/(size_mm*psc)+q[1]
        d=fx_sample(scan_mip(scan,size_mm*psc*density),u,v_)-.5
        rgb=grain(d*2*amp_,kk)
    v=min(2.,f.get('lined',0.))
    if v>1e-3:   # ruled notebook: blue lines every 7.5 mm below a header, red margin
        psc=psz('lined');sp=7.5*psc;top=min(22.*psc,H_*.18);t=(yt-top)%sp;d=np.minimum(t,sp-t)
        m=line(d,.3)*(yt>top-.5)
        rgb=tint(m*pw,(.45,.64,.88),min(1.,.85*v))
        if W_>50:rgb=tint(line(np.abs(xm-min(18.,W_*.15)),.35)*pw,(.92,.42,.42),min(1.,.8*v))
    g=min(2.,f.get('grid',0.))
    if g>1e-3:   # 5 mm grid, light teal
        psc=psz('grid');sp=5.*psc;tx=xm%sp;ty=yt%sp
        m=np.maximum(line(np.minimum(tx,sp-tx),.2),line(np.minimum(ty,sp-ty),.2))
        rgb=tint(m*pw,(.55,.76,.78),min(1.,.7*g))
    et=min(2.,f.get('edgetone',0.))
    if et>1e-3:   # Aged edges: the paper tones darker and warmer toward its edges (handled, light-struck), unevenly
        psc=psz('edgetone');wd=14.*psc;e=np.minimum(np.minimum(xm,W_-xm),np.minimum(yt,H_-yt))
        m=(1-np.clip(e/wd,0,1))**1.8*(.7+.6*(noise(80.*psc,float(rng.random()),float(rng.random()))-.5))+(1-np.clip(e/(wd*3.5),0,1))**2*.35
        rgb=tint(np.clip(m,0,1),(.80,.72,.58),min(1.,.55*et))
    st=min(3.,f.get('stain',0.))
    if st>1e-3:   # coffee ring near a corner: uneven ring + faint pool, over paper and ink
        rng=fx_rng(int(f.get('stain_seed') or seed),7)   # own seed: the Seed buttons move the ring
        R=float(rng.uniform(34.,42.))*float(np.clip(f.get('stain_size',1.) or 1.,.3,3.))   # a real mug base (~70-85 mm ring) x Pattern Size; other effects don't change it
        def spot(L):   # ring center: mostly on the paper (at most ~1/3 of the ring hangs over an edge)
            lo,hi=R*.35,L-R*.35
            return float(rng.uniform(lo,hi)) if hi>lo else L*.5
        cx=spot(W_);cy=spot(H_)
        d=np.hypot(xm-cx,yt-cy);th=np.arctan2(yt-cy,xm-cx);ph=float(rng.uniform(0,6.283))
        br=np.clip(.6+.55*np.sin(th*1.+ph)+.2*np.sin(th*3.+ph*2),0,1)   # the ring breaks up on one side
        wob=(noise(6.,.3,.8)-.5)*1.6
        ring=np.exp(-((d-R+wob)/1.4)**2)*br*(.8+.5*(noise(1.5,.9,.1)-.5))      # dried rim, ~2-3 mm wide
        ring2=np.exp(-((d-R*.93+wob)/.8)**2)*br*.35                           # faint second rim just inside
        pool=np.clip((R-d)/R,0,1)**.6*.30*(.6+.8*(noise(9.,.4,.4)-.5))       # tea-colored stain inside
        rgb=tint(np.clip(ring*1.15+ring2+pool*1.3,0,1),(.52,.33,.15),float(1-np.exp(-1.4*st)))   # Strength: Light .5 · Medium .75 · Strong .9+
    return np.clip(rgb,0,1)


def apply_effects(px,fx,density,res):
    """px: (h,w,4) float32, not preserved. res: {'hole':2D, 'edge_mask':2D, 'edge_height':2D or absent}"""
    f=fx_clean(fx);h,w=px.shape[:2]
    if h<2 or w<2 or not fx_active(f):return px
    L_=f['layers'];pi_=next((k for k,l in enumerate(L_) if l['id'] in ('PHOTO','POLAROID')),None)
    if pi_ and (f['polaroid']>1e-3 or f['frame']):   # click order: effects picked before the card go on the photo, the card wraps around them
        pre=fx_flatten(L_[:pi_],fx)
        if pre:pre=dict(pre,paint=None,texts=[]);px=apply_effects(px,pre,density,res)   # (paint / text belong on the finished card: once, below)
        post=fx_flatten(L_[pi_:],fx)
        return apply_effects(px,post,density,res) if post else px
    if f['polaroid']>1e-3 or f['frame']:px=polaroid_card(px,f,density)   # 0) Instant photo first: later aging also hits the card
    rgb=px[:,:,:3];a=px[:,:,3].copy()
    # Original brightness: bright = paper, dark = ink. Paper color is applied only by this ratio so ink color isn't buried.
    paper_w=np.clip((rgb@np.array([.299,.587,.114],np.float32)-.15)/.7,0,1)[...,None]
    seed=int(f.get('dmg_seed') or f['seed']);r=fx_rng(seed,1).random(8)   # damage patterns follow the effect's Seed
    yy,xx=np.mgrid[0:h,0:w].astype(np.float32)
    xm=(xx+.5)/density;ym=(yy+.5)/density;W_=w/density;H_=h/density   # mm
    # 1) Saturation · hue (YIQ rotation) — only on the original print colors. Done first so chosen ink/paper colors come out exact
    if abs(f['sat']-1)>1e-3 or abs(f['hue'])>1e-3:
        Y=rgb@np.array([.299,.587,.114],np.float32);I=rgb@np.array([.596,-.274,-.322],np.float32);Q=rgb@np.array([.211,-.523,.312],np.float32)
        th=f['hue']*2*np.pi;c,s_=np.cos(th),np.sin(th);I,Q=(I*c-Q*s_)*f['sat'],(I*s_+Q*c)*f['sat']
        rgb=np.clip(np.stack([Y+.956*I+.621*Q,Y-.272*I-.647*Q,Y-1.106*I+1.703*Q],-1),0,1)
    # 2) Ink color: screen -> black becomes ink color, white stays
    if f['ink'] is not None:
        ink=np.array(f['ink'],np.float32);scr=1-(1-rgb)*(1-ink);rgb=rgb+(scr-rgb)*f['ink_s']
    # 3) Paper color: multiply -> only white paper is tinted
    if f['tint'] is not None:
        tint=np.array(f['tint'],np.float32);rgb=rgb+(rgb*tint-rgb)*(f['tint_s']*paper_w)
    # 3b) Paper styles (lines, grid, kraft fibers, coffee ring): under the ink, like a real printed/written page
    if max(f.get('kraft',0.),f.get('lined',0.),f.get('grid',0.),f.get('stain',0.),f.get('water',0.),f.get('recycled',0.),f.get('laid',0.),f.get('linen',0.),f.get('edgetone',0.))>1e-3:
        rgb=paper_styles(rgb,paper_w,f,xm,ym,W_,H_,density,res.get('hole'),int(f.get('paper_seed') or f['seed']),res.get('scans'))
    # 4) Fade · yellowing
    if f['fade']>0:rgb=rgb+(FX_WHITE-rgb)*(f['fade']*.75)
    if f['yellow']>0:rgb=rgb+(rgb*FX_YELLOW-rgb)*f['yellow']
    if text_items(f):rgb,a=text_draw(rgb,a,f,h,w)   # 4b) Text: written on the paper, so later wear / holes / tears also hit it
    hole_tex=res.get('hole')
    # Hand paint is computed separately from presets (painted spots always show). Only Protect removes preset damage.
    paint=f['paint'] or {}
    pm={k:paint_upsample(v,w,h) for k,v in paint_masks(paint).items()}
    cuts=paint.get('cuts') or []
    wear_a=f['wear'];peel_a=f['peel'];holes_a=f['holes'];holes_boost=0.;peel_boost=0.
    if 'protect' in pm:rgb0=rgb.copy();a0=a.copy()
    def noise(scale_mm,ox,oy):
        return fx_sample(hole_tex,xm/scale_mm+ox,ym/scale_mm+oy)
    # 5) Wear: edges + blotches peel, with grime at the edges
    if np.max(wear_a)>0 and hole_tex is not None:
        ps_=160.*max(f.get('pattern',1.),.1)   # Mix two patterns of different sizes to hide tiling
        blot=np.clip((noise(ps_,r[0]*7,r[1]*7)+noise(ps_*1.618,r[1]*5+.37,r[0]*3+.71)-1.)*1.45+.5,0,1)
        edge_mm=np.minimum(np.minimum(xm,W_-xm),np.minimum(ym,H_-ym))
        edge=np.clip(1-edge_mm/max(f['wear_edge'],.1),0,1)*np.clip(blot*1.2+.2,0,1)
        patch=np.clip((blot-(1-wear_a*.55))*4,0,1)
        mask=np.clip((edge+patch)*wear_a*1.6,0,1)[...,None]
        rgb=rgb+(FX_WHITE-rgb)*mask
        grime=np.clip(edge*wear_a*.55,0,1)[...,None];rgb=rgb+(rgb*FX_GRIME-rgb)*grime
    white=np.zeros((h,w),np.float32)
    # 6) Print peel · holes (one noise, two thresholds — reference video method)
    if (np.max(peel_a)>0 or np.max(holes_a)>0) and hole_tex is not None:
        n=fx_damage_field(hole_tex,xm,ym,W_,H_,max(f['hole_size'],1.),seed);soft=max(f['hole_soft'],.002)
        if np.max(peel_a)>0:white=np.maximum(white,np.clip((n-(1-peel_a*.6-peel_boost))/soft,0,1)*(peel_a>0))
        if np.max(holes_a)>0:
            thr=1-holes_a*.5-holes_boost
            white=np.maximum(white,np.clip((n-(thr-f['hole_rim']))/soft,0,1)*(holes_a>0))
            a=a*(1-np.clip((n-thr)/soft,0,1)*(holes_a>0))
    # 7) Torn edges: Paper_Edge mask on each of the four sides
    em=res.get('edge_mask')
    if f['fray']>0 and em is not None:
        eh=res.get('edge_height')
        depth=max(f['fray_depth']*f['fray'],.01);period=depth/FX_EDGE_AMP
        cx=np.minimum(xm,W_-xm);cy=np.minimum(ym,H_-ym);cd=np.sqrt(cx*cx+cy*cy)
        extra=np.clip(1-cd/(depth*6+8),0,1)*f['fray_corner']*depth*1.5
        keep=np.ones((h,w),np.float32);rim=np.zeros((h,w),np.float32)
        if hole_tex is not None and 'hole_lo' not in res:   # For large smooth bends: blur the noise into 64 cells and remap to 0-1
            N=hole_tex.shape[0];b_=N//64;lo_=hole_tex[:b_*64,:b_*64].reshape(64,b_,64,b_).mean((1,3))
            o_=lo_.ravel().argsort();u_=np.empty(64*64,np.float32);u_[o_]=np.linspace(0,1,64*64,dtype=np.float32);res['hole_lo']=u_.reshape(64,64)
        extra_max=float(extra.max()) if extra.size else 0.
        for k,(dist,along) in enumerate(((xm,ym),(W_-xm,ym),(ym,xm),(H_-ym,xm))):
            ro=fx_rng(seed,20+k).random(8);L=H_ if k<2 else W_
            a1=ym[:,0] if k<2 else xm[0,:]                       # Only one row along the edge needs computing
            if hole_tex is not None:   # Different per edge: depth changes slowly, bends broadly, with a few big tears here and there
                lo_t=res['hole_lo']
                c1=fx_sample(lo_t,a1/(depth*30+120)+ro[0]*9,ro[1]*9+.5+0*a1)
                deep=depth*2.4*c1**2.2                   # Mostly shallow, deep inward in a few spots (tooth size unchanged)
                wob=(fx_sample(lo_t,a1/(depth*12+40)+ro[2]*7,ro[3]*7+.3+0*a1)-.5)*depth*1.4
                bite=np.zeros_like(a1)
                for b in range(int(ro[4]*3*f['fray']+.6)):   # 0-3 big tear spots
                    bc=(.1+.8*fx_rng(seed,40+k*5+b).random())*L;bw=depth*(4+8*fx_rng(seed,60+k*5+b).random())
                    bd=depth*(1.2+2.2*fx_rng(seed,80+k*5+b).random())
                    t=np.clip(1-((a1-bc)/bw)**2,0,1)
                    bite=np.maximum(bite,bd*t**.6*(.7+.6*fx_sample(lo_t,a1/(depth*6+20)+b*.37,ro[5]*5+b*.21+0*a1)))
                off=(deep+wob+bite).astype(np.float32)
            else:off=np.zeros_like(a1)
            off=off.reshape(-1,1) if k<2 else off.reshape(1,-1)
            # Inside this distance the paper is intact, no need to compute
            limit=float(off.max())+extra_max+period*(FX_EDGE_BAND[0]+.01)+1.
            if k==0:n_=int(np.searchsorted(xm[0,:],limit,'right'));sl=(slice(None),slice(0,n_))
            elif k==1:n_=int(np.searchsorted(xm[0,:],W_-limit,'left'));sl=(slice(None),slice(n_,w))
            elif k==2:n_=int(np.searchsorted(ym[:,0],limit,'right'));sl=(slice(0,n_),slice(None))
            else:n_=int(np.searchsorted(ym[:,0],H_-limit,'left'));sl=(slice(n_,h),slice(None))
            ds=dist[sl]
            if ds.size==0:continue
            off_s=off[sl[0],:] if k<2 else off[:,sl[1]]
            v=FX_EDGE_BAND[0]+.005-(ds-extra[sl]-off_s)/period;u=along[sl]/(period*(.8+.4*ro[6]))+r[4]*7.31+ro[7]*13.7
            m=fx_sample_clamped_v(em,u,np.maximum(v,.001));keep[sl]=np.minimum(keep[sl],m)
            if eh is not None:rim[sl]=np.maximum(rim[sl],m*(1-fx_sample_clamped_v(eh,u,np.maximum(v,.001))))
        a=a*keep;white=np.maximum(white,rim*f['fray_fiber'])
    rgb=rgb+(FX_WHITE-rgb)*white[...,None]
    if 'protect' in pm:   # Protect: revert preset damage
        # Split with a crisp torn-looking line instead of a semi-transparent blend
        pr=np.clip((pm['protect']+(noise(140.,r[3]*5+.5,r[0]*5+.3)-.5)*.5-.45)/.03,0,1) if hole_tex is not None else np.clip(pm['protect']*2,0,1)
        rgb=rgb+(rgb0-rgb)*pr[...,None];a=a+(a0-a)*pr
        if (a<.5).any() and pr.max()>.5:   # White cross-section also where protected areas meet holes
            steps=max(1,int(math.ceil(1.6*density)));dist=fx_dilate_dist(a<.5,steps)/density
            edge=np.clip((1.3-dist)*density*.8,0,1)*(dist>0)*pr
            rgb=rgb+(FX_WHITE-rgb)*edge[...,None]
    # 8) Hand-painted effects
    if hole_tex is not None:
        if 'wear' in pm:
            m=pm['wear'];bl=noise(120.,r[0]*3+.21,r[1]*3+.37);sc=noise(30.,r[2]*5+.11,r[3]*5+.53)
            k=np.clip(m*(.45+.75*bl)-.15*sc,0,1)*.8
            rgb=rgb+(FX_WHITE-rgb)*k[...,None];rgb=rgb+(rgb*FX_GRIME-rgb)*(np.clip(m-.5,0,1)*.4*bl)[...,None]
        if 'peel' in pm:
            t=pm['peel']+(noise(140.,r[4]*9+.3,r[5]*9+.7)-.5)*.6+(noise(45.,r[6]*7,r[7]*7)-.5)*.25
            rgb=rgb+(FX_WHITE-rgb)*np.clip((t-.5)/.05,0,1)[...,None]
        if 'tear' in pm:
            n2=noise(25.,r[7]*5+.4,r[6]*5+.2)
            t=pm['tear']+(noise(140.,r[5]*11+.6,r[6]*11+.9)-.5)*.6+(noise(45.,r[4]*3+.2,r[3]*3+.6)-.5)*.25+(n2-.5)*.08
            hole=t>.55
            rim_mm=float(paint.get('rim',FX_TEAR_RIM))
            if rim_mm>0 and hole.any():
                steps=max(1,int(math.ceil(rim_mm*1.7*density)))
                dist=fx_dilate_dist(hole,steps)/density
                width=rim_mm*(.4+1.2*noise(160.,r[1]*3+.8,r[2]*3+.1))   # White cross-section with slowly varying width
                fuzz=(n2-.5)*min(rim_mm,2.)*.6                          # Only the outer end frays like fibers
                rim=np.clip((width+fuzz-dist)*density*.8,0,1)*(dist>0)
                rgb=rgb+(FX_WHITE*(.97+.03*n2[...,None])-rgb)*rim[...,None]
            a=np.where(hole,0.,a)
    for c in cuts:   # Straight cut: clean like a knife
        x0,y0,x1,y1,side=c[:5];X0,Y0,X1,Y1=x0*W_,y0*H_,x1*W_,y1*H_
        L=max(math.hypot(X1-X0,Y1-Y0),1e-6)
        sd=((xm-X0)*(Y1-Y0)-(ym-Y0)*(X1-X0))/L
        a=a*np.clip(.5-sd*side*density,0,1)
    # Punched areas get the paper color (prevents black fringes with mipmaps/filtering)
    rgb=np.where((a<.5)[...,None],FX_WHITE,rgb)
    out=np.empty_like(px);out[:,:,:3]=np.clip(rgb,0,1);out[:,:,3]=a
    return out


FX_PRESETS=[
    # Paper kinds first (shown right after Paper Crumple): real-scan textures, then ruled / grid paper
    ('KRAFT','Kraft Texture',dict(kraft=1.)),
    ('WATER','Watercolor Paper',dict(water=1.)),
    ('LINEN','Linen Paper',dict(linen=1.)),
    ('LINED','Lined Note',dict(lined=1.)),
    ('GRIDP','Grid Paper',dict(grid=1.)),
    ('POSTIT','Sticky Note',dict(tint=(1.,.93,.43))),   # only the note color: no torn edges (user, 2026-10-12)
    ('FADE','Sun Faded',dict(fade=.45,yellow=.25,sat=.7)),
    ('EDGETONE','Aged Edges',dict(edgetone=1.)),
    ('OLD','Old Poster',dict(fade=.25,yellow=.55,wear=.45,wear_edge=20.,fray=.5,fray_depth=4.)),
    ('STREET','Street Flyer',dict(fade=.15,yellow=.2,wear=.35,peel=.35,holes=.12,hole_soft=.02,fray=.8,fray_depth=6.)),
    ('TORN','Torn Bill',dict(peel=.55,holes=.3,hole_soft=.05,hole_size=500.,fray=1.,fray_depth=8.,wear=.3)),
    ('COFFEE','Coffee Ring',dict(stain=1.))]
FX_PAPER_IDS={'PRESET:'+k for k in ('KRAFT','WATER','LINEN','LINED','GRIDP','EDGETONE')}
FX_DAMAGE_KEYS={'OLD','STREET','TORN'}
FX_PAPER_KIND_KEYS=('kraft','water','linen','lined','grid','edgetone')


def fx_preset_uses(p,what):
    """Does the previewed preset react to Pattern Size ('size') / Seed ('seed')? None = not a preset (show everything)."""
    if not p or not p.get('id','').startswith('PRESET:'):return True
    vals=next((v for k,_,v in FX_PRESETS if 'PRESET:'+k==p['id']),{})
    dmg=any(k in vals for k in ('wear','peel','holes','fray'));stain='stain' in vals
    if what=='size':return dmg or stain or any(k in vals for k in FX_PAPER_KIND_KEYS)
    return dmg or stain or any(k in vals for k in ('kraft','water','linen','edgetone'))   # These cut the paper (torn edges, holes, peel): outline and shadow change, so they get their own group
POSTIT_COLORS={'Y':('Yellow',(1.,.93,.43)),'P':('Pink',(1.,.71,.81)),'B':('Sky Blue',(.67,.85,1.)),'G':('Lime',(.73,.94,.75)),'O':('Orange',(1.,.66,.36)),'V':('Purple',(.80,.72,1.)),'RANDOM':('Random',None)}
POSTIT_PRESET6=[c for t,c in POSTIT_COLORS.values() if c]   # Yellow·pink·sky·lime + orange·purple
POSTIT_DEFAULT_POOL=POSTIT_PRESET6[:4]                        # Initial random uses the original 4 colors


def postit_pool(s):
    """Color list for sticky-note random (duplicates allowed = weight). Default 4 colors if empty."""
    try:
        v=json.loads(s.postit_pool) if s.postit_pool else None
        if isinstance(v,list) and v and all(isinstance(c,list) and len(c)==3 for c in v):return [tuple(float(x) for x in c) for c in v]
    except (ValueError,TypeError):pass
    return [tuple(c) for c in POSTIT_DEFAULT_POOL]


def set_postit_pool(s,pool):
    s.postit_pool=json.dumps([[round(float(x),4) for x in c] for c in pool])


FX_TINT_SETS={'POSTIT':[(1.,.93,.43),(1.,.71,.81),(.67,.85,1.),(.73,.94,.75)],
              'NEON':[(1.,.98,.35),(1.,.47,.75),(.47,1.,.63),(1.,.67,.24)]}
FX_JITTER_KEYS=('fade','yellow','wear','peel','holes','fray','fray_depth','hole_size','kraft','water','linen','edgetone','stain')


def fx_from_preset(key,rng,jitter):
    base=dict(next(v for k,_,v in FX_PRESETS if k==key))
    if isinstance(base.get('tint'),str):
        cols=FX_TINT_SETS[base['tint']];base['tint']=cols[int(rng.integers(len(cols)))]
    if jitter:
        for k in FX_JITTER_KEYS:
            if k in base:base[k]=float(base[k]*rng.uniform(.7,1.3))
        for k in ('fade','yellow','wear','peel','holes','fray'):
            if k in base:base[k]=min(1.,base[k])
    base['seed']=int(rng.integers(1,2**31-1))
    return fx_clean(base)


FX_TABS=[('COLOR','Color'),('WEAR','Wear'),('PEEL','Holes'),('FRAY','Tear'),('PAINT','Paint')]
PAPER_SLIDERS={'paper_strength':('Crumple Strength',0.,3.,'%.2f'),'paper_tile_mm':('Pattern Size mm',50.,1500.,'%.0f'),'paper_ao':('Crumple Shading',0.,1.,'%.2f')}
FX_TAB_KEYS={'COLOR':('tint','tint_s','ink','ink_s','sat','hue','fade','yellow'),'WEAR':('wear','wear_edge'),
             'PEEL':('peel','holes','hole_rim','hole_soft','hole_size'),'FRAY':('fray','fray_depth','fray_corner','fray_fiber')}
FX_SLIDERS={'tint_s':('Paper Color Strength',0.,1.,'%.2f'),'ink_s':('Ink Color Strength',0.,1.,'%.2f'),'sat':('Saturation',0.,2.,'%.2f'),'hue':('Hue Shift',-.5,.5,'%.2f'),
            'fade':('Fade',0.,1.,'%.2f'),'yellow':('Yellowing',0.,1.,'%.2f'),'wear':('Wear',0.,1.,'%.2f'),'wear_edge':('Edge Width mm',0.,60.,'%.0f'),
            'peel':('Print Peel',0.,1.,'%.2f'),'holes':('Holes',0.,1.,'%.2f'),'hole_rim':('Hole White Rim',0.,.15,'%.3f'),'hole_soft':('Edge Softness',.002,.15,'%.3f'),
            'hole_size':('Pattern Size mm',50.,1500.,'%.0f'),'fray':('Torn Edges',0.,1.,'%.2f'),'fray_depth':('Tear Depth mm',0.,20.,'%.1f'),
            'fray_corner':('Corner Focus',0.,1.,'%.2f'),'fray_fiber':('White Cross-section',0.,1.,'%.2f'),
            'brush_size':('Brush Size mm',2.,150.,'%.0f'),'brush_strength':('Brush Strength',.05,1.,'%.2f'),
            'tear_rim':('White Cross-section Width mm',0.,8.,'%.1f')}
FX_TAB_SLIDERS={'COLOR':('tint_s','ink_s','sat','hue','fade','yellow'),'WEAR':('wear','wear_edge'),
                'PEEL':('peel','holes','hole_rim','hole_soft','hole_size'),'FRAY':('fray','fray_depth','fray_corner','fray_fiber'),
                'PAINT':(),'PAPER':()}
# Two rows, count-fitted: row 1 = original + 8 colors, row 2 = 9 white/gray/black tones
FX_PAPER_SWATCHES=[None,(1.,.93,.43),(1.,.71,.81),(.67,.85,1.),(.73,.94,.75),(1.,.8,.6),(.84,.74,.58),(1.,.98,.35),(1.,.47,.75)]
FX_PAPER_GRAYS=[(1.,.98,.92),(.92,.9,.84),(.78,.65,.48),(.9,.9,.9),(.78,.78,.78),(.65,.65,.65),(.5,.5,.5),(.35,.35,.35),(.2,.2,.2)]
FX_INK_SWATCHES=[None,(.1,.18,.55),(.75,.12,.14),(.08,.35,.75),(.1,.45,.25),(.35,.22,.12),(.43,.16,.47),(1.,.28,.69),(1.,.66,.8)]
FX_INK_GRAYS=[(.02,.02,.02),(.12,.12,.12),(.22,.22,.22),(.33,.33,.33),(.45,.45,.45),(.58,.58,.58),(.7,.7,.7),(.82,.82,.82),(.95,.95,.95)]
FX_BRUSHES=[('peel','Peel'),('holes','Holes'),('wear','Wear'),('erase','Erase')]


def fx_toggle_preset(old,key,rng,jitter):
    """Stack a preset on top of existing effects. Pressing an applied preset again removes only that preset's values."""
    f=fx_clean(old);applied=list(f['presets'])
    if key in applied:
        applied.remove(key)
        keys=[k for k in next(v for k_,_,v in FX_PRESETS if k_==key) if k in FX_DEFAULTS]
        for k in keys:f[k]=FX_DEFAULTS[k]
        for other in applied:   # If remaining presets set the same value, fill it again
            base=fx_from_preset(other,rng,False)
            for k in keys:
                if k in next(v for k_,_,v in FX_PRESETS if k_==other):f[k]=base[k]
        f['presets']=applied
        return f if fx_active(f) else None
    base=fx_from_preset(key,rng,jitter)
    for k in next(v for k_,_,v in FX_PRESETS if k_==key):
        if k in FX_DEFAULTS:f[k]=base[k]
    if not f['seed']:f['seed']=base['seed']
    f['presets']=applied+[key]
    return f


FX_VALUE_KEYS=tuple(k for k in FX_DEFAULTS if k not in ('seed','presets','paint','layers','texts'))
# Strength a newly picked effect starts at (for a filming demo they were set to HIGH / HEAVY / HIGH).
FX_START_AMOUNT='MID';FX_START_PAPER='MID';FX_START_LOOK='MID'   # look 'MID' = strength 1.0
LOOK_K={'LOW':.5,'MID':1.,'HIGH':1.5}   # film look strength (polaroid_grade caps at 1.5)
FX_AMOUNTS={'LOW':('Light',.5),'MID':('Medium',1.),'HIGH':('Strong',1.7),'CUSTOM':('Custom',None)}
# Aged Edges: Strong = the darker, wider edge the user picked (Custom 3.0 / size 2.7); Light / Medium follow it (edge strength caps at 2)
FX_STRONG_OVERRIDES={'PRESET:EDGETONE':{'LOW':{'amount':.9,'scale':1.5},'MID':{'amount':1.45,'scale':2.1},'HIGH':{'amount':3.,'scale':2.7}}}
FX_SCALES={'LOW':('Small',.55),'MID':('Medium',1.),'HIGH':('Large',1.9),'CUSTOM':('Custom',None)}
PEND_SLIDERS={'amount_v':('Strength Scale',.1,3.,'%.2f'),'scale_v':('Size Scale',.2,5.,'%.2f')}
FX_TAB_NAMES={'COLOR':'Color Adjust','WEAR':'Wear Adjust','PEEL':'Holes Adjust','FRAY':'Tear Adjust'}
FX_TOUCH={'tint':('tint','tint_s'),'ink':('ink','ink_s')}   # a color swatch also sets its strength
# The keys that make a preset what it is: when later adjustments override all of them, the preset is gone
FX_MAIN_KEYS=('tint','ink','sat','hue','fade','yellow','wear','peel','holes','fray','stain','kraft','lined','grid','water','linen','edgetone','recycled','laid')
FX_BRUSH_TIPS=[('soft','Soft'),('hard','Hard'),('noise','Noise'),('spray','Spray')]
FX_BRUSH_POWER=[('Gentle',.25),('Medium',.6),('Firm',1.)]


def fx_layers(fx):
    """List of applied effect layers. Old effects without layer info count as one layer ('Previous Effects')."""
    if not fx:return []
    f=fx_clean(fx);L=[dict(l) for l in f['layers']]
    if not L:
        vals={k:f[k] for k in FX_VALUE_KEYS if f[k]!=FX_DEFAULTS[k]}
        if vals:L=[{'id':'OLD','name':'Previous Effects','values':vals}]
    return L


def fx_stack(a,b):
    """Adding the same effect again stacks it: intensities build up instead of being replaced."""
    out=dict(a)
    for k,v in b.items():
        if k in ('fade','yellow','wear','peel','holes','fray') and isinstance(v,(int,float)):
            o=float(a.get(k,0.));out[k]=float(min(1.,o+v*(1.-o)))
        elif k=='sat' and isinstance(v,(int,float)):out[k]=float(a.get(k,1.))*float(v)
        elif k=='paper' and isinstance(v,dict) and isinstance(a.get('paper'),dict):
            pv=dict(v);pv['strength']=float(min(3.,a['paper'].get('strength',0.)+v.get('strength',0.)));out[k]=pv
        else:out[k]=v
    return out


FX_DEP_KEYS=(('fray_depth',('fray',)),('wear_edge',('wear',)),('hole_size',('peel','holes')),('hole_soft',('peel','holes')),('pattern',('wear','peel','holes','fray')),('dmg_seed',('wear','peel','holes','fray')))


def fx_live_layers(layers):
    """Drop presets whose every main value (fade, tint, wear …) is set again by a later hand adjustment: nothing of them is left."""
    out=[];over=set()
    for l in reversed(layers):
        main={k for k in l['values'] if k in FX_MAIN_KEYS}
        if l['id'].startswith('PRESET:') and main and main<=over:continue
        out.append(l)
        if not l['id'].startswith('PRESET:') and l['id']!='PAPER':over|=main
    return out[::-1]


def fx_flatten(layers,base=None):
    """Overwrite layers in order to get final values (later layers override earlier). Paint and pattern seed are kept."""
    layers=fx_live_layers(layers)
    b=fx_clean(base);f=fx_clean(None)
    owner={}   # size / seed keys of damage: kept by the effect with the stronger matching damage
    for l in layers:
        vals={k:v for k,v in l['values'].items() if k in FX_VALUE_KEYS}
        if l['id'] in FX_PAPER_IDS and 'pattern' in vals:   # older paper layers stored their grain size as the shared 'pattern': keep it apart from damage
            pp=vals.pop('pattern');vals.setdefault('paper_pattern',pp)
        if l['id'].startswith('PRESET:'):   # presets stack: Sun Faded + Old Poster keep both fades, Old Poster + Torn Bill keep both wears
            for dep,srcs in FX_DEP_KEYS:
                if dep in vals:
                    w=sum(float(vals.get(k,0.) or 0.) for k in srcs)
                    if w<owner.get(dep,-1.):vals.pop(dep)
                    else:owner[dep]=w
            for k in ('fade','yellow','wear','peel','holes','fray'):
                if k in vals and isinstance(vals[k],(int,float)):vals[k]=float(1-(1-float(f.get(k,0.) or 0.))*(1-float(vals[k])))
            if isinstance(vals.get('sat'),(int,float)):vals['sat']=float(f.get('sat',1.))*float(vals['sat'])
        else:   # values typed / dialed by hand win
            for dep,srcs in FX_DEP_KEYS:
                if dep in vals:owner[dep]=1e9
        f.update(vals)
    f['seed']=b['seed'];f['paint']=b['paint'];f['texts']=b['texts'];f['layers']=[dict(l) for l in layers]
    f['presets']=[l['id'][7:] for l in layers if l['id'].startswith('PRESET:')]
    return f if fx_active(f) else None


def fx_summary(fx):
    if not fx_active(fx):return 'No Effects'
    f=fx_clean(fx);parts=[]
    if f['frame'] or f['polaroid']>1e-3:parts.append(' '.join(x for x in ('Photo',f.get('photo_fmt') or '',dict(POL_STYLE_NAMES).get(f['pol_style'],'') if f['polaroid']>1e-3 else '','border' if f['frame'] else '') if x))
    if f['tint']:parts.append('Paper Color')
    if f['ink']:parts.append('Ink Color')
    for k,name in (('fade','Fade'),('yellow','Yellowing'),('wear','Wear'),('peel','Peel'),('holes','Holes'),('fray','Tear')):
        if f[k]>1e-3:parts.append('%s %d'%(name,round(f[k]*100)))
    if abs(f['sat']-1)>1e-3:parts.append('Saturation %d'%round(f['sat']*100))
    if fx_has_paint(f):parts.append('Hand Painted')
    if text_items(f):parts.append('Text')
    if f.get('s_rough') is not None and f.get('p_rough') is None:parts.append('Surface %.2f'%f['s_rough'])
    return ' · '.join(parts)


def fx_seed(fx,path):
    f=fx_clean(fx)
    return f['seed'] or int(hashlib.md5(path.encode('utf-8')).hexdigest()[:8],16)


def _fx_load_gray(path):
    im=bpy.data.images.load(path,check_existing=False)
    try:
        im.colorspace_settings.name='Non-Color';w,h=im.size[:]
        buf=np.empty(w*h*4,np.float32);im.pixels.foreach_get(buf)
        return buf.reshape(h,w,4)[:,:,0].copy()
    finally:bpy.data.images.remove(im)


def _fx_load_rgb(path):
    im=bpy.data.images.load(path,check_existing=False)
    try:
        im.colorspace_settings.name='Non-Color';w,h=im.size[:]
        buf=np.empty(w*h*4,np.float32);im.pixels.foreach_get(buf)
        return buf.reshape(h,w,4)[:,:,:3].copy()
    finally:bpy.data.images.remove(im)


def paper_preview_maps(s,normal_path,ao_path,limit=1024):
    cache=fx_resources(s).setdefault('paper_maps',{});key=(normal_path,ao_path,limit)
    if key not in cache:
        n=_fx_load_rgb(normal_path)
        while n.shape[0]>limit:n=n[::2,::2]
        n=np.ascontiguousarray(n.transpose(2,0,1))   # Stored per channel for fast reads
        a=_fx_load_gray(ao_path) if ao_path else None
        while a is not None and a.shape[0]>limit:a=a[::2,::2]
        if len(cache)>6:cache.clear()
        cache[key]=(n,a)
    return cache[key]


def paper_info(s,pinfo,full=False):
    """Poster effect paper crumple values -> for shading. None if the texture is not found."""
    if not pinfo:return None
    folder=paper_folder(s);sets=paper_sets(folder) if folder and os.path.isdir(folder) else {}
    pset=pinfo.get('set') if pinfo.get('set') in sets else (sorted(sets)[0] if sets else None)
    if not pset:return None
    pseed=int(pinfo.get('seed',int(pinfo.get('variant',0))+1))
    seeds=sorted(sets[pset]);sd=seeds[(pseed-1)%len(seeds)];maps=sets[pset][sd]
    try:pm=paper_preview_maps(s,maps['normal'],maps.get('ambientocclusion'),2048 if full else 1024)
    except (OSError,RuntimeError,KeyError):return None
    return {'maps':pm,'strength':float(pinfo.get('strength',1.)),'tile':max(float(pinfo.get('tile',300.)),1.),'ao':float(pinfo.get('ao',.5)),'pseed':pseed,'nv':len(seeds)}


def paper_normal_ao(p,w,h,density,seed):
    """(OpenGL normal 0-1 RGB, shade multiplier) — build and preview use the same values."""
    N,A=p['maps'];yy,xx=np.mgrid[0:h,0:w].astype(np.float32)
    ps=int(p.get('pseed',1));k=((ps-1)//max(p.get('nv',1),1))%8   # Seed: pattern -> 8 rotations/flips -> position
    r_=np.random.default_rng(ps*7919+13).random(2)
    ox=(seed%997)*.0137+r_[0];oy=(seed%991)*.0173+r_[1]
    X=(xx+.5)/density/p['tile'];Y=(yy+.5)/density/p['tile']
    rot=k%4;flip=k>=4
    if flip:X=-X
    U,V=[(X,Y),(-Y,X),(-X,-Y),(Y,-X)][rot]
    u=U+ox;v=V+oy;st=p['strength']
    tx=(fx_sample(N[0],u,v)*2-1)*st;ty=-(fx_sample(N[1],u,v)*2-1)*st;nz=fx_sample(N[2],u,v)*2-1   # DirectX → OpenGL
    nx,ny=[(tx,ty),(ty,-tx),(-tx,-ty),(-ty,tx)][rot]   # Rotate the gradient direction back by the texture rotation
    if flip:nx=-nx
    ln=np.sqrt(nx*nx+ny*ny+nz*nz)+1e-6;nrm=np.stack([nx/ln,ny/ln,nz/ln],-1)
    ao=1-p['ao']*(1-fx_sample(A,u,v)) if A is not None else np.ones((h,w),np.float32)
    return nrm*.5+.5,ao.astype(np.float32)


def paper_choices(s):
    """[(texture, pattern #, button name)] — 'Crumple 1, 2…' if one texture, 'Paper1-1…' if several."""
    folder=paper_folder(s);sets=paper_sets(folder) if folder and os.path.isdir(folder) else {}
    out=[]
    for k in sorted(sets):
        num=int(re.sub(r'\D','',k) or 0) or (sorted(sets).index(k)+1)
        for v in range(len(sets[k])):out.append((k,v,'Crumple %d'%(v+1) if len(sets)==1 else 'Paper%d-%d'%(num,v+1)))
    return out


def paper_variant_index(s):
    folder=paper_folder(s);n=len(paper_sets(folder).get(s.paper_set,{})) if folder and os.path.isdir(folder) else 0
    return min(s.paper_variant,max(n-1,0))


PAPER_KEYS=('paper_auto','paper_set','paper_variant','paper_strength','paper_tile_mm','paper_ao')
PAPER_PRESETS=[('LIGHT','Light',dict(paper_strength=.6,paper_tile_mm=400.,paper_ao=.3,paper_variant=0)),
               ('MID','Medium',dict(paper_strength=1.,paper_tile_mm=300.,paper_ao=.5,paper_variant=1)),
               ('HEAVY','Heavy',dict(paper_strength=1.8,paper_tile_mm=200.,paper_ao=.75,paper_variant=2))]


def paper_preset_match(s):
    folder=paper_folder(s);nv=len(paper_sets(folder).get(s.paper_set,{})) if folder and os.path.isdir(folder) else 1
    for k,t,v in PAPER_PRESETS:
        if all(abs(getattr(s,a)-b)<1e-3 for a,b in v.items() if a!='paper_variant') and paper_variant_index(s)==min(v['paper_variant'],max(nv-1,0)):return k
    return 'CUSTOM'


def paper_label(s):
    if not s.paper_auto or not paper_choices(s):return ''
    k=paper_preset_match(s)
    return 'Paper Crumple · '+(dict((a,b) for a,b,_ in PAPER_PRESETS).get(k) or 'Custom (pattern %d)'%(paper_variant_index(s)+1))


def paper_shade(px,p,density,i):
    """Editor preview: lit by the normal + shading. (On build, shading goes into color and the normal into a normal map)"""
    h,w=px.shape[:2];nrm,ao=paper_normal_ao(p,w,h,density,i);n=nrm*2-1
    L=np.array([-.4,.5,.77],np.float32);L/=np.linalg.norm(L)
    shade=np.clip((n[...,0]*L[0]+n[...,1]*L[1]+n[...,2]*L[2])/L[2],0,1.5)*ao
    out=px.copy();out[:,:,:3]=np.clip(np.clip(px[:,:,:3],0,1)**2.2*shade[...,None],0,1)**(1/2.2)
    return out


def fx_resources(s):
    folder=paper_folder(s)
    key=(folder,tuple(os.path.getmtime(os.path.join(PAPER_SCAN_DIR,fn)) if os.path.isfile(os.path.join(PAPER_SCAN_DIR,fn)) else 0 for fn,_,_ in PAPER_SCANS.values()))
    if _FX_RES.get('key')==key:return _FX_RES
    _FX_RES.clear();_FX_RES['key']=key
    _FX_RES['hole']=hole_noise_cached()
    _FX_RES['scans']=load_paper_scans()   # main thread (image loading); effects then run in worker threads
    try:
        edges=edge_sets(folder) if folder else {}
        if edges:
            name='Paper_Edge' if 'Paper_Edge' in edges else sorted(edges)[0]
            maps=edges[name][sorted(edges[name])[0]]
            _FX_RES['edge_mask']=_fx_load_gray(maps['mask'])
            if 'height' in maps:_FX_RES['edge_height']=_fx_load_gray(maps['height'])
    except (OSError,RuntimeError,KeyError):pass
    return _FX_RES


def srgb_from_linear(c):
    return tuple(12.92*v if v<=.0031308 else 1.055*v**(1/2.4)-.055 for v in c)


def linear_from_srgb(c):
    return tuple(v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in c)


def layout_pixels(data,crop,turn,out_w,out_h,background):
    """Same order as building: crop -> background composite -> layout rotation -> size fit."""
    ih,iw=data.shape[:2];ca,cb,cc,cd=crop
    cx0=max(0,min(iw-1,round(ca*iw)));cy0=max(0,min(ih-1,round(cb*ih)))
    cx1=max(cx0+1,min(iw,round(cc*iw)));cy1=max(cy0+1,min(ih,round(cd*ih)))
    d=data[cy0:cy1,cx0:cx1].copy()
    if background!='TRANSPARENT':
        bg=np.array((1.,1.,1.) if background=='WHITE' else (0.,0.,0.),np.float32)
        d[:,:,:3]=d[:,:,:3]*d[:,:,3:4]+bg*(1-d[:,:,3:4]);d[:,:,3]=1
    d=np.ascontiguousarray(np.rot90(d,turn,axes=(0,1)))
    return resize(d,out_w,out_h)


def user_paper_folder(s):
    """User-specified extra texture folder ('' if unset or missing)."""
    if not s.paper_dir.strip():return ''
    p=os.path.abspath(bpy.path.abspath(s.paper_dir))
    return p if os.path.isdir(p) else ''


def paper_folder(s):
    """The extra folder if set, otherwise the addon's built-in texture folder."""
    return user_paper_folder(s) or (BUILTIN_PAPER_DIR if os.path.isdir(BUILTIN_PAPER_DIR) else '')


def _is_builtin(folder):
    return bool(folder) and os.path.normcase(os.path.abspath(folder))==os.path.normcase(BUILTIN_PAPER_DIR)


def _scan_paper_sets(folder):
    try:stamp=max([os.path.getmtime(os.path.join(r,d)) for r,ds,_ in os.walk(folder) for d in ds]+[os.path.getmtime(folder)])
    except OSError:return {}
    key=(folder,stamp)
    if _PAPER_CACHE['key']==key:return _PAPER_CACHE['sets']
    sets={}
    for root,_,files in os.walk(folder):
        for f in files:
            m=PAPER_FILE_RE.match(f)
            if m:sets.setdefault(m.group(1),{}).setdefault(int(m.group(2)),{})[m.group(3).lower()]=os.path.join(root,f)
    sets={k:{seed:maps for seed,maps in v.items() if 'normal' in maps} for k,v in sets.items()}
    sets={k:v for k,v in sets.items() if v}
    _PAPER_CACHE.update(key=key,sets=sets)
    return sets


_BUILTIN_SETS=None


def builtin_paper_sets():
    global _BUILTIN_SETS
    if _BUILTIN_SETS is None:
        sets={}
        if os.path.isdir(BUILTIN_PAPER_DIR):
            for root,_,files in os.walk(BUILTIN_PAPER_DIR):
                for f in files:
                    m=PAPER_FILE_RE.match(f)
                    if m:sets.setdefault(m.group(1),{}).setdefault(int(m.group(2)),{})[m.group(3).lower()]=os.path.join(root,f)
        sets={k:{seed:maps for seed,maps in v.items() if 'normal' in maps} for k,v in sets.items()}
        _BUILTIN_SETS={k:v for k,v in sets.items() if v}
    return _BUILTIN_SETS


def paper_sets(folder):
    """Built-in textures + extra folder textures (extra folder wins on name clash)."""
    base=builtin_paper_sets()
    if not folder or _is_builtin(folder):return base
    merged=dict(base);merged.update(_scan_paper_sets(folder))
    return merged


def paper_set_items(self,context):
    _PAPER_ITEMS.clear()
    folder=paper_folder(self)
    sets=paper_sets(folder) if folder and os.path.isdir(folder) else {}
    for name in sorted(sets):_PAPER_ITEMS.append((name,name,'%d variants'%len(sets[name])))
    if not _PAPER_ITEMS:_PAPER_ITEMS.append(('NONE','No paper texture','No baked textures in the folder.'))
    return _PAPER_ITEMS


def paper_image(path):
    path=os.path.abspath(path)
    for im in bpy.data.images:
        if im.filepath and os.path.normcase(os.path.abspath(bpy.path.abspath(im.filepath)))==os.path.normcase(path):return im
    im=bpy.data.images.load(path,check_existing=True);im.colorspace_settings.name='Non-Color'
    return im


def mix_in(node,name):
    return next(x for x in node.inputs if x.name==name and x.enabled)


def mix_out(node):
    return next(x for x in node.outputs if x.enabled)


PAPER_INPUTS=[('Color','NodeSocketColor',(1,1,1,1)),('Strength','NodeSocketFloat',1.),('Tile Size mm','NodeSocketFloat',300.),
    ('Crumple Shading','NodeSocketFloat',.5),('Roughness','NodeSocketFloat',.85),
    ('Fade','NodeSocketFloat',0.),('Yellowing','NodeSocketFloat',0.),('Saturation','NodeSocketFloat',1.),('Tint','NodeSocketFloat',0.),('Color Random','NodeSocketFloat',0.),
    ('Wear','NodeSocketFloat',0.),('Edge Width mm','NodeSocketFloat',15.),('Crease Wear','NodeSocketFloat',.5),('Wear Random','NodeSocketFloat',0.),
    ('Paper Color Strength','NodeSocketFloat',0.),('Palette Count','NodeSocketFloat',1.)]+[('Palette %d'%(i+1),'NodeSocketColor',(1,1,1,1)) for i in range(6)]+[
    ('Ink Color Strength','NodeSocketFloat',0.),('Ink Palette Count','NodeSocketFloat',1.)]+[('Ink %d'%(i+1),'NodeSocketColor',(0,0,0,1)) for i in range(6)]+[
    ('Alpha','NodeSocketFloat',1.),('Worn Edges','NodeSocketFloat',0.),('Edge Depth mm','NodeSocketFloat',3.),('Corner Focus','NodeSocketFloat',.6),
    ('Edge Wear Random','NodeSocketFloat',.5),('Fiber Rim','NodeSocketFloat',.7),('Fiber Length mm','NodeSocketFloat',1.2),
    ('Hole Amount','NodeSocketFloat',0.),('Hole White Rim','NodeSocketFloat',.03),('Hole Size mm','NodeSocketFloat',400.),('Hole Random','NodeSocketFloat',.6),('Print Peel','NodeSocketFloat',0.),('Edge Softness','NodeSocketFloat',.004)]
PAPER_OUTPUTS=[('Color','NodeSocketColor'),('Normal','NodeSocketVector'),('Roughness','NodeSocketFloat'),('Alpha','NodeSocketFloat')]
PAPER_PROP_INPUTS=[('Fade','color_fade'),('Yellowing','color_yellow'),('Saturation','color_saturation'),('Tint','color_hue'),('Color Random','color_random'),
    ('Wear','wear_amount'),('Edge Width mm','wear_edge_mm'),('Crease Wear','wear_crease'),('Wear Random','wear_random'),
    ('Worn Edges','fray_amount'),('Edge Depth mm','fray_depth_mm'),('Corner Focus','fray_corner'),('Edge Wear Random','fray_random'),('Fiber Rim','fray_fiber'),('Fiber Length mm','fray_fiber_mm'),
    ('Hole Amount','hole_amount'),('Hole White Rim','hole_rim'),('Hole Size mm','hole_size_mm'),('Hole Random','hole_random'),('Print Peel','peel_amount'),('Edge Softness','hole_soft')]
PAPER_WHITE=(.86,.84,.79,1.)   # Paper color revealed where the print peels
PAPER_YELLOW=(1.,.86,.6,1.)
PAPER_GRIME=(.7,.66,.58,1.)     # Edge grime
PAPER_FIBER=(.93,.92,.88,1.)    # White fibers at torn or worn cross-sections
TINT_ATTR='poster_tint';TINT_ON_ATTR='poster_tint_on'
INK_ATTR='poster_ink';INK_ON_ATTR='poster_ink_on'
def srgb(r,g,b):
    f=lambda c:c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4
    return (f(r/255),f(g/255),f(b/255))
PAPER_PALETTE_PRESETS={
    'POSTIT':('Sticky Note 4 Colors',[srgb(255,238,110),srgb(255,182,206),srgb(170,218,255),srgb(186,240,190)]),
    'NEON':('Neon Flyer',[srgb(255,250,90),srgb(255,120,190),srgb(120,255,160),srgb(255,170,60)]),
    'KRAFT':('Kraft·Recycled',[srgb(214,188,148),srgb(232,222,200),srgb(196,180,160)]),
    'PASTEL':('Pastel Print',[srgb(252,230,214),srgb(222,236,250),srgb(236,226,250),srgb(230,248,226)])}
INK_PALETTE_PRESETS={
    'PEN':('Ballpoint·Marker',[srgb(25,45,140),srgb(20,20,22),srgb(190,30,35)]),
    'STAMP':('Stamp·Seal',[srgb(200,35,40),srgb(40,70,170),srgb(110,40,120)]),
    'OLDPRINT':('Old Print',[srgb(60,45,35),srgb(35,40,60),srgb(70,30,30)]),
    'RISO':('Riso Print',[srgb(255,72,176),srgb(0,120,191),srgb(0,169,92),srgb(255,102,94)])}    # Yellow tinge of old paper


def paper_interface(g):
    want={(n,'INPUT') for n,*_ in PAPER_INPUTS}|{(n,'OUTPUT') for n,*_ in PAPER_OUTPUTS}
    for i in [i for i in g.interface.items_tree if i.item_type=='SOCKET' and (i.name,i.in_out) not in want]:g.interface.remove(i)   # sockets left from older versions
    have={(i.name,i.in_out) for i in g.interface.items_tree if i.item_type=='SOCKET'}
    for name,kind,default in PAPER_INPUTS:
        if (name,'INPUT') not in have:
            it=g.interface.new_socket(name=name,in_out='INPUT',socket_type=kind);it.default_value=default
    for name,kind in PAPER_OUTPUTS:
        if (name,'OUTPUT') not in have:g.interface.new_socket(name=name,in_out='OUTPUT',socket_type=kind)


def paper_group(set_name,seed,maps,edge_maps=None,hole_path=None):
    name='PST_Paper · %s · s%d'%(set_name,seed)
    g=bpy.data.node_groups.get(name) or bpy.data.node_groups.new(name,'ShaderNodeTree')
    paper_interface(g)
    nt=g;nt.nodes.clear();L=nt.links.new
    def n(kind,x,y,label=None,**kw):
        node=nt.nodes.new(kind);node.location=(x,y)
        if label:node.label=label
        for k,v in kw.items():setattr(node,k,v)
        return node
    def put(sock,v):
        if isinstance(v,bpy.types.NodeSocket):L(v,sock)
        elif v is not None:sock.default_value=v
    def M(op,a,b=None,c=None,x=0,y=0,clamp=False,label=None):
        node=n('ShaderNodeMath',x,y,label,operation=op,use_clamp=clamp)
        put(node.inputs[0],a);put(node.inputs[1],b);put(node.inputs[2],c)
        return node.outputs[0]
    def mix(a,b,f,x,y,label=None,blend='MIX'):
        node=n('ShaderNodeMix',x,y,label,data_type='RGBA',blend_type=blend,clamp_factor=True)
        put(mix_in(node,'Factor'),f);put(mix_in(node,'A'),a);put(mix_in(node,'B'),b)
        return mix_out(node)
    def tex(path,uvsock,x,y,label):
        node=n('ShaderNodeTexImage',x,y,label);node.image=paper_image(path);node.extension='REPEAT';L(uvsock,node.inputs['Vector'])
        return node.outputs['Color']
    def uvmap(layer,x,y,label):
        node=n('ShaderNodeUVMap',x,y,label);node.uv_map=layer;return node.outputs['UV']
    def sep(vec,x,y):
        node=n('ShaderNodeSeparateXYZ',x,y);L(vec,node.inputs[0]);return node.outputs[0],node.outputs[1]
    gi=n('NodeGroupInput',-2200,0);go=n('NodeGroupOutput',1400,0);I=gi.outputs
    # --- Coords: real-size (mm) tile + per-poster offset
    rnd=n('ShaderNodeObjectInfo',-2200,-700,'Per-Poster Random').outputs['Random']
    rnd2=M('FRACT',M('MULTIPLY',rnd,7.13,x=-2000,y=-800),x=-1850,y=-800,label='Second Random')
    per_mm=M('DIVIDE',1000.,I['Tile Size mm'],x=-2000,y=-150,label='1000 / Tile Size')
    off=n('ShaderNodeCombineXYZ',-1850,-500,'Position Offset')
    L(M('MULTIPLY',rnd,37.17,x=-2000,y=-450),off.inputs['X']);L(M('MULTIPLY',rnd,91.73,x=-2000,y=-550),off.inputs['Y'])
    paper=uvmap(PAPER_UV,-2200,300,'Real-size Coords (m)')
    sc=n('ShaderNodeVectorMath',-1850,300,'mm-based Tile',operation='SCALE');L(paper,sc.inputs[0]);L(per_mm,sc.inputs['Scale'])
    tuv=n('ShaderNodeVectorMath',-1650,300,operation='ADD');L(sc.outputs['Vector'],tuv.inputs[0]);L(off.outputs['Vector'],tuv.inputs[1]);tuv=tuv.outputs['Vector']
    # Large pattern for wear blotches: read the same height map at 0.37× from another position (reproducible in Unreal with the same texture)
    wuv=n('ShaderNodeVectorMath',-1650,0,'Blotch Coords',operation='MULTIPLY_ADD')
    L(tuv,wuv.inputs[0]);wuv.inputs[1].default_value=(.37,.37,.37);wuv.inputs[2].default_value=(.29,.61,0);wuv=wuv.outputs['Vector']
    # --- Crumple normal (DirectX -> OpenGL)
    nc=tex(maps['normal'],tuv,-1400,500,'Crumple Normal (DirectX)')
    sp=n('ShaderNodeSeparateColor',-1150,500);L(nc,sp.inputs['Color'])
    cb=n('ShaderNodeCombineColor',-900,500);L(sp.outputs[0],cb.inputs[0]);L(M('SUBTRACT',1.,sp.outputs[1],x=-1050,y=420,label='Invert G'),cb.inputs[1]);L(sp.outputs[2],cb.inputs[2])
    nm=n('ShaderNodeNormalMap',-700,500);L(cb.outputs['Color'],nm.inputs['Color']);L(I['Strength'],nm.inputs['Strength']);L(nm.outputs['Normal'],go.inputs['Normal'])
    # --- Crumple shading (AO)
    ao=tex(maps['ambientocclusion'],tuv,-1400,200,'Crumple AO') if 'ambientocclusion' in maps else 1.
    if not isinstance(ao,float):
        aos=n('ShaderNodeSeparateColor',-1150,200);L(ao,aos.inputs['Color']);ao=aos.outputs[0]
    shade_amt=M('MULTIPLY',I['Crumple Shading'],I['Strength'],x=-1150,y=100,clamp=True,label='Shading Amount')
    shade=M('SUBTRACT',1.,M('MULTIPLY',M('SUBTRACT',1.,ao,x=-1000,y=200),shade_amt,x=-850,y=200),x=-700,y=200,label='Shading (1=bright)')
    crease=M('SUBTRACT',1.,ao,x=-1000,y=50,label='Folded Creases')
    # --- Wear mask
    if 'height' in maps:
        hc=tex(maps['height'],wuv,-1400,-150,'Blotch Pattern (height map)');hs=n('ShaderNodeSeparateColor',-1150,-150);L(hc,hs.inputs['Color'])
        blot=M('MULTIPLY',M('SUBTRACT',hs.outputs[0],.33,x=-1000,y=-150),3.,x=-850,y=-150,clamp=True,label='Blotch 0-1')
    else:blot=.5
    pu=uvmap(POSTER_UV,-2200,-250,'Poster 0-1');ps=uvmap(POSTER_SIZE_UV,-2200,-350,'Poster Size (m)')
    u,v=sep(pu,-2000,-250);w,h=sep(ps,-2000,-350)
    dx=M('MULTIPLY',M('MINIMUM',u,M('SUBTRACT',1.,u,x=-1850,y=-200),x=-1700,y=-200),w,x=-1550,y=-220)
    dy=M('MULTIPLY',M('MINIMUM',v,M('SUBTRACT',1.,v,x=-1850,y=-300),x=-1700,y=-300),h,x=-1550,y=-300)
    edge_mm=M('MULTIPLY',M('MINIMUM',dx,dy,x=-1400,y=-260),1000.,x=-1250,y=-260,label='mm to Edge')
    edge=M('SUBTRACT',1.,M('DIVIDE',edge_mm,M('MAXIMUM',I['Edge Width mm'],.1,x=-1250,y=-380),x=-1100,y=-300,clamp=True),x=-950,y=-300,label='Edge 1')
    edge=M('MULTIPLY',edge,M('MULTIPLY_ADD',blot,1.2,.2,x=-950,y=-400),x=-800,y=-320,clamp=True,label='Ragged Edge')
    crease_w=M('MULTIPLY',M('MULTIPLY',crease,6.,x=-850,y=0),I['Crease Wear'],x=-700,y=0,clamp=True,label='Crease Wear')
    wear_amt=M('MULTIPLY',I['Wear'],M('MULTIPLY_ADD',M('SUBTRACT',rnd2,.5,x=-1700,y=-700),M('MULTIPLY',I['Wear Random'],2.,x=-1700,y=-800),1.,x=-1550,y=-750),x=-1400,y=-700,clamp=True,label='Per-Poster Wear Amount')
    patch=M('MULTIPLY',M('SUBTRACT',blot,M('SUBTRACT',1.,M('MULTIPLY',wear_amt,.55,x=-1250,y=-600),x=-1100,y=-600),x=-950,y=-550),4.,x=-800,y=-550,clamp=True,label='Blotch Peel')
    raw=M('ADD',M('ADD',edge,crease_w,x=-650,y=-150),patch,x=-500,y=-300)
    wear=M('MULTIPLY',raw,M('MULTIPLY',wear_amt,1.6,x=-650,y=-650),x=-350,y=-350,clamp=True,label='Wear Mask')
    # --- Color
    col_rand=M('MULTIPLY_ADD',M('SUBTRACT',rnd,.5,x=-1550,y=-950),M('MULTIPLY',I['Color Random'],2.,x=-1550,y=-1050),1.,x=-1400,y=-1000,label='Per-Poster Color Variation')
    fade=M('MULTIPLY',I['Fade'],col_rand,x=-1250,y=-950,clamp=True)
    yel=M('MULTIPLY',I['Yellowing'],M('MULTIPLY_ADD',M('SUBTRACT',rnd2,.5,x=-1400,y=-1150),M('MULTIPLY',I['Color Random'],2.,x=-1400,y=-1250),1.,x=-1250,y=-1150),x=-1100,y=-1100,clamp=True)
    hsv=n('ShaderNodeHueSaturation',-500,250,'Hue · Saturation');L(I['Color'],hsv.inputs['Color'])
    L(M('ADD',I['Tint'],.5,x=-650,y=350),hsv.inputs['Hue']);L(I['Saturation'],hsv.inputs['Saturation'])
    def pick_color(prefix,count,mult,attr_name,on_name,y):
        r=M('FRACT',M('MULTIPLY',rnd,mult,x=-1700,y=y),x=-1550,y=y)
        idx=M('FLOOR',M('MULTIPLY',r,M('MAXIMUM',I[count],1.,x=-1550,y=y-100),x=-1400,y=y-50),x=-1250,y=y-50)
        col=I[prefix+'1']
        for i in range(2,7):
            col=mix(col,I[prefix+str(i)],M('GREATER_THAN',idx,i-1.5,x=-1100,y=y-i*60),-950,y-i*60,prefix+str(i))
        attr=n('ShaderNodeAttribute',-1100,y-450,'Per-Poster Override',attribute_type='GEOMETRY',attribute_name=attr_name)
        on=n('ShaderNodeAttribute',-1100,y-600,'Override On',attribute_type='GEOMETRY',attribute_name=on_name)
        return mix(col,attr.outputs['Color'],on.outputs['Fac'],-750,y-350,'Override Color Wins'),on.outputs['Fac']
    # Ink color: screen, so black becomes ink color and white stays white
    ink,ink_on=pick_color('Ink ','Ink Palette Count',29.71,INK_ATTR,INK_ON_ATTR,-2200)
    ink_amt=M('MAXIMUM',I['Ink Color Strength'],ink_on,x=-750,y=-2550,clamp=True)
    c=mix(hsv.outputs['Color'],ink,ink_amt,-550,250,'Ink Color',blend='SCREEN')
    # Paper color: multiply, so black ink stays and only white paper changes color
    tint,tint_on=pick_color('Palette ','Palette Count',13.37,TINT_ATTR,TINT_ON_ATTR,-1350)
    tint_amt=M('MAXIMUM',I['Paper Color Strength'],tint_on,x=-750,y=-1850,clamp=True)
    c=mix(c,tint,tint_amt,-400,250,'Paper Color',blend='MULTIPLY')
    c=mix(c,PAPER_WHITE,M('MULTIPLY',fade,.75,x=-400,y=-950),-250,250,'Fade')
    # Faded print lightens dark ink more: lowers contrast
    c=mix(c,PAPER_YELLOW,yel,-50,250,'Yellowing',blend='MULTIPLY')
    c=mix(c,PAPER_WHITE,wear,150,250,'Wear (print peel)')
    # Edges touched by hands lose print and pick up grime at the same time
    grime=M('MULTIPLY',M('MULTIPLY',edge,wear_amt,x=0,y=-450),.55,x=150,y=-450,clamp=True,label='Edge Grime')
    c=mix(c,PAPER_GRIME,grime,250,100,'Edge Grime',blend='MULTIPLY')
    shd=n('ShaderNodeCombineColor',200,100);L(shade,shd.inputs[0]);L(shade,shd.inputs[1]);L(shade,shd.inputs[2])
    c=mix(c,shd.outputs['Color'],1.,350,250,'Crumple Shading',blend='MULTIPLY')
    # --- Worn edges: attach Substance Paper_Edge (tear mask + height) to each of the four sides (in mm)
    fray_amt=M('MULTIPLY',I['Worn Edges'],M('MULTIPLY_ADD',M('SUBTRACT',M('FRACT',M('MULTIPLY',rnd,53.1,x=-1700,y=-3400),x=-1550,y=-3400),.5,x=-1400,y=-3400),
               M('MULTIPLY',I['Edge Wear Random'],2.,x=-1400,y=-3500),1.,x=-1250,y=-3450),x=-1100,y=-3450,clamp=True,label='Per-Poster Edge Wear')
    on=M('MULTIPLY',fray_amt,20.,x=-1100,y=-3600,clamp=True,label='On')
    cx=M('MULTIPLY',dx,1000.,x=-1250,y=-3700);cy=M('MULTIPLY',dy,1000.,x=-1250,y=-3800)
    cdist=M('SQRT',M('ADD',M('MULTIPLY',cx,cx,x=-1100,y=-3700),M('MULTIPLY',cy,cy,x=-1100,y=-3800),x=-950,y=-3750),x=-800,y=-3750,label='mm to Corner')
    depth=M('MAXIMUM',M('MULTIPLY',I['Edge Depth mm'],fray_amt,x=-950,y=-3500),.01,x=-800,y=-3500,label='Tear Depth mm')
    corner=M('SUBTRACT',1.,M('DIVIDE',cdist,M('MULTIPLY_ADD',depth,6.,8.,x=-650,y=-3850),x=-500,y=-3800,clamp=True),x=-350,y=-3800,label='Corner 1')
    extra=M('MULTIPLY',M('MULTIPLY',corner,I['Corner Focus'],x=-200,y=-3800),M('MULTIPLY',depth,1.5,x=-200,y=-3900),x=-50,y=-3850,label='Corner Extra mm')
    period=M('DIVIDE',depth,EDGE_AMPLITUDE,x=-650,y=-3500,label='Texture Sheet mm')
    alpha_e=1.;rim_e=0.
    if edge_maps:
        def side(dist_mm,along_m,size_m,shift,y):
            # dist_mm: distance to this edge, along: position along the edge (m) -> texture coords
            vv=M('SUBTRACT',EDGE_BAND[0]+.005,M('DIVIDE',M('SUBTRACT',dist_mm,extra,x=-500,y=y),period,x=-350,y=y),x=-200,y=y)
            uu=M('ADD',M('DIVIDE',M('MULTIPLY',along_m,1000.,x=-500,y=y-100),period,x=-350,y=y-100),M('MULTIPLY_ADD',rnd,7.31,shift,x=-350,y=y-200),x=-200,y=y-100)
            vec=n('ShaderNodeCombineXYZ',-50,y);L(uu,vec.inputs['X']);L(M('MAXIMUM',vv,.001,x=-50,y=y-150),vec.inputs['Y'])
            mt=n('ShaderNodeTexImage',100,y,'Tear Line Mask');mt.image=paper_image(edge_maps['mask']);mt.extension='REPEAT';L(vec.outputs['Vector'],mt.inputs['Vector'])
            ms=n('ShaderNodeSeparateColor',300,y);L(mt.outputs['Color'],ms.inputs['Color'])
            if 'height' in edge_maps:
                ht=n('ShaderNodeTexImage',100,y-300,'Torn Layer Height');ht.image=paper_image(edge_maps['height']);ht.extension='REPEAT';L(vec.outputs['Vector'],ht.inputs['Vector'])
                hs=n('ShaderNodeSeparateColor',300,y-300);L(ht.outputs['Color'],hs.inputs['Color'])
                rim=M('MULTIPLY',ms.outputs[0],M('SUBTRACT',1.,hs.outputs[0],x=450,y=y-300),x=600,y=y-250)
            else:rim=0.
            return ms.outputs[0],rim
        # Read left/right/bottom/top edges at different positions so each tear differs
        sl,rl=side(M('MULTIPLY',M('MULTIPLY',u,w,x=-800,y=-4000),1000.,x=-650,y=-4000),M('MULTIPLY',v,h,x=-800,y=-4100),h,.11,-4000)
        sr,rr=side(M('MULTIPLY',M('MULTIPLY',M('SUBTRACT',1.,u,x=-950,y=-4600),w,x=-800,y=-4600),1000.,x=-650,y=-4600),M('MULTIPLY',v,h,x=-800,y=-4700),h,.43,-4600)
        sb,rb=side(M('MULTIPLY',M('MULTIPLY',v,h,x=-800,y=-5200),1000.,x=-650,y=-5200),M('MULTIPLY',u,w,x=-800,y=-5300),w,.67,-5200)
        st,rt=side(M('MULTIPLY',M('MULTIPLY',M('SUBTRACT',1.,v,x=-950,y=-5800),h,x=-800,y=-5800),1000.,x=-650,y=-5800),M('MULTIPLY',u,w,x=-800,y=-5900),w,.89,-5800)
        alpha_e=M('MINIMUM',M('MINIMUM',sl,sr,x=750,y=-4300),M('MINIMUM',sb,st,x=750,y=-5500),x=900,y=-4900,label='Torn Silhouette')
        rim_e=M('MAXIMUM',M('MAXIMUM',rl,rr,x=750,y=-4400),M('MAXIMUM',rb,rt,x=750,y=-5600),x=900,y=-5000,label='Torn Layer')
    keep=M('ADD',M('MULTIPLY',alpha_e,on,x=1050,y=-4900),M('SUBTRACT',1.,on,x=1050,y=-5050),x=1200,y=-4950,label='Remaining Paper')
    # --- Holes: split one noise with two thresholds into 'punched' and the surrounding 'white paper' (reference video method)
    hole=0.;hole_white=0.
    if hole_path:
        hs_=M('DIVIDE',1000.,M('MAXIMUM',I['Hole Size mm'],1.,x=-950,y=-6300),x=-800,y=-6300,label='1000 / Hole Size')
        hv=n('ShaderNodeVectorMath',-650,-6200,'Hole Coords',operation='SCALE');L(paper,hv.inputs[0]);L(hs_,hv.inputs['Scale'])
        ho=n('ShaderNodeCombineXYZ',-650,-6400);L(M('MULTIPLY',rnd,53.7,x=-800,y=-6450),ho.inputs['X']);L(M('MULTIPLY',rnd,29.3,x=-800,y=-6550),ho.inputs['Y'])
        hadd=n('ShaderNodeVectorMath',-500,-6250,operation='ADD');L(hv.outputs['Vector'],hadd.inputs[0]);L(ho.outputs['Vector'],hadd.inputs[1])
        htex=n('ShaderNodeTexImage',-350,-6250,'Hole Noise');htex.image=paper_image(hole_path);htex.extension='REPEAT';L(hadd.outputs['Vector'],htex.inputs['Vector'])
        hsep=n('ShaderNodeSeparateColor',-150,-6250);L(htex.outputs['Color'],hsep.inputs['Color'])
        rnd5=M('FRACT',M('MULTIPLY',rnd,71.9,x=-800,y=-6700),x=-650,y=-6700)
        var=M('MULTIPLY_ADD',M('SUBTRACT',rnd5,.5,x=-500,y=-6700),M('MULTIPLY',I['Hole Random'],2.,x=-500,y=-6800),1.,x=-350,y=-6750,label='Per-Poster Scale')
        amt=M('MULTIPLY',I['Hole Amount'],var,x=-200,y=-6700,clamp=True,label='Per-Poster Hole Amount')
        peel=M('MULTIPLY',I['Print Peel'],var,x=-200,y=-6900,clamp=True,label='Per-Poster Peel Amount')
        soft=M('MAXIMUM',I['Edge Softness'],.002,x=-200,y=-7000,label='Border Width')
        thr=M('SUBTRACT',1.,M('MULTIPLY',amt,.5,x=-50,y=-6700),x=100,y=-6700,label='Threshold (above = hole)')
        hole=M('DIVIDE',M('SUBTRACT',hsep.outputs[0],thr,x=250,y=-6300),soft,x=400,y=-6300,clamp=True,label='Punched Area')
        hole_white=M('MULTIPLY',M('DIVIDE',M('SUBTRACT',hsep.outputs[0],M('SUBTRACT',thr,I['Hole White Rim'],x=250,y=-6500),x=400,y=-6450),soft,x=550,y=-6450,clamp=True),
                     M('MULTIPLY',amt,50.,x=550,y=-6600,clamp=True),x=700,y=-6500,label='White Paper Around Holes')
        # Print peel: lower threshold of the same noise -> wide white paper area around holes (Color Ramp B in the video)
        pthr=M('SUBTRACT',1.,M('MULTIPLY',peel,.6,x=-50,y=-6900),x=100,y=-6900,label='Peel Threshold')
        peel_w=M('MULTIPLY',M('DIVIDE',M('SUBTRACT',hsep.outputs[0],pthr,x=250,y=-6800),soft,x=400,y=-6800,clamp=True),M('MULTIPLY',peel,50.,x=400,y=-6950,clamp=True),x=550,y=-6850,label='White Paper Under Peeled Print')
        hole_white=M('MAXIMUM',hole_white,peel_w,x=850,y=-6600)
        keep=M('MULTIPLY',keep,M('SUBTRACT',1.,hole,x=850,y=-6300),x=1000,y=-6000,label='Remaining Paper (incl. holes)')
    L(M('MULTIPLY',I['Alpha'],keep,x=1350,y=-4900),go.inputs['Alpha'])
    whiten=M('MULTIPLY',M('MULTIPLY',rim_e,I['Fiber Rim'],x=1050,y=-5200),on,x=1200,y=-5200,clamp=True,label='Torn Layer Is White Paper')
    whiten=M('MAXIMUM',whiten,hole_white,x=1350,y=-5200)
    c=mix(c,PAPER_FIBER,whiten,550,250,'Torn Layer')
    L(c,go.inputs['Color'])
    rough=M('MULTIPLY_ADD',crease,.3,I['Roughness'],x=600,y=-150,clamp=True)
    rough=M('MULTIPLY_ADD',wear,.12,rough,x=800,y=-150,clamp=True,label='Peeled Areas Rougher')
    L(rough,go.inputs['Roughness'])
    g['poster_paper_set']=set_name;g['poster_paper_seed']=seed
    return g


def ensure_paper_uv(mesh,scale=1.):
    want=[l for l in (PAPER_UV,POSTER_UV,POSTER_SIZE_UV) if l not in mesh.uv_layers]
    if not want:return False
    render=next((l for l in mesh.uv_layers if l.active_render),None);active=mesh.uv_layers.active
    xs=[v.co.x for v in mesh.vertices] or [0.];ys=[v.co.y for v in mesh.vertices] or [0.]
    x0,x1,y0,y1=min(xs),max(xs),min(ys),max(ys);wx,wy=max(x1-x0,1e-9),max(y1-y0,1e-9)
    for name in want:
        layer=mesh.uv_layers.new(name=name)
        if layer is None:continue
        for loop in mesh.loops:
            co=mesh.vertices[loop.vertex_index].co
            layer.data[loop.index].uv=((co.x*scale,co.y*scale) if name==PAPER_UV else
                                       ((co.x-x0)/wx,(co.y-y0)/wy) if name==POSTER_UV else (wx*scale,wy*scale))
    if render:render.active_render=True
    if active:mesh.uv_layers.active=active
    return True


def poster_material(mat):
    if not mat or not mat.use_nodes:return None,None
    tex=next((x for x in mat.node_tree.nodes if x.type=='TEX_IMAGE' and x.label in ('Poster Atlas Texture','포스터 묶음')),None)
    bs=next((x for x in mat.node_tree.nodes if x.type=='BSDF_PRINCIPLED'),None)
    return (tex,bs) if tex and bs else (None,None)


def apply_paper(mat,group,s):
    tex,bs=poster_material(mat)
    if tex is None:return False
    nt=mat.node_tree
    node=next((x for x in nt.nodes if x.type=='GROUP' and x.label in PAPER_NODE_LABELS),None)
    if node is None:
        node=nt.nodes.new('ShaderNodeGroup');node.label=PAPER_NODE_LABEL;node.location=(tex.location.x+250,tex.location.y-260)
    node.node_tree=group
    node.inputs['Strength'].default_value=s.paper_strength
    node.inputs['Tile Size mm'].default_value=s.paper_tile_mm
    node.inputs['Crumple Shading'].default_value=s.paper_ao
    for key,prop in PAPER_PROP_INPUTS:node.inputs[key].default_value=getattr(s,prop)
    cols=[tuple(s.tint_color)] if s.tint_mode=='SINGLE' else [tuple(c.color) for c in s.palette if c.use][:6]
    if not cols:cols=[(1.,1.,1.)]
    node.inputs['Paper Color Strength'].default_value=0. if s.tint_mode=='OFF' else s.tint_strength
    node.inputs['Palette Count'].default_value=len(cols)
    for i in range(6):node.inputs['Palette %d'%(i+1)].default_value=(*cols[min(i,len(cols)-1)],1.)
    inks=[tuple(s.ink_color)] if s.ink_mode=='SINGLE' else [tuple(c.color) for c in s.ink_palette if c.use][:6]
    if not inks:inks=[(0.,0.,0.)]
    node.inputs['Ink Color Strength'].default_value=0. if s.ink_mode=='OFF' else s.ink_strength
    node.inputs['Ink Palette Count'].default_value=len(inks)
    for i in range(6):node.inputs['Ink %d'%(i+1)].default_value=(*inks[min(i,len(inks)-1)],1.)
    node.inputs['Roughness'].default_value=bs.inputs['Roughness'].default_value if not bs.inputs['Roughness'].is_linked else .85
    nt.links.new(tex.outputs['Color'],node.inputs['Color'])
    nt.links.new(node.outputs['Color'],bs.inputs['Base Color'])
    nt.links.new(node.outputs['Normal'],bs.inputs['Normal'])
    nt.links.new(node.outputs['Roughness'],bs.inputs['Roughness'])
    fin=finish_roughness_socket(mat)
    if fin is not None:nt.links.new(fin,node.inputs['Roughness'])   # crumple adds onto the photo / paper roughness map
    nt.links.new(tex.outputs['Alpha'],node.inputs['Alpha'])
    nt.links.new(node.outputs['Alpha'],bs.inputs['Alpha'])
    mat['poster_paper']=json.dumps({'set':group['poster_paper_set'],'seed':group['poster_paper_seed'],'strength':s.paper_strength,'tile_mm':s.paper_tile_mm,'ao':s.paper_ao,**{p:getattr(s,p) for _,p in PAPER_PROP_INPUTS}})
    return True


def remove_paper(mat):
    tex,bs=poster_material(mat)
    if tex is None:return False
    nt=mat.node_tree;found=False
    for node in [x for x in nt.nodes if x.type=='GROUP' and x.label in PAPER_NODE_LABELS]:
        nt.nodes.remove(node);found=True
    nt.links.new(tex.outputs['Color'],bs.inputs['Base Color'])
    nt.links.new(tex.outputs['Alpha'],bs.inputs['Alpha'])
    fin=finish_roughness_socket(mat)
    if fin is not None:nt.links.new(fin,bs.inputs['Roughness'])
    if 'poster_paper' in mat:del mat['poster_paper']
    return found


def paper_group_for(s):
    sets=paper_sets(paper_folder(s)) if paper_folder(s) else {}
    if s.paper_set not in sets:raise ValueError('No usable texture found in the paper texture folder.')
    seeds=sorted(sets[s.paper_set]);seed=seeds[min(s.paper_variant,len(seeds)-1)]
    edges=edge_sets(paper_folder(s));edge=None
    if edges:
        name='Paper_Edge' if 'Paper_Edge' in edges else sorted(edges)[0]
        es=sorted(edges[name]);edge=edges[name][es[min(s.paper_variant,len(es)-1)]]
    try:hole=ensure_hole_texture(paper_folder(s))
    except (OSError,RuntimeError):hole=None
    return paper_group(s.paper_set,seed,sets[s.paper_set][seed],edge,hole)


def paper_targets(context,scope):
    mats=set()
    if scope=='SELECTED':
        for ob in context.selected_objects:
            if ob.type=='MESH':mats.update(m for m in ob.data.materials if poster_material(m)[0])
    else:mats.update(m for m in bpy.data.materials if poster_material(m)[0])
    return mats


def find_sd_tool(s,name):
    dirs=([bpy.path.abspath(s.sd_dir)] if s.sd_dir.strip() else [])+SD_DEFAULT_DIRS
    for d in dirs:
        p=os.path.join(d,name)
        if os.path.isfile(p):return p
    return shutil.which(name)


def sbs_graph_info(path):
    import xml.etree.ElementTree as ET
    root=ET.parse(path).getroot();graphs=[]
    for graph in root.iter('graph'):
        ident=graph.find('identifier')
        outs=[o.find('identifier').get('v') for o in graph.iter('graphoutput') if o.find('identifier') is not None]
        if ident is not None:graphs.append((ident.get('v'),outs))
    return graphs


def make_poster(rec,mat,collection,scale):
    w,h=rec['width_mm']*.001/scale,rec['height_mm']*.001/scale
    ts=[0,1]
    # Local origin is the midpoint of the top edge; paper extends downward.
    verts=[((u-.5)*w,-t*h,0) for t in ts for u in (0,1)]
    faces=[(0,2,3,1)]
    mesh=bpy.data.meshes.new(rec['name']);mesh.from_pydata(verts,[],faces);mesh.update()
    layer=mesh.uv_layers.new(name='UVMap')
    u0,v0,u1,v1=rec['uv']
    for loop in mesh.loops:
        idx=loop.vertex_index;u=idx%2;v=1-ts[idx//2]
        u,v=rotate_uv(u,v,rec.get('packing_rotation',0)//90)
        layer.data[loop.index].uv=(u0+(u1-u0)*u,v0+(v1-v0)*v)
    ensure_paper_uv(mesh,scale)
    mesh.materials.append(mat)
    for p in mesh.polygons:p.use_smooth=True
    ob=bpy.data.objects.new(rec.get('object_name','%03d · %s'%(rec['number'],rec['name'])),mesh);collection.objects.link(ob)
    ob.rotation_euler.x=math.pi/2
    ob['poster_pivot']='TOP_CENTER'
    ob['poster_uv_rect']=rec['uv']
    ob['poster_atlas_id']=rec.get('atlas_id',rec['atlas'])
    ob['poster_source_key']=rec.get('source_key',rec['source'])
    ob['poster_schema']=1
    ob['poster_packing_rotation']=rec.get('packing_rotation',0)
    for key in ['id','number','width_mm','height_mm','atlas','source']:
        ob['poster_'+key]=rec[key]
    return ob


def detach_object(ob):
    """Take an object out of every collection instead of deleting it: deleting datablocks in the middle of a build
    left the undo history pointing at freed materials (Ctrl+Z crashed Blender). Orphans are dropped on save."""
    for c in list(ob.users_collection):c.objects.unlink(ob)


def build_parent(context):
    """Where a new batch goes: the collection that is active in the Outliner (e.g. 'hide'), or the scene root."""
    lc=getattr(context.view_layer,'active_layer_collection',None)
    c=lc.collection if lc else None
    if c is None or c==context.scene.collection or c.get('poster_manifest'):return None
    if c.get('poster_groups_root') or c.get('poster_shared_group') or c.get('poster_group'):return None   # never inside Poster Groups or a batch's group
    s=getattr(context.scene,'poster_atlas',None)
    if s is not None and c.name in {f.group.strip() for f in s.files if f.selected} and not c.get('poster_manifest'):
        # the selected collection is used as a group (e.g. 'Group1'): the batch goes next to it, its posters are linked in
        par=next((p for p in bpy.data.collections if c.name in p.children),None)
        return par if par is not None and not any(par.get(t) for t in POSTER_TAGS) else None
    return c


def batch_groups(s):
    """Group names of the images going into this build, most used first (ties: list order)."""
    count={};first={}
    for k,f in enumerate(build_files(s)):
        g=f.group.strip()
        if g:count[g]=count.get(g,0)+1;first.setdefault(g,k)
    return sorted(count,key=lambda g:(-count[g],first[g]))


def batch_number(previous=None):
    """Batch 1, 2, 3 … in build order (a re-edited batch keeps its number)."""
    if previous is not None and previous.get('poster_batch_no'):return int(previous['poster_batch_no'])
    used=[int(c.get('poster_batch_no',0)) for c in bpy.data.collections if c.get('poster_manifest')]
    old=len([c for c in bpy.data.collections if c.get('poster_manifest') and not c.get('poster_batch_no')])
    return max(used+[old])+1


def batch_names(n,groups):
    """('Batch 2 · Wall, Notes, String', 'Batch02_Wall_Notes_String'): collection name and file-safe name."""
    label=', '.join(groups)
    safe='_'.join(re.sub(r'[^\w]+','_',g).strip('_') for g in groups if re.sub(r'[^\w]+','',g))
    return ('Batch %d'%n)+(' · '+label if label else ''),('Batch%02d'%n)+('_'+safe if safe else '')


def build_destination(context,exclude=None):
    """Where a new batch goes: the Outliner-selected collection; if none is usable (nothing / a batch / a group is
    selected), next to the newest batch (e.g. inside 'Poster'); None = the scene root. Never an extra folder."""
    t=build_parent(context)
    if t is not None:return t
    others=[c for c in bpy.data.collections if c.get('poster_manifest') and c!=exclude and c.users]
    others.sort(key=lambda c:int(c.get('poster_batch_no') or 0))
    for c in reversed(others):
        p=next((p for p in bpy.data.collections if c.name in p.children and not any(p.get(k) for k in POSTER_TAGS)),None)
        if p is not None:return p
    return None


def build(context,s,layout_spec=None):
    previous=s.last_collection if s.update_previous else None
    if s.update_previous and previous is None:raise ValueError('There is no previous build batch to update.')
    batch_no=batch_number(previous);batch_label,job=batch_names(batch_no,batch_groups(s))
    custom_=s.batch_name.strip() if previous is None else ''
    if custom_:   # the name typed for this batch (folder / texture names follow it)
        batch_label=custom_;job=re.sub(r'[^\w]+','_',custom_).strip('_') or job
    paths=list(layout_spec['paths']) if layout_spec else [file_path(x) for x in build_files(s)]
    originals={file_path(x):(bpy.path.abspath(x.path),x.quarter_turns*90) for x in build_files(s)}
    if not paths:raise ValueError('Check the images to use with the checkboxes on the left of the list. Press Select All to use all of them.')
    if layout_spec:
        res=int(s.resolution);pad=max(4,round(4*res/2048));rects=layout_spec['rects']
        if layout_spec['resolution']!=res:raise ValueError('The resolution changed. Please reopen the layout editor.')
        if len(rects)!=len(paths):raise ValueError('Layout count does not match the image count.')
        for r in rects:
            if len(r)!=4 or any(not isinstance(v,int) for v in r) or not (pad<=r[0]<r[2]<=res-pad and pad<=r[1]<r[3]<=res-pad):raise ValueError('Please move images inside the canvas.')
        physical=layout_spec.get('physical_sizes',[None]*len(paths))
        rotations=layout_spec.get('rotations',[0]*len(paths))
        crops=layout_spec.get('crops',[[0.,0.,1.,1.] for _ in paths])
        effects=layout_spec.get('effects') or []
        if len(crops)!=len(paths) or any(len(c)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in c) or not (0<=c[0]<c[2]<=1 and 0<=c[1]<c[3]<=1) for c in crops):raise ValueError('Invalid crop data.')
        if len(rotations)!=len(paths) or any(type(v)!=int or not 0<=v<4 for v in rotations):raise ValueError('Invalid layout rotation data.')
        if len(physical)!=len(paths):raise ValueError('Size data does not match the image count.')
        for r,mm,turn in zip(rects,physical,rotations):
            pixels=(r[3]-r[1],r[2]-r[0]) if turn%2 else (r[2]-r[0],r[3]-r[1])
            if mm is not None and (len(mm)!=2 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in mm)
                or any(abs(p*layout_density(s)-px)>.501 for p,px in zip(mm,pixels))):
                raise ValueError('Size data differs from the layout size. Select the images and press the size again.')
        if layout_conflicts(rects,0):raise ValueError('Images overlap. Please move them slightly.')
    for p in paths:
        if not os.path.isfile(p):raise ValueError('File not found: '+p)
    if not s.output_dir.strip():raise ValueError('Please choose a folder to save textures.')
    parent=os.path.abspath(bpy.path.abspath(s.output_dir));os.makedirs(parent,exist_ok=True)
    token=uuid.uuid4().hex[:10];folder=os.path.join(parent,job);k_=2
    while os.path.exists(folder):folder=os.path.join(parent,'%s_%d'%(job,k_));k_+=1   # a re-edit / same number again: Batch02_Wall_2
    os.makedirs(folder)
    collection=None;images=[];materials=[];objects=[];baked={}
    if not layout_spec:effects=[]
    manifest={'version':2,'resolution':int(s.resolution),'size_mode':'LINKED','reference_paper_mm':[210,297],'uv_origin':'bottom_left','pixel_origin':'bottom_left','poster_pivot':'top_center','posters':[]}
    if layout_spec:
        manifest.update(size_mode='CANVAS',layout=layout_spec,pixels_per_mm=layout_density(s),background=s.background,job_name=s.job_name)
    try:
        res=int(s.resolution);basew,baseh=dimensions(s);pad=4
        count,cols,rows=atlas_layout(s)
        pack=bool(layout_spec) or s.mode=='PACK'
        if layout_spec:count=len(paths);pad=max(4,round(4*res/2048))
        batches=math.ceil(len(paths)/count) if pack else len(paths)
        batch_id=previous.get('poster_batch_id',uuid.uuid4().hex) if previous else uuid.uuid4().hex
        atlas_ids=json.loads(previous.get('poster_atlas_ids','[]')) if previous else []
        old_manifest={}
        if previous and previous.get('poster_manifest'):
            try:
                with open(bpy.path.abspath(previous['poster_manifest']),encoding='utf-8') as f:
                    old_manifest={r['id']:r for r in json.load(f).get('posters',[])}
            except (OSError,ValueError,KeyError):pass
        old_sources={}
        for old in previous.all_objects if previous else []:
            oldrec=old_manifest.get(old.get('poster_id',''),{})
            key=old.get('poster_source_key',old.get('poster_source','')+'|'+str(oldrec.get('source_cell') or 0))
            old_sources[key]=old
        collection=bpy.data.collections.new(batch_label);context.scene.collection.children.link(collection)
        collection['poster_batch_id']=batch_id;collection['poster_job']=s.job_name;collection['poster_batch_no']=batch_no
        if custom_:collection['poster_custom_name']=True
        scale=max(context.scene.unit_settings.scale_length,1e-6)
        for batch in range(batches):
            bg=(1.,1.,1.,1.) if s.background=='WHITE' else (0.,0.,0.,1.) if s.background=='BLACK' else (0.,0.,0.,0.)
            canvas=np.empty((res,res,4),np.float32);canvas[:]=bg;records=[];ncanvas=None;fx_jobs=[]
            sources=paths[batch*count:(batch+1)*count] if pack else [paths[batch]]
            sheet=read_pixels(sources[0]) if not pack else None
            limit=len(sources) if pack else (min(s.last_count,count) if batch==batches-1 and s.last_count else count)
            atlas_number=(int(previous.get('poster_atlas_start',1)) if previous else s.atlas_next)+batch
            if batch>=len(atlas_ids):atlas_ids.append(uuid.uuid4().hex)
            atlas_id=atlas_ids[batch]
            atlas_name='T_%s_A%02d.png'%(job,atlas_number)
            for i in range(limit):
                col,row=i%cols,i//cols
                path=sources[i] if pack else sources[0]
                if pack:data=read_pixels(path)
                else:
                    sh,sw=sheet.shape[:2]
                    x0,x1=round(col*sw/cols),round((col+1)*sw/cols)
                    y0,y1=sh-round((row+1)*sh/rows),sh-round(row*sh/rows)
                    inset=s.split_inset
                    if x1-x0<=2*inset or y1-y0<=2*inset:raise ValueError('The trim margin is larger than the cell size.')
                    data=sheet[y0+inset:y1-inset,x0+inset:x1-inset].copy()
                ih,iw=data.shape[:2]
                if min(iw,ih)<1:raise ValueError('Row/column count exceeds the source image size.')
                if layout_spec:
                    ca,cb,cc,cd=crops[i]
                    cx0=max(0,min(iw-1,round(ca*iw)));cy0=max(0,min(ih-1,round(cb*ih)))
                    cx1=max(cx0+1,min(iw,round(cc*iw)));cy1=max(cy0+1,min(ih,round(cd*ih)))
                    data=data[cy0:cy1,cx0:cx1].copy()
                    x,y,x1,y1=rects[i];rw,rh=x1-x,y1-y
                    density=layout_density(s);pw,ph=rw/density,rh/density
                    if rotations[i]%2:pw,ph=ph,pw
                    if physical[i] is not None:pw,ph=physical[i]
                    # Dragging preserves ratio; only integer pixel rounding differs.
                    if s.background!='TRANSPARENT':
                        data[:,:,:3]=data[:,:,:3]*data[:,:,3:4]+np.array(bg[:3],dtype=np.float32)*(1-data[:,:,3:4]);data[:,:,3]=1
                    data=np.ascontiguousarray(np.rot90(data,rotations[i],axes=(0,1)))
                    paper=resize(data,rw,rh)
                    fx=effects[i] if i<len(effects) else None
                    if fx_active(fx):fx=fx_clean(fx);fx['seed']=fx_seed(fx,path);baked[path]=fx
                    else:fx=None
                    fx_jobs.append((x,y,rw,rh,paper,fx,rotations[i]));caption_ensure(fx,rw if rotations[i]%2 else rh)   # Effects are computed below for several sheets at once
                else:
                    pw,ph=poster_size(s,iw,ih,cols,rows)
                    left,right=round(col*res/cols)+pad,round((col+1)*res/cols)-pad
                    bottom,top=res-round((row+1)*res/rows)+pad,res-round(row*res/rows)-pad
                    if right<=left or top<=bottom:raise ValueError('Too many rows/columns.')
                    factor=min((right-left)/pw,(top-bottom)/ph)
                    rw=max(1,min(right-left,round(pw*factor)));rh=max(1,min(top-bottom,round(ph*factor)))
                    x=left+(right-left-rw)//2;y=bottom+(top-bottom-rh)//2
                    paper=on_paper(data,rw,rh,False)
                if layout_spec:pass
                else:canvas[y-pad:y+rh+pad,x-pad:x+rw+pad]=np.pad(paper,((pad,pad),(pad,pad),(0,0)),mode='edge')
                num=len(manifest['posters'])+len(records)+1
                original,rotation=originals.get(path,(path,0))
                name=os.path.splitext(os.path.basename(original))[0]+(' · %02d'%(i+1) if not pack else '')
                records.append({'id':token+'_%05d'%num,'number':num,'name':name,'source':original,'rotation_degrees':rotation,'packing_rotation':rotations[i]*90 if layout_spec else 0,'source_cell':i+1 if not pack else None,'atlas':atlas_name,'width_mm':pw,'height_mm':ph,'pixel_rect':[x,y,rw,rh],'uv':[x/res,y/res,(x+rw)/res,(y+rh)/res],'effects':baked.get(path)})
            if fx_jobs:   # Effects/paper crumple: compute several sheets concurrently (numpy only, so safe)
                den_=layout_density(s);fres=fx_resources(s)
                pinfs=[paper_info(s,j[5].get('paper'),full=True) if j[5] else None for j in fx_jobs]   # Texture reads happen on the main thread
                def fx_work(k):
                    x,y,rw,rh,paper,fx,t=fx_jobs[k];nt=None;t=int(t or 0)%4
                    if fx is not None:
                        if t:paper=np.ascontiguousarray(np.rot90(paper,-t,axes=(0,1)))   # turned to pack: make the frame / caption / paper on the upright card, then turn the whole card
                        paper=apply_effects(paper,fx,den_,fres)
                        if pinfs[k]:
                            uh,uw=paper.shape[:2]
                            nt,aom=paper_normal_ao(pinfs[k],uw,uh,den_,fx['seed'])
                            paper[:,:,:3]=np.clip(np.clip(paper[:,:,:3],0,1)**2.2*aom[...,None],0,1)**(1/2.2)
                        if t:
                            paper=np.ascontiguousarray(np.rot90(paper,t,axes=(0,1)))
                            if nt is not None:nt=rot_normal_tex(nt,t)
                    return paper,nt
                from concurrent.futures import ThreadPoolExecutor
                wm=context.window_manager;wm.progress_begin(0,len(fx_jobs))
                try:
                    with ThreadPoolExecutor(max_workers=max(1,min(8,(os.cpu_count() or 4)-1))) as ex:
                        for k,(paper,nt) in enumerate(ex.map(fx_work,range(len(fx_jobs)))):
                            x,y,rw,rh=fx_jobs[k][:4];canvas[y:y+rh,x:x+rw]=paper
                            if nt is not None:
                                if ncanvas is None:ncanvas=np.empty((res,res,4),np.float32);ncanvas[:]=(.5,.5,1.,1.)
                                ncanvas[y:y+rh,x:x+rw,:3]=nt
                            wm.progress_update(k+1)
                finally:wm.progress_end()
                fx_jobs=[]
            duplicate_keys={}
            for j,rec in enumerate(records):
                basekey=rec['source']+'|'+str(rec['source_cell'] or 0)
                occurrence=duplicate_keys.get(basekey,0);duplicate_keys[basekey]=occurrence+1
                key=basekey+('|copy'+str(occurrence) if occurrence else '')
                rec['source_key']=key
                old=old_sources.get(key)
                rec['id']=old.get('poster_id',rec['id']) if old else rec['id']
                rec['atlas_id']=atlas_id
                rec['object_name']='PST_%s_A%02d_%03d'%(job,atlas_number,j+1)
            im=save_atlas(os.path.join(folder,atlas_name),canvas,s.pack_textures);images.append(im)
            im['poster_atlas_id']=atlas_id
            mat=atlas_material(im);materials.append(mat)
            rcanvas=finish_canvas(records,res)
            if rcanvas is not None:   # Printed photos: roughness (R) / metallic (G) map, paper keeps 0.85 / 0
                rim=save_atlas(os.path.join(folder,atlas_name.replace('.png','_RM.png')),rcanvas,s.pack_textures)
                rim.colorspace_settings.name='Non-Color';images.append(rim);atlas_add_finish(mat,rim)
            if ncanvas is not None:   # Paper crumple normal map (OpenGL)
                nim=save_atlas(os.path.join(folder,atlas_name.replace('.png','_N.png')),ncanvas,s.pack_textures)
                nim.colorspace_settings.name='Non-Color';images.append(nim);atlas_add_normal(mat,nim)
            for rec in records:objects.append(make_poster(rec,mat,collection,scale))
            manifest['posters'].extend(records)
        # Arrange source objects in a reviewable upright contact sheet at the cursor.
        gridcols=min(8,max(1,math.ceil(math.sqrt(len(objects)))))
        maxw=max(r['width_mm'] for r in manifest['posters'])*.001/scale
        maxh=max(r['height_mm'] for r in manifest['posters'])*.001/scale
        origin=context.scene.cursor.location.copy()
        for i,ob in enumerate(objects):
            # Move the new origin upward to preserve the contact sheet's geometry.
            halfh=ob['poster_height_mm']*.001/scale/2
            ob.location=origin+Vector(((i%gridcols)*(maxw+.03/scale),0,-(i//gridcols)*(maxh+.03/scale)+halfh))
        with open(os.path.join(folder,'poster_info.json'),'w',encoding='utf-8') as f:json.dump(manifest,f,ensure_ascii=False,indent=2)
        collection['poster_manifest']=os.path.join(folder,'poster_info.json')
        collection['poster_atlas_ids']=json.dumps(atlas_ids[:batches])
        collection['poster_atlas_start']=int(previous.get('poster_atlas_start',1)) if previous else s.atlas_next
        collection['poster_revision']=int(previous.get('poster_revision',0))+1 if previous else 1
        if previous:
            old_mats={m for o in previous.all_objects if o.data for m in o.data.materials if m}
            # Replace data in-place to preserve manual placement pointers and IDs.
            for ob in list(objects):
                old=old_sources.get(ob.get('poster_source_key',''))
                if old:
                    oldmesh=old.data;old.data=ob.data
                    for key in ob.keys():old[key]=ob[key]
                    objects[objects.index(ob)]=old;detach_object(ob)
                else:
                    previous.objects.link(ob);collection.objects.unlink(ob)
            # Images taken out of the batch in the editor leave the scene too (their posters disappear from the walls
            # after the refresh below). Only ones pinned by hand in a Scatter area (Place Specific Posters) are kept.
            keep_=({o.as_pointer() for o in objects})
            pinned_={p.poster.name for a in bpy.data.objects if getattr(a,'poster_scatter',None) is not None for p in getattr(a.poster_scatter,'manual',()) if getattr(p,'poster',None)}
            for o in [o for o in previous.all_objects if o.as_pointer() not in keep_ and o.get('poster_id') and o.name not in pinned_]:
                detach_object(o)
            for key in collection.keys():previous[key]=collection[key]
            for par in [c for c in [context.scene.collection]+list(context.scene.collection.children_recursive) if collection.name in c.children]:par.children.unlink(collection)
            collection=previous
            if not collection.get('poster_custom_name') and collection.name.split(' · ')[0]=='Batch %d'%batch_no and collection.name!=batch_label:
                collection.name=batch_label   # still the automatic name: it follows the groups (a name the user gave it stays)
        else:s.atlas_next+=batches
        ngroups=group_batch(collection,objects,manifest,{bpy.path.abspath(x.path):x.group.strip() for x in build_files(s) if x.group.strip()})
        s.last_collection=collection
        if not previous:   # a re-edited batch stays where it is; a new one goes into the Outliner-selected collection
            target=build_destination(context,exclude=collection)
            if target is not None:
                if collection.name not in target.children:target.children.link(collection)
                if collection.name in context.scene.collection.children:context.scene.collection.children.unlink(collection)
        for ob in context.selected_objects:ob.select_set(False)
        if objects:objects[0].select_set(True);context.view_layer.objects.active=objects[0]
        if not previous:s.batch_name=''   # the next batch gets its own (automatic) name again
        s.last_result='Built %d posters / %d textures'%(len(objects),len(images))+(' · %d groups'%ngroups if ngroups else '');s.last_folder=folder
        context.view_layer.update()
        if previous:
            s.last_result+=' · updated %d placed posters'%refresh_scatter_areas(collection)
            pass   # pre-change materials / textures are left as orphans (no users): Blender drops them on save, and Ctrl+Z stays safe
        return manifest,collection
    except Exception:
        if collection and collection!=previous:
            for ob in list(collection.objects):
                mesh=ob.data;bpy.data.objects.remove(ob,do_unlink=True)
                if mesh.users==0:bpy.data.meshes.remove(mesh)
            bpy.data.collections.remove(collection)
        for mat in materials:
            if mat.users==0:bpy.data.materials.remove(mat)
        for im in images:
            if im.users==0:bpy.data.images.remove(im)
        # Only this newly allocated transaction directory is removed on failure.
        if os.path.dirname(folder)==parent and os.path.basename(folder)=='Poster_'+token:shutil.rmtree(folder)
        raise


def refresh_scatter_areas(collection):
    """Re-read the sources of [Poster Scatter] areas that use a re-edited batch and swap in the new textures."""
    ps=sys.modules.get('poster_scatter');n=0
    if ps is None:return 0
    mine_={o.name for o in collection.all_objects}
    for area in bpy.context.scene.objects:
        st=getattr(area,'poster_scatter',None)
        if not st or not st.enabled or not st.collection or not st.cache:continue
        inside_=st.collection.name in {c.name for c in collection.children_recursive}   # an area using one group of the batch
        shared_=bool(mine_ & {o.name for o in st.collection.all_objects})   # e.g. 'Group · Wall' made of several batches
        if st.collection!=collection and not inside_ and not shared_ and collection.name not in {c.name for c in st.collection.children_recursive}:continue
        try:ps.refresh_sources(area);ps.rebuild(area);ps.SIGNATURES[area.as_pointer()]=ps.signature(area);n+=1
        except Exception as exc:st.status='Error re-reading sources: '+str(exc)
    return n


def poster_batches(s):
    """Build batches that can be re-edited (made with the layout editor)."""
    out=[];seen=set()
    roots=[c for c in (s.library_collection,s.last_collection) if c]
    scn=s.id_data if isinstance(s.id_data,bpy.types.Scene) else bpy.context.scene
    roots.append(scn.collection)   # batches moved anywhere in the scene (e.g. into 'hide') are still found
    for root in roots:
        for c in [root]+list(root.children_recursive):
            if c.get('poster_manifest') and c.name not in seen:seen.add(c.name);out.append(c)
    return out


def snapshot_file_list(s):
    return {'files':[{k:getattr(f,k) for k in ('path','quarter_turns','selected','picked','group')} for f in s.files],'active':s.active,'no_row':s.no_row}


def restore_file_list(s,snap):
    """Put the image list back exactly as in the snapshot (used when a Re-edit session ends)."""
    global SELECTION_BATCH
    SELECTION_BATCH=True
    try:
        s.files.clear()
        for d in snap['files']:
            it=s.files.add()
            for k,v in d.items():setattr(it,k,v)
    finally:SELECTION_BATCH=False
    s.active=max(0,min(snap['active'],len(s.files)-1));s.no_row=snap.get('no_row',False)


def reedit_alive(collection,posters,plan):
    """Posters deleted from the scene (Outliner / viewport X) are left out of the Re-edit, so the next Build drops them too.
    Every per-image list of the layout plan is filtered the same way. A batch whose objects are all gone is kept whole."""
    live={o.get('poster_id') for o in collection.all_objects if o.get('poster_id')}
    n=len(posters);keep=[k for k,rec in enumerate(posters) if rec.get('id') in live]
    if not live or not keep or len(keep)==n:return posters,plan
    plan=dict(plan)
    for k_,v in list(plan.items()):
        if isinstance(v,list) and len(v)==n:plan[k_]=[v[i] for i in keep]
    return [posters[i] for i in keep],plan


def reedit_prepare(s,collection):
    """Restore the list, layout and effects from a build batch record (poster_info.json)."""
    path=bpy.path.abspath(collection.get('poster_manifest',''))
    try:
        with open(path,encoding='utf-8') as f:manifest=json.load(f)
    except (OSError,ValueError):raise ValueError('Build record not found: '+path)
    plan=manifest.get('layout');posters=manifest.get('posters',[])
    if not plan or len(posters)!=len(plan.get('paths',[])):
        raise ValueError('Only batches made with [Layout Editor · Build] can be re-edited.')
    posters,plan=reedit_alive(collection,posters,plan)
    wanted=[]
    for rec in posters:
        src=os.path.abspath(bpy.path.abspath(rec['source']))
        if not os.path.isfile(src):raise ValueError('Source image missing: '+src)
        wanted.append((src,int(round(rec.get('rotation_degrees',0)/90))%4))
    # Groups (Group…) live in the batch's group collections: give each image its group back so the next Build keeps them
    groups={}
    for c in collection.children:
        g=c.get('poster_group')
        if g:
            for ob in c.objects:
                if ob.get('poster_source'):groups[os.path.normcase(os.path.abspath(bpy.path.abspath(ob['poster_source'])))]=g
    used=set();order=[]
    for src,turns in wanted:
        idx=next((i for i,f in enumerate(s.files) if i not in used and f.quarter_turns==turns and os.path.abspath(bpy.path.abspath(f.path))==src),None)
        if idx is None:
            item=s.files.add();item.path=src;item.quarter_turns=turns;idx=len(s.files)-1
        g=groups.get(os.path.normcase(src))
        if g and s.files[idx].group!=g:s.files[idx].group=g
        used.add(idx);s.files[idx]['_reedit']=len(order);order.append(idx)
    for f in s.files:
        if f.selected:f.selected=False
    # Restored images go to the top of the list in the same order
    for target in range(len(order)):
        cur=next(i for i,f in enumerate(s.files) if f.get('_reedit')==target)
        if cur!=target:s.files.move(cur,target)
    for i in range(len(order)):
        del s.files[i]['_reedit'];s.files[i].selected=True
    plan=dict(plan);plan['paths']=[file_path(s.files[i]) for i in range(len(order))]
    s.mode='PACK';set_resolution(s,int(plan['resolution']))
    if manifest.get('background') in ('WHITE','BLACK','TRANSPARENT'):s.background=manifest['background']
    s.job_name=collection.get('poster_job') or manifest.get('job_name') or (collection.name.split(' · ')[1] if collection.name.count(' · ')>=2 else s.job_name)
    s.layout_plan=json.dumps(plan,ensure_ascii=False)
    s.last_collection=collection;s.update_previous=True;s.active=0
    return len(order)


def sync_open_layouts():
    if SELECTION_DRAGS:return .1
    for editor in list(CUT_EDITORS):
        if editor.layout_mode and not editor.closed:
            try:editor.refresh_layout_sources()
            except Exception as exc:editor.report({'ERROR'},_T(str(exc)))
    return None


def build_scope_changed(self,context):
    if SELECTION_BATCH or SELECTION_DRAGS:return
    if CUT_EDITORS and not bpy.app.timers.is_registered(sync_open_layouts):
        bpy.app.timers.register(sync_open_layouts,first_interval=.01)


def file_selection_changed(self,context):
    # Checking an image is an explicit request to work on the checked subset.
    # Unchecking the last one stays empty; it must never fall back to all files.
    settings=self.id_data.poster_atlas
    build_scope_changed(settings,context)
    if not SELECTION_BATCH and not SELECTION_DRAGS and context.region and context.region.type=='UI':
        index=next((i for i,f in enumerate(settings.files) if f.as_pointer()==self.as_pointer()),-1)
        if index>=0:
            try:bpy.ops.poster_atlas.drag_select('INVOKE_DEFAULT',index=index)
            except RuntimeError:pass


def file_pick_changed(self,context):
    # Clicking a name starts the same drag as the checkboxes (with auto-scroll past the list edge), but for the name selection
    if not SELECTION_BATCH and not SELECTION_DRAGS and context.region and context.region.type=='UI':
        settings=self.id_data.poster_atlas
        index=next((i for i,f in enumerate(settings.files) if f.as_pointer()==self.as_pointer()),-1)
        if index>=0:
            settings.active=index;settings.no_row=False   # a click on a name also makes it the current row, like clicking the row itself
            try:bpy.ops.poster_atlas.drag_select('INVOKE_DEFAULT',index=index,field='picked')
            except RuntimeError:pass


GROUP_SUGGESTIONS=('Wall','Notes','String','Outer')
LAST_GROUP=['Wall']
# Blender's collection colors: the list shows COLLECTION_COLOR_0n next to the name, the canvas badge uses the same color
GROUP_COLORS={1:(.80,.27,.27),2:(.86,.50,.18),3:(.80,.68,.15),4:(.30,.62,.30),5:(.25,.48,.82),6:(.55,.36,.78),7:(.82,.38,.62),8:(.55,.42,.30)}
GROUP_FIXED={'wall':5,'notes':3,'string':4,'outer':2,'photos':6}


def group_color_index(g):
    g=(g or '').strip()
    if not g:return 0
    k=GROUP_FIXED.get(g.casefold())
    if k:return k
    free=[6,7,1,8];return free[sum(map(ord,g.casefold()))%len(free)]


def group_rows(s):
    """Which list rows Group… / Drop Group act on: the posters selected on the canvas while the Layout Editor is open,
    otherwise the checked images."""
    e=next((x for x in CUT_EDITORS if getattr(x,'layout_mode',False) and not getattr(x,'closed',False)),None)
    if e is not None:
        try:
            rows=e.group_targets()
            if rows:return rows,e
        except Exception:pass
    return checked_indices(s),None


def group_drop_poll(self,c):
    """Collections that can be a group: not a batch / Poster Groups itself."""
    return not (c.get('poster_manifest') or c.get('poster_groups_root') or c.get('poster_batch_id'))


def group_drop_changed(self,context):
    """A collection dropped on the sidebar's group field: the checked images get that group, then the field empties again."""
    c=self.group_drop
    if c is None:return
    g=(c.get('poster_shared_group') or c.get('poster_group') or c.name).strip()
    idx,e=group_rows(self)
    for i in idx:self.files[i].group=g
    if g:LAST_GROUP[0]=g
    self.group_drop=None
    if e is not None:
        try:e.area.tag_redraw()
        except Exception:pass


def group_icon(g):
    k=group_color_index(g);return 'COLLECTION_COLOR_0%d'%k if k else 'OUTLINER_COLLECTION'


POSTER_TAGS=('poster_groups_root','poster_shared_group','poster_group','poster_manifest','poster_batch_id')


def user_group_collections():
    """Collections the user made to hold posters (e.g. 'Group1' in 'Poster'): not made by Poster Print and holding
    nothing but posters (or nothing yet). Picking one as a group puts that group's posters in it."""
    scene=bpy.context.scene;inscene={c.name for c in scene.collection.children_recursive}
    out=[]
    for c in bpy.data.collections:
        if c.name not in inscene or any(c.get(t) for t in POSTER_TAGS):continue
        if not all(k.get('poster_group') for k in c.children):continue   # a parent like 'Poster' (batches, other folders) is not a group
        if all(o.get('poster_id') for o in c.objects):out.append(c)
    return out


def user_group_collection(g):
    return next((c for c in user_group_collections() if c.name==g),None)


def known_groups():
    """Group names in the list and in built batches, most used first; then the user's own empty / poster collections."""
    names={}
    s=getattr(bpy.context.scene,'poster_atlas',None)
    for f in (s.files if s else []):
        g=f.group.strip()
        if g:names[g]=names.get(g,0)+1
    for c in bpy.data.collections:
        g=c.get('poster_group') or c.get('poster_shared_group')
        if g:names[g]=names.get(g,0)+1
    out=sorted(names,key=lambda g:-names[g])
    try:out+=[c.name for c in user_group_collections() if c.name not in names]
    except Exception:pass
    return out


def group_name_search(self,context,edit_text):
    t=(edit_text or '').strip().casefold();out=[]
    for g in known_groups()+list(GROUP_SUGGESTIONS):
        if g not in out and (not t or t in g.casefold()):out.append(g)
    return out


class PA_OT_batch_rename(bpy.types.Operator):
    """Name of the batch: the next one (before Build) or the one being edited (renamed right away)."""
    bl_idname='poster_atlas.batch_rename';bl_label=_T('Batch Name');bl_options={'UNDO','INTERNAL'}
    name:StringProperty(name=_T('Name'),default='')
    def target(self,context):
        s=context.scene.poster_atlas
        return s.last_collection if (s.update_previous and s.last_collection) else None
    def invoke(self,context,event):
        s=context.scene.poster_atlas;t=self.target(context)
        self.name=t.name if t else (s.batch_name.strip() or batch_names(batch_number(None),batch_groups(s))[0])
        for e in [x for x in CUT_EDITORS if getattr(x,'layout_mode',False)]:e.settings_popup=True
        return context.window_manager.invoke_props_dialog(self,width=320,title=_T('Batch name'))
    def draw(self,context):
        self.layout.prop(self,'name',text=_T(''),icon='OUTLINER_COLLECTION')
        r=self.layout.row();r.active=False;r.label(text=_T('Empty = automatic (Batch N · groups)'))
    def done(self):
        for e in [x for x in CUT_EDITORS if getattr(x,'layout_mode',False)]:
            e.settings_popup=False;e._where_key=None
            try:e.area.tag_redraw()
            except Exception:pass
    def cancel(self,context):self.done()
    def execute(self,context):
        s=context.scene.poster_atlas;t=self.target(context);nm=self.name.strip()
        if t is not None:   # editing a built batch: rename its collection now (Build keeps it)
            if nm:t.name=nm;t['poster_custom_name']=True
            else:
                t['poster_custom_name']=False
                t.name=batch_names(int(t.get('poster_batch_no') or batch_number(None)),batch_groups(s))[0]
        else:s.batch_name='' if nm==batch_names(batch_number(None),batch_groups(s))[0] else nm
        self.done();return {'FINISHED'}


class PA_OT_group_rename(bpy.types.Operator):
    bl_idname='poster_atlas.group_rename';bl_label=_T('Rename Group');bl_options={'UNDO','INTERNAL'}
    old:StringProperty(options={'HIDDEN','SKIP_SAVE'})
    name:StringProperty(name=_T('Name'),default='',search=group_name_search,search_options={'SUGGESTION'})
    def invoke(self,context,event):
        self.name=self.old
        for e in [x for x in CUT_EDITORS if getattr(x,'layout_mode',False)]:e.settings_popup=True
        return context.window_manager.invoke_props_dialog(self,width=300,title=_T('Rename "%s"'%self.old))
    def draw(self,context):
        self.layout.prop(self,'name',text=_T(''),icon='OUTLINER_COLLECTION')
    def done(self):
        for e in [x for x in CUT_EDITORS if getattr(x,'layout_mode',False)]:
            e.settings_popup=False
            try:e.area.tag_redraw()
            except Exception:pass
    def cancel(self,context):self.done()
    def execute(self,context):
        new=self.name.strip();self.done()
        if not new or new==self.old:return {'CANCELLED'}
        n=0
        for f in context.scene.poster_atlas.files:
            if f.group.strip()==self.old:f.group=new;n+=1
        LAST_GROUP[0]=new;self.report({'INFO'},_T('Group "%s" → "%s" · %d image(s)'%(self.old,new,n)))
        return {'FINISHED'}


class PA_OT_set_group(bpy.types.Operator):
    bl_idname='poster_atlas.set_group';bl_label=_T('Group Checked Images');bl_options={'UNDO'}
    bl_description=_T('Give the checked images a group. Build puts each group in its own collection inside the batch (e.g. Photos for the string, Notes for the wall), so Scatter can use them separately. X clears it')
    name:StringProperty(name=_T('Group'),default='',search=group_name_search,search_options={'SUGGESTION'})
    ask:BoolProperty(default=True,options={'SKIP_SAVE','HIDDEN'})
    editor:BoolProperty(default=False,options={'SKIP_SAVE','HIDDEN'})   # True: the images selected on the Layout Editor canvas
    def rows(self,context):
        return group_rows(context.scene.poster_atlas)[0]   # canvas selection while the editor is open, else the checked images
    def invoke(self,context,event):
        if not self.ask:return self.execute(context)
        s=context.scene.poster_atlas;idx=self.rows(context)
        e=next((x for x in CUT_EDITORS if x.layout_mode),None) if self.editor else None
        if e:e.settings_popup=True
        cur={s.files[i].group.strip() for i in idx}-{''}
        self.name=cur.pop() if len(cur)==1 else LAST_GROUP[0]   # the group these images already have, else the last one used
        return context.window_manager.invoke_props_dialog(self,width=320,title=_T('Group %d image%s'%(len(idx),'' if len(idx)==1 else 's')))
    def draw(self,context):
        l=self.layout;l.prop(self,'name',text=_T(''),icon='OUTLINER_COLLECTION')
        col=l.column(align=True);col.scale_y=.8
        col.label(text=_T('Pick one from the list or type a new name.'),icon='INFO')
        col.label(text=_T('Same name in another batch = the same group:'))
        col.label(text=_T('Poster Pin can then use "Group · Name" for all of them.'))
        col.label(text=_T('Empty name = no group.'))
    def popup_done(self):
        for e in [x for x in CUT_EDITORS if x.layout_mode] if self.editor else []:e.settings_popup=False;e.area.tag_redraw()
    def cancel(self,context):self.popup_done()
    def execute(self,context):
        s=context.scene.poster_atlas;idx=self.rows(context);n=len(idx);self.popup_done()
        for i in idx:s.files[i].group=self.name.strip()
        if self.name.strip():LAST_GROUP[0]=self.name.strip()
        if not n:self.report({'WARNING'},_T('Check images in the list (or select posters in the editor) first'));return {'CANCELLED'}
        for e_ in [x for x in CUT_EDITORS if getattr(x,'layout_mode',False)]:
            try:e_.area.tag_redraw()
            except Exception:pass
        self.report({'INFO'},_T('%d image%s → %s'%(n,'' if n==1 else 's',self.name.strip() or 'no group')))
        return {'FINISHED'}


GROUPS_ROOT='Poster Groups'


def find_layer_collection(lc,c):
    if lc.collection==c:return lc
    for k in lc.children:
        r=find_layer_collection(k,c)
        if r:return r
    return None


def place_groups_root(scene,parent):
    """'Poster Groups' sits in the same collection as the batches (moved there if it was somewhere else), excluded from the view layers."""
    root=next((c for c in bpy.data.collections if c.get('poster_groups_root')),None)
    if root is None or parent is None or root.name in parent.children:return
    unlink_everywhere(root);parent.children.link(root)
    for vl in scene.view_layers:
        lc=find_layer_collection(vl.layer_collection,root)
        if lc:lc.exclude=True


def shared_group(g,scene=None):
    """'Group · <name>' inside the 'Poster Groups' collection: every batch's group collection with this name is linked in,
    so Poster Pin can use one group across batches. 'Poster Groups' is excluded from the view layers (nothing shows twice
    and hidden batches stay hidden); Poster Pin reads the collection directly. Build then moves it next to the batches."""
    scene=scene or bpy.context.scene
    root=next((c for c in bpy.data.collections if c.get('poster_groups_root')),None)
    if root is None:root=bpy.data.collections.new(GROUPS_ROOT);root['poster_groups_root']=True
    if not any(root.name in p.children for p in bpy.data.collections) and root.name not in scene.collection.children:
        scene.collection.children.link(root)
        for vl in scene.view_layers:
            lc=find_layer_collection(vl.layer_collection,root)
            if lc:lc.exclude=True
    sh=next((c for c in root.children if c.get('poster_shared_group')==g),None)
    if sh is None:sh=bpy.data.collections.new('Group · '+g);sh['poster_shared_group']=g;root.children.link(sh)
    return sh


def unlink_everywhere(c):
    """Take a collection out of every parent instead of deleting it (deleting in a Build broke Ctrl+Z before)."""
    for par in [p for p in bpy.data.collections if c.name in p.children]:par.children.unlink(c)
    for scn in bpy.data.scenes:
        if c.name in scn.collection.children:scn.collection.children.unlink(c)


def pin_uses(c):
    return any(getattr(getattr(o,'poster_scatter',None),'collection',None)==c for o in bpy.data.objects if hasattr(o,'poster_scatter'))


def group_batch(collection,objects,manifest,group_of):
    """Each named group gets its own collection inside the batch; ungrouped images stay in the batch itself.
    Scatter can use the batch (all) or one group."""
    want={ob.name:group_of.get(ob.get('poster_source',''),'') for ob in objects}
    kids={c.get('poster_group'):c for c in collection.children if c.get('poster_group')}
    if not any(want.values()) and not kids:return 0   # No groups: keep the batch flat as before
    for ob in objects:
        g=want[ob.name];c=kids.get(g) if g else collection
        if c is None:
            # 'Wall · Batch 2' (group first: never the same name as a one-group batch 'Batch 2 · Wall')
            c=bpy.data.collections.new((g+' · Batch %d'%collection['poster_batch_no']) if (collection.get('poster_batch_no') and not collection.get('poster_custom_name')) else g+' · '+collection.name)
            c['poster_group']=g;collection.children.link(c);kids[g]=c
        for other in [collection]+list(kids.values()):
            if other!=c and ob.name in other.objects:other.objects.unlink(ob)
        if ob.name not in c.objects:c.objects.link(ob)
    for g,c in list(kids.items()):   # a group no image uses any more (renamed / emptied): take its empty collection out
        if not c.objects and not c.children and not pin_uses(c):unlink_everywhere(c);kids.pop(g,None)
    users_=user_group_collections();mine_={ob.name for ob in objects}
    for p in users_:   # the user's own group collections hold the posters directly (no extra collection inside)
        for k in list(p.children):   # older builds linked the whole group collection: put its posters in directly instead
            if k.get('poster_group'):
                for ob in k.objects:
                    if ob.name not in p.objects:p.objects.link(ob)
                p.children.unlink(k)
        for ob in list(p.objects):   # a poster of this batch whose group changed in a re-edit leaves it
            if ob.name in mine_ and want.get(ob.name)!=p.name:p.objects.unlink(ob)
    for g,c in kids.items():   # every group also shows up in 'Poster Groups › Group · <name>' (all batches together)
        uc=next((p for p in users_ if p.name==g),None)
        if uc is not None:   # a collection the user made (e.g. 'Group1'): the group's posters go straight in there
            for ob in c.objects:
                if ob.name not in uc.objects:uc.objects.link(ob)
            continue
        # (no shared 'Poster Groups › Group · X' any more: the user found those collections useless)
        for sh in [p for p in bpy.data.collections if p.get('poster_shared_group') and c.name in p.children]:sh.children.unlink(c)
    root=next((c for c in bpy.data.collections if c.get('poster_groups_root')),None)
    for sh in list(root.children) if root else []:   # a shared group left with nothing in it goes away too (unless Poster Pin uses it)
        if sh.get('poster_shared_group') and not sh.all_objects and not pin_uses(sh):root.children.unlink(sh)
    return len({g for g in want.values() if g})


def picked_indices(s):
    """Rows whose name is selected; none selected = the highlighted row (nothing after None)."""
    idx=[i for i,f in enumerate(s.files) if f.picked]
    if idx or s.no_row:return idx
    return [max(0,min(s.active,len(s.files)-1))] if s.files else []


def checked_indices(s):
    """What Remove / Del / Group / Move to Cut act on: the checked images (the same ones that go into the layout).
    Nothing checked = the highlighted (blue) row."""
    idx=[i for i,f in enumerate(s.files) if f.selected]
    if idx or s.no_row:return idx
    return [max(0,min(s.active,len(s.files)-1))] if s.files else []


remove_indices=checked_indices


def list_row_set(self,v):
    self.no_row=False;self.active=max(0,v)   # Clicking a row brings the blue row back


def clear_picks(s):
    """None / click on empty space: no names selected and no blue row."""
    global SELECTION_BATCH
    SELECTION_BATCH=True
    try:
        for f in s.files:
            if f.picked:f.picked=False
    finally:SELECTION_BATCH=False
    s.no_row=True


class PA_OT_pick_all(bpy.types.Operator):
    bl_idname='poster_atlas.pick_all';bl_label=_T('Select All Names');bl_options={'UNDO'}
    bl_description=_T('Select (or deselect) every name in the list. Selection is for Group; checkboxes are not changed')
    pick:BoolProperty(default=True)
    def execute(self,context):
        global SELECTION_BATCH
        s=context.scene.poster_atlas
        if not self.pick:clear_picks(s);return {'FINISHED'}   # None: also no blue row
        SELECTION_BATCH=True   # no drag-select per item
        try:
            for f in s.files:f.picked=True
        finally:SELECTION_BATCH=False
        s.no_row=False
        return {'FINISHED'}


class PA_OT_select_all(bpy.types.Operator):
    bl_idname='poster_atlas.select_all';bl_label=_T('Check All Images');bl_options={'UNDO'}
    bl_description=_T('Check (or uncheck) every image: checked images go into the layout and the build')
    select:BoolProperty(default=True)
    def execute(self,context):
        global SELECTION_BATCH
        s=context.scene.poster_atlas
        SELECTION_BATCH=True
        try:
            for item in s.files:item.selected=self.select
        finally:SELECTION_BATCH=False
        build_scope_changed(s,context)
        return {'FINISHED'}


class PA_OT_drag_select(bpy.types.Operator):
    bl_idname='poster_atlas.drag_select';bl_label=_T('Box-select multiple images')
    index:IntProperty(options={'HIDDEN'})
    field:StringProperty(default='selected',options={'HIDDEN'})   # 'selected' = checkboxes, 'picked' = names
    def invoke(self,context,event):
        global SELECTION_TIMER
        if SELECTION_DRAGS or event.value=='RELEASE' or event.type not in {'LEFTMOUSE','MOUSEMOVE','INBETWEEN_MOUSEMOVE'}:return {'CANCELLED'}
        region=context.region
        visible=LIST_ROWS.get(region.as_pointer(),[]) if region else []
        if not visible or self.index not in visible:return {'CANCELLED'}
        self.settings=context.scene.poster_atlas;self.area=context.area;self.region=region;self.window=context.window
        fl=self.field if self.field in ('selected','picked') else 'selected';self.field=fl
        self.original=[getattr(f,fl) for f in self.settings.files];self.paint=getattr(self.settings.files[self.index],fl)
        self.original[self.index]=not self.paint
        if fl=='picked' and not (event.ctrl or event.shift):   # Plain click on a name: select just this one (then drag for more); Ctrl/Shift adds
            global SELECTION_BATCH
            SELECTION_BATCH=True
            try:
                for k,f in enumerate(self.settings.files):
                    v=k==self.index
                    if f.picked!=v:f.picked=v
            finally:SELECTION_BATCH=False
            self.paint=True
        if fl=='picked':self.settings.active=self.index   # The name button takes the click, so make this the current row (preview, blue row) ourselves
        self.settings.no_row=False   # dragging brings the blue row back (a -1 row would make Blender jump the list to the top on release)
        self.mouse_x=event.mouse_x;self.mouse_y=event.mouse_y
        self.start_x=event.mouse_prev_press_x
        v0=region.view2d.region_to_view(0,0);v1=region.view2d.region_to_view(0,100)
        self.row_height=20*context.preferences.system.ui_scale*100/max(.001,abs(v1[1]-v0[1]))
        self.top=event.mouse_prev_press_y+(self.index-min(visible)+.5)*self.row_height
        self.bottom=self.top-len(visible)*self.row_height;self.last=self.index;self.closed=False
        self.timer=context.window_manager.event_timer_add(.05,window=context.window)
        SELECTION_TIMER=self.timer;self.next_scroll=time.monotonic()+.10
        SELECTION_DRAGS.append(self);context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    def finish(self,cancel=False):
        global SELECTION_BATCH,SELECTION_TIMER
        if self.closed:return
        self.closed=True;bpy.context.window_manager.event_timer_remove(self.timer)
        SELECTION_TIMER=None
        if cancel:
            SELECTION_BATCH=True
            try:
                for item,selected in zip(self.settings.files,self.original):setattr(item,self.field,selected)
            finally:SELECTION_BATCH=False
        if self in SELECTION_DRAGS:SELECTION_DRAGS.remove(self)
        build_scope_changed(self.settings,bpy.context);self.area.tag_redraw()
    def paint_to(self,index):
        s=self.settings
        if not s.files:return
        index=max(0,min(len(s.files)-1,index))
        for i in range(min(self.last,index),max(self.last,index)+1):setattr(s.files[i],self.field,self.paint)
        self.last=index;s.active=index;self.area.tag_redraw()
    def modal(self,context,event):
        if self.closed:return {'CANCELLED','PASS_THROUGH'}
        if event.type=='LEFTMOUSE' and event.value=='RELEASE':self.finish();return {'FINISHED','PASS_THROUGH'}
        if event.type=='WINDOW_DEACTIVATE':self.finish();return {'FINISHED','PASS_THROUGH'}
        if event.type=='TIMER' and selection_button_held() is False:self.finish();return {'FINISHED','PASS_THROUGH'}
        if event.type in {'ESC','RIGHTMOUSE'} and event.value=='PRESS':self.finish(True);return {'CANCELLED','PASS_THROUGH'}
        if self.area not in list(context.screen.areas):self.finish();return {'CANCELLED'}
        # Every event carries the current mouse position. Blender's own checkbox drag-toggle swallows the mouse moves,
        # so read it from the timer ticks too; otherwise reaching the list edge is never noticed and it never scrolls.
        self.mouse_x=event.mouse_x;self.mouse_y=event.mouse_y
        visible=LIST_ROWS.get(self.region.as_pointer(),[])
        if visible and abs(self.mouse_x-self.start_x)<60*context.preferences.system.ui_scale:
            if event.type in {'MOUSEMOVE','INBETWEEN_MOUSEMOVE'}:
                offset=int((self.top-self.mouse_y)/self.row_height)
                self.paint_to(visible[min(len(visible)-1,max(0,offset))])
            elif event.type=='TIMER' and time.monotonic()>=self.next_scroll:
                # Blender's Event has no timer attribute. Other add-ons may also
                # emit TIMER events, so throttle by elapsed time instead.
                self.next_scroll=time.monotonic()+.10
                # Past the list edge: keep going one row per tick (the list itself can't be scrolled from Python)
                if self.mouse_y<=self.bottom+self.row_height*.35:self.paint_to(max(self.last,max(visible))+1)
                elif self.mouse_y>=self.top-self.row_height*.35:self.paint_to(min(self.last,min(visible))-1)
                else:   # Inside the list: follow the mouse too (the name buttons swallow the mouse moves while dragging)
                    offset=int((self.top-self.mouse_y)/self.row_height)
                    self.paint_to(visible[min(len(visible)-1,max(0,offset))])
        return {'RUNNING_MODAL'}


class PA_File(bpy.types.PropertyGroup):
    path:StringProperty(subtype='FILE_PATH')
    quarter_turns:IntProperty(name=_T('Rotate Image'),default=0,min=0,max=3)
    selected:BoolProperty(name=_T('Select Images to Build'),default=False,description=_T('Checked images go into the layout and the build; Remove / Del, Group and Move to Cut use them too. Drag over the boxes for several. The blue row is the preview target.'),update=file_selection_changed)
    picked:BoolProperty(name=_T('Select'),default=False,description=_T('Internal (older name selection, no longer shown)'),update=file_pick_changed)
    group:StringProperty(name=_T('Group'),default='',description=_T('Build puts each group in its own collection inside the batch (e.g. Photos for the string, Notes for the wall), so Scatter can use them separately. Empty: stays in the batch itself'))


class PA_Color(bpy.types.PropertyGroup):
    color:FloatVectorProperty(name=_T('Color'),subtype='COLOR',size=3,min=0.,max=1.,default=(1.,1.,1.))
    use:BoolProperty(name=_T('Use'),default=True)


class PA_UL_palette(bpy.types.UIList):
    def draw_item(self,context,layout,data,item,icon,active_data,active_propname,index):
        row=layout.row(align=True);row.prop(item,'use',text=_T(''));row.prop(item,'color',text=_T(''))


def res_label(res):
    res=int(res);return '2K' if res==2048 else '4K' if res==4096 else '%d px'%res


def set_resolution(s,res):
    """Set the texture size, including custom sizes (stored in custom_resolution)."""
    res=int(res)
    if res not in (2048,4096) and s.custom_resolution!=res:s.custom_resolution=res
    if s.resolution!=str(res):s.resolution=str(res)


_RES_ITEMS=[]
def resolution_items(self,context):
    c=int(getattr(self,'custom_resolution',3072) or 3072)
    items=[('2048','2K · 2048','2048 × 2048 px texture',0),('4096','4K · 4096','4096 × 4096 px texture',1)]
    if c not in (2048,4096):items.append((str(c),'Custom · %d'%c,'%d × %d px texture'%(c,c),2))
    _RES_ITEMS[:]=items;return _RES_ITEMS   # keep the strings alive for Blender


def custom_resolution_changed(self,context):
    if self.resolution!=str(self.custom_resolution):self.resolution=str(self.custom_resolution)


def resolution_changed(self,context):
    """If the resolution is changed in the panel while the layout editor is open, move the current layout over right away."""
    res=int(self.resolution)
    for e in list(CUT_EDITORS):
        if not getattr(e,'layout_mode',False) or getattr(e,'closed',False) or e.w==res:continue
        e.change_resolution(res)
        if e.w!=res:set_resolution(self,e.w)   # If it didn't fit and couldn't change, revert the panel value too


class PA_Settings(bpy.types.PropertyGroup):
    job_name:StringProperty(name=_T('Job Name'),default='',description=_T('Prefixed to texture file, object and collection names. Only letters, digits and _ are used; if empty, Poster is used.'))
    atlas_next:IntProperty(name=_T('Next Texture Number'),default=1,min=1)
    last_collection:PointerProperty(type=bpy.types.Collection)
    library_collection:PointerProperty(name=_T('Poster Library'),type=bpy.types.Collection)
    update_previous:BoolProperty(name=_T('Update Previous Build Batch'),default=False,description=_T('Keeps the source objects and IDs of the same images and updates meshes and textures. Existing sources removed from the list are kept.'))
    files:CollectionProperty(type=PA_File)
    cut_files:CollectionProperty(type=PA_File)
    cut_active:IntProperty(default=0)
    postit_pool:StringProperty(default='')   # Sticky-note random colors (JSON)
    strip_cols:IntProperty(name=_T('Strip Columns'),default=1,min=1,max=6)
    strip_rows:IntProperty(name=_T('Strip Rows'),default=4,min=1,max=8)
    strip_stagger:BoolProperty(name=_T('Stagger Columns'),default=False,description=_T('Every other column sits a little lower, like some photo booth strips'))
    strip_frame:EnumProperty(name=_T('Strip Frame'),items=_T_items([('WHITE','White',''),('BLACK','Black','')]),default='BLACK')
    layout_tab:EnumProperty(name=_T('Layout Tab'),items=_T_items([('PAPER','Paper','Paper sizes for posters and notes'),('PICTURE','Picture','Photo prints and instant films: card size, white border and film look')]),default='PAPER')
    list_tab:EnumProperty(name=_T('List'),items=_T_items([('TEXTURE','Texture Images','Images to turn into poster textures'),('CUT','Images to Cut','Source sheets with several images on one page')]),default='TEXTURE')
    active:IntProperty(default=0)
    batch_name:StringProperty(name=_T('Batch Name'),default='',description=_T('Name of the next batch collection (empty: Batch N · groups). Click it in the editor to change it'))
    group_count:IntProperty(name=_T('Groups'),default=2,min=1,max=8,description=_T('How many group buttons the Layout Editor shows'))
    group_drop:PointerProperty(name=_T('Drop a Collection'),type=bpy.types.Collection,poll=group_drop_poll,update=group_drop_changed,
                               description=_T('Drag a collection from the Outliner here (or pick one): the checked images get it as their group'))
    remove_after_build:BoolProperty(name=_T('Remove Built Images from List'),default=True,description=_T('After a successful Build, the images that went into it leave the image list, so only the ones still to do remain. Image files on disk are kept; Re-edit brings a batch back'))
    # What the image list shows as its blue row: the current image, or none while several names are selected
    # (then the selected names light up instead, so there is only one kind of highlight at a time)
    # While dragging it follows the current row, so the list scrolls along past its edge
    # None (or a click on empty space) clears it too: no_row hides the blue row until a row is clicked again
    list_row:IntProperty(get=lambda self:-1 if (self.no_row and not SELECTION_DRAGS) else self.active,set=list_row_set)   # -1 makes Blender scroll the list to the top, so only for None
    no_row:BoolProperty(default=False,options={'HIDDEN'})
    layout_plan:StringProperty(options={'HIDDEN'})
    custom_width:FloatProperty(name=_T('Width (mm)'),default=210,min=.1,max=10000,precision=1)
    custom_height:FloatProperty(name=_T('Height (mm)'),default=297,min=.1,max=10000,precision=1)
    layout_gap:IntProperty(name=_T('Spacing between images (px)'),default=16,min=0,max=1024)
    random_size_pct:IntProperty(name=_T('Random Size (±%)'),default=0,min=0,max=60,description=_T('Random Size: each selected image gets its own size within ± this percent of its current size, keeping its ratio'))
    background:EnumProperty(name=_T('Background'),items=_T_items([('WHITE','White','White background'),('BLACK','Black','Black background'),('TRANSPARENT','Transparent','Saves empty PNG areas as transparent.')]),default='WHITE')
    edit_mode:EnumProperty(name=_T('Edit Mode'),items=_T_items(EDIT_MODES),default='SCALE')
    cut_columns:IntProperty(name=_T('Cut Columns'),default=4,min=1,max=32)
    cut_rows:IntProperty(name=_T('Cut Rows'),default=2,min=1,max=32)
    chroma_inset:IntProperty(name=_T('Green Inset'),default=2,min=0,max=60,description=_T('Green trim: cut this many extra pixels inside every edge (removes the green fringe)'))
    cut_output_dir:StringProperty(name=_T('Cut PNG Folder'),subtype='DIR_PATH',description=_T('Saves into per-cut subfolders inside this folder. If empty, the texture folder is used.'))
    mode:EnumProperty(name=_T('Input Mode'),items=_T_items([('PACK','Combine Individual Images','Builds posters from several sources.'),('SPLIT','Split Grid Image','Splits a combined image into equal cells.')]),default='PACK')   # Hidden in the UI: sheet splitting is handled by the [Images to Cut] tab
    custom_resolution:IntProperty(name=_T('Custom Size (px)'),description=_T('Square texture size in pixels'),default=3072,min=256,max=8192,update=custom_resolution_changed)
    resolution:EnumProperty(name=_T('Output Resolution'),items=_T_items(resolution_items),default=0,update=resolution_changed)
    capacity:EnumProperty(name=_T('Texture Layout'),items=_T_items([('AUTO','Auto · fit image count','Puts all images in the list on one sheet. Count and rows/columns are recalculated as images are added or removed.')]+[(str(x),str(x)+'Split by Count','') for x in [2,4,6,9,16,24]]+[('CUSTOM','Set Rows/Columns','')]),default='AUTO')
    columns:IntProperty(name=_T('Cols'),default=3,min=1,max=32)
    rows:IntProperty(name=_T('Rows'),default=2,min=1,max=32)
    last_count:IntProperty(name=_T('Cells Used in Last Image'),description=_T('0 uses all cells of the last image. Row-major from the top.'),default=0,min=0,max=1024)
    split_inset:IntProperty(name=_T('Exclude Cell Inner Margin (px)'),description=_T('Excludes this many pixels from each of the four edges of each cell in the source image.'),default=0,min=0,max=1024)
    output_dir:StringProperty(name=_T('Save Folder'),subtype='DIR_PATH')
    pack_textures:BoolProperty(name=_T('Pack Textures into .blend'),default=True,description=_T('Saves external PNGs and also packs the image data. Save the .blend yourself.'))
    last_result:StringProperty()
    last_folder:StringProperty(subtype='DIR_PATH')
    paper_dir:StringProperty(name=_T('Extra Paper Texture Folder'),subtype='DIR_PATH',description=_T('Built-in paper textures ship with the addon. To use more of your own baked <name>_s<number>_normal.png textures, set that folder. If empty, only built-in textures are used.'))
    paper_set:EnumProperty(name=_T('Paper Texture'),items=_T_items(paper_set_items))
    paper_variant:IntProperty(name=_T('Variant'),default=0,min=0,max=63,description=_T('A different pattern (seed) of the same texture.'))
    paper_strength:FloatProperty(name=_T('Crumple Strength'),default=1.,min=0.,max=3.,precision=2)
    paper_tile_mm:FloatProperty(name=_T('Pattern Size (mm)'),default=300.,min=10.,max=5000.,precision=0,description=_T('Real-world size one texture tile covers. Wrinkles look the same size regardless of poster size.'))
    paper_ao:FloatProperty(name=_T('Crumple Shading'),default=.5,min=0.,max=1.,precision=2)
    paper_auto:BoolProperty(name=_T('Auto-apply on Build'),default=True)
    color_fade:FloatProperty(name=_T('Fade'),default=0.,min=0.,max=1.,precision=2,description=_T('How much the print has faded in sunlight.'))
    color_yellow:FloatProperty(name=_T('Yellowing'),default=0.,min=0.,max=1.,precision=2,description=_T('Yellowing of old paper.'))
    color_saturation:FloatProperty(name=_T('Saturation'),default=1.,min=0.,max=2.,precision=2)
    color_hue:FloatProperty(name=_T('Hue Shift'),default=0.,min=-.5,max=.5,precision=2)
    color_random:FloatProperty(name=_T('Per-Poster Variation'),default=.3,min=0.,max=1.,precision=2,description=_T('Varies fade and yellowing per poster.'))
    tint_mode:EnumProperty(name=_T('Paper Color'),items=_T_items([('OFF','Off','Original image color'),('SINGLE','Single Color','All posters on the same paper color'),('PALETTE','Palette Random','Each poster picks one from the palette')]),default='OFF')
    tint_color:FloatVectorProperty(name=_T('Color'),subtype='COLOR',size=3,min=0.,max=1.,default=srgb(255,238,110))
    tint_strength:FloatProperty(name=_T('Strength'),default=1.,min=0.,max=1.,precision=2)
    palette:CollectionProperty(type=PA_Color)
    palette_active:IntProperty(default=0)
    ink_mode:EnumProperty(name=_T('Ink Color'),items=_T_items([('OFF','Off','Original image color'),('SINGLE','Single Color','All dark parts in the same color'),('PALETTE','Palette Random','Each poster picks one from the ink palette')]),default='OFF')
    ink_color:FloatVectorProperty(name=_T('Color'),subtype='COLOR',size=3,min=0.,max=1.,default=srgb(25,45,140))
    ink_strength:FloatProperty(name=_T('Strength'),default=1.,min=0.,max=1.,precision=2)
    ink_palette:CollectionProperty(type=PA_Color)
    ink_palette_active:IntProperty(default=0)
    wear_amount:FloatProperty(name=_T('Wear'),default=0.,min=0.,max=1.,precision=2,description=_T('How much the print peels off to reveal paper.'))
    wear_edge_mm:FloatProperty(name=_T('Edge Width (mm)'),default=15.,min=0.,max=300.,precision=0)
    wear_crease:FloatProperty(name=_T('Crease Wear'),default=.5,min=0.,max=1.,precision=2)
    wear_random:FloatProperty(name=_T('Per-Poster Variation'),default=.5,min=0.,max=1.,precision=2)
    fray_amount:FloatProperty(name=_T('Worn Edges'),default=0.,min=0.,max=1.,precision=2,description=_T('Actually eats into the paper border so the silhouette becomes ragged.'))
    fray_depth_mm:FloatProperty(name=_T('Depth (mm)'),default=5.,min=0.,max=50.,precision=1,description=_T('How far the torn line wiggles inward. The pattern size scales with this too.'))
    fray_corner:FloatProperty(name=_T('Corner Focus'),default=.6,min=0.,max=1.,precision=2,description=_T('Wears the corners more.'))
    fray_random:FloatProperty(name=_T('Per-Poster Variation'),default=.5,min=0.,max=1.,precision=2)
    fray_fiber:FloatProperty(name=_T('Torn Layer (white cross-section)'),default=.8,min=0.,max=1.,precision=2,description=_T('White paper fibers exposed inside the worn edge.'))
    hole_amount:FloatProperty(name=_T('Hole Amount'),default=0.,min=0.,max=1.,precision=2,description=_T('Amount of holes torn out of the middle of the paper. At 1, up to about half the area is punched.'))
    hole_rim:FloatProperty(name=_T('White Rim'),default=.03,min=0.,max=.15,precision=3,description=_T('Width of the white paper band exposed around holes.'))
    hole_size_mm:FloatProperty(name=_T('Pattern Size (mm)'),default=400.,min=20.,max=5000.,precision=0,description=_T('Real-world size one hole-pattern tile covers. Smaller means finer, more numerous holes.'))
    peel_amount:FloatProperty(name=_T('Print Peel'),default=0.,min=0.,max=1.,precision=2,description=_T('Wide areas where the print layer peeled off, exposing white paper. Holes always form inside these areas.'))
    hole_soft:FloatProperty(name=_T('Edge Softness'),default=.004,min=.002,max=.15,precision=3,description=_T('Small values give crisp knife-cut edges; large values bleed softly like clouds.'))
    hole_random:FloatProperty(name=_T('Per-Poster Variation'),default=.6,min=0.,max=1.,precision=2,description=_T('Higher values mix posters without holes and heavily punched ones.'))
    fray_fiber_mm:FloatProperty(name=_T('Fiber Length (mm)'),default=1.2,min=0.,max=10.,precision=1,description=_T('Maximum length of fibers sticking out past the cut line.'))
    sd_dir:StringProperty(name=_T('Substance Designer Folder'),subtype='DIR_PATH',description=_T('If empty, looks in the default install location.'))
    bake_size:EnumProperty(name=_T('Bake Resolution'),items=_T_items([('10','1K',''),('11','2K',''),('12','4K','')]),default='11')
    bake_variants:IntProperty(name=_T('Variant Count'),default=4,min=1,max=16)


def pa_list_filter(ul,items):
    """Search / A→Z sort for the image lists, by file name (the items have only a path). Invert and reverse are applied by Blender."""
    import fnmatch
    names=[os.path.basename(i.path).casefold() for i in items]
    flags=[]
    if ul.filter_name:
        pat='*%s*'%ul.filter_name.casefold()
        flags=[ul.bitflag_filter_item if fnmatch.fnmatchcase(n,pat) else 0 for n in names]
    order=[]
    if ul.use_filter_sort_alpha:
        ranked=sorted(range(len(names)),key=lambda i:names[i]);order=[0]*len(names)
        for pos,i in enumerate(ranked):order[i]=pos
    return flags,order


class PA_UL_files(bpy.types.UIList):
    def draw_filter(self,context,layout):
        # Search · check-all toggle · invert · A→Z · reverse
        row=layout.row(align=True)
        files=context.scene.poster_atlas.files;on=bool(files) and all(f.selected for f in files)
        row.operator('poster_atlas.select_all',text=_T(''),icon='CHECKBOX_HLT' if on else 'CHECKBOX_DEHLT').select=not on   # under the checkbox column
        row.prop(self,'filter_name',text=_T(''),icon='VIEWZOOM')
        row.prop(self,'use_filter_invert',text=_T(''),icon='ARROW_LEFTRIGHT')
        sub=row.row(align=True)
        sub.prop(self,'use_filter_sort_alpha',text=_T(''),icon='SORTALPHA')
        sub.prop(self,'use_filter_sort_reverse',text=_T(''),icon='SORT_DESC' if self.use_filter_sort_reverse else 'SORT_ASC')
    def filter_items(self,context,data,propname):
        LIST_ROWS[context.region.as_pointer()]=[]
        return pa_list_filter(self,getattr(data,propname))
    def draw_item(self,context,layout,data,item,icon,active_data,active_propname,index):
        LIST_ROWS.setdefault(context.region.as_pointer(),[]).append(index)
        layout.prop(item,'selected',text=_T(''))
        # The whole row (name + group) is one selection button, so a selected image lights up across the row
        name=os.path.splitext(os.path.basename(item.path))[0]   # file name only: a row number in front looked like part of the name
        g=item.group.strip()
        if g:   # the group in its own column with its color, so it stays visible even when the name is long
            sp=layout.split(factor=.6,align=True);sp.label(text=_T(name));sp.label(text=_T(g),icon=group_icon(g));return
        layout.label(text=_T(name))   # click = blue row (preview); the checkbox decides what Build / Remove / Group use


class PA_OT_add(bpy.types.Operator,ImportHelper):
    bl_idname='poster_atlas.add';bl_label=_T('Add Images');bl_options={'UNDO'}
    filename_ext=''
    files:CollectionProperty(type=bpy.types.OperatorFileListElement)
    directory:StringProperty(subtype='DIR_PATH')
    filter_glob:StringProperty(default='*.png;*.jpg;*.jpeg;*.webp;*.tif;*.tiff;*.bmp;*.tga;*.exr',options={'HIDDEN'})
    target:EnumProperty(items=_T_items([('TEXTURE','For Textures',''),('CUT','For Cutting','')]),default='TEXTURE',options={'HIDDEN','SKIP_SAVE'})
    def execute(self,context):
        s=context.scene.poster_atlas
        coll=s.cut_files if self.target=='CUT' else s.files
        existing={os.path.normcase(bpy.path.abspath(f.path)) for f in coll}
        paths=[os.path.join(self.directory,f.name) for f in self.files] or [self.filepath]
        for p in sorted(paths,key=lambda x:os.path.basename(x).casefold()):
            if os.path.splitext(p)[1].lower() in EXTS and os.path.normcase(p) not in existing:
                coll.add().path=p;existing.add(os.path.normcase(p))
        if self.target=='CUT':s.cut_active=max(0,len(s.cut_files)-1)
        return {'FINISHED'}


class PA_OT_drop_images(bpy.types.Operator):
    """Image files dropped on the Poster Atlas sidebar go into the list of the open tab (Textures or Cut)"""
    bl_idname='poster_atlas.drop_images';bl_label=_T('Add Dropped Images');bl_options={'UNDO','INTERNAL'}
    directory:StringProperty(subtype='DIR_PATH',options={'SKIP_SAVE','HIDDEN'})
    files:CollectionProperty(type=bpy.types.OperatorFileListElement,options={'SKIP_SAVE','HIDDEN'})
    filepath:StringProperty(subtype='FILE_PATH',options={'SKIP_SAVE','HIDDEN'})
    def invoke(self,context,event):
        if self.directory or self.filepath:return self.execute(context)
        return {'CANCELLED'}
    def execute(self,context):
        s=context.scene.poster_atlas;cut=s.list_tab=='CUT'
        coll=s.cut_files if cut else s.files
        existing={os.path.normcase(bpy.path.abspath(f.path)) for f in coll}
        paths=[os.path.join(self.directory,f.name) for f in self.files if f.name] or ([self.filepath] if self.filepath else [])
        added=0;skipped=0
        for p in sorted(paths,key=lambda x:os.path.basename(x).casefold()):
            if os.path.splitext(p)[1].lower() in EXTS and os.path.normcase(p) not in existing:
                coll.add().path=p;existing.add(os.path.normcase(p));added+=1
            else:skipped+=1
        if added:
            if cut:s.cut_active=len(s.cut_files)-1
            else:s.active=len(s.files)-1;build_scope_changed(s,context)
        self.report({'INFO'},_T('Added %d image(s) to the %s list'%(added,'Cut' if cut else 'Textures')+(' · %d skipped (already in the list or not an image)'%skipped if skipped else '')))
        for a in context.screen.areas:
            if a.type=='VIEW_3D':a.tag_redraw()
        return {'FINISHED'} if added else {'CANCELLED'}


_TEXT_FONT_ITEMS=[]


def text_font_items(self,context):
    if not _TEXT_FONT_ITEMS:_TEXT_FONT_ITEMS.extend((p,nm,p) for p,nm in text_font_list())
    return _TEXT_FONT_ITEMS or [('NONE','No fonts found','')]


class PA_OT_text_font(bpy.types.Operator):
    bl_idname='poster_atlas.text_font';bl_label=_T('Font');bl_options={'INTERNAL'}
    bl_description=_T('Pick any font installed on this computer for the text (type to search)')
    bl_property='font'
    font:EnumProperty(name=_T('Font'),items=_T_items(text_font_items))
    def invoke(self,context,event):
        context.window_manager.invoke_search_popup(self);return {'RUNNING_MODAL'}
    def execute(self,context):
        e=next((e for e in reversed(CUT_EDITORS) if getattr(e,'layout_mode',False) and not getattr(e,'closed',False)),None)
        if e is None or self.font=='NONE':return {'CANCELLED'}
        e.text_button(('F',self.font));return {'FINISHED'}


class PA_OT_caption(bpy.types.Operator):
    bl_idname='poster_atlas.caption';bl_label=_T('Caption');bl_options={'INTERNAL'}
    bl_description=_T('Write a handwritten caption on the bottom margin of the selected photo cards (instant formats). Empty text removes it')
    text:StringProperty(name=_T('Text'),default='',description=_T('" / " starts a second line. Latin letters only: the handwriting fonts have no Korean'))
    font:EnumProperty(name=_T('Handwriting'),items=_T_items([(k,v[0],'') for k,v in CAPTION_FONTS.items()]),default='INK')
    ink:EnumProperty(name=_T('Pen'),items=_T_items([(k,v[0],'') for k,v in CAPTION_INKS.items()]),default='BLACK')
    def editor(self):
        eds=[e for e in CUT_EDITORS if getattr(e,'layout_mode',False) and not getattr(e,'closed',False)]
        return eds[-1] if eds else None
    def invoke(self,context,event):
        e=self.editor()
        if e is None:return {'CANCELLED'}
        ph=e.photo_get(e.selected) or {}
        self.text=(ph.get('caption') or '').replace('\n',' / ');self.font=ph.get('cap_font') or getattr(e,'cap_font_last','INK');self.ink=ph.get('cap_ink') or getattr(e,'cap_ink_last','BLACK')
        return context.window_manager.invoke_props_dialog(self,width=380,title=_T('Caption on the photo card'),confirm_text='Write')
    def draw(self,context):
        l=self.layout;l.prop(self,'text')
        r=l.row(align=True);r.prop(self,'font',text=_T(''))
        r=l.row(align=True);r.prop(self,'ink',expand=True)
        l.label(text=_T('" / " starts a new line · empty text removes the caption'),icon='INFO')
    def execute(self,context):
        e=self.editor()
        if e is None:return {'CANCELLED'}
        idx=[i for i in getattr(e,'selection',{e.selected}) if 0<=i<len(e.rects)]
        cards=[i for i in idx if (e.photo_get(i) or {}).get('frame')]
        if not cards:self.report({'WARNING'},_T('Captions go on photo cards: pick a Format (e.g. Instant Mini) first'));return {'CANCELLED'}
        txt='\n'.join(s.strip() for s in self.text.replace(' / ','\n').split('\n')).strip()
        e.remember_layout();e.cap_font_last=self.font;e.cap_ink_last=self.ink
        e.photo_set(cards,caption=(txt,self.font,self.ink))
        if txt:caption_mask(txt,self.font)
        e.area.tag_redraw()
        self.report({'INFO'},_T(('Caption on %d card(s)'%len(cards) if txt else 'Caption removed from %d card(s)'%len(cards))+(' · %d without a photo card skipped'%(len(idx)-len(cards)) if len(idx)>len(cards) else '')))
        return {'FINISHED'}


class PA_OT_pick_all_key(bpy.types.Operator):
    """Ctrl+A / Alt+A over the Poster Atlas sidebar: check / uncheck every image"""
    bl_idname='poster_atlas.pick_all_key';bl_label=_T('Select All Images (Ctrl+A)');bl_options={'UNDO','INTERNAL'}
    deselect:BoolProperty(default=False,options={'SKIP_SAVE'})
    @classmethod
    def poll(cls,context):   # Only over the Poster Atlas sidebar; elsewhere A keeps its normal meaning (select all objects)
        r=context.region;s=getattr(context.scene,'poster_atlas',None)
        if not s or not r or r.type!='UI' or not context.area or context.area.type!='VIEW_3D' or SELECTION_DRAGS:return False
        if getattr(r,'active_panel_category','Poster Print') not in ('Poster Print',None,''):return False
        return bool(s.files) and s.list_tab!='CUT'
    def execute(self,context):
        r=bpy.ops.poster_atlas.select_all(select=not self.deselect)
        context.area.tag_redraw();return r


class PA_OT_pick_clear(bpy.types.Operator):
    """Click on empty space in the Poster Atlas sidebar: clear the name selection"""
    bl_idname='poster_atlas.pick_clear';bl_label=_T('Clear Name Selection');bl_options={'INTERNAL'}
    @classmethod
    def poll(cls,context):
        r=context.region;s=getattr(context.scene,'poster_atlas',None)
        if not s or not r or r.type!='UI' or not context.area or context.area.type!='VIEW_3D' or SELECTION_DRAGS:return False
        if getattr(r,'active_panel_category','Poster Print') not in ('Poster Print',None,''):return False
        return any(f.picked for f in s.files)   # names are no longer selectable: only tidy up leftovers, keep the blue row
    def invoke(self,context,event):
        clear_picks(context.scene.poster_atlas);context.scene.poster_atlas.no_row=False
        context.area.tag_redraw()
        return {'PASS_THROUGH'}   # never eat the click


class PA_OT_list_key_remove(bpy.types.Operator):
    """Del / X over the Poster Atlas sidebar: remove the checked images (nothing checked: the highlighted one) from the open list. Source files are kept"""
    bl_idname='poster_atlas.list_key_remove';bl_label=_T('Remove Image from List');bl_options={'UNDO','INTERNAL'}
    @classmethod
    def poll(cls,context):
        r=context.region;s=getattr(context.scene,'poster_atlas',None)
        if not s or not r or r.type!='UI' or not context.area or context.area.type!='VIEW_3D':return False
        if getattr(r,'active_panel_category','Poster Print') not in ('Poster Print',None,''):return False
        return bool(s.cut_files if s.list_tab=='CUT' else s.files)
    def execute(self,context):
        s=context.scene.poster_atlas
        if s.list_tab=='CUT':return bpy.ops.poster_atlas.cut_list(action='REMOVE')
        return bpy.ops.poster_atlas.list_edit(action='REMOVE')


ADDON_KEYMAPS=[]


def on_print_tab(context):
    """The mouse is over the Poster Print tab of the 3D View sidebar."""
    a=context.area;r=context.region
    return bool(a and a.type=='VIEW_3D' and r and r.type=='UI' and getattr(r,'active_panel_category','Poster Print') in ('Poster Print',None,''))


DROP_SWAPS=[]   # (Blender's handler, our stand-in) while the add-on is on


def _quiet_handler(orig):
    """Same handler as Blender's, except it stays out of drops on the Poster Print tab."""
    f=orig.__dict__['poll_drop'].__func__
    def poll_drop(cls,context):return (not on_print_tab(context)) and f(cls,context)
    return type(orig.__name__+'_PA',(orig,),{'bl_idname':orig.bl_idname,'poll_drop':classmethod(poll_drop)})


def quiet_builtin_drops():
    """Blender's own image drops (Add Empty Image / Camera Background) also answer a drop on the sidebar, so Blender
    asks which one to use. They are swapped (unregister + register, the supported way) for stand-ins that ignore drops on
    the Poster Print tab; everywhere else they work as before. Never edit poll_drop on a registered class: Blender keeps a
    pointer to it and a real drop then crashes (2026-10-12)."""
    if DROP_SWAPS:return
    try:import bl_operators.view3d as v3
    except Exception:return
    for name in ('VIEW3D_FH_empty_image','VIEW3D_FH_camera_background_image'):
        orig=getattr(v3,name,None)
        if orig is None or getattr(bpy.types,name,None) is not orig:continue
        sub=_quiet_handler(orig)
        try:bpy.utils.unregister_class(orig)
        except Exception:continue
        try:bpy.utils.register_class(sub);DROP_SWAPS.append((orig,sub))
        except Exception:
            try:bpy.utils.register_class(orig)
            except Exception:pass


def restore_builtin_drops():
    for orig,sub in reversed(DROP_SWAPS):
        try:bpy.utils.unregister_class(sub)
        except Exception:pass
        try:bpy.utils.register_class(orig)
        except Exception:pass
    DROP_SWAPS.clear()


class PA_FH_images(bpy.types.FileHandler):
    bl_idname='PA_FH_images';bl_label=_T('Poster Print: add to list')
    bl_import_operator='poster_atlas.drop_images'
    bl_file_extensions='.png;.jpg;.jpeg;.webp;.tif;.tiff;.bmp;.tga;.exr'
    @classmethod
    def poll_drop(cls,context):
        # Only when dropped on the Poster Print tab of the 3D View sidebar; drops on the viewport keep Blender's default behavior
        return on_print_tab(context)


class PA_OT_list(bpy.types.Operator):
    bl_idname='poster_atlas.list_edit';bl_label=_T('Edit Image List');bl_options={'UNDO'}
    action:EnumProperty(items=_T_items([('REMOVE','Remove Checked Images','Removes the checked images from the list. Nothing checked: the highlighted one. Source files are kept.'),('CLEAR','Clear List',''),('UP','Up',''),('DOWN','Down','')]))
    @classmethod
    def description(cls,context,properties):
        if properties.action=='REMOVE':return 'Removes the checked images from the list (nothing checked: the highlighted one). Source files are not deleted. Ctrl+Z brings them back.'
        return 'Reorder or clear the image list.'
    def execute(self,context):
        s=context.scene.poster_atlas;n=len(s.files)
        if not n:return {'CANCELLED'}
        i=max(0,min(s.active,n-1))
        if self.action=='CLEAR':s.files.clear();s.active=0;self.report({'INFO'},_T('Cleared the list · Ctrl+Z to undo'))
        elif self.action=='REMOVE':
            indices=remove_indices(s)   # checked images (what goes in = what comes out); nothing checked: the highlighted row
            if not indices:self.report({'INFO'},_T('Nothing checked · check the images to remove'));return {'CANCELLED'}
            active=i-sum(index<i for index in indices)
            for index in reversed(indices):s.files.remove(index)
            s.active=max(0,min(active,len(s.files)-1))
            self.report({'INFO'},_T('Removed %d image%s from the list · source files kept · Ctrl+Z to undo'%(len(indices),'' if len(indices)==1 else 's')))
        else:
            j=max(0,min(n-1,i+(-1 if self.action=='UP' else 1)));s.files.move(i,j);s.active=j
        build_scope_changed(s,context)
        return {'FINISHED'}


class PA_UL_cut_files(bpy.types.UIList):
    def filter_items(self,context,data,propname):
        return pa_list_filter(self,getattr(data,propname))
    def draw_item(self,context,layout,data,item,icon,active_data,active_propname,index):
        layout.label(text=_T(os.path.splitext(os.path.basename(item.path))[0]))


class PA_OT_cut_list(bpy.types.Operator):
    bl_idname='poster_atlas.cut_list';bl_label=_T('Edit Cut List');bl_options={'UNDO'}
    action:EnumProperty(items=_T_items([('REMOVE','Remove Current Item','Removes it only from the cut list. Source files are kept.'),('CLEAR','Clear List','Clears the cut list. Source files are kept.'),
                               ('UP','Up',''),('DOWN','Down',''),
                               ('TO_TEXTURE','Move to Texture Images','Moves the current image to the texture list without cutting.'),
                               ('FROM_TEXTURE','Move to Cut List','Moves the checked texture images (or the highlighted row) to the cut list.')]))
    def execute(self,context):
        s=context.scene.poster_atlas
        key=lambda f:os.path.normcase(bpy.path.abspath(f.path))
        if self.action=='FROM_TEXTURE':
            if not s.files:return {'CANCELLED'}
            idx=checked_indices(s)   # checked images (nothing checked: the highlighted row)
            have={key(f) for f in s.cut_files}
            for i in idx:
                f=s.files[i]
                if key(f) not in have:
                    it=s.cut_files.add();it.path=f.path;it.quarter_turns=f.quarter_turns;have.add(key(f))
            for i in reversed(idx):s.files.remove(i)
            s.active=max(0,min(s.active,len(s.files)-1));s.cut_active=max(0,len(s.cut_files)-1);s.list_tab='CUT'
            build_scope_changed(s,context)
            self.report({'INFO'},_T('Moved %d to the cut list.'%len(idx)));return {'FINISHED'}
        n=len(s.cut_files)
        if not n:return {'CANCELLED'}
        i=max(0,min(s.cut_active,n-1))
        if self.action=='CLEAR':s.cut_files.clear();s.cut_active=0
        elif self.action=='REMOVE':s.cut_files.remove(i);s.cut_active=max(0,min(i,len(s.cut_files)-1))
        elif self.action=='TO_TEXTURE':
            f=s.cut_files[i]
            if key(f) not in {key(x) for x in s.files}:
                it=s.files.add();it.path=f.path;it.quarter_turns=f.quarter_turns
            s.cut_files.remove(i);s.cut_active=max(0,min(i,len(s.cut_files)-1))
            build_scope_changed(s,context)
        else:
            j=max(0,min(n-1,i+(-1 if self.action=='UP' else 1)));s.cut_files.move(i,j);s.cut_active=j
        return {'FINISHED'}


def draw_cut_tab(layout,s,context):
    layout.operator('poster_atlas.add',text=_T('Add Images to Cut'),icon='FILE_IMAGE').target='CUT'
    col=layout.column()
    row=col.row()   # Same layout as the Textures list: list on the left, buttons in a column on the right
    row.template_list('PA_UL_cut_files','',s,'cut_files',s,'cut_active',rows=4)   # rows = minimum; drag the grip under the list to resize
    side=row.column(align=True)
    side.operator('poster_atlas.cut_list',text=_T(''),icon='TRIA_UP').action='UP'
    side.operator('poster_atlas.cut_list',text=_T(''),icon='TRIA_DOWN').action='DOWN'
    side.separator()
    side.operator('poster_atlas.cut_list',text=_T(''),icon='REMOVE').action='REMOVE'
    side.operator('poster_atlas.cut_list',text=_T(''),icon='X').action='CLEAR'
    col.label(text=_T('%d images to cut'%len(s.cut_files)))
    if s.cut_files:
        item=s.cut_files[max(0,min(s.cut_active,len(s.cut_files)-1))]
        box=layout.box();box.label(text=_T('Preview'))
        try:icon=preview_icon(file_path(item))
        except (OSError,RuntimeError,ValueError):icon=0
        if icon:
            r=box.row();r.alignment='CENTER'
            ui_scale=max(1.,context.preferences.system.ui_scale)
            width=max(40.,min(240.,context.region.width/ui_scale-60))
            r.template_icon(icon_value=icon,scale=width/20.)
        else:box.label(text=_T('Cannot read the image.'),icon='ERROR')
        box.label(text=_T(os.path.basename(item.path)))
    box=layout.box();box.label(text=_T('Cut Selected Image'),icon='IMAGE_DATA')
    box.operator('poster_atlas.cut',icon='EDITMODE_HLT')
    box.label(text=_T('Cut PNG Folder'),icon='FILE_FOLDER')
    box.prop(s,'cut_output_dir',text=_T(''))


class PA_OT_rotate(bpy.types.Operator):
    bl_idname='poster_atlas.rotate';bl_label=_T('Rotate Image 90°');bl_options={'UNDO'}
    bl_description=_T('Rotates the current preview image. The source file is kept; the rotation is used when building textures and posters.')
    step:IntProperty(default=1)
    @classmethod
    def poll(cls,context):
        return bool(context.scene.poster_atlas.files) and not any(not e.preview_only and not e.layout_mode for e in CUT_EDITORS)
    def execute(self,context):
        try:rotate_item(context.scene.poster_atlas,self.step)
        except Exception as exc:self.report({'ERROR'},_T(str(exc)));return {'CANCELLED'}
        for ar in context.screen.areas:ar.tag_redraw()
        return {'FINISHED'}

class PA_OT_photo_custom(bpy.types.Operator):
    bl_idname='poster_atlas.photo_custom';bl_label=_T('Picture Settings')
    bl_description=_T('Custom white border (mm) or print surface (roughness / metallic) for the selected pictures')
    kind:EnumProperty(items=_T_items([('BORDER','Custom Border',''),('FINISH','Print Surface',''),('PAPER','Paper Surface','')]))
    paper_rough:FloatProperty(name=_T('Paper Roughness'),default=.55,min=0.,max=1.,precision=2,description=_T('Low = shiny coated paper, high = plain matte paper. Glossy 0.25 · Silk 0.4 · Satin 0.55 · Matte 0.85'))
    side:FloatProperty(name=_T('Sides (mm)'),default=4.5,min=0.,max=100.,precision=1)
    top:FloatProperty(name=_T('Top (mm)'),default=6.5,min=0.,max=100.,precision=1)
    bottom:FloatProperty(name=_T('Bottom (mm)'),default=21.5,min=0.,max=200.,precision=1)
    rough:FloatProperty(name=_T('Photo Roughness'),default=.62,min=0.,max=1.,precision=2,description=_T('Low = shiny glossy print, high = matte. Matte 0.62 · Satin 0.45 · Silk 0.35 · Glossy 0.18'))
    frame_rough:FloatProperty(name=_T('Border Roughness'),default=.42,min=0.,max=1.,precision=2,description=_T('The white border of instant film and prints is a little less shiny than the picture'))
    metal:FloatProperty(name=_T('Metallic'),default=0.,min=0.,max=1.,precision=2,description=_T('Photo paper is not metal: keep 0 for a real print. Raise only for foil / metallic paper looks'))

    def invoke(self,context,event):
        self.editor=next((e for e in CUT_EDITORS if e.layout_mode),None)
        if self.editor is None:return {'CANCELLED'}
        e=self.editor;i=e.selected if e.rects else 0;ph=e.photo_get(i) or {}
        if self.kind=='BORDER':self.side,self.top,self.bottom=[round(v,1) for v in e.photo_border_mm(i)]
        elif self.kind=='PAPER':
            sv=fx_clean(e.effects[i] if i<len(e.effects) else None).get('s_rough');self.paper_rough=sv if sv is not None else PAPER_FINISHES['MATTE'][1]
        elif ph.get('p_rough') is not None:self.rough,self.frame_rough,self.metal=ph['p_rough'],ph['f_rough'],ph['p_metal']
        e.settings_popup=True
        return context.window_manager.invoke_props_dialog(self,width=320)

    def draw(self,context):
        col=self.layout.column()
        if self.kind=='BORDER':
            col.prop(self,'side');col.prop(self,'top');col.prop(self,'bottom')
            col.label(text=_T('Instant Classic 4.5 / 6.5 / 21.5 · Mini/Square/Wide 4 / 6.5 / 17.5'),icon='INFO')
        elif self.kind=='PAPER':
            col.prop(self,'paper_rough');col.label(text=_T('Matte 0.85 · Satin 0.55 · Silk 0.4 · Glossy 0.25'),icon='INFO')
        else:
            col.prop(self,'rough');col.prop(self,'frame_rough');col.prop(self,'metal')
            col.label(text=_T('Matte 0.62 · Satin 0.45 · Silk 0.35 · Glossy 0.18 · Metallic 0'),icon='INFO')

    def execute(self,context):
        e=getattr(self,'editor',None) or next((x for x in CUT_EDITORS if x.layout_mode),None)
        if e is None:return {'CANCELLED'}
        try:
            idx=[i for i in getattr(e,'selection',{e.selected}) if 0<=i<len(e.rects)]
            e.remember_layout()
            if self.kind=='BORDER':e.photo_set(idx,frame=True,margins=(self.side,self.top,self.bottom))
            elif self.kind=='PAPER':e.paper_surface_set(idx,self.paper_rough)
            else:e.photo_set(idx,finish=(self.rough,self.frame_rough,self.metal))
        finally:
            e.settings_popup=False;e.area.tag_redraw()
        return {'FINISHED'}

    def cancel(self,context):
        self.editor.settings_popup=False;self.editor.area.tag_redraw()


class PA_OT_layout_options(bpy.types.Operator):
    bl_idname='poster_atlas.layout_options';bl_label=_T('Layout Settings')
    kind:EnumProperty(items=_T_items([('SIZE','Enter Size Manually',''),('GAP','Spacing Between Images',''),('RES','Texture Size','')]))
    res:IntProperty(name=_T('Texture Size (px)'),default=3072,min=256,max=8192)
    width:FloatProperty(name=_T('Width (mm)'),default=210,min=.1,max=10000,precision=1)
    height:FloatProperty(name=_T('Height (mm)'),default=297,min=.1,max=10000,precision=1)
    gap:IntProperty(name=_T('Spacing (px)'),default=16,min=0,max=1024)

    def invoke(self,context,event):
        self.editor=next((e for e in CUT_EDITORS if e.layout_mode),None)
        if self.editor is None:return {'CANCELLED'}
        s=self.editor.settings
        self.width=s.custom_width;self.height=s.custom_height;self.gap=s.layout_gap;self.res=self.editor.w if self.editor.w not in (2048,4096) else s.custom_resolution
        self.editor.settings_popup=True
        return context.window_manager.invoke_props_dialog(self,width=300)

    def draw(self,context):
        if self.kind=='RES':
            self.layout.prop(self,'res')
            self.layout.label(text=_T('Square texture · posters keep their size'))
            self.layout.label(text=_T('Larger = sharper, but bigger files and slower'))
            return
        if self.kind=='SIZE':
            self.layout.label(text=_T('Selected Image Size'))
            self.layout.prop(self,'width');self.layout.prop(self,'height')
            if self.editor.settings.edit_mode=='CROP':
                self.layout.label(text=_T('Crop · lock frame to the entered size'))
                self.layout.label(text=_T('Fill with the photo, then drag to choose the crop'))
            elif self.editor.settings.edit_mode=='SCALE':
                self.layout.label(text=_T('Scale · apply the entered size as is'))
                self.layout.label(text=_T('The width/height ratio of the whole photo changes.'))
            else:
                self.layout.label(text=_T('Keep Ratio · show the whole photo'))
                self.layout.label(text=_T('Scale to fit inside the entered size'))
        else:
            self.layout.prop(self,'gap')
            self.layout.label(text=_T('From 0 px · arrow buttons move the selected images'))

    def execute(self,context):
        e=self.editor
        try:
            if self.kind=='RES':e.change_resolution(self.res)
            elif self.kind=='SIZE':
                e.set_preset((self.width,self.height))
                e.settings.custom_width=self.width;e.settings.custom_height=self.height
            else:e.settings.layout_gap=self.gap
        except Exception as exc:
            self.report({'ERROR'},_T(str(exc)));return {'CANCELLED'}
        finally:
            e.settings_popup=False;e.area.tag_redraw()
        return {'FINISHED'}

    def cancel(self,context):
        self.editor.settings_popup=False;self.editor.area.tag_redraw()


FX_FLOAT_FIELDS=[('tint_s','Strength',0.,1.),('ink_s','Strength',0.,1.),('sat','Saturation',0.,2.),('hue','Hue Shift',-.5,.5),('fade','Fade',0.,1.),('yellow','Yellowing',0.,1.),
    ('wear','Wear',0.,1.),('wear_edge','Edge Width (mm)',0.,300.),('peel','Print Peel',0.,1.),('holes','Holes',0.,1.),('hole_rim','Hole White Rim',0.,.15),
    ('hole_soft','Edge Softness',.002,.15),('hole_size','Pattern Size (mm)',20.,5000.),('fray','Torn Edges',0.,1.),('fray_depth','Tear Depth (mm)',0.,50.),
    ('fray_corner','Corner Focus',0.,1.),('fray_fiber','White Cross-section',0.,1.)]


class PA_OT_fx_pick_color(bpy.types.Operator):
    bl_idname='poster_atlas.fx_pick_color';bl_label=_T('Pick Color Manually')
    target:EnumProperty(items=_T_items([('tint','Paper Color',''),('ink','Ink Color',''),('pool','Sticky Note Random Color','')]))
    color:FloatVectorProperty(name=_T('Color'),subtype='COLOR',size=3,min=0.,max=1.,default=(1.,.84,.15))
    def invoke(self,context,event):
        self.editor=next((e for e in CUT_EDITORS if e.layout_mode),None)
        if self.editor is None:return {'CANCELLED'}
        if self.target=='pool':
            pool=postit_pool(self.editor.settings);p=getattr(self.editor,'fx_pending',None) or {}
            cur=pool[max(0,min(p.get('pool_sel',0),len(pool)-1))]
        else:cur=self.editor.fx_draft_get()[self.target]
        if cur:self.color=linear_from_srgb(cur)
        self.editor.settings_popup=True
        return context.window_manager.invoke_props_dialog(self,width=340 if self.target=='pool' else 260)
    def draw(self,context):
        self.layout.label(text=_T({'tint':'Paper color (white areas)','ink':'Ink color (black areas)','pool':'Sticky Note Random Color'}[self.target]));self.layout.prop(self,'color',text=_T(''))
        if self.target=='pool':
            self.layout.label(text=_T('Press OK to switch to this color.'))
        else:self.layout.label(text=_T('After choosing, press [Apply to Selection].'))
    def execute(self,context):
        e=self.editor
        if self.target=='pool':
            e.remember_layout()
            st=e.settings;pool=postit_pool(st);p=getattr(e,'fx_pending',None) or {}
            sel=max(0,min(p.get('pool_sel',0),len(pool)-1));pool[sel]=tuple(srgb_from_linear(self.color))
            set_postit_pool(st,pool)
            if p:p['cache']={}
            e.settings_popup=False;e.area.tag_redraw();return {'FINISHED'}
        e.fx_draft_get()[self.target]=srgb_from_linear(self.color)
        e.fx_touch('TAB:COLOR',FX_TAB_NAMES['COLOR'],(self.target,));e.fx_commit(quiet=True)
        e.settings_popup=False;e.area.tag_redraw();return {'FINISHED'}
    def cancel(self,context):
        self.editor.settings_popup=False;self.editor.area.tag_redraw()


class PA_OT_layout_effects(bpy.types.Operator):
    bl_idname='poster_atlas.layout_effects';bl_label=_T('Effect Details')
    bl_description=_T('Sets color, wear, holes and tears for the images selected in the layout editor. Baked into the texture on build.')
    use_tint:BoolProperty(name=_T('Paper Color'),default=False,description=_T('Tints only the white paper areas with this color.'))
    tint:FloatVectorProperty(name=_T(''),subtype='COLOR',size=3,min=0.,max=1.,default=(1.,.84,.15))
    use_ink:BoolProperty(name=_T('Ink Color'),default=False,description=_T('Replaces dark areas with this color.'))
    ink:FloatVectorProperty(name=_T(''),subtype='COLOR',size=3,min=0.,max=1.,default=(.01,.03,.25))
    tint_s:FloatProperty(name=_T('Strength'),default=1.,min=0.,max=1.,precision=2)
    ink_s:FloatProperty(name=_T('Strength'),default=1.,min=0.,max=1.,precision=2)
    sat:FloatProperty(name=_T('Saturation'),default=1.,min=0.,max=2.,precision=2)
    hue:FloatProperty(name=_T('Hue Shift'),default=0.,min=-.5,max=.5,precision=2)
    fade:FloatProperty(name=_T('Fade'),default=0.,min=0.,max=1.,precision=2)
    yellow:FloatProperty(name=_T('Yellowing'),default=0.,min=0.,max=1.,precision=2)
    wear:FloatProperty(name=_T('Wear'),default=0.,min=0.,max=1.,precision=2)
    wear_edge:FloatProperty(name=_T('Edge Width (mm)'),default=15.,min=0.,max=300.,precision=0)
    peel:FloatProperty(name=_T('Print Peel'),default=0.,min=0.,max=1.,precision=2)
    holes:FloatProperty(name=_T('Holes'),default=0.,min=0.,max=1.,precision=2)
    hole_rim:FloatProperty(name=_T('Hole White Rim'),default=.03,min=0.,max=.15,precision=3)
    hole_soft:FloatProperty(name=_T('Edge Softness'),default=.004,min=.002,max=.15,precision=3)
    hole_size:FloatProperty(name=_T('Pattern Size (mm)'),default=400.,min=20.,max=5000.,precision=0)
    fray:FloatProperty(name=_T('Torn Edges'),default=0.,min=0.,max=1.,precision=2)
    fray_depth:FloatProperty(name=_T('Tear Depth (mm)'),default=5.,min=0.,max=50.,precision=1)
    fray_corner:FloatProperty(name=_T('Corner Focus'),default=.6,min=0.,max=1.,precision=2)
    fray_fiber:FloatProperty(name=_T('White Cross-section'),default=.8,min=0.,max=1.,precision=2)
    reseed:BoolProperty(name=_T('Reshuffle Patterns'),default=False,description=_T('Re-rolls hole and tear positions for each image.'))
    keep_each:BoolProperty(name=_T('Keep Each Pattern'),default=True,description=_T("Keeps each image's hole and tear positions even when changing several together."))

    def invoke(self,context,event):
        self.editor=next((e for e in CUT_EDITORS if e.layout_mode),None)
        if self.editor is None:return {'CANCELLED'}
        e=self.editor;self.targets=e.fx_targets()
        if not self.targets:
            self.report({'WARNING'},_T('Select images to apply effects to first.'));return {'CANCELLED'}
        src=e.selected if e.selected in self.targets else self.targets[0]
        f=fx_clean(e.effects[src])
        for key,_,_,_ in FX_FLOAT_FIELDS:setattr(self,key,f[key])
        self.use_tint=f['tint'] is not None;self.use_ink=f['ink'] is not None
        if f['tint']:self.tint=linear_from_srgb(f['tint'])
        if f['ink']:self.ink=linear_from_srgb(f['ink'])
        e.settings_popup=True
        return context.window_manager.invoke_props_dialog(self,width=360)

    def draw(self,context):
        L=self.layout;n=len(self.targets)
        L.label(text=_T('Applied to %d selected · loaded values of #%d'%(n,(self.editor.selected+1))),icon='INFO')
        b=L.box();b.label(text=_T('Color'),icon='COLOR')
        row=b.row(align=True);row.prop(self,'use_tint');sub=row.row(align=True);sub.active=self.use_tint;sub.prop(self,'tint');sub.prop(self,'tint_s')
        row=b.row(align=True);row.prop(self,'use_ink');sub=row.row(align=True);sub.active=self.use_ink;sub.prop(self,'ink');sub.prop(self,'ink_s')
        c=b.column(align=True);c.prop(self,'sat');c.prop(self,'hue');c.prop(self,'fade');c.prop(self,'yellow')
        b=L.box();b.label(text=_T('Wear'),icon='MOD_NOISE');c=b.column(align=True);c.prop(self,'wear');c.prop(self,'wear_edge')
        b=L.box();b.label(text=_T('Peel · Holes'),icon='MOD_BOOLEAN');c=b.column(align=True)
        for k in ('peel','holes','hole_rim','hole_soft','hole_size'):c.prop(self,k)
        b=L.box();b.label(text=_T('Torn Edges'),icon='MOD_EDGESPLIT');c=b.column(align=True)
        for k in ('fray','fray_depth','fray_corner','fray_fiber'):c.prop(self,k)
        row=L.row();row.prop(self,'reseed')
        if n>1:row.prop(self,'keep_each')

    def execute(self,context):
        e=getattr(self,'editor',None) or next((x for x in CUT_EDITORS if x.layout_mode),None)
        if e is None:return {'CANCELLED'}
        self.editor=e
        if not getattr(self,'targets',None):self.targets=e.fx_targets()
        try:
            vals={k:getattr(self,k) for k,_,_,_ in FX_FLOAT_FIELDS}
            vals['tint']=srgb_from_linear(self.tint) if self.use_tint else None
            vals['ink']=srgb_from_linear(self.ink) if self.use_ink else None
            rng=np.random.default_rng()
            def make(i):
                f=fx_clean(vals);old=e.effects[i];f['presets']=fx_clean(old)['presets'] if old else []
                if old:f.update({k:fx_clean(old)[k] for k in ('polaroid','pol_style','frame','frame_m','photo_fmt')})   # Keep the Picture look and border
                f['seed']=int(rng.integers(1,2**31-1)) if self.reseed or not old else (old.get('seed',0) if self.keep_each or len(self.targets)==1 else int(rng.integers(1,2**31-1)))
                return f if fx_active(f) else None
            e.set_effects(self.targets,make)
        except Exception as exc:
            self.report({'ERROR'},_T(str(exc)));return {'CANCELLED'}
        finally:
            e.settings_popup=False;e.area.tag_redraw()
        return {'FINISHED'}

    def cancel(self,context):
        self.editor.settings_popup=False;self.editor.area.tag_redraw()


class PA_OT_reedit(bpy.types.Operator):
    bl_idname='poster_atlas.reedit';bl_label=_T('Re-edit')
    bl_description=_T('Reopens an existing poster batch in the layout editor. Adjust color, wear, holes, crumple or size and [Build] to update the same posters, including ones placed on walls.')
    collection_name:StringProperty(options={'HIDDEN','SKIP_SAVE'})
    @classmethod
    def poll(cls,context):return bool(context.area and context.area.type=='VIEW_3D' and context.mode=='OBJECT')
    def invoke(self,context,event):return self.execute(context)
    def execute(self,context):
        s=context.scene.poster_atlas
        if CUT_EDITORS:self.report({'WARNING'},_T('Please close the open editor first.'));return {'CANCELLED'}
        col=bpy.data.collections.get(self.collection_name) if self.collection_name else None
        if col is None:
            ob=context.active_object
            src=ob.get('poster_source_object') if ob else None
            if src and src in bpy.data.objects:ob=bpy.data.objects[src]
            col=next((c for c in (ob.users_collection if ob else []) if c.get('poster_manifest')),None)
        if col is None:self.report({'ERROR'},_T('Choose a poster batch to re-edit, or select a built poster.'));return {'CANCELLED'}
        before=(s.update_previous,s.last_collection)
        snap=snapshot_file_list(s)   # list as it was, restored when the editor closes
        try:n=reedit_prepare(s,col)
        except Exception as exc:self.report({'ERROR'},_T(str(exc)));return {'CANCELLED'}
        r=bpy.ops.poster_atlas.cut('INVOKE_DEFAULT',layout_mode=True)
        if 'RUNNING_MODAL' not in r:
            s.update_previous,s.last_collection=before;restore_file_list(s,snap);return {'CANCELLED'}
        if CUT_EDITORS:CUT_EDITORS[-1].reedit_restore=before;CUT_EDITORS[-1].reedit_list=snap   # Closing restores the batch state and the list
        self.report({'INFO'},_T('Reopened %s · %d images. [Build] will update this batch.'%(col.name,n)))
        return {'FINISHED'}


class PA_OT_stop_edit(bpy.types.Operator):
    bl_idname='poster_atlas.stop_edit';bl_label=_T('Stop Editing This Batch');bl_options={'UNDO','INTERNAL'}
    bl_description=_T('The next Build makes a new batch instead of updating the one being edited')
    def execute(self,context):
        context.scene.poster_atlas.update_previous=False;return {'FINISHED'}


class PA_OT_build(bpy.types.Operator):
    bl_idname='poster_atlas.build';bl_label=_T('Apply · Build Posters');bl_options={'UNDO'}
    bl_description=_T('Builds a new source poster batch from the current list and settings. Previous build results are kept.')
    @classmethod
    def poll(cls,context):return context.mode=='OBJECT'
    def execute(self,context):
        s=context.scene.poster_atlas;used=[f.path for f in build_files(s)]
        try:
            build(context,s)
        except Exception as exc:
            self.report({'ERROR'},_T(str(exc)));return {'CANCELLED'}
        n=remove_built_from_list(s,used)
        self.report({'INFO'},_T(s.last_result+(' · %d removed from the list'%n if n else '')))
        return {'FINISHED'}


def remove_built_from_list(s,paths):
    """After a successful Build: the images that went into it leave the list (option, on by default). Files stay on disk."""
    if not getattr(s,'remove_after_build',True) or not paths:return 0
    used={os.path.normcase(bpy.path.abspath(p)) for p in paths};n=0
    for k in reversed(range(len(s.files))):
        if os.path.normcase(bpy.path.abspath(s.files[k].path)) in used:s.files.remove(k);n+=1
    s.active=max(0,min(s.active,len(s.files)-1))
    return n


def draw_paper(layout,s):
    box=layout.box();box.label(text=_T('Paper Texture'),icon='TEXTURE')
    box.prop(s,'paper_dir',text=_T('Extra Folder'))
    row=box.row(align=True);row.prop(s,'paper_set',text=_T(''));row.prop(s,'paper_variant',text=_T('Variant'))
    col=box.column(align=True);col.prop(s,'paper_strength');col.prop(s,'paper_tile_mm');col.prop(s,'paper_ao')
    row=box.row(align=True);row.scale_y=1.2
    op=row.operator('poster_atlas.paper_apply',text=_T('Apply to All Posters'),icon='CHECKMARK');op.scope='ALL';op.remove=False
    op=row.operator('poster_atlas.paper_apply',text=_T('Selected Only'));op.scope='SELECTED';op.remove=False
    op=row.operator('poster_atlas.paper_apply',text=_T(''),icon='X');op.scope='ALL';op.remove=True
    box.label(text=_T('You can also choose it in the [Paper] tab of the [Layout Editor · Build] window.'),icon='INFO')
    box.label(text=_T('Color, wear, holes and tears are set per image in that window.'))
    box.prop(s,'paper_auto')
    sub=box.box();sub.label(text=_T('Bake New Texture in Substance'),icon='IMPORT')
    row=sub.row(align=True);row.prop(s,'bake_size',expand=True);row.prop(s,'bake_variants',text=_T('Variant'))
    sub.operator('poster_atlas.paper_bake',icon='FILE_BLEND')
    sub.prop(s,'sd_dir',text=_T('SD Folder'))


class PA_PT_panel(bpy.types.Panel):
    bl_label=_T('Poster Print');bl_idname='PA_PT_panel';bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='Poster Print'
    def draw(self,context):
        layout=self.layout;s=context.scene.poster_atlas
        layout.use_property_decorate=False
        col=layout.column(align=True)   # Output: save folder (names come from the batch number and its groups)
        col.prop(s,'output_dir',text=_T(''),icon='FILE_FOLDER')
        row=layout.row(align=True)
        row.prop_enum(s,'list_tab','TEXTURE',text=_T('Textures'),icon='TEXTURE')
        row.prop_enum(s,'list_tab','CUT',text=_T('Cut'),icon='SCULPTMODE_HLT')
        if s.list_tab=='CUT':
            draw_cut_tab(layout,s,context);return
        n_on=sum(f.selected for f in s.files)
        header,body=layout.panel('PA_images',default_closed=False)
        header.label(text=_T('Images'),icon='IMAGE_DATA')
        header.label(text=_T('%d / %d'%(n_on,len(s.files))))
        if body:
            body.operator('poster_atlas.add',text=_T('Add Images'),icon='ADD')
            row=body.row()
            row.template_list('PA_UL_files','',s,'files',s,'list_row',rows=4)   # rows = minimum; drag the grip under the list to resize
            side=row.column(align=True)
            side.operator('poster_atlas.list_edit',text=_T(''),icon='TRIA_UP').action='UP'
            side.operator('poster_atlas.list_edit',text=_T(''),icon='TRIA_DOWN').action='DOWN'
            side.separator()
            side.operator('poster_atlas.list_edit',text=_T(''),icon='REMOVE').action='REMOVE'
            side.operator('poster_atlas.list_edit',text=_T(''),icon='X').action='CLEAR'
            row=body.row(align=True)   # checkboxes + grouping in one row
            row.operator('poster_atlas.select_all',text=_T('All'),icon='CHECKBOX_HLT').select=True
            row.operator('poster_atlas.select_all',text=_T('None'),icon='CHECKBOX_DEHLT').select=False
            # where the build goes: right under the grouping, so the two are read together
            if s.update_previous and s.last_collection:   # Only [Edit] below turns this on; Build then updates that batch
                atlas_=next((o.get('poster_atlas') for o in s.last_collection.all_objects if o.get('poster_atlas')),None)
                name_=os.path.splitext(atlas_)[0].replace('T_Poster_','').replace('T_','') if atlas_ else s.last_collection.name.split('· ')[-1]
                box=body.box();row=box.row(align=True)
                row.label(text=_T('Editing %s · Build updates it'%name_),icon='GREASEPENCIL')
                row.operator('poster_atlas.stop_edit',text=_T(''),icon='X')
            else:
                dest=build_destination(context)
                where=dest.name if dest else 'Scene Collection'
                box=body.box();col=box.column(align=True)
                col.label(text=_T('Goes into: '+where),icon='OUTLINER_COLLECTION')
                groups=sorted({f.group.strip() for f in build_files(s) if f.group.strip()})
                if groups:
                    sub=col.row();sub.active=False;sub.label(text=_T('Groups: '+', '.join(groups)),icon='BLANK1')
        header,body=layout.panel('PA_preview',default_closed=False)
        header.label(text=_T('Preview'),icon='IMAGE')
        if body:
            if s.files:
                item=s.files[max(0,min(s.active,len(s.files)-1))]
                try:icon=preview_icon(file_path(item))
                except (OSError,RuntimeError,ValueError):icon=0
                if icon:
                    row=body.row();row.alignment='CENTER'
                    ui_scale=max(1.,context.preferences.system.ui_scale)
                    # File previews preserve aspect themselves. Legacy Texture previews
                    # sample using their draggable render height and are unsafe here.
                    width=max(40.,min(240.,context.region.width/ui_scale-60))
                    row.template_icon(icon_value=icon,scale=width/20.)
                else:body.label(text=_T('Cannot read the image.'),icon='ERROR')
                row=body.row()
                row.label(text=_T('#%03d   ·   %d°'%(s.active+1,item.quarter_turns*90)))
                sub=row.row(align=True)
                sub.operator('poster_atlas.rotate',text=_T(''),icon='LOOP_BACK').step=-1
                sub.operator('poster_atlas.rotate',text=_T(''),icon='LOOP_FORWARDS').step=1
                row.operator('poster_atlas.cut',text=_T(''),icon='ZOOM_IN').preview_only=True
        layout.separator()
        row=layout.row();row.scale_y=1.6
        row.operator('poster_atlas.cut',text=_T('Layout Editor  ·  Build'),icon='IMAGE_DATA').layout_mode=True
        info=layout.row();info.active=False   # what the build makes (texture size / background are set in the editor)
        info.label(text=_T('%d images · one %s sheet (~%d A4)'%(len(build_files(s)),res_label(s.resolution),max(1,round(6*(int(s.resolution)/2048)**2)))),icon='INFO')
        col=layout.column(align=True)   # Build options (was a separate Texture panel)
        col.prop(s,'remove_after_build')
        col.prop(s,'pack_textures')
        if not (paper_folder(s) and os.path.isdir(paper_folder(s))):col.prop(s,'paper_dir',text=_T('Paper'))
        batches=poster_batches(s)
        if batches:
            header,body=layout.panel('PA_reedit',default_closed=False)
            header.label(text=_T('Re-edit Built Posters'),icon='GREASEPENCIL')
            if body:
                for c in batches[:12]:
                    on=s.update_previous and s.last_collection==c
                    atlas=next((o.get('poster_atlas') for o in c.all_objects if o.get('poster_atlas')),None)
                    name=os.path.splitext(atlas)[0].replace('T_Poster_','').replace('T_','') if atlas else c.name.split('· ')[-1]
                    row=body.row(align=True).split(factor=.62,align=True)
                    row.label(text=_T('%s  ·  %d'%(name,len(c.all_objects))),icon='RADIOBUT_ON' if on else 'OUTLINER_COLLECTION')
                    row.operator('poster_atlas.reedit',text=_T('Edit'),icon='GREASEPENCIL').collection_name=c.name
        col=layout.column(align=True)
        if s.last_collection:col.operator('poster_atlas.to_scatter',icon='FORWARD')


class PA_OT_paper_apply(bpy.types.Operator):
    bl_idname='poster_atlas.paper_apply';bl_label=_T('Apply Paper Texture');bl_options={'UNDO'}
    bl_description=_T('Layers the paper texture onto poster materials. Materials that already have it are updated to the current settings.')
    scope:EnumProperty(items=_T_items([('ALL','All Posters',''),('SELECTED','Selected Posters','')]),default='ALL')
    remove:BoolProperty(default=False)
    def execute(self,context):
        s=context.scene.poster_atlas
        mats=paper_targets(context,self.scope)
        if not mats:self.report({'WARNING'},_T('No poster material found.'));return {'CANCELLED'}
        if self.remove:
            n=sum(remove_paper(m) for m in mats);self.report({'INFO'},_T('Paper texture removed: %d materials'%n));return {'FINISHED'}
        try:group=paper_group_for(s)
        except ValueError as e:self.report({'ERROR'},_T(str(e)));return {'CANCELLED'}
        scale=max(context.scene.unit_settings.scale_length,1e-6);uvs=0
        for mesh in {ob.data for ob in bpy.data.objects if ob.type=='MESH' and any(m in mats for m in ob.data.materials)}:
            uvs+=ensure_paper_uv(mesh,scale)
        n=sum(apply_paper(m,group,s) for m in mats)
        self.report({'INFO'},_T('Paper texture applied: %d materials, %d meshes got coords'%(n,uvs)))
        return {'FINISHED'}


class PA_OT_palette(bpy.types.Operator):
    bl_idname='poster_atlas.palette';bl_label=_T('Edit Palette');bl_options={'UNDO'}
    action:EnumProperty(items=_T_items([('ADD','Add Color',''),('REMOVE','Remove Color',''),('PRESET','Load Preset','')]))
    target:EnumProperty(items=_T_items([('PAPER','Paper',''),('INK','Ink','')]),default='PAPER')
    preset:EnumProperty(items=_T_items([(k,v[0],'') for k,v in PAPER_PALETTE_PRESETS.items()]))
    def execute(self,context):
        s=context.scene.poster_atlas;ink=self.target=='INK'
        pal=s.ink_palette if ink else s.palette;key='ink_palette_active' if ink else 'palette_active'
        if self.action=='ADD':
            if len(pal)>=6:self.report({'WARNING'},_T('Palettes hold up to 6 colors.'));return {'CANCELLED'}
            c=pal.add();c.color=s.ink_color if ink else s.tint_color;setattr(s,key,len(pal)-1)
        elif self.action=='REMOVE' and pal:
            pal.remove(getattr(s,key));setattr(s,key,max(0,min(getattr(s,key),len(pal)-1)))
        return {'FINISHED'}


class PA_OT_palette_preset(bpy.types.Operator):
    bl_idname='poster_atlas.palette_preset';bl_label=_T('Paper Color Preset');bl_options={'UNDO'}
    preset:EnumProperty(items=_T_items([(k,v[0],'') for k,v in PAPER_PALETTE_PRESETS.items()]))
    def execute(self,context):
        s=context.scene.poster_atlas;s.palette.clear()
        for col in PAPER_PALETTE_PRESETS[self.preset][1]:s.palette.add().color=col
        s.tint_mode='PALETTE';return {'FINISHED'}


class PA_OT_ink_preset(bpy.types.Operator):
    bl_idname='poster_atlas.ink_preset';bl_label=_T('Ink Color Preset');bl_options={'UNDO'}
    preset:EnumProperty(items=_T_items([(k,v[0],'') for k,v in INK_PALETTE_PRESETS.items()]))
    def execute(self,context):
        s=context.scene.poster_atlas;s.ink_palette.clear()
        for col in INK_PALETTE_PRESETS[self.preset][1]:s.ink_palette.add().color=col
        s.ink_mode='PALETTE';return {'FINISHED'}


def poster_origin(ob):
    # Layout copies (normalized source / lifted copy) store the source object name in 'source'.
    src=ob.get('poster_source_object')
    if isinstance(src,bpy.types.Object):return src
    name=ob.get('source')
    if isinstance(name,str) and name in bpy.data.objects and ob.get('ps_owned'):return bpy.data.objects[name]
    return ob


def tint_targets(context):
    origin={poster_origin(ob).name for ob in context.selected_objects if ob.type=='MESH'}
    meshes=set()
    for ob in bpy.data.objects:
        if ob.type=='MESH' and (ob.name in origin or poster_origin(ob).name in origin):meshes.add(ob.data)
    return meshes


def set_mesh_tint(mesh,color,attr=TINT_ATTR,on_attr=TINT_ON_ATTR):
    for name in (attr,on_attr):
        if name in mesh.attributes:mesh.attributes.remove(mesh.attributes[name])
    if color is None:return
    a=mesh.attributes.new(attr,'FLOAT_COLOR','POINT');a.data.foreach_set('color',[*color,1.]*len(mesh.vertices))
    b=mesh.attributes.new(on_attr,'FLOAT','POINT');b.data.foreach_set('value',[1.]*len(mesh.vertices))


class PA_OT_tint_selected(bpy.types.Operator):
    bl_idname='poster_atlas.tint_selected';bl_label=_T('Set Paper Color of Selected Posters')
    bl_description=_T('Locks the paper color of the selected source posters and their placed copies to the color above. Other posters are unaffected.')
    bl_options={'UNDO'}
    clear:BoolProperty(default=False)
    target:EnumProperty(items=_T_items([('PAPER','Paper',''),('INK','Ink','')]),default='PAPER')
    def execute(self,context):
        s=context.scene.poster_atlas;meshes=tint_targets(context);ink=self.target=='INK'
        if not meshes:self.report({'WARNING'},_T('Please select posters.'));return {'CANCELLED'}
        color=None if self.clear else tuple(s.ink_color if ink else s.tint_color)
        for me in meshes:
            set_mesh_tint(me,color,*((INK_ATTR,INK_ON_ATTR) if ink else (TINT_ATTR,TINT_ON_ATTR)));me.update()
        self.report({'INFO'},_T('%s color %s: %d meshes'%('Ink' if ink else 'Paper','cleared' if self.clear else 'set',len(meshes))))
        return {'FINISHED'}


class PA_OT_paper_bake(bpy.types.Operator,ImportHelper):
    bl_idname='poster_atlas.paper_bake';bl_label=_T('Bake from Substance File')
    bl_description=_T('Bakes a .sbs or .sbsar into tiling textures with the Substance Designer command-line tools and adds them to the paper texture folder.')
    filename_ext=''
    filter_glob:StringProperty(default='*.sbs;*.sbsar',options={'HIDDEN'})
    def execute(self,context):
        import subprocess
        s=context.scene.poster_atlas;src=os.path.abspath(self.filepath)
        folder=user_paper_folder(s)
        if not folder:self.report({'ERROR'},_T('First set the "Extra Paper Texture Folder" to store baked textures. Built-in textures ship with the addon.'));return {'CANCELLED'}
        render=find_sd_tool(s,'sbsrender.exe') or find_sd_tool(s,'sbsrender')
        if not render:self.report({'ERROR'},_T('sbsrender not found. Please set the Substance Designer folder.'));return {'CANCELLED'}
        name=re.sub(r'[^0-9A-Za-z가-힣_-]+','_',os.path.splitext(os.path.basename(src))[0]).strip('_') or 'Paper'
        graph=None;outputs=[];out=None
        try:
            if src.lower().endswith('.sbs'):
                cooker=find_sd_tool(s,'sbscooker.exe') or find_sd_tool(s,'sbscooker')
                if not cooker:self.report({'ERROR'},_T('sbscooker not found.'));return {'CANCELLED'}
                info=sbs_graph_info(src)
                if not info:self.report({'ERROR'},_T('Graph not found.'));return {'CANCELLED'}
                graph,outputs=info[0]
                cook=os.path.join(folder,'_cooked');os.makedirs(cook,exist_ok=True)
                r=subprocess.run([cooker,'--inputs',src,'--output-path',cook],capture_output=True,text=True,timeout=600)
                archive=os.path.join(cook,os.path.splitext(os.path.basename(src))[0]+'.sbsar')
                if r.returncode or not os.path.isfile(archive):self.report({'ERROR'},_T('Compile failed: '+(r.stderr or r.stdout)[-300:]));return {'CANCELLED'}
            else:archive=src
            edge_graph='Mask' in outputs
            maps=('Mask','height') if edge_graph else PAPER_MAPS
            out=os.path.join(shared_dir(folder),name) if edge_graph else os.path.join(folder,name);os.makedirs(out,exist_ok=True)
            size='12' if edge_graph else s.bake_size
            for seed in range(s.bake_variants):
                cmd=[render,'render','--input',archive,'--set-value','$outputsize@%s,%s'%(size,size),'--set-value','$randomseed@%d'%seed,
                     '--output-format','png','--output-path',out,'--output-name','%s_s%d_{outputNodeName}'%(name,seed)]
                if graph:cmd[3:3]=['--input-graph',graph]
                for o in maps:
                    if not outputs or o in outputs:cmd+=['--input-graph-output',o]
                if not outputs or 'height' in outputs:cmd+=['--set-output-bit-depth','height@16']
                r=subprocess.run(cmd,capture_output=True,text=True,timeout=900)
                if r.returncode:self.report({'ERROR'},_T('Bake failed: '+(r.stderr or r.stdout)[-300:]));return {'CANCELLED'}
        except (OSError,subprocess.SubprocessError) as e:
            self.report({'ERROR'},_T(str(e)));return {'CANCELLED'}
        _PAPER_CACHE['key']=None
        if 'Mask' in outputs:
            self.report({'INFO'},_T('Baked torn-edge %s, %d variants. Re-apply to use them on worn edges.'%(name,s.bake_variants)));return {'FINISHED'}
        if not os.path.isfile(os.path.join(out,'%s_s0_normal.png'%name)):
            self.report({'ERROR'},_T('No normal output. Check the graph output names.'));return {'CANCELLED'}
        s.paper_set=name
        self.report({'INFO'},_T('Baked %s, %d variants.'%(name,s.bake_variants)))
        return {'FINISHED'}


class PA_OT_to_scatter(bpy.types.Operator):
    bl_idname='poster_atlas.to_scatter';bl_label=_T('Link to Poster Scatter')
    def execute(self,context):
        s=context.scene.poster_atlas
        if not s.last_collection or not hasattr(context.scene,'poster_scatter_setup'):
            self.report({'ERROR'},_T('Requires a build result and the Poster Scatter addon.'));return {'CANCELLED'}
        context.scene.poster_scatter_setup.collection=s.library_collection or s.last_collection
        if hasattr(context.scene,'buts_settings'):context.scene.buts_settings.poster_job=s.job_name
        self.report({'INFO'},_T('Linked the source collection. Select a wall and create an area in the Poster Scatter tab.'))
        return {'FINISHED'}



class PA_Prefs(bpy.types.AddonPreferences):
    bl_idname=__name__
    language:EnumProperty(name='Language',items=[('EN','English','English interface'),('KO','한국어','한국어 인터페이스')],
        default=_i18n_lang(),update=_i18n_lang_changed,description='Interface language of Print & Pin (Poster Print and Poster Pin)')
    def draw(self,context):
        col=self.layout.column()
        col.prop(self,'language')
        if self.language=='KO':
            col.label(text='패널·편집기·메시지는 바로 바뀌어요. 버튼 이름과 툴팁 일부는 블렌더를 다시 시작하면 바뀌어요.',icon='INFO')
        else:
            col.label(text='Panels, the editor and messages switch right away. Some button names and tooltips change after restarting Blender.',icon='INFO')
        col.label(text='Print & Pin · by G_ni')

CLASSES=(PA_Prefs,PA_File,PA_Color,PA_UL_palette,PA_Settings,PA_UL_files,PA_OT_add,PA_OT_drop_images,PA_FH_images,PA_OT_list_key_remove,PA_OT_caption,PA_OT_text_font,PA_OT_pick_all_key,PA_OT_pick_clear,PA_OT_list,PA_UL_cut_files,PA_OT_cut_list,PA_OT_rotate,PA_OT_photo_custom,PA_OT_layout_options,PA_OT_fx_pick_color,PA_OT_layout_effects,PA_OT_reedit,PA_OT_stop_edit,PA_OT_build,PA_OT_cut,PA_OT_batch_rename,PA_OT_group_rename,PA_OT_set_group,PA_OT_pick_all,PA_OT_select_all,PA_OT_drag_select,PA_OT_paper_apply,PA_OT_palette,PA_OT_palette_preset,PA_OT_ink_preset,PA_OT_tint_selected,PA_OT_paper_bake,PA_OT_to_scatter,PA_PT_panel)
# Trimmed swatch sets (UI 1.79): fewer, clearly different choices; 'Custom' still picks any color.
FX_PAPER_SWATCHES=[None,(1.,.93,.43),(1.,.71,.81),(.67,.85,1.),(.73,.94,.75),(1.,.8,.6)]
FX_PAPER_GRAYS=[(1.,.98,.92),(.92,.9,.84),(.78,.65,.48),(.9,.9,.9),(.65,.65,.65),(.35,.35,.35)]
FX_INK_SWATCHES=[None,(.1,.18,.55),(.75,.12,.14),(.08,.35,.75),(.1,.45,.25),(.35,.22,.12),(.43,.16,.47)]
FX_INK_GRAYS=[(.02,.02,.02),(.12,.12,.12),(.22,.22,.22),(.35,.35,.35),(.5,.5,.5),(.7,.7,.7),(.95,.95,.95)]


def register():
    for cls in CLASSES:
        if cls.__doc__ and not getattr(cls,'bl_description',None) and _i18n_lang()=='KO':
            try:cls.__doc__=_T(cls.__doc__)
            except Exception:pass
        bpy.utils.register_class(cls)
    bpy.types.Scene.poster_atlas=PointerProperty(type=PA_Settings)
    quiet_builtin_drops()   # dropping images on the Poster Print tab goes straight into the list (no "which handler" menu)
    for h in (bpy.app.handlers.load_post,bpy.app.handlers.render_init,bpy.app.handlers.depsgraph_update_post):   # HDRI guard was removed; drop handlers left by older versions
        for f in [f for f in h if getattr(f,'__name__','').startswith('_hdri_guard')]:h.remove(f)
    kc=bpy.context.window_manager.keyconfigs.addon
    if kc:   # Del / X / Backspace over the sidebar remove the current list item (the operator only runs there)
        km=kc.keymaps.new(name='3D View Generic',space_type='VIEW_3D')
        for key in ('DEL','X','BACK_SPACE'):ADDON_KEYMAPS.append((km,km.keymap_items.new('poster_atlas.list_key_remove',key,'PRESS')))
        # A click on empty sidebar space (buttons take their own clicks first) clears the name selection
        ADDON_KEYMAPS.append((km,km.keymap_items.new('poster_atlas.pick_clear','LEFTMOUSE','PRESS')))
        # Ctrl+A: select all names (plain A is taken by Blender: it opens/closes the panel under the mouse)
        ADDON_KEYMAPS.append((km,km.keymap_items.new('poster_atlas.pick_all_key','A','PRESS',ctrl=True)))
        kmi=km.keymap_items.new('poster_atlas.pick_all_key','A','PRESS',alt=True);kmi.properties.deselect=True;ADDON_KEYMAPS.append((km,kmi))
def unregister():
    restore_builtin_drops()
    for km,kmi in ADDON_KEYMAPS:
        try:km.keymap_items.remove(kmi)
        except Exception:pass
    ADDON_KEYMAPS.clear()
    global PREVIEW_ICONS,SELECTION_TIMER
    for drag in list(SELECTION_DRAGS):
        try:drag.finish()
        except ReferenceError:pass
    SELECTION_DRAGS.clear()
    if SELECTION_TIMER is not None:
        try:bpy.context.window_manager.event_timer_remove(SELECTION_TIMER)
        except (ReferenceError,RuntimeError):pass
        SELECTION_TIMER=None
    LIST_ROWS.clear()
    for editor in list(CUT_EDITORS):editor.finish(save=True)   # Preserve work while the addon updates
    if bpy.app.timers.is_registered(sync_open_layouts):bpy.app.timers.unregister(sync_open_layouts)
    if PREVIEW_ICONS is not None:
        bpy.utils.previews.remove(PREVIEW_ICONS);PREVIEW_ICONS=None
    if hasattr(bpy.types.Scene,'poster_atlas'):del bpy.types.Scene.poster_atlas
    for cls in reversed(CLASSES):bpy.utils.unregister_class(cls)
if __name__=='__main__':register()
