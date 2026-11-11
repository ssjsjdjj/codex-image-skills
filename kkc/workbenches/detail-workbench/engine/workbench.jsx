var workbenchInk = [33, 51, 48];
var workbenchGreen = [34, 118, 77];
var workbenchActiveJob = null;
var workbenchModelPaths = [["矩形 991"], ["矩形 991 拷贝"], ["组 1123", "组 1132", "矩形 991 拷贝 2"],
                           ["组 1123", "组 1132 拷贝", "矩形 991 拷贝 2"]];

function checkTemplateLayers(parent, names) {
    if (parent.layers.length !== names.length) {
        throw new Error("母版需要使用未套版的结构，请检查分组：" + parent.name);
    }
    for (var i = 0; i < names.length; i++) findLayer(parent, [names[i]]);
}

function checkTemplateAnchor(layer, expected) {
    if (!layer.visible) throw new Error("母版定位图层已隐藏：" + layer.name);
    var actual = box(layer);
    for (var i = 0; i < expected.length; i++) {
        if (Math.abs(actual[i] - expected[i]) > 8) {
            throw new Error("母版定位图层尺寸或位置不兼容：" + layer.name);
        }
    }
}

function checkWorkbenchTemplate(doc) {
    if (doc.width.as("px") !== 790 || doc.height.as("px") < 11750) {
        throw new Error("当前工作台母版需要 790 px 宽并容纳完整图位");
    }
    checkTemplateLayers(doc, ["背景", "T1 拷贝 2", "产品信息", "尺码", "17.模特展示", "19.门店"]);
    var header = findLayer(doc, ["T1 拷贝 2"]);
    if (!header.visible || box(header)[3] > 650) throw new Error("母版页头需要保留在商品主图上方");
    var panel = findLayer(doc, ["产品信息"]);
    checkTemplateLayers(panel, ["矩形 948", "矩形 948 拷贝", "这样选更准确", "颜色", "产品信息"]);
    checkTemplateAnchor(findLayer(panel, ["矩形 948 拷贝"]), [10, 3656, 780, 5130]);
    checkTemplateLayers(findLayer(panel, ["产品信息"]), ["看看产品信息"]);
    checkTemplateLayers(findLayer(panel, ["颜色"]), ["组 1071", "直线 1512 拷贝"]);
    var sizes = findLayer(doc, ["尺码"]);
    checkTemplateLayers(sizes, ["3", "4", "5"]);
    var model = findLayer(doc, ["17.模特展示"]);
    if (!panel.visible || !sizes.visible || !model.visible) throw new Error("母版的产品信息、尺码和模特分组需要保持显示");
    var section = findLayer(sizes, ["3"]);
    var replaceable = ["矩形 959 拷贝 4", "矩形 2101", "矩形 2107", "矩形 2107 拷贝", "矩形 2107 拷贝 2",
                       "尺码", "组 841 拷贝 3", "组 1004", "组 1003", "组 1003 拷贝", "组 1003 拷贝 2",
                       "组 1003 拷贝 3", "组 1003 拷贝 4"];
    checkTemplateLayers(section, replaceable.concat(["矩形 959 拷贝 3", "注：因手工测量的方式不同，会有1-2cm误差属正常范围",
        "直线 2029", "矩形 2101 拷贝", "选择你的尺码 拷贝", "组 1071", "/cm", "Size", "组 483", "M", "F"]));
    checkTemplateAnchor(findLayer(section, ["矩形 959 拷贝 4"]), [31, 5432, 760, 5893]);
    section = findLayer(sizes, ["4"]);
    checkTemplateLayers(section, ["矩形 959 拷贝 2", "组 1262", "组 841 拷贝 3", "组 1004", "矢量智能对象",
                                  "尺码快选", "椭圆 760 拷贝", "S4", "身高/体重"]);
    findLayer(section, ["组 1004", "身高cm/体重kg"]);
    checkTemplateAnchor(findLayer(section, ["组 1262", "矩形 959 拷贝 4"]), [30, 6128, 759, 6589]);
    section = findLayer(sizes, ["5"]);
    checkTemplateLayers(section, ["矩形 959 拷贝 2", "矢量智能对象", "试穿报告", "椭圆 760 拷贝", "S5", "/cm", "组 1263"]);
    if (findLayer(section, ["/cm"]).kind !== LayerKind.TEXT) throw new Error("试穿报告的单位需要是文字图层");
    checkTemplateAnchor(findLayer(section, ["组 1263", "矩形 959 拷贝 4"]), [28, 6818, 757, 7066]);
    checkTemplateLayers(model, ["模特展示", "矩形 991", "矩形 991 拷贝", "组 1123", "形状 1241"]);
    checkTemplateLayers(findLayer(model, ["组 1123"]), ["组 1132", "组 1132 拷贝"]);
    var frames = [[8, 7475, 776, 8556], [91, 8698, 692, 9486], [8, 9662, 776, 10672], [8, 10727, 776, 11737]];
    for (var i = 0; i < frames.length; i++) {
        var path = workbenchModelPaths[i];
        if (path.length > 1) checkTemplateLayers(findLayer(model, path.slice(0, -1)), [path[path.length - 1]]);
        var mask = findLayer(model, path);
        if (mask.typename !== "ArtLayer") throw new Error("模特图框需要是可剪贴图层");
        checkTemplateAnchor(mask, frames[i]);
    }
    var footer = findLayer(doc, ["19.门店"]);
    var footerBounds = box(footer);
    if (!footer.visible || footerBounds[1] < 11750 || footerBounds[2] - footerBounds[0] < 600 ||
        footerBounds[3] - footerBounds[1] < 200 || footerBounds[3] > doc.height.as("px") + 8) {
        throw new Error("工作台门店页尾的位置或可见范围不兼容");
    }
}

function writeTemplatePreview(doc, path, from, to) {
    var preview = doc.duplicate("母版预览", true);
    try {
        preview.flatten();
        preview.crop([UnitValue(0, "px"), UnitValue(from, "px"), UnitValue(790, "px"), UnitValue(to, "px")]);
        preview.resizeImage(UnitValue(395, "px"), null, null, ResampleMethod.BICUBICSHARPER);
        var options = new JPEGSaveOptions();
        options.quality = 8;
        preview.saveAs(new File(path), options, true, Extension.LOWERCASE);
    } finally {
        preview.close(SaveOptions.DONOTSAVECHANGES);
    }
}

function reviewUploadedTemplate(spec) {
    var units = app.preferences.rulerUnits;
    var dialogs = app.displayDialogs;
    var prior = app.documents.length ? app.activeDocument : null;
    var doc;
    try {
        app.preferences.rulerUnits = Units.PIXELS;
        app.displayDialogs = DialogModes.NO;
        templateImportStage(spec, "打开母版工作副本");
        doc = app.open(new File(spec.source));
        doc.activeChannels = doc.componentChannels;
        doc.selection.deselect();
        templateImportStage(spec, "识别母版结构");
        var classified = classifyTemplateDocument(doc, spec);
        var normalized = false;
        if (classified.family === "raw_workbench") {
            if (!spec.normalizedOutput) throw new Error("此长版原稿需要先整理，请从上传母版入口导入。");
            prepareLegacyWorkbenchDocument(doc, spec);
            classified = classifyTemplateDocument(doc, spec);
            normalized = true;
        }
        var classic = classified.family === "classic" ? classified.bindings : null;
        var sections = classified.family === "section" ? classified.bindings : null;
        if (sections && spec.normalizedOutput) {
            sections = prepareSectionTemplateDocument(doc, sections, spec);
            classified.bindings = sections;
            normalized = true;
        }
        if (normalized) {
            templateImportStage(spec, "保存整理后的工作母版");
            saveDetailPsb(new File(spec.normalizedOutput));
        }
        if (spec.output && !normalized) {
            templateImportStage(spec, "保存工作母版");
            saveDetailPsb(new File(spec.output));
        }
        var profile = spec.profileOutput ? extractManifestAssets(doc, spec, classic, sections, classified) : null;
        templateImportStage(spec, "导出页头和页尾预览");
        var footerModule = profile ? manifestFindModule(profile, "footer") : null;
        var headerModule = profile ? manifestFindModule(profile, "header") : null;
        var footer = footerModule ? footerModule.rect : manifestRect(findLayer(doc, [classic ? "门店" : "19.门店"]));
        var headerBottom = headerModule ? headerModule.rect[1] + headerModule.rect[3] : 550;
        writeTemplatePreview(doc, spec.headerPreview, 0, headerBottom);
        writeTemplatePreview(doc, spec.footerPreview, Math.max(0, footer[1]),
            Math.min(doc.height.as("px"), footer[1] + footer[3]));
        if (spec.layoutReport) {
            var report = new File(spec.layoutReport);
            if (!report.open("w")) throw new Error("无法记录母版版式");
            report.write(classic ? "classic" : "workbench");
            report.close();
        }
        templateImportStage(spec, "关闭母版工作副本");
    } finally {
        if (doc) {
            try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (closeError) {}
        }
        app.preferences.rulerUnits = units;
        app.displayDialogs = dialogs;
        if (prior) {
            try { app.activeDocument = prior; } catch (priorError) {}
        }
    }
}

function workbenchText(group, label, value, x, y, width, px, fonts, color, align) {
    return tableText(group, label, value, x, y, width, px, color || workbenchInk,
                     fonts.cn.postScriptName, align || Justification.LEFT, fonts);
}

function workbenchCropPlacement(frame, crop, smartBounds, currentBounds) {
    var cropWidth = crop[2] - crop[0];
    var cropHeight = crop[3] - crop[1];
    var smartWidth = smartBounds[2] - smartBounds[0];
    var currentWidth = currentBounds[2] - currentBounds[0];
    var pixelScale = frame[2] / cropWidth;
    var nativeRatio = currentWidth / smartWidth;
    var percent = 100 * pixelScale / nativeRatio;
    if (!isFinite(percent) || percent <= 0 || cropHeight <= 0 || smartWidth <= 0 || currentWidth <= 0 ||
        Math.abs(pixelScale - frame[3] / cropHeight) > Math.max(0.00001, pixelScale * 0.00001)) {
        throw new Error("照片取景或可见范围无效");
    }
    // smartBounds is measured in the EXIF-oriented source document before
    // duplication. It can be a transparent image's visible box, not its canvas.
    return {percent: percent, pixel_scale: pixelScale,
            left: frame[0] + (smartBounds[0] - crop[0]) * pixelScale,
            top: frame[1] + (smartBounds[1] - crop[1]) * pixelScale};
}

function workbenchPicture(doc, group, item, label, frame, clip, slotKey, commonProductScale) {
    var source = app.open(new File(item.staged));
    var rasterBounds;
    var smartBounds;
    try {
        rasterBounds = box(source.activeLayer);
        executeAction(stringIDToTypeID("newPlacedLayer"), new ActionDescriptor(), DialogModes.NO);
        smartBounds = box(source.activeLayer);
        var layer = source.activeLayer.duplicate(doc, ElementPlacement.PLACEATBEGINNING);
    } finally {
        source.close(SaveOptions.DONOTSAVECHANGES);
    }
    app.activeDocument = doc;
    if (layer.kind !== LayerKind.SMARTOBJECT) throw new Error("无法嵌入图片：" + label);
    if (layer.parent.id !== group.id) layer.move(group, ElementPlacement.INSIDE);
    layer.name = label;
    if (layer.grouped) layer.grouped = false;
    if (clip) {
        var b = box(clip);
        frame = [b[0], b[1], b[2] - b[0], b[3] - b[1]];
    }
    var view = slotKey && workbenchActiveJob && workbenchActiveJob.views ? workbenchActiveJob.views[slotKey] : null;
    if (slotKey === "measurement") {
        // Match the preview's contain fit to the complete source canvas,
        // even when Photoshop's layer bounds exclude transparent margins.
        var containScale = Math.min(frame[2] / item.width, frame[3] / item.height);
        var fitWidth = item.width * containScale, fitHeight = item.height * containScale;
        view = {frame: [frame[0] + (frame[2] - fitWidth) / 2, frame[1] + (frame[3] - fitHeight) / 2,
                        fitWidth, fitHeight], source_box: [0, 0, item.width, item.height]};
    }
    if (view && view.frame) frame = view.frame;
    var bounds = box(layer);
    if (commonProductScale && item.is_product) {
        var nativeRatio = (bounds[2] - bounds[0]) / (smartBounds[2] - smartBounds[0]);
        layer.resize(100 * commonProductScale / nativeRatio, 100 * commonProductScale / nativeRatio, AnchorPosition.MIDDLECENTER);
        bounds = box(layer);
        var visibleLeft = bounds[0] + (rasterBounds[0] - smartBounds[0]) * commonProductScale;
        var visibleTop = bounds[1] + (rasterBounds[1] - smartBounds[1]) * commonProductScale;
        var visibleWidth = (rasterBounds[2] - rasterBounds[0]) * commonProductScale;
        var visibleHeight = (rasterBounds[3] - rasterBounds[1]) * commonProductScale;
        layer.translate(UnitValue(frame[0] + frame[2] / 2 - visibleLeft - visibleWidth / 2, "px"),
                        UnitValue(frame[1] + frame[3] - visibleTop - visibleHeight, "px"));
    } else if (view && (view.source_box || view.crop_box) && !item.is_product) {
        var crop = view.source_box || view.crop_box;
        var placement = workbenchCropPlacement(frame, crop, smartBounds, bounds);
        layer.resize(placement.percent, placement.percent, AnchorPosition.MIDDLECENTER);
        bounds = box(layer);
        layer.translate(UnitValue(placement.left - bounds[0], "px"), UnitValue(placement.top - bounds[1], "px"));
    } else {
    var scale = clip && !item.is_product ? Math.max(frame[2] / (bounds[2] - bounds[0]), frame[3] / (bounds[3] - bounds[1])) :
                       Math.min(frame[2] / (bounds[2] - bounds[0]), frame[3] / (bounds[3] - bounds[1]));
    if (!isFinite(scale) || scale <= 0) throw new Error("图片没有可见内容：" + label);
    layer.resize(100 * scale, 100 * scale, AnchorPosition.MIDDLECENTER);
    bounds = box(layer);
    layer.translate(UnitValue(frame[0] + frame[2] / 2 - (bounds[0] + bounds[2]) / 2, "px"),
                    UnitValue(frame[1] + frame[3] / 2 - (bounds[1] + bounds[3]) / 2, "px"));
    }
    if (clip) {
        layer.move(clip, ElementPlacement.PLACEBEFORE);
        layer.grouped = true;
    }
    return layer;
}

function workbenchInformation(doc, job, fonts) {
    var panel = findLayer(doc, ["产品信息"]);
    var info = findLayer(panel, ["产品信息"]);
    var fields = ["名称", "货号", "尺码", "材质"];
    for (var i = 0; i < fields.length; i++) {
        var field = fields[i];
        var y = 3905 + i * 59;
        workbenchText(info, field + "标签", field, 61, y, 116, 28, fonts);
        if (field !== "材质") {
            workbenchText(info, field + "值", job.info[field], 190, y, 550, 27, fonts);
            continue;
        }
        var material = info.artLayers.add();
        material.kind = LayerKind.TEXT;
        material.name = "材质值";
        var item = material.textItem;
        item.kind = TextType.PARAGRAPHTEXT;
        item.position = [UnitValue(190, "px"), UnitValue(y - 28, "px")];
        item.width = UnitValue(549, "px");
        item.height = UnitValue(129, "px");
        item.contents = job.info[field];
        var materialPx = job.info[field].length > 85 ? 18 : 24;
        item.size = UnitValue(materialPx * 72 / doc.resolution, "pt");
        item.font = fonts.cn.postScriptName;
        item.color = rgb(workbenchInk);
        applyDetailMixedFonts(material, fonts);
    }
    var colors = findLayer(panel, ["颜色"]);
    var step = 720 / job.products.length;
    for (i = 0; i < job.products.length; i++) {
        var product = job.products[i];
        var center = 35 + (i + 0.5) * step;
        var span = Math.min(210, step - 25);
        workbenchPicture(doc, colors, product, "商品图 · " + product.label, [center - span / 2, 4708, span, 263]);
        workbenchText(colors, "色名 · " + product.label, product.label, center, 5048, step - 12, 27,
                      fonts, workbenchInk, Justification.CENTER);
    }
}

function workbenchModels(doc, scenes) {
    var model = findLayer(doc, ["17.模特展示"]);
    if (!scenes.length) {
        model.remove();
        return null;
    }
    var paths = workbenchModelPaths;
    for (var i = 0; i < paths.length; i++) {
        var frame = findLayer(model, paths[i]);
        if (i < scenes.length) {
            workbenchPicture(doc, frame.parent, scenes[i], "模特图 " + (i + 1), null, frame);
        } else {
            frame.visible = false;
        }
    }
    var shape = findLayer(model, ["形状 1241"]);
    if (scenes.length >= 2) shape.move(findLayer(model, paths[1]), ElementPlacement.PLACEAFTER);
    else shape.visible = false;
    return box(findLayer(model, paths[scenes.length - 1]))[3];
}

function verifyWorkbench(doc, job) {
    var info = findLayer(doc, ["产品信息", "产品信息"]);
    for (var field in job.info) {
        var layer = findLayer(info, [field + "值"]);
        if (layer.kind !== LayerKind.TEXT || layer.textItem.contents !== job.info[field]) throw new Error("重开后字段校验失败：" + field);
    }
    var sections = {"03选尺码": "3", "05尺码快选": "4", "试穿报告": "5"};
    for (var key in sections) {
        var matrix = job.tables[key];
        if (!matrix) continue;
        var section = findLayer(doc, ["尺码", sections[key]]);
        var table = findLayer(section, [key + "（可编辑）"]);
        for (var r = 0; r < matrix.length; r++) {
            var row = findLayer(table, [r === 0 ? "表头" : "第 " + r + " 行"]);
            for (var c = 0; c < matrix[r].length; c++) {
                var cell = findLayer(row, ["第 " + (c + 1) + " 列"]);
                if (cell.kind !== LayerKind.TEXT || cell.textItem.contents !== (matrix[r][c] || " ")) {
                    throw new Error("重开后表格校验失败：" + key + " 第 " + (r + 1) + " 行");
                }
            }
        }
    }
    var count = verifyEmbedded(findLayer(doc, ["主视觉"]), /^主视觉图$/);
    count += verifyEmbedded(findLayer(doc, ["产品信息", "颜色"]), /^商品图 · /);
    if (job.scenes.length) count += verifyEmbedded(findLayer(doc, ["17.模特展示"]), /^模特图 [1-4]$/);
    if (count !== 1 + job.products.length + job.scenes.length) throw new Error("嵌入式智能对象数量异常");
}

function verifyEmbedded(parent, pattern) {
    var count = 0;
    var key = stringIDToTypeID;
    for (var i = 0; i < parent.layers.length; i++) {
        var layer = parent.layers[i];
        if (layer.typename === "LayerSet") count += verifyEmbedded(layer, pattern);
        else if (pattern.test(layer.name)) {
            var ref = new ActionReference();
            ref.putProperty(key("property"), key("smartObject"));
            ref.putIdentifier(key("layer"), layer.id);
            var smart = executeActionGet(ref).getObjectValue(key("smartObject"));
            if (layer.kind !== LayerKind.SMARTOBJECT || (smart.hasKey(key("linked")) && smart.getBoolean(key("linked")))) {
                throw new Error("图片未嵌入：" + layer.name);
            }
            count++;
        }
    }
    return count;
}

function runDetailWorkbench(job) {
    if (job.profile && job.geometry) return runManifestWorkbench(job);
    var units = app.preferences.rulerUnits;
    var dialogs = app.displayDialogs;
    var prior = app.documents.length ? app.activeDocument : null;
    var doc, preview;
    try {
        app.preferences.rulerUnits = Units.PIXELS;
        app.displayDialogs = DialogModes.NO;
        var fonts = loadDetailMixedFonts();
        doc = app.open(new File(job.template));
        var classic = classicTemplateProfile(doc);
        var contentHeight;
        if (classic) {
            contentHeight = buildClassicWorkbench(doc, job, fonts, classic);
        } else {
            checkWorkbenchTemplate(doc);
            var hero = doc.layerSets.add();
            hero.name = "主视觉";
            rectangle(doc, hero, "主视觉底色", 10, 550, 770, 2780, [235, 245, 242], 24);
            workbenchText(hero, "主标题", job.info["名称"], 51, 756, 690,
                          Math.min(62, Math.floor(680 / job.info["名称"].length)), fonts);
            workbenchText(hero, "货号", job.info["货号"], 54, 830, 680, 34, fonts, workbenchGreen);
            var frame = rectangle(doc, hero, "主视觉照片框", 28, 930, 734, 1850, [225, 240, 235], 20);
            var mainPicture = job.hero || job.products[0];
            if (mainPicture.is_product) workbenchPicture(doc, hero, mainPicture, "主视觉图", [65, 980, 660, 1740]);
            else workbenchPicture(doc, hero, mainPicture, "主视觉图", null, frame);
            var colorNames = [];
            for (var i = 0; i < job.products.length; i++) colorNames.push(job.products[i].label);
            workbenchText(hero, "配色提示", "配色  /  " + colorNames.join(" · "), 52, 2985, 690, 33, fonts, workbenchGreen);
            workbenchText(hero, "尺码提示", "尺码  /  " + job.info["尺码"], 52, 3090, 690, 33, fonts);
            workbenchInformation(doc, job, fonts);
            var lastSceneBottom = workbenchModels(doc, job.scenes);
            var unit = findLayer(doc, ["尺码", "5", "/cm"]);
            unit.textItem.contents = "cm / kg";
            unit.translate(UnitValue(739 - box(unit)[2], "px"), UnitValue(0, "px"));
            applyDetailMixedFonts(unit, fonts);
            rebuildPantsDetailTables(doc, job.tables, fonts);
            if (!job.tables["试穿报告"]) findLayer(doc, ["尺码", "5"]).remove();
            var footer = findLayer(doc, ["19.门店"]);
            var sizesBottom = box(findLayer(doc, ["尺码"]))[3];
            var footerTop = Math.ceil((lastSceneBottom || sizesBottom) + 125);
            footer.translate(UnitValue(0, "px"), UnitValue(footerTop - box(footer)[1], "px"));
            contentHeight = Math.ceil(box(footer)[3] + 10);
            doc.resizeCanvas(UnitValue(790, "px"), UnitValue(contentHeight, "px"), AnchorPosition.TOPCENTER);
        }
        app.activeDocument = doc;
        var output = new File(job.output);
        if (output.exists) throw new Error("暂存成品已存在");
        saveDetailPsb(output);
        if (!output.exists || output.length < 26) throw new Error("没有生成可重开的 PSB");
        doc.close(SaveOptions.DONOTSAVECHANGES);
        doc = app.open(output);
        if (classic) verifyClassicWorkbench(doc, job);
        else verifyWorkbench(doc, job);
        preview = doc.duplicate("workbench-preview", true);
        preview.flatten();
        preview.resizeImage(UnitValue(500, "px"), null, null, ResampleMethod.BICUBICSHARPER);
        var options = new JPEGSaveOptions();
        options.quality = 9;
        preview.saveAs(new File(job.preview), options, true, Extension.LOWERCASE);
    } finally {
        if (preview) preview.close(SaveOptions.DONOTSAVECHANGES);
        if (doc) doc.close(SaveOptions.DONOTSAVECHANGES);
        app.preferences.rulerUnits = units;
        app.displayDialogs = dialogs;
        if (prior) app.activeDocument = prior;
    }
    var marker = new File(job.completed);
    if (!marker.open("w")) throw new Error("无法写入核验记录");
    marker.write(String(contentHeight));
    marker.close();
}
