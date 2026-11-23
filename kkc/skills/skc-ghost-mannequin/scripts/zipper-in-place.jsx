(function(c) {
    var oldDialogs=app.displayDialogs, oldUnits=app.preferences.rulerUnits, original=null, working=null, openedHere=false;
    var ch=charIDToTypeID, st=stringIDToTypeID, z=c.zipper;
    function target(path) {
        var f=new File(path);
        if(f.exists) throw new Error('Refusing to overwrite: '+path);
        if(!f.parent.exists) throw new Error('Output folder does not exist.');
        return f;
    }
    var outPng=target(c.png),outJpg=target(c.jpg),outPsd=c.psd?target(c.psd):null;
    var input=new File(c.input);
    try {
        app.displayDialogs=DialogModes.NO;
        app.preferences.rulerUnits=Units.PIXELS;
        for(var n=0;n<app.documents.length;n++) {
            try { if(app.documents[n].fullName.fsName===input.fsName) original=app.documents[n]; } catch(ignore) {}
        }
        if(original && !original.saved) throw new Error('Input has unsaved edits. Save a versioned copy or close it before running.');
        if(!original) { original=app.open(input); openedHere=true; }
        working=original.duplicate('Original zipper in-place enhancement',true);
        if(openedHere) { original.close(SaveOptions.DONOTSAVECHANGES); original=null; }
        app.activeDocument=working;
        if(working.mode!==DocumentMode.RGB || working.bitsPerChannel!==BitsPerChannelType.EIGHT)
            throw new Error('Use an 8-bit RGB full image.');
        var w=working.width.as('px'),h=working.height.as('px');
        var sx=w/c.reference_size[0],sy=h/c.reference_size[1],factor=Math.sqrt(sx*sy),poly=[];
        if(Math.abs(sx/sy-1)>0.01) throw new Error('Preset aspect ratio differs; re-locate the zipper.');
        if(!z.polygon || z.polygon.length<3) throw new Error('Need a polygon with at least 3 points.');
        for(var i=0;i<z.polygon.length;i++) {
            var x=z.polygon[i][0]*sx,y=z.polygon[i][1]*sy;
            if(x<0 || y<0 || x>w || y>h) throw new Error('Polygon is outside the canvas.');
            poly.push([x,y]);
        }
        function selectZipper() {
            working.activeChannels=working.componentChannels;
            working.selection.select(poly,SelectionType.REPLACE,z.feather*factor,true);
        }
        var base=working.activeLayer; base.name='Whole AI image - original retained';
        var main=base.duplicate(); main.name='Original zipper - deblur and local contrast'; working.activeLayer=main;
        selectZipper();
        var a=new ActionDescriptor();
        a.putUnitDouble(ch('Amnt'),ch('#Prc'),z.smart_sharpen_amount);
        a.putUnitDouble(ch('Rds '),ch('#Pxl'),z.smart_sharpen_radius*factor);
        a.putUnitDouble(st('noiseReduction'),ch('#Prc'),z.noise_reduction);
        a.putEnumerated(st('blur'),st('blurType'),st('lensBlur')); a.putBoolean(st('moreAccurate'),true);
        a.putEnumerated(st('presetKind'),st('presetKindType'),st('presetKindCustom'));
        function tone(fade,width) {
            var d=new ActionDescriptor(); d.putUnitDouble(ch('Amnt'),ch('#Prc'),fade);
            d.putUnitDouble(ch('Wdth'),ch('#Prc'),width); d.putInteger(ch('Rds '),z.tone_radius); return d;
        }
        a.putObject(st('highlightMode'),st('adaptCorrectTones'),tone(z.highlight_fade,z.highlight_width));
        a.putObject(st('shadowMode'),st('adaptCorrectTones'),tone(z.shadow_fade,z.shadow_width));
        executeAction(st('smartSharpen'),a,DialogModes.NO);
        main.applyUnSharpMask(z.usm_amount,z.usm_radius*factor,z.usm_threshold);
        main.blendMode=BlendMode.LUMINOSITY;
        var mask=new ActionDescriptor(),ref=new ActionReference();
        mask.putClass(ch('Nw  '),ch('Chnl')); ref.putEnumerated(ch('Chnl'),ch('Chnl'),ch('Msk '));
        mask.putReference(ch('At  '),ref); mask.putEnumerated(ch('Usng'),ch('UsrM'),ch('RvlS'));
        executeAction(ch('Mk  '),mask,DialogModes.NO); working.selection.deselect();
        var smooth=main.duplicate(); smooth.name='Original zipper - fine finish 25 percent'; working.activeLayer=smooth;
        selectZipper(); smooth.applySmartBlur(z.smooth_radius*factor,z.smooth_threshold,SmartBlurQuality.HIGH,SmartBlurMode.NORMAL);
        working.selection.deselect(); smooth.blendMode=BlendMode.LUMINOSITY; smooth.opacity=z.smooth_opacity;
        working.activeChannels=working.componentChannels;
        var p=new PNGSaveOptions();p.interlaced=false;p.compression=1;working.saveAs(outPng,p,true,Extension.LOWERCASE);
        var j=new JPEGSaveOptions();j.quality=12;j.embedColorProfile=true;working.saveAs(outJpg,j,true,Extension.LOWERCASE);
        if(outPsd) { var ps=new PhotoshopSaveOptions();ps.layers=true;ps.embedColorProfile=true;working.saveAs(outPsd,ps,true,Extension.LOWERCASE); }
        return 'OK|'+w+'|'+h+'|Photoshop '+app.version+'|original pixels and masks';
    } finally {
        if(working) working.close(SaveOptions.DONOTSAVECHANGES);
        if(openedHere && original) original.close(SaveOptions.DONOTSAVECHANGES);
        app.displayDialogs=oldDialogs;
        app.preferences.rulerUnits=oldUnits;
    }
})(SUPER_CLARITY_CONFIG);
