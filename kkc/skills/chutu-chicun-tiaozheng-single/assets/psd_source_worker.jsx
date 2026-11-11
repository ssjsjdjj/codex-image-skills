/* Fixed Photoshop-native PSD worker. Request data is parsed as JSON, never eval. */
(function (argv) {
    function fail(message) { throw new Error(message); }
    function parseJSON(text) {
        if (typeof JSON !== 'undefined' && JSON.parse) return JSON.parse(text);
        var index = 0;
        function space() { while (index < text.length && /\s/.test(text.charAt(index))) index++; }
        function string() {
            if (text.charAt(index++) !== '"') fail('Invalid JSON string');
            var out = '', c, code, escaped;
            while (index < text.length) {
                c = text.charAt(index++);
                if (c === '"') return out;
                if (c === '\\') {
                    escaped = text.charAt(index++);
                    if (escaped === 'u') {
                        code = text.substr(index, 4);
                        if (!/^[0-9a-fA-F]{4}$/.test(code)) fail('Invalid JSON Unicode escape');
                        out += String.fromCharCode(parseInt(code, 16)); index += 4;
                    } else {
                        var escapes = {'"':'"', '\\':'\\', '/':'/', 'b':'\b', 'f':'\f', 'n':'\n', 'r':'\r', 't':'\t'};
                        if (!escapes.hasOwnProperty(escaped)) fail('Invalid JSON escape');
                        out += escapes[escaped];
                    }
                } else {
                    if (c.charCodeAt(0) < 32) fail('JSON control character');
                    out += c;
                }
            }
            fail('Unterminated JSON string');
        }
        function value() {
            space(); var c = text.charAt(index), result, key, match;
            if (c === '"') return string();
            if (c === '[') {
                index++; result = []; space();
                if (text.charAt(index) === ']') { index++; return result; }
                while (true) {
                    result.push(value()); space(); c = text.charAt(index++);
                    if (c === ']') return result;
                    if (c !== ',') fail('Invalid JSON array');
                }
            }
            if (c === '{') {
                index++; result = {}; space();
                if (text.charAt(index) === '}') { index++; return result; }
                while (true) {
                    space(); key = string();
                    if (key === '__proto__' || key === 'constructor' || key === 'prototype' || result.hasOwnProperty(key)) fail('Unsafe or duplicate JSON key');
                    space(); if (text.charAt(index++) !== ':') fail('Invalid JSON object');
                    result[key] = value(); space(); c = text.charAt(index++);
                    if (c === '}') return result;
                    if (c !== ',') fail('Invalid JSON object');
                }
            }
            if (text.substr(index, 4) === 'true') { index += 4; return true; }
            if (text.substr(index, 5) === 'false') { index += 5; return false; }
            if (text.substr(index, 4) === 'null') { index += 4; return null; }
            match = text.substr(index).match(/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/);
            if (!match) fail('Invalid JSON value');
            index += match[0].length; result = Number(match[0]);
            if (!isFinite(result)) fail('Non-finite JSON number');
            return result;
        }
        var result = value(); space();
        if (index !== text.length) fail('Trailing JSON content');
        return result;
    }
    function stringify(value) {
        if (typeof JSON !== 'undefined' && JSON.stringify) return JSON.stringify(value);
        function quote(text) {
            return '"' + String(text).replace(/[\\"\x00-\x1f]/g, function (c) {
                if (c === '\\') return '\\\\'; if (c === '"') return '\\"';
                var hex = c.charCodeAt(0).toString(16); while (hex.length < 4) hex = '0' + hex;
                return '\\u' + hex;
            }) + '"';
        }
        if (value === null) return 'null';
        if (typeof value === 'string') return quote(value);
        if (typeof value === 'number' || typeof value === 'boolean') return String(value);
        var values = [], key, i;
        if (value instanceof Array) {
            for (i = 0; i < value.length; i++) values.push(stringify(value[i]));
            return '[' + values.join(',') + ']';
        }
        for (key in value) if (value.hasOwnProperty(key)) values.push(quote(key) + ':' + stringify(value[key]));
        return '{' + values.join(',') + '}';
    }
    function readJSON(path) {
        var file = new File(path); file.encoding = 'UTF8';
        if (!file.open('r')) fail('Cannot open fixed request JSON');
        var text = file.read(); file.close();
        if (text.charCodeAt(0) === 0xfeff) text = text.substr(1);
        return parseJSON(text);
    }
    function writeJSON(path, object) {
        var file = new File(path); file.encoding = 'UTF8';
        if (!file.open('w')) fail('Cannot write native PSD result');
        file.write(stringify(object)); file.close();
    }
    if (!argv || argv.length !== 1) fail('Exactly one fixed request path is required');
    var request = readJSON(argv[0]);
    if (!request.response_path) fail('Missing native response path');
    var originalIDs = {}, originalActive = null, owned = [], originalRulers, originalDialogs;
    var result = {ok:false, code:'PHOTOSHOP_NATIVE_ERROR'}, i;
    for (i = 0; i < app.documents.length; i++) originalIDs[String(app.documents[i].id)] = true;
    if (app.documents.length) originalActive = app.activeDocument.id;
    originalRulers = app.preferences.rulerUnits; originalDialogs = app.displayDialogs;
    function own(document) {
        if (originalIDs[String(document.id)]) fail('Refusing to modify a pre-existing user document');
        owned.push({document:document, id:document.id}); return document;
    }
    function active(document) { app.activeDocument = document; }
    function closeOwn(document) {
        if (originalIDs[String(document.id)]) fail('Refusing to close a user document');
        document.close(SaveOptions.DONOTSAVECHANGES);
    }
    function dimensions(document) { return [Math.round(document.width.as('px')), Math.round(document.height.as('px'))]; }
    function ensureNew(path) { if (!path || new File(path).exists) fail('Native output exists or path is missing'); }
    function openCopy(path) {
        var file = new File(path); if (!file.exists) fail('Independent PSD cache copy does not exist');
        return own(app.open(file));
    }
    function maskFlags(layer) {
        var reference = new ActionReference(); reference.putIdentifier(charIDToTypeID('Lyr '), layer.id);
        var descriptor = executeActionGet(reference);
        function flag(name) { var key = stringIDToTypeID(name); return descriptor.hasKey(key) && descriptor.getBoolean(key); }
        return {mask:flag('hasUserMask'), vector_mask:flag('hasVectorMask')};
    }
    function structure(document) {
        active(document);
        function visit(layers) {
            var rows = [], j, layer, flags, row;
            for (j = 0; j < layers.length; j++) {
                layer = layers[j]; flags = maskFlags(layer);
                row = {name:layer.name, kind:layer.typename === 'LayerSet' ? 'group' : String(layer.kind),
                       visible:layer.visible, mask:flags.mask, vector_mask:flags.vector_mask};
                if (layer.typename === 'LayerSet') row.children = visit(layer.layers);
                rows.push(row);
            }
            return rows;
        }
        return visit(document.layers);
    }
    function savePSD(document, path) {
        ensureNew(path); active(document);
        var options = new PhotoshopSaveOptions(); options.layers = true; options.alphaChannels = true;
        options.embedColorProfile = true; options.annotations = true; options.spotColors = true;
        document.saveAs(new File(path), options, true, Extension.LOWERCASE);
    }
    function render() {
        ensureNew(request.variant_path); ensureNew(request.preview_path);
        var opened = openCopy(request.source_copy);
        var document = own(opened.duplicate('Codex native working copy', false)); closeOwn(opened); active(document);
        var before = structure(document), sourceSize = dimensions(document), viewport = request.viewport, size = request.size;
        if (document.pixelAspectRatio !== 1) fail('Non-square source pixels are not supported by this native backend');
        if (!viewport || viewport.length !== 4 || !size || size.length !== 2) fail('Invalid native geometry request');
        if (viewport[0] < 0 || viewport[1] < 0 || viewport[2] > sourceSize[0] || viewport[3] > sourceSize[1]) fail('Native padding is not supported');
        var cropWidth = viewport[2] - viewport[0], cropHeight = viewport[3] - viewport[1];
        if (cropWidth <= 0 || cropHeight <= 0 || Math.abs(cropWidth / cropHeight - size[0] / size[1]) > 0.000001) fail('Native stretch is not permitted');
        document.crop([UnitValue(viewport[0],'px'),UnitValue(viewport[1],'px'),UnitValue(viewport[2],'px'),UnitValue(viewport[3],'px')]);
        var actualCrop = dimensions(document);
        if (actualCrop[0] !== cropWidth || actualCrop[1] !== cropHeight) fail('Photoshop crop pixels differ from the approved integer plan');
        var method = size[0] > cropWidth ? ResampleMethod.BICUBICSMOOTHER : ResampleMethod.BICUBICSHARPER;
        document.resizeImage(UnitValue(size[0],'px'), undefined, undefined, method);
        var actualSize = dimensions(document);
        if (actualSize[0] !== size[0] || actualSize[1] !== size[1]) fail('Native proportional resize did not reach the exact target size');
        var after = structure(document);
        if (stringify(before) !== stringify(after)) fail('Native PSD layer structure changed during crop/resize');
        savePSD(document,request.variant_path);
        var preview = own(document.duplicate('Codex lossless PNG preview', true)); active(preview);
        if (preview.mode !== DocumentMode.RGB) preview.changeMode(ChangeMode.RGB);
        if (preview.bitsPerChannel !== BitsPerChannelType.EIGHT) preview.bitsPerChannel = BitsPerChannelType.EIGHT;
        preview.convertProfile('sRGB IEC61966-2.1',Intent.RELATIVECOLORIMETRIC,true,true);
        var pngOptions = new PNGSaveOptions(); pngOptions.interlaced = false; pngOptions.compression = 0;
        preview.saveAs(new File(request.preview_path),pngOptions,true,Extension.LOWERCASE); closeOwn(preview);
        return {size:actualSize, source_size:sourceSize, before_structure:before, after_structure:after, preview_color_space:'sRGB'};
    }
    function wrapLayers(document, name) {
        active(document); var layers = [], locked = [], j, layer, oldName;
        for (j = 0; j < document.layers.length; j++) layers.push(document.layers[j]);
        var group = document.layerSets.add(); group.name = name;
        for (j = layers.length - 1; j >= 0; j--) {
            layer = layers[j]; oldName = layer.name;
            if (layer.typename === 'ArtLayer' && layer.isBackgroundLayer) { layer.isBackgroundLayer = false; layer.name = oldName; }
            locked[j] = layer.allLocked;
            if (locked[j]) layer.allLocked = false;
            layer.move(group, ElementPlacement.INSIDE);
            if (locked[j]) layer.allLocked = true;
        }
        return group;
    }
    function groupSources() {
        ensureNew(request.destination);
        if (!request.source_copies || !request.names || request.source_copies.length !== request.names.length || !request.names.length) fail('Invalid native group request');
        var opened = openCopy(request.source_copies[0]);
        var destination = own(opened.duplicate('Codex native grouped source',false)); closeOwn(opened); active(destination);
        var sourceSize = dimensions(destination), firstBefore = structure(destination);
        var firstGroup = wrapLayers(destination,request.names[0]); firstGroup.visible = true;
        if (stringify(structure(destination)[0].children) !== stringify(firstBefore)) fail('First native source order changed while grouping');
        var j, source, before, group, copied, actual;
        for (j = 1; j < request.source_copies.length; j++) {
            source = openCopy(request.source_copies[j]); active(source);
            actual = dimensions(source);
            if (actual[0] !== sourceSize[0] || actual[1] !== sourceSize[1]) fail('Native group source dimensions differ');
            before = structure(source); group = wrapLayers(source,request.names[j]);
            if (stringify(structure(source)[0].children) !== stringify(before)) fail('Native source order changed while grouping');
            copied = group.duplicate(destination,ElementPlacement.PLACEATEND); copied.visible = false;
            closeOwn(source); active(destination);
        }
        var groups = destination.layerSets;
        if (groups.length !== request.names.length) fail('Native group count mismatch');
        for (j = 0; j < groups.length; j++) {
            if (groups[j].name !== request.names[j]) fail('Native group panel order mismatch');
            groups[j].visible = j === 0;
        }
        savePSD(destination,request.destination);
        return {size:sourceSize, native_structure:structure(destination), panel_order:request.names, visible_groups:[request.names[0]]};
    }
    function testFixture() {
        ensureNew(request.destination);
        var side = request.side || 800;
        var document = own(app.documents.add(UnitValue(side,'px'),UnitValue(side,'px'),72,'Codex isolated native fixture',NewDocumentMode.RGB,DocumentFill.TRANSPARENT));
        var group = document.layerSets.add(); group.name = 'Native group';
        var pixel = group.artLayers.add(); pixel.name = 'Smart content'; active(document); document.activeLayer = pixel;
        var color = new SolidColor(); color.rgb.red = 30; color.rgb.green = 120; color.rgb.blue = 210;
        document.selection.select([[side*.1,side*.2],[side*.9,side*.2],[side*.9,side*.9],[side*.1,side*.9]]);
        document.selection.fill(color); document.selection.deselect();
        executeAction(stringIDToTypeID('newPlacedLayer'),undefined,DialogModes.NO);
        document.activeLayer.name = 'Native smart object';
        var mask = new ActionDescriptor(); mask.putClass(charIDToTypeID('Nw  '),charIDToTypeID('Chnl'));
        var reference = new ActionReference(); reference.putEnumerated(charIDToTypeID('Chnl'),charIDToTypeID('Chnl'),charIDToTypeID('Msk '));
        mask.putReference(charIDToTypeID('At  '),reference); mask.putEnumerated(charIDToTypeID('Usng'),charIDToTypeID('UsrM'),charIDToTypeID('RvlA'));
        executeAction(charIDToTypeID('Mk  '),mask,DialogModes.NO);
        var text = group.artLayers.add(); text.name = 'Editable text'; text.kind = LayerKind.TEXT;
        text.textItem.contents = 'NATIVE PSD'; text.textItem.position = [UnitValue(side*.1,'px'),UnitValue(side*.15,'px')]; text.textItem.size = UnitValue(24,'pt');
        document.convertProfile('sRGB IEC61966-2.1',Intent.RELATIVECOLORIMETRIC,true,true);
        savePSD(document,request.destination);
        return {size:dimensions(document), native_structure:structure(document)};
    }
    try {
        app.preferences.rulerUnits = Units.PIXELS; app.displayDialogs = DialogModes.NO;
        if (request.action === 'render') result.result = render();
        else if (request.action === 'group') result.result = groupSources();
        else if (request.action === 'test_fixture') result.result = testFixture();
        else fail('Unsupported fixed native action');
        result.ok = true; result.photoshop_version = app.version;
    } catch (error) {
        result.ok = false; result.error = String(error) + (error.line ? ' (JSX line ' + error.line + ')' : '');
    } finally {
        var remainingOwned = [], j, exists, k;
        for (j = owned.length - 1; j >= 0; j--) {
            exists = false;
            for (k = 0; k < app.documents.length; k++) if (app.documents[k].id === owned[j].id) { exists = true; break; }
            if (exists) {
                try { active(owned[j].document); closeOwn(owned[j].document); }
                catch (closeError) { remainingOwned.push(owned[j].id); }
            }
        }
        result.owned_documents_closed = remainingOwned.length === 0;
        try { app.preferences.rulerUnits = originalRulers; app.displayDialogs = originalDialogs; result.preferences_restored = true; }
        catch (preferencesError) { result.preferences_restored = false; }
        result.active_document_restored = originalActive === null;
        if (originalActive !== null) for (j = 0; j < app.documents.length; j++) if (app.documents[j].id === originalActive) {
            try { app.activeDocument = app.documents[j]; result.active_document_restored = true; } catch (activeError) {}
            break;
        }
        if (!result.owned_documents_closed || !result.preferences_restored || !result.active_document_restored) {
            result.ok = false; result.error = (result.error || '') + ' Native task cleanup or original activity restoration failed.';
        }
        writeJSON(request.response_path,result);
    }
    return stringify(result);
})(arguments);
