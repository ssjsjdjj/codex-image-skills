(function(c) {
    var previous=app.documents.length?app.activeDocument:null, oldDialogs=app.displayDialogs;
    var oldUnits=app.preferences.rulerUnits, oldBackground=app.backgroundColor;
    var owned=[], working=null, reopened=null, s=stringIDToTypeID, k=charIDToTypeID;
    var p=c.profile, w=p.output_size[0], h=p.output_size[1];
    function ownOpen(path) {
        var f=new File(path);
        for(var i=0;i<app.documents.length;i++) {
            try { if(app.documents[i].fullName.fsName===f.fsName) {
                if(!app.documents[i].saved) throw new Error('Input has unsaved edits: '+path);
                var copy=app.documents[i].duplicate('SC disposable input',true); owned.push(copy); return copy;
            }} catch(e) { if(String(e).indexOf('unsaved')>=0) throw e; }
        }
        var d=app.open(f); owned.push(d); return d;
    }
    function closeOwned(d) {
        for(var i=owned.length-1;i>=0;i--) if(owned[i]===d) { d.close(SaveOptions.DONOTSAVECHANGES); owned.splice(i,1); return; }
    }
    function fresh(path) {
        var f=new File(path); if(f.exists) throw new Error('Refusing overwrite: '+path);
        if(!f.parent.exists) throw new Error('Missing output directory.'); return f;
    }
    function fit(d) {
        var iw=d.width.as('px'),ih=d.height.as('px'),ratio=Math.min(w/iw,h/ih);
        if(Math.abs((iw/ih)/(p.reference_size[0]/p.reference_size[1])-1)>0.01) throw new Error('Input aspect differs from reviewed composition.');
        var fw=Math.round(iw*ratio),fh=Math.round(ih*ratio);
        d.resizeImage(UnitValue(fw,'px'),UnitValue(fh,'px'),null,ResampleMethod.BICUBIC);
        if(fw!==w || fh!==h) {
            d.resizeCanvas(UnitValue(w,'px'),UnitValue(h,'px'),AnchorPosition.MIDDLECENTER);
            var pad=d.artLayers.add();pad.name='White canvas padding';d.selection.selectAll();d.selection.fill(app.backgroundColor);d.selection.deselect();pad.move(d,ElementPlacement.PLACEATEND);
        }
    }
    function poly(region) {
        var points=[],sx=w/p.reference_size[0],sy=h/p.reference_size[1];
        for(var i=0;i<region.polygon.length;i++) {
            var x=region.polygon[i][0]*sx,y=region.polygon[i][1]*sy;
            if(x<0||y<0||x>w||y>h) throw new Error('Region outside canvas: '+region.id);
            points.push([x,y]);
        }
        return points;
    }
    function maskSelection(regions,feather,protect) {
        working.activeChannels=working.componentChannels;
        for(var i=0;i<regions.length;i++) working.selection.select(poly(regions[i]),i?SelectionType.EXTEND:SelectionType.REPLACE,feather,true);
        for(var j=0;j<protect.length;j++) working.selection.select(poly(protect[j]),SelectionType.DIMINISH,0,true);
    }
    function revealMask() {
        var a=new ActionDescriptor(),r=new ActionReference();a.putClass(k('Nw  '),k('Chnl'));
        r.putEnumerated(k('Chnl'),k('Chnl'),k('Msk '));a.putReference(k('At  '),r);
        a.putEnumerated(k('Usng'),k('UsrM'),k('RvlS'));executeAction(k('Mk  '),a,DialogModes.NO);
        working.selection.deselect();working.activeChannels=working.componentChannels;
    }
    function savePng(d,file) { var o=new PNGSaveOptions();o.compression=1;o.interlaced=false;d.saveAs(file,o,true,Extension.LOWERCASE); }
    var png=fresh(c.png),psd=fresh(c.psd),baseline=fresh(c.baseline_png);
    try {
        app.displayDialogs=DialogModes.NO;app.preferences.rulerUnits=Units.PIXELS;
        var white=new SolidColor();white.rgb.red=255;white.rgb.green=255;white.rgb.blue=255;app.backgroundColor=white;
        var source=ownOpen(c.input);
        if(source.mode!==DocumentMode.RGB || source.bitsPerChannel!==BitsPerChannelType.EIGHT) throw new Error('Use 8-bit RGB white-background source.');
        working=source.duplicate('SKC material-safe v2',true);owned.push(working);closeOwned(source);app.activeDocument=working;
        executeAction(s('newPlacedLayer'),undefined,DialogModes.NO);
        var nativeSource=working.activeLayer;nativeSource.name='Original unenhanced source - embedded complete native pixels';
        fit(working);
        var base=nativeSource.duplicate();working.activeLayer=base;base.rasterize(RasterizeType.ENTIRELAYER);
        base.name='Baseline - unenhanced complete raster';
        working.artLayers.getByName('Original unenhanced source - embedded complete native pixels').visible=false;
        working.artLayers.getByName('Original unenhanced source - embedded complete native pixels').allLocked=true;
        working.artLayers.getByName('Baseline - unenhanced complete raster').visible=true;
        savePng(working,baseline);working.artLayers.getByName('Baseline - unenhanced complete raster').allLocked=true;
        if(c.problem) {
            var problem=ownOpen(c.problem);
            if(problem.width.as('px')!==w||problem.height.as('px')!==h) throw new Error('Problem image must match delivery dimensions for intact preservation.');
            var originalProblem=problem.activeLayer.duplicate(working,ElementPlacement.PLACEATEND);closeOwned(problem);
            app.activeDocument=working;originalProblem.name='Original problem image - complete untouched comparison';originalProblem.visible=false;originalProblem.allLocked=true;
        }
        var candidate=ownOpen(c.candidate);fit(candidate);
        var ai=candidate.activeLayer.duplicate(working,ElementPlacement.PLACEATBEGINNING);closeOwned(candidate);app.activeDocument=working;
        working.activeLayer=ai;ai.name='AI detail - approved plain fabric only';ai.blendMode=BlendMode.LUMINOSITY;ai.opacity=p.ai_opacity;
        maskSelection(p.ai_regions,p.feather_px||0,p.protected_regions||[]);revealMask();
        var expectedMasks=1;
        if(p.zipper && p.zipper.enabled) {
            var zip=working.artLayers.getByName('Baseline - unenhanced complete raster').duplicate(working,ElementPlacement.PLACEATBEGINNING);working.activeLayer=zip;
            zip.allLocked=false;zip.rasterize(RasterizeType.ENTIRELAYER);zip.name='Original zipper - mild in-place finish';
            maskSelection([p.zipper],p.zipper.feather_px||0,p.protected_regions||[]);
            zip.applyUnSharpMask(p.zipper.amount,p.zipper.radius_px,p.zipper.threshold);
            zip.blendMode=BlendMode.LUMINOSITY;zip.opacity=p.zipper.opacity;revealMask();expectedMasks++;
        }
        working.artLayers.getByName('Original unenhanced source - embedded complete native pixels').visible=false;
        if(c.problem) working.artLayers.getByName('Original problem image - complete untouched comparison').visible=false;
        var so=new PhotoshopSaveOptions();so.layers=true;so.embedColorProfile=true;so.maximizeCompatibility=true;
        working.saveAs(psd,so,false,Extension.LOWERCASE);closeOwned(working);working=null;
        reopened=ownOpen(psd.fsName);app.activeDocument=reopened;
        var foundMasks=0,foundBaseline=false,foundNative=false,foundOriginal=!c.problem;
        for(var n=0;n<reopened.layers.length;n++) {
            var layer=reopened.layers[n];
            if(layer.name.indexOf('Baseline - ')===0) foundBaseline=layer.kind===LayerKind.NORMAL;
            if(layer.name.indexOf('Original unenhanced source')===0) foundNative=layer.kind===LayerKind.SMARTOBJECT && !layer.visible;
            if(layer.name.indexOf('Original problem image')===0) foundOriginal=!layer.visible && layer.allLocked;
            var ref=new ActionReference();ref.putIdentifier(k('Lyr '),layer.id);var info=executeActionGet(ref);
            if(info.hasKey(s('hasUserMask')) && info.getBoolean(s('hasUserMask'))) foundMasks++;
        }
        if(!foundBaseline||!foundNative||!foundOriginal||foundMasks!==expectedMasks) throw new Error('PSD layer or editable mask verification failed.');
        savePng(reopened,png);
        return 'OK|'+w+'|'+h+'|layers='+reopened.layers.length+'|editable_masks='+foundMasks+'|Photoshop '+app.version;
    } finally {
        for(var j=owned.length-1;j>=0;j--) { try { owned[j].close(SaveOptions.DONOTSAVECHANGES); }catch(ignore){} }
        app.displayDialogs=oldDialogs;app.preferences.rulerUnits=oldUnits;app.backgroundColor=oldBackground;
        if(previous) {try {app.activeDocument=previous;}catch(ignore2){}}
    }
})(SUPER_CLARITY_CONFIG);
