(function(c) {
    var previous=app.documents.length?app.activeDocument:null,oldDialogs=app.displayDialogs,oldUnits=app.preferences.rulerUnits;
    var owned=[],working=null,nonwhite=null,st=stringIDToTypeID,ch=charIDToTypeID,p=c.profile;
    function openOwned(path) {
        var f=new File(path);
        for(var i=0;i<app.documents.length;i++) {
            try { if(app.documents[i].fullName.fsName===f.fsName) {
                if(!app.documents[i].saved) throw new Error('Input has unsaved changes.');
                var copy=app.documents[i].duplicate('SC V3 disposable source',false);owned.push(copy);return copy;
            }} catch(e) {if(String(e).indexOf('unsaved')>=0) throw e;}
        }
        var d=app.open(f);owned.push(d);return d;
    }
    function closeOwned(d) {for(var i=owned.length-1;i>=0;i--) if(owned[i]===d) {d.close(SaveOptions.DONOTSAVECHANGES);owned.splice(i,1);return;}}
    function fresh(path) {var f=new File(path);if(f.exists)throw new Error('Refusing overwrite: '+path);return f;}
    function savePng(d,file) {var o=new PNGSaveOptions();o.compression=1;o.interlaced=false;d.saveAs(file,o,true,Extension.LOWERCASE);}
    function selectRegion(r,w,h) {
        working.activeChannels=working.componentChannels;
        function mapped(points) {
            var result=[];
            for(var i=0;i<points.length;i++) {
                var x=points[i][0]*w/p.reference_size[0],y=points[i][1]*h/p.reference_size[1];
                if(x<0||y<0||x>w||y>h)throw new Error('Region outside canvas: '+r.id);
                result.push([x,y]);
            }
            return result;
        }
        for(var n=0;n<r.polygons.length;n++)working.selection.select(mapped(r.polygons[n]),n?SelectionType.EXTEND:SelectionType.REPLACE,r.feather_px||0,true);
        var protection=p.protected_regions||[];
        for(var j=0;j<protection.length;j++)working.selection.select(mapped(protection[j].polygon),SelectionType.DIMINISH,0,true);
        if(nonwhite)working.selection.load(nonwhite,SelectionType.INTERSECT);
    }
    function makeMask() {
        var a=new ActionDescriptor(),r=new ActionReference();a.putClass(ch('Nw  '),ch('Chnl'));r.putEnumerated(ch('Chnl'),ch('Chnl'),ch('Msk '));a.putReference(ch('At  '),r);
        a.putEnumerated(ch('Usng'),ch('UsrM'),ch('RvlS'));executeAction(ch('Mk  '),a,DialogModes.NO);working.selection.deselect();working.activeChannels=working.componentChannels;
    }
    function deblur(r) {
        var a=new ActionDescriptor();a.putUnitDouble(ch('Amnt'),ch('#Prc'),r.amount);a.putUnitDouble(ch('Rds '),ch('#Pxl'),r.radius_px);
        a.putUnitDouble(st('noiseReduction'),ch('#Prc'),r.noise_reduction);a.putEnumerated(st('blur'),st('blurType'),st('lensBlur'));a.putBoolean(st('moreAccurate'),true);
        a.putEnumerated(st('presetKind'),st('presetKindType'),st('presetKindCustom'));
        function tone(amount,width) {var d=new ActionDescriptor();d.putUnitDouble(ch('Amnt'),ch('#Prc'),amount);d.putUnitDouble(ch('Wdth'),ch('#Prc'),width);d.putInteger(ch('Rds '),r.tone_radius);return d;}
        a.putObject(st('highlightMode'),st('adaptCorrectTones'),tone(r.highlight_fade,r.highlight_width));a.putObject(st('shadowMode'),st('adaptCorrectTones'),tone(r.shadow_fade,r.shadow_width));
        executeAction(st('smartSharpen'),a,DialogModes.NO);
    }
    var png=fresh(c.png),psd=c.preview_only?null:fresh(c.psd);
    try {
        app.displayDialogs=DialogModes.NO;app.preferences.rulerUnits=Units.PIXELS;
        var source=openOwned(c.input_psd);working=source.duplicate('SKC regional definition V3',false);owned.push(working);closeOwned(source);
        if(working.mode!==DocumentMode.RGB||working.bitsPerChannel!==BitsPerChannelType.EIGHT)throw new Error('This module expects the reviewed 8-bit RGB baseline.');
        var w=working.width.as('px'),h=working.height.as('px');
        if(w!==p.reference_size[0]||h!==p.reference_size[1])throw new Error('Relocate and rescale the regional profile for this canvas.');
        var snapshot=openOwned(c.input_png);
        if(snapshot.mode!==DocumentMode.RGB||snapshot.bitsPerChannel!==BitsPerChannelType.EIGHT)throw new Error('Snapshot must be 8-bit RGB.');
        if(snapshot.width.as('px')!==w||snapshot.height.as('px')!==h)throw new Error('Baseline PSD and PNG sizes differ.');
        var frozen=snapshot.activeLayer.duplicate(working,ElementPlacement.PLACEATBEGINNING);closeOwned(snapshot);app.activeDocument=working;
        working.activeLayer=frozen;working.activeLayer.name='V3 baseline - exact accepted PNG full frame';working.activeLayer.allLocked=true;
        var matte=working.artLayers.getByName('V3 baseline - exact accepted PNG full frame').duplicate(working,ElementPlacement.PLACEATBEGINNING);
        working.activeLayer=matte;matte.allLocked=false;matte.name='SC temporary background protection';
        var threshold=new ActionDescriptor();threshold.putInteger(ch('Lvl '),254);executeAction(ch('Thrs'),threshold,DialogModes.NO);executeAction(ch('Invr'),undefined,DialogModes.NO);
        working.selection.load(working.componentChannels[0],SelectionType.REPLACE);
        nonwhite=working.channels.add();nonwhite.name='SC temporary nonwhite selection';working.selection.store(nonwhite,SelectionType.REPLACE);
        working.selection.deselect();working.activeChannels=working.componentChannels;
        working.artLayers.getByName('SC temporary background protection').remove();
        for(var i=0;i<p.regions.length;i++) {
            var r=p.regions[i];var layer=working.artLayers.getByName('V3 baseline - exact accepted PNG full frame').duplicate(working,ElementPlacement.PLACEATBEGINNING);
            working.activeLayer=layer;layer.allLocked=false;layer.name='Definition - '+r.id;
            selectRegion(r,w,h);deblur(r);
            working.activeLayer.blendMode=BlendMode.DARKEN;working.activeLayer.opacity=r.opacity;makeMask();
        }
        working.activeChannels=working.componentChannels;nonwhite.remove();nonwhite=null;
        if(c.preview_only) {savePng(working,png);return 'OK|preview|'+w+'|'+h+'|regions='+p.regions.length;}
        var o=new PhotoshopSaveOptions();o.layers=true;o.embedColorProfile=true;o.maximizeCompatibility=true;working.saveAs(psd,o,false,Extension.LOWERCASE);closeOwned(working);working=null;
        var reopened=openOwned(psd.fsName),count=0;
        for(var j=0;j<reopened.layers.length;j++) {
            var item=reopened.layers[j];
            if(item.name.indexOf('Definition - ')===0) {
                var ref=new ActionReference();ref.putIdentifier(ch('Lyr '),item.id);var info=executeActionGet(ref);
                if(!info.hasKey(st('hasUserMask'))||!info.getBoolean(st('hasUserMask'))||item.blendMode!==BlendMode.DARKEN)throw new Error('Missing editable regional mask or highlight guard.');
                count++;
            }
        }
        if(count!==p.regions.length)throw new Error('Regional layer count differs.');
        savePng(reopened,png);
        return 'OK|'+w+'|'+h+'|regional_masks='+count+'|layers='+reopened.layers.length+'|Photoshop '+app.version;
    } finally {
        for(var z=owned.length-1;z>=0;z--){try{owned[z].close(SaveOptions.DONOTSAVECHANGES);}catch(ignore){}}
        app.displayDialogs=oldDialogs;app.preferences.rulerUnits=oldUnits;
        if(previous){try{app.activeDocument=previous;}catch(ignore2){}}
    }
})(SUPER_CLARITY_CONFIG);
