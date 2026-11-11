function selectTemplateLayer(doc, layerId) {
    app.activeDocument = doc;
    var reference = new ActionReference();
    reference.putIdentifier(stringIDToTypeID("layer"), layerId);
    var descriptor = new ActionDescriptor();
    descriptor.putReference(stringIDToTypeID("null"), reference);
    descriptor.putBoolean(stringIDToTypeID("makeVisible"), false);
    executeAction(stringIDToTypeID("select"), descriptor, DialogModes.NO);
    doc.activeChannels = doc.componentChannels;
}

function deleteTemplateLayer(layerId) {
    var reference = new ActionReference();
    reference.putIdentifier(stringIDToTypeID("layer"), layerId);
    var descriptor = new ActionDescriptor();
    descriptor.putReference(stringIDToTypeID("null"), reference);
    executeAction(stringIDToTypeID("delete"), descriptor, DialogModes.NO);
}

function keepLayers(parent, names) {
    var removals = [];
    var children = parent.layers;
    for (var i = 0, count = children.length; i < count; i++) {
        var layer = children[i];
        var keep = false;
        for (var j = 0; j < names.length; j++) if (layer.name === names[j]) keep = true;
        if (!keep) removals.push(layer.id);
    }
    for (i = removals.length - 1; i >= 0; i--) deleteTemplateLayer(removals[i]);
}

function legacyTemplateLayer(doc, path, typename) {
    var layer = findLayer(doc, path);
    if (typename && layer.typename !== typename) throw new Error("原始长版图层类型不符：" + path.join(" / "));
    return layer;
}

function legacyTemplateAnchor(layer, expected) {
    if (!layer.visible) throw new Error("原始长版定位图层已隐藏：" + layer.name);
    var actual = box(layer);
    for (var i = 0; i < expected.length; i++) {
        if (Math.abs(actual[i] - expected[i]) > 8) throw new Error("原始长版定位不符：" + layer.name);
    }
}

function validateRawWorkbenchTemplate(doc) {
    if (doc.width.as("px") !== 790 || doc.height.as("px") !== 40000) {
        throw new Error("原始裤装长版需要 790 × 40,000 px 及对应的原生分组");
    }
    var roots = ["T1 拷贝 2", "产品信息", "尺码", "17.模特展示", "19.门店"];
    for (var i = 0; i < roots.length; i++) {
        var root = legacyTemplateLayer(doc, [roots[i]], "LayerSet");
        if (!root.visible) throw new Error("原始长版模块已隐藏：" + roots[i]);
    }
    legacyTemplateLayer(doc, ["背景"], "ArtLayer");
    var required = [
        [["T1 拷贝 2"], ["矩形 1325", "组 1353", "儿童 功能性户外 服饰", "组 841 拷贝"]],
        [["产品信息"], ["矩形 948", "矩形 948 拷贝", "这样选更准确", "颜色", "产品信息"]],
        [["产品信息", "产品信息"], ["看看产品信息"]],
        [["产品信息", "颜色"], ["组 1071", "直线 1512 拷贝"]],
        [["尺码"], ["3", "4", "5"]],
        [["尺码", "3"], ["矩形 959 拷贝 4", "矩形 2101", "矩形 2107", "矩形 2107 拷贝",
            "矩形 2107 拷贝 2", "尺码", "组 841 拷贝 3", "组 1004", "组 1003", "组 1003 拷贝",
            "组 1003 拷贝 2", "组 1003 拷贝 3", "组 1003 拷贝 4", "矩形 959 拷贝 3",
            "注：因手工测量的方式不同，会有1-2cm误差属正常范围", "直线 2029", "矩形 2101 拷贝",
            "选择你的尺码 拷贝", "组 1071", "/cm", "Size", "组 483", "M", "F"]],
        [["尺码", "4"], ["矩形 959 拷贝 2", "组 1262", "组 841 拷贝 3", "组 1004",
            "矢量智能对象", "尺码快选", "椭圆 760 拷贝", "S4", "身高/体重"]],
        [["尺码", "4", "组 1004"], ["身高cm/体重kg"]],
        [["尺码", "4", "组 1262"], ["矩形 959 拷贝 4"]],
        [["尺码", "5"], ["矩形 959 拷贝 2", "矢量智能对象", "试穿报告", "椭圆 760 拷贝", "S5", "/cm", "组 1263"]],
        [["尺码", "5", "组 1263"], ["矩形 959 拷贝 4"]],
        [["17.模特展示"], ["模特展示", "矩形 991", "矩形 991 拷贝", "组 1123", "形状 1241"]],
        [["17.模特展示", "组 1123"], ["组 1132", "组 1132 拷贝"]],
        [["17.模特展示", "组 1123", "组 1132"], ["矩形 991 拷贝 2"]],
        [["17.模特展示", "组 1123", "组 1132 拷贝"], ["矩形 991 拷贝 2"]]
    ];
    for (i = 0; i < required.length; i++) {
        for (var j = 0; j < required[i][1].length; j++) {
            legacyTemplateLayer(doc, required[i][0].concat([required[i][1][j]]));
        }
    }
    var header = box(findLayer(doc, ["T1 拷贝 2", "矩形 1325"]));
    if (header[1] < 0 || header[3] > 650 || header[2] - header[0] < 600) {
        throw new Error("原始长版页头定位范围不符");
    }
    legacyTemplateAnchor(findLayer(doc, ["产品信息", "矩形 948 拷贝"]), [10, 25456, 780, 26930]);
    var anchors = [
        [["尺码", "3", "矩形 959 拷贝 4"], [31, 27232, 760, 27693]],
        [["尺码", "4", "组 1262", "矩形 959 拷贝 4"], [30, 27928, 759, 28389]],
        [["尺码", "5", "组 1263", "矩形 959 拷贝 4"], [28, 28618, 757, 28866]],
        [["17.模特展示", "矩形 991"], [8, 30875, 776, 31956]],
        [["17.模特展示", "矩形 991 拷贝"], [91, 32098, 692, 32886]],
        [["17.模特展示", "组 1123", "组 1132", "矩形 991 拷贝 2"], [8, 33062, 776, 34072]],
        [["17.模特展示", "组 1123", "组 1132 拷贝", "矩形 991 拷贝 2"], [8, 34127, 776, 35137]]
    ];
    for (i = 0; i < anchors.length; i++) {
        legacyTemplateAnchor(legacyTemplateLayer(doc, anchors[i][0], "ArtLayer"), anchors[i][1]);
    }
    if (findLayer(doc, ["尺码", "5", "/cm"]).kind !== LayerKind.TEXT) {
        throw new Error("原始长版试穿单位需要原生文字图层");
    }
    var footer = box(findLayer(doc, ["19.门店"]));
    if (footer[1] < 35137 || footer[2] - footer[0] < 600 || footer[3] - footer[1] < 200 ||
        footer[3] > doc.height.as("px") + 8) throw new Error("原始长版门店页尾范围不符");
    return {header: ["T1 拷贝 2"], source_size: [790, 40000]};
}

function prepareLegacyWorkbenchDocument(doc, spec) {
    validateRawWorkbenchTemplate(doc);
    templateImportStage(spec, "生成长页母版原稿预览");
    if (spec.originalPreview && !spec.originalPreviewReady) snapshotReferenceDocument(doc, spec.originalPreview);
    templateImportStage(spec, "准备长页母版的工作布局");
    selectTemplateLayer(doc, findLayer(doc, ["T1 拷贝 2"]).id);
    keepLayers(doc, ["背景", "T1 拷贝 2", "产品信息", "尺码", "17.模特展示", "19.门店"]);
    keepLayers(findLayer(doc, ["T1 拷贝 2"]), ["矩形 1325", "组 1353", "儿童 功能性户外 服饰",
        "专注儿童 户外 18年", "专注儿童 户外 18年 ", "专注儿童 户外 18年  ", "组 841 拷贝"]);
    keepLayers(findLayer(doc, ["产品信息"]), ["矩形 948", "矩形 948 拷贝", "这样选更准确", "颜色", "产品信息"]);
    keepLayers(findLayer(doc, ["产品信息", "产品信息"]), ["看看产品信息"]);
    keepLayers(findLayer(doc, ["产品信息", "颜色"]), ["组 1071", "直线 1512 拷贝"]);
    keepLayers(findLayer(doc, ["尺码"]), ["3", "4", "5"]);
    keepLayers(findLayer(doc, ["17.模特展示"]), ["模特展示", "矩形 991", "矩形 991 拷贝", "组 1123", "形状 1241"]);
    var pairs = ["组 1132", "组 1132 拷贝"];
    for (var i = 0; i < pairs.length; i++) {
        keepLayers(findLayer(doc, ["17.模特展示", "组 1123", pairs[i]]), ["矩形 991 拷贝 2"]);
    }
    var compact = [["产品信息"], ["尺码"], ["17.模特展示"], ["19.门店"]];
    for (i = 0; i < compact.length; i++) {
        templateImportStage(spec, "整理长页工作母版 · " + compact[i][0]);
        findLayer(doc, compact[i]).translate(UnitValue(0, "px"), UnitValue(-21800, "px"));
    }
    findLayer(doc, ["17.模特展示"]).translate(UnitValue(0, "px"), UnitValue(-1600, "px"));
    var footerRoot = findLayer(doc, ["19.门店"]);
    selectTemplateLayer(doc, footerRoot.id);
    var footer = footerRoot.merge();
    footer.name = "19.门店";
    footer.translate(UnitValue(0, "px"), UnitValue(11900 - box(footer)[1], "px"));
    doc.resizeCanvas(UnitValue(790, "px"), UnitValue(13395, "px"), AnchorPosition.TOPCENTER);
    doc.activeChannels = doc.componentChannels;
    spec.sourceIsWorking = false;
    return {family: "workbench"};
}

function prepareWorkbenchTemplate(spec) {
    var input = new File(spec.source);
    var output = new File(spec.output);
    var units = app.preferences.rulerUnits;
    var dialogs = app.displayDialogs;
    var prior = app.documents.length ? app.activeDocument : null;
    var doc;
    if (output.exists) throw new Error("工作台母版已存在");
    for (var i = 0; i < app.documents.length; i++) {
        try { var path = app.documents[i].fullName.fsName; } catch (_) { continue; }
        if (path.toLowerCase() === input.fsName.toLowerCase()) throw new Error("请先关闭已打开的原母版");
    }
    try {
        app.preferences.rulerUnits = Units.PIXELS;
        app.displayDialogs = DialogModes.NO;
        templateImportStage(spec, "打开长页母版工作副本");
        doc = app.open(input);
        doc.activeChannels = doc.componentChannels;
        doc.selection.deselect();
        prepareLegacyWorkbenchDocument(doc, spec);
        templateImportStage(spec, "保存长页工作母版");
        saveDetailPsb(output);
        if (!output.exists || output.length < 26) throw new Error("未生成工作台母版");
        templateImportStage(spec, "关闭长页母版工作副本");
        return "母版已准备：" + doc.height.as("px") + " px";
    } finally {
        if (doc) { try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (closeError) {} }
        app.preferences.rulerUnits = units;
        app.displayDialogs = dialogs;
        if (prior) { try { app.activeDocument = prior; } catch (priorError) {} }
    }
}
