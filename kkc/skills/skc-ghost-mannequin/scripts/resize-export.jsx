(function (c) {
    var dialogs = app.displayDialogs, units = app.preferences.rulerUnits, owned = null;
    function freshFile(path) {
        var f = new File(path);
        if (f.exists) throw new Error('Refusing to overwrite: ' + path);
        if (!f.parent.exists) throw new Error('Output folder does not exist: ' + path);
        return f;
    }
    var png = freshFile(c.png), jpg = freshFile(c.jpg), input = new File(c.input);
    for (var i=0; i<app.documents.length; i++) {
        try { if (app.documents[i].fullName.fsName === input.fsName) throw new Error('Input is already open; close that raw intermediate first.'); }
        catch (e) { if (String(e).indexOf('already open') >= 0) throw e; }
    }
    try {
        app.displayDialogs = DialogModes.NO;
        app.preferences.rulerUnits = Units.PIXELS;
        owned = app.open(input);
        if (owned.width.as('px') !== c.expected_width || owned.height.as('px') !== c.expected_height)
            throw new Error('Native 4x dimensions do not match source.');
        if (owned.mode !== DocumentMode.RGB) throw new Error('Expected RGB output.');
        owned.resizeImage(UnitValue(c.width,'px'), UnitValue(c.height,'px'), null, ResampleMethod.BICUBIC);
        var p = new PNGSaveOptions(); p.interlaced=false; p.compression=1;
        owned.saveAs(png,p,true,Extension.LOWERCASE);
        var j = new JPEGSaveOptions(); j.quality=12; j.embedColorProfile=true;
        owned.saveAs(jpg,j,true,Extension.LOWERCASE);
        return 'OK|' + owned.width.as('px') + '|' + owned.height.as('px') + '|Photoshop ' + app.version;
    } finally {
        if (owned) owned.close(SaveOptions.DONOTSAVECHANGES);
        app.displayDialogs = dialogs;
        app.preferences.rulerUnits = units;
    }
})(SUPER_CLARITY_CONFIG);
