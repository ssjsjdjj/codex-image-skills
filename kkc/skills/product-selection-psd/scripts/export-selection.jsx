function exportProductSelection(job) {
    var output = new File(job.output);
    var source = new File(job.source);
    if (!source.exists || output.exists || !/\.psd$/i.test(output.name) || !output.parent.exists)
        throw new Error("Invalid source or output path");
    if (!job.layers || !job.layers.length) throw new Error("No product layers specified");
    function ensureClosed(file) {
        for (var i = 0; i < app.documents.length; i++) {
            var openedPath = null;
            try { openedPath = app.documents[i].fullName.fsName; } catch (ignored) {}
            if (openedPath === file.fsName) throw new Error("File is already open. Use an on-disk copy.");
        }
    }
    ensureClosed(source);

    var previous = app.documents.length ? app.activeDocument : null;
    var dialogs = app.displayDialogs;
    var units = app.preferences.rulerUnits;
    var doc, maskDoc, reopened;
    var bounds = [];
    var c = charIDToTypeID;

    function selectionBounds(document) {
        var box = document.selection.bounds;
        return [box[0].as("px"), box[1].as("px"), box[2].as("px"), box[3].as("px")].join(",");
    }

    function maskReference() {
        var reference = new ActionReference();
        reference.putEnumerated(c("Chnl"), c("Chnl"), c("Msk "));
        return reference;
    }

    var i;
    try {
        app.displayDialogs = DialogModes.NO;
        app.preferences.rulerUnits = Units.PIXELS;
        doc = app.open(source);
        if (doc.layers.length !== 1 || !doc.layers[0].isBackgroundLayer ||
            doc.mode !== DocumentMode.RGB || doc.bitsPerChannel !== BitsPerChannelType.EIGHT)
            throw new Error("Expected a flat 8-bit RGB background image");
        var base = doc.layers[0];
        var width = Math.round(doc.width.as("px")), height = Math.round(doc.height.as("px"));

        for (i = 0; i < job.layers.length; i++) {
            var item = job.layers[i];
            var maskFile = new File(item.mask);
            if (!item.name || !maskFile.exists || !/\.png$/i.test(maskFile.name))
                throw new Error("Missing layer name or mask PNG");

            var product = base.duplicate(doc.layers[0], ElementPlacement.PLACEBEFORE);
            doc.activeLayer = product;
            if (item.smartObject)
                executeAction(stringIDToTypeID("newPlacedLayer"), new ActionDescriptor(), DialogModes.NO);
            doc.activeLayer.name = item.name;

            ensureClosed(maskFile);
            maskDoc = app.open(maskFile);
            if (Math.round(maskDoc.width.as("px")) !== width || Math.round(maskDoc.height.as("px")) !== height ||
                maskDoc.mode !== DocumentMode.GRAYSCALE || maskDoc.bitsPerChannel !== BitsPerChannelType.EIGHT)
                throw new Error("Expected a same-size 8-bit grayscale mask");
            maskDoc.resizeImage(undefined, undefined, doc.resolution, ResampleMethod.NONE);
            maskDoc.selection.selectAll();
            maskDoc.selection.copy();
            maskDoc.close(SaveOptions.DONOTSAVECHANGES);
            maskDoc = null;

            app.activeDocument = doc;
            var alpha = doc.channels.add();
            doc.activeChannels = [alpha];
            doc.paste();
            doc.selection.deselect();
            doc.selection.load(alpha, SelectionType.REPLACE);
            bounds.push(selectionBounds(doc));
            doc.activeChannels = doc.componentChannels;
            alpha.remove();

            var make = new ActionDescriptor();
            make.putClass(c("Nw  "), c("Chnl"));
            make.putReference(c("At  "), maskReference());
            make.putEnumerated(c("Usng"), c("UsrM"), c("RvlS"));
            executeAction(c("Mk  "), make, DialogModes.NO);
            doc.selection.deselect();
        }

        var options = new PhotoshopSaveOptions();
        options.layers = true;
        options.embedColorProfile = true;
        if (output.exists) throw new Error("Output path already exists");
        doc.saveAs(output, options, true, Extension.LOWERCASE);
        doc.close(SaveOptions.DONOTSAVECHANGES);
        doc = null;

        reopened = app.open(output);
        var count = job.layers.length;
        if (Math.round(reopened.width.as("px")) !== width || Math.round(reopened.height.as("px")) !== height ||
            reopened.layers.length !== count + 1 || !reopened.layers[count].isBackgroundLayer ||
            !reopened.layers[count].visible)
            throw new Error("Unexpected saved document structure");

        for (i = 0; i < count; i++) {
            var layer = reopened.layers[count - 1 - i];
            if (layer.name !== job.layers[i].name ||
                layer.kind !== (job.layers[i].smartObject ? LayerKind.SMARTOBJECT : LayerKind.NORMAL))
                throw new Error("Unexpected saved product layer");
            reopened.activeLayer = layer;
            var load = new ActionDescriptor();
            var target = new ActionReference();
            target.putProperty(c("Chnl"), c("fsel"));
            load.putReference(c("null"), target);
            load.putReference(c("T   "), maskReference());
            executeAction(c("setd"), load, DialogModes.NO);
            if (selectionBounds(reopened) !== bounds[i]) throw new Error("Saved mask bounds differ");
            reopened.selection.deselect();
        }
        return "Verified " + width + " x " + height + ", product layers: " + count;
    } finally {
        if (maskDoc) maskDoc.close(SaveOptions.DONOTSAVECHANGES);
        if (doc) doc.close(SaveOptions.DONOTSAVECHANGES);
        if (reopened) reopened.close(SaveOptions.DONOTSAVECHANGES);
        app.displayDialogs = dialogs;
        app.preferences.rulerUnits = units;
        if (previous) app.activeDocument = previous;
    }
}
