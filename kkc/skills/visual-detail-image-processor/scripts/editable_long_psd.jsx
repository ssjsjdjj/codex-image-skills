/* Photoshop ExtendScript. The input template is opened from a private disk copy. */
function buildEditableLongPsd(job) {
    var original = new File(job.template);
    var output = new File(job.output);
    if (!original.exists || !output.parent.exists || !/\.ps[db]$/i.test(output.name)) {
        throw new Error("需要可读母版及已存在的 PSD/PSB 输出目录。");
    }
    if (output.exists) throw new Error("输出文件已存在：" + output.fsName);
    var token = String(new Date().getTime()) + "-" + Math.floor(Math.random() * 1000000);
    var suffix = /\.psb$/i.test(original.name) ? ".psb" : ".psd";
    var work = new File(output.parent.fsName + "/.template-" + token + suffix);
    var outputExtension = /\.psb$/i.test(output.name) ? ".psb" : ".psd";
    var staged = new File(output.parent.fsName + "/.output-" + token + outputExtension);
    var prior = app.documents.length ? app.activeDocument : null;
    var dialogs = app.displayDialogs;
    var units = app.preferences.rulerUnits;
    var doc;
    var tablesBuilt = 0;
    var product = "产品信息 拷贝 2";
    var sizePath = [product, "尺码", "组 830", "03选尺码"];
    var quickPath = [product, "尺码", "05尺码快选"];
    try {
        app.displayDialogs = DialogModes.NO;
        app.preferences.rulerUnits = Units.PIXELS;
        var detailFonts = loadDetailMixedFonts();
        if (!original.copy(work.fsName)) throw new Error("无法复制母版。");
        doc = app.open(work);
        var height = doc.height.as("px");
        if (doc.width.as("px") !== 790 || (height !== 40000 && height !== 11657 && height !== 11706)) {
            throw new Error("当前绑定支持 790 px 宽的新裤子母版、产品信息T和原产品信息母版。");
        }
        var pantsTemplate = height === 40000;
        if (pantsTemplate && outputExtension !== ".psb") throw new Error("新裤子母版为 40000 px 高，整页请存为 PSB。");
        var nativeTemplate = height === 11657 ? getNativeDetailTemplate(doc) : null;
        if (height === 11657 && !nativeTemplate) throw new Error("产品信息T母版的原生表格结构不匹配。");
        var fontTargets = pantsTemplate ? [] : nativeTemplate ? null : legacyDetailFontTargets(doc, product);
        var textJobs = job.text || [];
        var imageJobs = job.images || [];
        var i;
        for (i = 0; i < textJobs.length; i++) {
            var textLayer = findLayer(doc, textJobs[i].path);
            if (textLayer.kind !== LayerKind.TEXT) throw new Error("目标不是文字层：" + textJobs[i].path.join(" / "));
            if (pantsTemplate && pantsDetailMixedProductPath(textJobs[i].path)) fontTargets.push(textLayer);
            var before = box(textLayer);
            var value = textJobs[i].value.replace(/\r\n|\n/g, "\r");
            textLayer.textItem.contents = value || " ";
            var after = box(textLayer);
            if (value && (after[0] < 0 || after[2] > 790 ||
                after[3] > before[3] + 5 || after[1] < before[1] - 5)) {
                throw new Error("文字超出母版空间：" + textJobs[i].path.join(" / "));
            }
        }
        for (i = 0; i < imageJobs.length; i++) replaceImage(doc, imageJobs[i]);
        var tables = job.tables || {};
        if (pantsTemplate) {
            tablesBuilt = rebuildPantsDetailTables(doc, tables, detailFonts);
        } else if (nativeTemplate) {
            updateNativeDetailTables(nativeTemplate, tables);
            fontTargets = nativeDetailFontTargets(nativeTemplate);
            tablesBuilt = 2;
        } else {
            if (tables["03选尺码"]) {
                buildTable(doc, findLayer(doc, sizePath), tables["03选尺码"], false, detailFonts);
                tablesBuilt++;
            }
            if (tables["05尺码快选"]) {
                buildTable(doc, findLayer(doc, quickPath), tables["05尺码快选"], true, detailFonts);
                tablesBuilt++;
            }
        }
        for (i = 0; i < fontTargets.length; i++) applyDetailMixedFonts(fontTargets[i], detailFonts);
        var options = new PhotoshopSaveOptions();
        options.layers = true;
        options.embedColorProfile = true;
        options.maximizeCompatibility = true;
        if (outputExtension === ".psb") {
            saveDetailPsb(staged);
        } else {
            doc.saveAs(staged, options, true, Extension.LOWERCASE);
        }
        doc.close(SaveOptions.DONOTSAVECHANGES);
        doc = null;
        if (!staged.exists || output.exists || !staged.rename(output.name)) {
            throw new Error("无法写入最终 PSD：" + output.fsName);
        }
        return "已生成 " + output.fsName + "，可编辑表格 " + tablesBuilt + " 张";
    } finally {
        if (doc) doc.close(SaveOptions.DONOTSAVECHANGES);
        if (work.exists) work.remove();
        var pending = new File(output.parent.fsName + "/.output-" + token + outputExtension);
        if (pending.exists) pending.remove();
        app.preferences.rulerUnits = units;
        app.displayDialogs = dialogs;
        if (prior) app.activeDocument = prior;
    }
}

function saveDetailPsb(file) {
    var key = stringIDToTypeID;
    var format = new ActionDescriptor();
    format.putBoolean(key("maximizeCompatibility"), true);
    var save = new ActionDescriptor();
    save.putObject(key("as"), key("largeDocumentFormat"), format);
    save.putPath(key("in"), file);
    save.putBoolean(key("copy"), true);
    executeAction(key("save"), save, DialogModes.NO);
}

function legacyDetailFontTargets(doc, product) {
    var info = findLayer(doc, [product, "组 844"]);
    var targets = [];
    for (var i = 0; i < info.artLayers.length; i++) {
        var layer = info.artLayers[i];
        if (layer.kind === LayerKind.TEXT && /^(KQ[0-9]|[0-9]+-[0-9]+$|面层\/底层)/.test(layer.name)) {
            targets.push(layer);
        }
    }
    var sizes = findLayer(doc, [product, "尺码"]);
    collectLegacyTableFonts(sizes, targets, false);
    return targets;
}

function collectLegacyTableFonts(parent, targets, insideTable) {
    for (var i = 0; i < parent.layers.length; i++) {
        var layer = parent.layers[i];
        if (layer.typename === "LayerSet") {
            collectLegacyTableFonts(layer, targets, insideTable || /^(03选尺码|05尺码快选)（可编辑）$/.test(layer.name));
        } else if (insideTable && layer.kind === LayerKind.TEXT && /^第 [0-9]+ 列$/.test(layer.name)) {
            targets.push(layer);
        }
    }
}

function findLayer(doc, path) {
    var parent = doc;
    for (var i = 0; i < path.length; i++) {
        var found = null;
        for (var j = 0; j < parent.layers.length; j++) {
            if (parent.layers[j].name === path[i]) {
                if (found) throw new Error("图层路径有重名：" + path.join(" / "));
                found = parent.layers[j];
            }
        }
        if (!found) throw new Error("找不到图层：" + path.join(" / "));
        parent = found;
    }
    return parent;
}

function box(layer) {
    var b = layer.bounds;
    return [b[0].as("px"), b[1].as("px"), b[2].as("px"), b[3].as("px")];
}

function replaceImage(doc, item) {
    var layer = findLayer(doc, item.path);
    var file = new File(item.source);
    if (layer.kind !== LayerKind.SMARTOBJECT || !file.exists) {
        throw new Error("图片槽位或素材无效：" + item.path.join(" / "));
    }
    var oldBounds = box(layer);
    doc.activeLayer = layer;
    // A duplicated instance can share its embedded content with another slot.
    // Create a new instance before replacing contents.
    executeAction(stringIDToTypeID("placedLayerMakeCopy"), new ActionDescriptor(), DialogModes.NO);
    var replacement = doc.activeLayer;
    replacement.move(layer, ElementPlacement.PLACEBEFORE);
    var slotName = layer.name;
    if (replacement.grouped !== layer.grouped) replacement.grouped = layer.grouped;
    var args = new ActionDescriptor();
    args.putPath(charIDToTypeID("null"), file);
    executeAction(stringIDToTypeID("placedLayerReplaceContents"), args, DialogModes.NO);
    replacement.name = slotName;
    var current = box(replacement);
    for (var i = 0; i < 4; i++) {
        if (Math.abs(oldBounds[i] - current[i]) > 2) {
            throw new Error("替换图片改变了母版构图，请先将素材适配原智能对象画布：" + item.path.join(" / "));
        }
    }
    layer.remove();
}

function rgb(values) {
    var color = new SolidColor();
    color.rgb.red = values[0];
    color.rgb.green = values[1];
    color.rgb.blue = values[2];
    return color;
}

function rectangle(doc, group, name, x, y, w, h, color, radius) {
    var key = stringIDToTypeID;
    var make = new ActionDescriptor();
    var ref = new ActionReference();
    ref.putClass(key("contentLayer"));
    make.putReference(key("null"), ref);
    var content = new ActionDescriptor();
    var fill = new ActionDescriptor();
    var channels = new ActionDescriptor();
    channels.putDouble(key("red"), color[0]);
    channels.putDouble(key("green"), color[1]);
    channels.putDouble(key("blue"), color[2]);
    fill.putObject(key("color"), key("RGBColor"), channels);
    content.putObject(key("type"), key("solidColorLayer"), fill);
    var shape = new ActionDescriptor();
    shape.putUnitDouble(key("top"), key("pixelsUnit"), y);
    shape.putUnitDouble(key("left"), key("pixelsUnit"), x);
    shape.putUnitDouble(key("bottom"), key("pixelsUnit"), y + h);
    shape.putUnitDouble(key("right"), key("pixelsUnit"), x + w);
    if (radius) {
        shape.putUnitDouble(key("topLeft"), key("pixelsUnit"), radius);
        shape.putUnitDouble(key("topRight"), key("pixelsUnit"), radius);
        shape.putUnitDouble(key("bottomLeft"), key("pixelsUnit"), radius);
        shape.putUnitDouble(key("bottomRight"), key("pixelsUnit"), radius);
    }
    content.putObject(key("shape"), key("rectangle"), shape);
    make.putObject(key("using"), key("contentLayer"), content);
    doc.activeLayer = group;
    executeAction(key("make"), make, DialogModes.NO);
    var result = doc.activeLayer;
    result.name = name;
    if (result.parent.id !== group.id) result.move(group, ElementPlacement.INSIDE);
    return result;
}

function installedFont(candidates) {
    for (var i = 0; i < candidates.length; i++) {
        for (var j = 0; j < app.fonts.length; j++) {
            if (app.fonts[j].postScriptName === candidates[i]) return candidates[i];
        }
    }
    throw new Error("未找到表格所需的 Photoshop 字体：" + candidates.join(", "));
}

function tableText(group, name, value, x, y, width, px, color, font, align, detailFonts) {
    var layer = group.artLayers.add();
    layer.kind = LayerKind.TEXT;
    layer.name = name;
    var item = layer.textItem;
    item.contents = String(value === null ? "" : value) || " ";
    item.position = [UnitValue(x, "px"), UnitValue(y, "px")];
    item.justification = align || Justification.CENTER;
    item.font = font;
    var pointsPerPixel = 72 / app.activeDocument.resolution;
    item.size = UnitValue(px * pointsPerPixel, "pt");
    item.color = rgb(color);
    if (detailFonts) applyDetailMixedFonts(layer, detailFonts);
    if (value !== "" && value !== null) {
        var b = box(layer);
        if (b[2] - b[0] > width) {
            var reduced = Math.floor(px * width / (b[2] - b[0])) - 1;
            if (reduced < px * 0.75) throw new Error("表格文字过宽：" + name + " " + value);
            item.size = UnitValue(reduced * pointsPerPixel, "pt");
            if (detailFonts) applyDetailMixedFonts(layer, detailFonts);
            b = box(layer);
            if (b[2] - b[0] > width) throw new Error("表格文字过宽：" + name + " " + value);
        }
    }
    return layer;
}

function buildTable(doc, legacy, matrix, quick, detailFonts) {
    var capacity = quick ? 8 : 7;
    if (matrix.length < 2 || matrix.length > 8 || !matrix[0] ||
        matrix[0].length < 2 || matrix[0].length > capacity) {
        throw new Error(legacy.name + " 超出母版容量或缺少表头/数据。");
    }
    var rows = matrix.length;
    var cols = matrix[0].length;
    for (var r = 0; r < rows; r++) {
        if (matrix[r].length !== cols) throw new Error(legacy.name + " 第 " + (r + 1) + " 行列数不一致。");
    }
    if (legacy.kind !== LayerKind.SMARTOBJECT) throw new Error("原始表格槽位类型不匹配：" + legacy.name);
    var group = legacy.parent.layerSets.add();
    group.name = legacy.name + "（可编辑）";
    group.move(legacy, ElementPlacement.PLACEBEFORE);
    var chinese = installedFont(["FZLTZHJW--GB1-0", "AdobeHeitiStd-Regular", "MicrosoftYaHei"]);
    var numeric = installedFont(["G8321-Medium", "AlimamaFangYuanTiVF-MediumRound", "MicrosoftYaHei"]);
    var dark = [21, 21, 21];
    var base = quick ? 3368 : 1745;
    var x = quick ? 22 : 30;
    var w = quick ? 746 : 730;
    var y = base + (quick ? 99 : 239);
    var header = quick ? 54 : 77;
    var rowHeight = (quick ? 290 : 365) / (rows - 1);
    var height = header + rowHeight * (rows - 1);
    var lead = quick ? 113 : w / cols;
    var column = (w - lead) / (cols - 1);
    if (quick) {
        rectangle(doc, group, "面板底色", 0, base, 790, 511, [240, 240, 240]);
        rectangle(doc, group, "表格衬底", 18, base + 95, 754, 376, [247, 247, 247]);
        tableText(group, "标题", "尺码快选", 37, base + 65, 340, 38, dark, chinese, Justification.LEFT);
        tableText(group, "单位", "身高cm/体重kg", 745, base + 65, 250, 26, dark, chinese, Justification.RIGHT);
    } else {
        rectangle(doc, group, "面板底色", 0, base + 151, 790, 571, [240, 240, 240]);
        rectangle(doc, group, "内容底色", 10, base + 151, 770, 571, [247, 247, 247]);
        // Bring the existing native title and unit above the replacement panel.
        legacy.parent.artLayers.getByName("Size").move(group, ElementPlacement.PLACEBEFORE);
        legacy.parent.artLayers.getByName("/cm").move(group, ElementPlacement.PLACEBEFORE);
    }
    rectangle(doc, group, "表格底", x, y, w, height, [255, 255, 255], 12);
    for (r = 0; r < rows; r++) {
        var rowY = r === 0 ? y : y + header + (r - 1) * rowHeight;
        var band = r === 0 ? header : rowHeight;
        if (r === 0) {
            var headerColor = quick ? [40, 153, 66] : [231, 231, 231];
            rectangle(doc, group, "表头底色", x, rowY, w, band, headerColor, 12);
            rectangle(doc, group, "表头下沿", x, rowY + band / 2, w, band / 2, headerColor);
        } else if (quick) {
            rectangle(doc, group, "行标底色 " + r, x, rowY, lead, band, [237, 241, 243]);
            if (r > 1) rectangle(doc, group, "横线 " + r, x, rowY, w, 1, [225, 225, 225]);
        } else if (r % 2 === 0 && r < rows - 1) {
            rectangle(doc, group, "交替行底色 " + r, x, rowY, w, band, [249, 249, 249]);
        }
    }
    if (quick) {
        for (var c = 1; c < cols; c++) {
            rectangle(doc, group, "竖线 " + c, x + lead + (c - 1) * column, y + header, 1, height - header, [225, 225, 225]);
        }
    }
    for (r = 0; r < rows; r++) {
        var row = group.layerSets.add();
        row.name = r === 0 ? "表头" : "第 " + r + " 行";
        var baseline = r === 0 ? y + (quick ? 36 : 51) : y + header + (r - 0.5) * rowHeight + (quick ? 7 : 12);
        for (c = 0; c < cols; c++) {
            var center = c === 0 ? x + lead / 2 : x + lead + (c - 0.5) * column;
            var value = matrix[r][c];
            var font = /[\u2e80-\uffff]/.test(String(value)) ? chinese : numeric;
            tableText(row, "第 " + (c + 1) + " 列", value, center, baseline,
                (c === 0 ? lead : column) - 6, quick ? 20 : 27,
                quick && r === 0 ? [255, 255, 255] : dark, font, null, detailFonts);
        }
    }
    legacy.remove();
}


