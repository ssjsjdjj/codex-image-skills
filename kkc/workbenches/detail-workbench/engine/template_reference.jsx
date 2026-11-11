/* Capture the saved source document before any normalization or data cleanup. */
function snapshotReferenceDocument(doc, output) {
    var preview;
    var stage = "切换到原稿副本";
    try {
        app.activeDocument = doc;
        stage = "复制原稿合成图";
        preview = doc.duplicate("母版原稿完整参考", true);
        app.activeDocument = preview;
        stage = "合并原稿预览";
        preview.flatten();
        stage = "调整原稿参考尺寸";
        var scale = Math.min(1, 790 / preview.width.as("px"), 30000 / preview.height.as("px"));
        if (scale < 1) preview.resizeImage(UnitValue(Math.max(1, Math.round(preview.width.as("px") * scale)), "px"),
                                           null, null, ResampleMethod.BICUBICSHARPER);
        var options = new JPEGSaveOptions();
        options.quality = 10;
        stage = "保存原稿参考图";
        preview.saveAs(new File(output), options, true, Extension.LOWERCASE);
    } catch (error) {
        throw new Error(stage + "失败，原第 " + error.line + " 行：" + error.message);
    } finally {
        if (preview) { try { preview.close(SaveOptions.DONOTSAVECHANGES); } catch (closePreviewError) {} }
        try { app.activeDocument = doc; } catch (restoreSourceError) {}
    }
}

function snapshotTemplateReference(spec) {
    var prior = app.documents.length ? app.activeDocument : null;
    var units = app.preferences.rulerUnits;
    var dialogs = app.displayDialogs;
    var source;
    try {
        app.preferences.rulerUnits = Units.PIXELS;
        app.displayDialogs = DialogModes.NO;
        source = app.open(new File(spec.source));
        snapshotReferenceDocument(source, spec.output);
        if (!(new File(spec.output)).exists) throw new Error("未生成母版原稿完整参考图");
    } finally {
        if (source) { try { source.close(SaveOptions.DONOTSAVECHANGES); } catch (closeSourceError) {} }
        app.preferences.rulerUnits = units;
        app.displayDialogs = dialogs;
        if (prior) { try { app.activeDocument = prior; } catch (restorePriorError) {} }
    }
}
