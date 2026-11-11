/* Flat, separately grouped information / sizing / photography masters. */
function sectionRoots(doc) {
    var roots = [];
    var layers = doc.layers;
    for (var i = 0, count = layers.length; i < count; i++) {
        var layer = layers[i];
        if (!layer.visible || layer.typename !== "LayerSet") continue;
        var name = layer.name.replace(/^\s*\d+\s*[.、．]\s*/, "").replace(/^\s+|\s+$/g, "");
        roots.push({name: name, layer: layer});
    }
    return roots;
}

function sectionRoot(roots, expression) {
    var found = null;
    for (var i = 0; i < roots.length; i++) {
        if (!expression.test(roots[i].name)) continue;
        if (found) throw new Error("母版模块存在多个可见候选：" + roots[i].name);
        found = roots[i].layer;
    }
    return found;
}

function sectionText(parent, expression) {
    var found = null;
    for (var i = 0; i < parent.artLayers.length; i++) {
        var layer = parent.artLayers[i];
        if (!layer.visible || layer.kind !== LayerKind.TEXT || !expression.test(layer.textItem.contents)) continue;
        if (found) throw new Error("母版文字存在多个可见候选：" + layer.name);
        found = layer;
    }
    return found;
}

function sectionRequired(layer, name) {
    if (!layer) throw new Error("独立分组母版尚未定位模块：" + name);
    return layer;
}

function sectionVisibleRect(layer) {
    if (layer.typename !== "LayerSet") return manifestPageRect(manifestRect(layer));
    var rectangles = manifestStaticRects(layer, []);
    if (!rectangles.length) throw new Error("母版模块没有可见内容：" + layer.name);
    return manifestPageRect(manifestUnion(rectangles));
}

function sectionInfoContainers(parent, depth) {
    var found = [];
    if (optionalClassicLayer(parent, "名称") && optionalClassicLayer(parent, "货号")) found.push(parent);
    if (!depth) return found;
    for (var i = 0; i < parent.layers.length; i++) {
        var child = parent.layers[i];
        if (child.visible && child.typename === "LayerSet") found = found.concat(sectionInfoContainers(child, depth - 1));
    }
    return found;
}

function sectionPhotoFrames(parent) {
    var frames = [];
    for (var i = 0; i < parent.layers.length; i++) {
        var layer = parent.layers[i];
        if (!layer.visible) continue;
        if (layer.typename === "LayerSet") {
            frames = frames.concat(sectionPhotoFrames(layer));
            continue;
        }
        if (!layer.visible || !/^矩形 991(?: 拷贝(?: \d+)?)?$/.test(layer.name)) continue;
        var rect = manifestRect(layer);
        if (rect[2] >= 200 && rect[3] >= 300) frames.push(layer);
    }
    frames.sort(function (a, b) { return box(a)[1] - box(b)[1]; });
    for (i = 0; i < frames.length; i++) {
        if (manifestResolvePaths(app.activeDocument, manifestPath(frames[i])).length !== 1) {
            throw new Error("模特图框路径存在重名：" + frames[i].name);
        }
    }
    return frames;
}

function sectionTemplateProfile(doc) {
    var roots = sectionRoots(doc);
    var product = sectionRoot(roots, /^产品信息$/);
    if (!product) return null;
    var candidates = sectionInfoContainers(product, 2);
    if (!candidates.length) return null;
    if (candidates.length !== 1) throw new Error("商品字段存在多个可见分组，请明确商品信息位置");
    var info = candidates[0];
    var names = ["名称", "货号", "颜色"];
    for (var i = 0; i < names.length; i++) {
        var label = findLayer(info, [names[i]]);
        if (!label.visible || label.kind !== LayerKind.TEXT) {
            throw new Error("商品字段需要原生文字：" + names[i]);
        }
    }
    var material = optionalClassicLayer(info, "材质");
    if (material && !material.visible) material = null;
    if (material && material.kind !== LayerKind.TEXT) throw new Error("材质字段需要原生文字");
    var sizeLabel = optionalClassicLayer(info, "码段");
    if (!sizeLabel || !sizeLabel.visible) sizeLabel = optionalClassicLayer(info, "尺码");
    if (!sizeLabel || !sizeLabel.visible || sizeLabel.kind !== LayerKind.TEXT) throw new Error("未定位商品信息中的尺码／码段文字");
    var header = sectionRequired(sectionRoot(roots, /^T1(?:\s*拷贝(?:\s*\d+)?)?$/), "页头");
    var headerBase = findLayer(header, ["矩形 1325"]);
    var headerRect = manifestRect(headerBase);
    if (headerRect[1] < 0 || headerRect[1] + headerRect[3] > 650) throw new Error("页头定位底层超出顶部范围");
    var size = sectionRequired(sectionRoot(roots, /^尺码$/), "尺码");
    var quick = sectionRoot(roots, /^尺码快选$/);
    var trial = sectionRoot(roots, /^试穿报告$/);
    var model = sectionRequired(sectionRoot(roots, /^模特展示$/), "模特展示");
    var brand = sectionRequired(sectionRoot(roots, /^品牌故事$/), "品牌故事");
    var footer = sectionRequired(sectionRoot(roots, /^门店$/), "门店");
    var frames = sectionPhotoFrames(model);
    if (!frames.length || frames.length > 4) throw new Error("独立模特模块需要 1–4 个已确认的原生图框");
    var brandFrame = findLayer(brand, ["矩形 991 拷贝 3"]);
    var brandRect = manifestRect(brandFrame);
    if (brandRect[2] < 200 || brandRect[3] < 300) throw new Error("品牌场景图框尺寸不足");
    findLayer(product, ["矩形 948 拷贝"]);
    var colors = optionalClassicLayer(product, "颜色");
    if (!colors || colors.typename !== "LayerSet") colors = product;
    var colorDivider = findLayer(colors, ["直线 1512 拷贝"]);
    findLayer(size, ["矩形 959 拷贝 2"]);
    findLayer(size, ["矩形 1602 拷贝 4"]);
    if (quick) findLayer(quick, ["矩形 1147 拷贝"]);
    if (trial) findLayer(trial, ["矩形 959 拷贝 4"]);
    sectionRequired(sectionText(colors, /选个喜欢的颜色|选颜色|挑颜色/), "选颜色标题");
    sectionRequired(sectionText(size, /选择你的尺码|选.*尺码|尺码表/), "尺码表标题");
    if (quick) sectionRequired(sectionText(quick, /^尺码快选$/), "尺码快选标题");
    if (trial) sectionRequired(sectionText(trial, /试穿报告/), "试穿报告标题");
    return {product: product, info: info, colors: colors, colorDivider: colorDivider,
            material: material, sizeLabel: sizeLabel, header: header, headerBase: headerBase,
            size: size, quick: quick, trial: trial, model: model, frames: frames,
            brand: brand, brandFrame: brandFrame, footer: footer};
}

function sectionSceneRect(binding) {
    var rectangles = [];
    var title = sectionRequired(sectionText(binding.model, /模特SHOW|模特展示/), "模特展示标题");
    rectangles.push(manifestRect(title));
    for (var i = 0; i < binding.frames.length; i++) rectangles.push(manifestRect(binding.frames[i]));
    var backing = optionalClassicLayer(binding.model, "矩形 899");
    if (backing) rectangles.push(manifestRect(backing));
    return manifestPageRect(manifestUnion(rectangles));
}

function sectionBrandRect(binding) {
    var rectangles = [manifestRect(binding.brandFrame)];
    var title = sectionRequired(sectionText(binding.brand, /^品牌故事$/), "品牌故事标题");
    rectangles.push(manifestRect(title));
    return manifestPageRect(manifestUnion(rectangles));
}

function sectionDeleteLayer(layer) {
    var name = layer.name;
    var reference = new ActionReference();
    reference.putIdentifier(stringIDToTypeID("layer"), layer.id);
    var deletion = new ActionDescriptor();
    deletion.putReference(stringIDToTypeID("null"), reference);
    try { executeAction(stringIDToTypeID("delete"), deletion, DialogModes.NO); }
    catch (error) { throw new Error("整理原稿分区 " + name + " 失败：" + error.message); }
}

function sectionCompactModelInfo(doc, binding, omitted) {
    var modelInfo = optionalClassicLayer(binding.product, "模特信息");
    if (!modelInfo || modelInfo.typename !== "LayerSet") return binding;
    sectionDeleteLayer(modelInfo);
    omitted.push("产品信息 / 模特信息（原稿示例姓名、身高和体重）");
    binding = sectionTemplateProfile(doc);
    if (binding.colors.id === binding.product.id) return binding;
    var info = sectionVisibleRect(binding.info);
    var divider = box(binding.colorDivider)[1];
    var shift = Math.min(0, info[1] + info[3] + 60 - divider);
    if (shift < 0) {
        binding.colors.translate(UnitValue(0, "px"), UnitValue(shift, "px"));
        var backing = findLayer(binding.product, ["矩形 948 拷贝"]);
        var before = box(backing);
        var height = before[3] - before[1];
        if (height + shift <= 0) throw new Error("移除示例模特信息后商品面板高度无效");
        backing.resize(100, 100 * (height + shift) / height, AnchorPosition.TOPCENTER);
        var after = box(backing);
        backing.translate(UnitValue(before[0] - after[0], "px"), UnitValue(before[1] - after[1], "px"));
    }
    return sectionTemplateProfile(doc);
}

function prepareSectionTemplateDocument(doc, binding, spec) {
    templateImportStage(spec, "保存完整原稿参考");
    if (!spec.originalPreviewReady) snapshotReferenceDocument(doc, spec.originalPreview);
    var kept = [binding.header, binding.product, binding.size, binding.model, binding.brand, binding.footer];
    if (binding.quick) kept.push(binding.quick);
    if (binding.trial) kept.push(binding.trial);
    var keptIds = [];
    for (var k = 0; k < kept.length; k++) keptIds.push(kept[k].id);
    templateImportStage(spec, "整理工作母版 · 激活页头分组");
    var activeReference = new ActionReference();
    activeReference.putIdentifier(stringIDToTypeID("layer"), keptIds[0]);
    var activate = new ActionDescriptor();
    activate.putReference(stringIDToTypeID("null"), activeReference);
    activate.putBoolean(stringIDToTypeID("makeVisible"), false);
    executeAction(stringIDToTypeID("select"), activate, DialogModes.NO);
    doc.activeChannels = doc.componentChannels;
    var omitted = [];
    for (var i = doc.layers.length - 1; i >= 0; i--) {
        var layer = doc.layers[i];
        if (layer.name === "背景" && layer.typename === "ArtLayer") continue;
        var keep = false;
        for (var j = 0; j < keptIds.length; j++) if (layer.id === keptIds[j]) keep = true;
        if (keep) continue;
        var layerName = layer.name;
        if (layer.visible) omitted.push(layerName);
        templateImportStage(spec, "整理工作母版 · 移除原稿分区 " + layerName);
        sectionDeleteLayer(layer);
    }
    templateImportStage(spec, "整理独立分组母版工作布局");
    binding = sectionTemplateProfile(doc);
    binding = sectionCompactModelInfo(doc, binding, omitted);
    var parts = [
        {layer: binding.product, rect: sectionVisibleRect(binding.product)},
        {layer: binding.size, rect: manifestRect(findLayer(binding.size, ["矩形 959 拷贝 2"]))},
        {layer: binding.model, rect: sectionSceneRect(binding)},
        {layer: binding.brand, rect: sectionBrandRect(binding)},
        {layer: binding.footer, rect: sectionVisibleRect(binding.footer)}
    ];
    if (binding.trial) parts.push({layer: binding.trial, rect: sectionVisibleRect(binding.trial)});
    if (binding.quick) parts.push({layer: binding.quick, rect: sectionVisibleRect(binding.quick)});
    parts.sort(function (a, b) { return a.rect[1] - b.rect[1]; });
    var head = manifestRect(binding.headerBase);
    var end = head[1] + head[3];
    var sourceEnd = end;
    for (i = 0; i < parts.length; i++) {
        var part = parts[i];
        var gap = i === 0 ? 60 : Math.max(30, Math.min(80, part.rect[1] - sourceEnd));
        var top = end + gap;
        templateImportStage(spec, "整理工作母版 · 定位 " + part.layer.name);
        part.layer.translate(UnitValue(0, "px"), UnitValue(top - part.rect[1], "px"));
        sourceEnd = part.rect[1] + part.rect[3];
        end = top + part.rect[3];
    }
    doc.resizeCanvas(UnitValue(790, "px"), UnitValue(Math.ceil(end + 20), "px"), AnchorPosition.TOPCENTER);
    spec.sourceIsWorking = false;
    spec.sectionImportWarnings = ["此长版原稿已整理为页头、商品信息、颜色、尺码、模特、品牌及门店的工作母版。" +
        "完整原稿可在母版版式中查看；未纳入自动套版的原稿分区：" + omitted.reverse().join("、") + "。"];
    return sectionTemplateProfile(doc);
}

function sectionFieldBindings(doc, binding) {
    var product = binding.info;
    var names = ["名称", "货号", "颜色", "尺码"];
    if (binding.material) names.push("材质");
    var labels = [], result = {};
    for (var i = 0; i < names.length; i++) {
        var layer = names[i] === "尺码" ? binding.sizeLabel : findLayer(product, [names[i]]);
        labels.push({name: names[i], layer: layer, rect: manifestRect(layer)});
    }
    labels.sort(function (a, b) { return a.rect[1] - b.rect[1]; });
    for (i = 0; i < labels.length; i++) {
        var row = labels[i], paths = [], visible = [];
        for (var j = 0; j < product.artLayers.length; j++) {
            var candidate = product.artLayers[j];
            if (candidate.kind !== LayerKind.TEXT) continue;
            var rect = manifestRect(candidate);
            if (rect[0] <= row.rect[0] + row.rect[2] + 12 || Math.abs(rect[1] - row.rect[1]) > 25) continue;
            paths.push(manifestPath(candidate));
            if (candidate.visible) visible.push(candidate);
        }
        if (visible.length !== 1) throw new Error("未唯一定位独立分组母版的商品字段：" + row.name);
        var value = visible[0];
        var valueRect = manifestRect(value);
        var style = manifestStyle(value, doc);
        style.align = "right";
        result[row.name] = {paths: paths, rect: [180, row.rect[1], 570, Math.max(38,
            (i + 1 < labels.length ? labels[i + 1].rect[1] : row.rect[1] + 58) - row.rect[1] - 8)],
            original_rect: valueRect, label_path: manifestPath(row.layer), label_rect: row.rect,
            original_text: value.textItem.contents, original_style: manifestStyle(value, doc), style: style};
    }
    return result;
}

function sectionColorBindings(doc, binding, rect) {
    var parent = binding.colors;
    var heading = sectionText(parent, /选个喜欢的颜色|选颜色|挑颜色/);
    var headingBottom = box(heading)[3];
    var labels = [], images = [], paths = [];
    for (var i = 0; i < parent.artLayers.length; i++) {
        var layer = parent.artLayers[i];
        var bounds = manifestRect(layer);
        if (bounds[1] < headingBottom || bounds[1] >= rect[1] + rect[3]) continue;
        if (layer.kind === LayerKind.SMARTOBJECT && bounds[2] >= 100 && bounds[3] >= 100) {
            paths.push(manifestPath(layer));
            if (layer.visible) images.push(layer);
        } else if (layer.kind === LayerKind.TEXT) {
            paths.push(manifestPath(layer));
            if (layer.visible) labels.push(layer);
        }
    }
    if (!labels.length || (images.length && images.length !== labels.length)) {
        throw new Error("独立选颜色模块中的图片与色名无法唯一配对");
    }
    labels.sort(function (a, b) { return box(a)[0] - box(b)[0]; });
    images.sort(function (a, b) { return box(a)[0] - box(b)[0]; });
    var slots = [];
    for (i = 0; i < labels.length; i++) {
        var labelRect = manifestRect(labels[i]);
        var imageRect;
        if (images.length) imageRect = manifestRect(images[i]);
        else {
            var height = Math.min(260, labelRect[1] - headingBottom - 35);
            var width = Math.min(210, rect[2] / labels.length - 24);
            if (height < 100 || width < 80) throw new Error("空白选色区域不足以容纳商品图，请设置独立图框");
            imageRect = [Math.max(rect[0] + 8, labelRect[0] + labelRect[2] / 2 - width / 2),
                labelRect[1] - 20 - height, width, height];
        }
        if (images.length && Math.abs(imageRect[0] + imageRect[2] / 2 - labelRect[0] - labelRect[2] / 2) > 70) {
            throw new Error("选颜色图片与色名位置不一致，请核对原稿");
        }
        slots.push({image_path: images.length ? manifestPath(images[i]) : null, label_path: manifestPath(labels[i]),
            rect: imageRect, label_rect: labelRect, text: labels[i].textItem.contents,
            style: manifestStyle(labels[i], doc)});
    }
    return {rect: rect, slots: slots, original_count: slots.length, columns: slots.length,
        data_paths: paths, heading_path: manifestPath(heading), generated_image_slots: !images.length,
        prototype: {image_rect: slots[0].rect,
            label_rect: slots[0].label_rect, style: slots[0].style}};
}

function sectionMeasurementMethod(parent) {
    var heading = sectionText(parent, /测量方法|量体方法/);
    if (!heading) return null;
    var titleRect = manifestRect(heading);
    var top = titleRect[1];
    for (var i = 0; i < parent.artLayers.length; i++) {
        var layer = parent.artLayers[i];
        if (!layer.visible || layer.kind !== LayerKind.SOLIDFILL) continue;
        var rect = manifestRect(layer);
        if (rect[2] >= 400 && rect[3] <= 140 && rect[1] <= titleRect[1] &&
            rect[1] + rect[3] >= titleRect[1] + titleRect[3]) top = Math.min(top, rect[1]);
    }
    var paths = [], rectangles = [];
    for (i = 0; i < parent.layers.length; i++) {
        layer = parent.layers[i];
        rect = manifestRect(layer);
        if (rect[1] < top || rect[2] <= 0 || rect[3] <= 0) continue;
        paths.push(manifestPath(layer));
        if (layer.visible) rectangles.push(rect);
    }
    if (!paths.length || !rectangles.length) throw new Error("测量方法标题下没有可确认的图文内容");
    return {paths: paths, rect: manifestPageRect(manifestUnion(rectangles))};
}

function sectionTableNote(parent, method) {
    var result = null;
    for (var i = 0; i < parent.artLayers.length; i++) {
        var layer = parent.artLayers[i];
        if (!layer.visible || layer.kind !== LayerKind.TEXT) continue;
        var text = layer.textItem.contents;
        if (text.indexOf("注：") !== 0 && text.indexOf("注:") !== 0 &&
            text.indexOf("备注：") !== 0 && text.indexOf("备注:") !== 0 &&
            text.indexOf("尺码备注：") !== 0 && text.indexOf("尺码备注:") !== 0) continue;
        if (method && box(layer)[1] >= method.rect[1]) continue;
        if (result) throw new Error("尺码表下存在多条独立备注，请明确主要尺码备注");
        result = layer;
    }
    return result;
}

function sectionTable(doc, role, key, parent, base, title, units, note, method) {
    var retained = [manifestPath(title), manifestPath(base)];
    if (units) retained.push(manifestPath(units));
    if (note) retained.push(manifestPath(note));
    if (method) retained = retained.concat(method.paths);
    var data = [], rect;
    if (role === "size_table") {
        var header = manifestRect(findLayer(parent, ["矩形 1602 拷贝 4"]));
        var bottom = header[1] + header[3];
        var tableLimit = note ? manifestRect(note)[1] : method ? method.rect[1] : Infinity;
        for (var i = 0; i < parent.artLayers.length; i++) {
            var child = parent.artLayers[i];
            var r = manifestRect(child);
            if (child.visible && child.kind === LayerKind.TEXT && child.id !== title.id &&
                (!note || child.id !== note.id) && (!units || child.id !== units.id) &&
                r[1] >= header[1] && r[1] < tableLimit) bottom = Math.max(bottom, r[1] + r[3]);
        }
        rect = [header[0], header[1], header[2], bottom + 16 - header[1]];
    } else rect = manifestRect(base);
    for (var j = 0; j < parent.layers.length; j++) {
        var layer = parent.layers[j];
        var path = manifestPath(layer);
        if (manifestExcluded(path, retained)) continue;
        data.push(path);
    }
    var styles = {headerHeight: role === "size_table" ? 66 : 58, headerMin: 32,
        rowHeight: 55, px: role === "size_table" ? 24 : 22, accent: false,
        header_fill: role === "try_on" ? [232, 232, 232] : [46, 158, 73],
        header_text_color: role === "try_on" ? [54, 54, 54] : [255, 255, 255],
        stripe_fill: [248, 248, 248], text_color: [54, 54, 54], lead_fill: [255, 255, 255]};
    var module = manifestTable(doc, role, key, parent, rect, role === "size_table" ? null : manifestPath(base),
        data, styles, sectionVisibleRect(parent), []);
    if (role === "size_table") {
        module.table.cover_rect = rect.slice();
        module.background_paths = [manifestPath(base)];
    }
    if (method) {
        var outer = manifestRect(base);
        module.rect = [outer[0], outer[1], outer[2], method.rect[1] - outer[1]];
        module.move_paths = [];
        for (var k = 0; k < parent.layers.length; k++) {
            var childPath = manifestPath(parent.layers[k]);
            if (!manifestExcluded(childPath, method.paths)) module.move_paths.push(childPath);
        }
        for (k = module.titles.length - 1; k >= 0; k--) {
            if (manifestExcluded(module.titles[k].path, method.paths)) module.titles.splice(k, 1);
        }
    }
    return module;
}

function sectionPhotoData(parent, frames, role) {
    var keep = [];
    for (var i = 0; i < frames.length; i++) keep.push(manifestPath(frames[i]));
    var images = manifestImageData(parent, role);
    var result = [];
    for (i = 0; i < images.length; i++) {
        var path = images[i].path;
        if (!manifestExcluded(path, keep) && path[path.length - 1].indexOf("形状") !== 0) result.push(images[i]);
    }
    return result;
}

function manifestSectionTemplate(doc, binding, reportStage) {
    var result = {version: 1, family: "section", canvas: {width: 790, height: doc.height.as("px")},
        modules: [], view_slots: {}, original_images: [], omitted_paths: [], stretch_paths: []};
    if (reportStage) reportStage("读取独立商品与颜色分组");
    result.fields = sectionFieldBindings(doc, binding);
    var split = manifestRect(binding.colorDivider);
    var productRect = sectionVisibleRect(binding.product);
    var colorRect = [productRect[0], split[1], productRect[2], productRect[1] + productRect[3] - split[1]];
    result.colors = sectionColorBindings(doc, binding, colorRect);
    var fieldPaths = [];
    for (var field in result.fields) fieldPaths = fieldPaths.concat(result.fields[field].paths);
    var product = manifestModule(doc, "product", binding.product,
        [productRect[0], productRect[1], productRect[2], split[1] - productRect[1]], fieldPaths.concat(result.colors.data_paths), []);
    var colors = manifestModule(doc, "colors", binding.product, colorRect,
        fieldPaths.concat(result.colors.data_paths), []);
    product.move_paths = []; colors.move_paths = [];
    product.titles = []; colors.titles = [];
    var backing = findLayer(binding.product, ["矩形 948 拷贝"]);
    for (var i = 0; i < binding.product.layers.length; i++) {
        var item = binding.product.layers[i];
        var itemRect = manifestRect(item);
        var target = itemRect[1] >= split[1] ? colors : product;
        if (item.id !== backing.id) target.move_paths.push(manifestPath(item));
    }
    var fixedTexts = manifestTitles(binding.product, fieldPaths.concat(result.colors.data_paths), doc);
    for (i = 0; i < fixedTexts.length; i++) {
        if (fixedTexts[i].rect[1] >= split[1]) colors.titles.push(fixedTexts[i]);
        else product.titles.push(fixedTexts[i]);
    }
    result.stretch_paths.push({path: manifestPath(backing), role: "colors"});
    result.modules.push(manifestModule(doc, "header", binding.header,
        [0, 0, 790, box(binding.headerBase)[3]], [], []));
    result.modules.push(product); result.modules.push(colors);
    if (reportStage) reportStage("读取独立尺码表与试穿分组");
    var method = sectionMeasurementMethod(binding.size);
    var note = sectionTableNote(binding.size, method);
    result.modules.push(sectionTable(doc, "size_table", "03选尺码", binding.size,
        findLayer(binding.size, ["矩形 959 拷贝 2"]), sectionText(binding.size, /选择你的尺码|选.*尺码|尺码表/), null, note, method));
    if (method) {
        var otherPaths = [];
        for (i = 0; i < binding.size.layers.length; i++) {
            var childPath = manifestPath(binding.size.layers[i]);
            if (!manifestExcluded(childPath, method.paths)) otherPaths.push(childPath);
        }
        var methodModule = manifestModule(doc, "measurement_method", binding.size, method.rect, otherPaths, []);
        methodModule.move_paths = method.paths;
        result.modules.push(methodModule);
    }
    if (binding.quick) result.modules.push(sectionTable(doc, "quick_size", "05尺码快选", binding.quick,
        findLayer(binding.quick, ["矩形 1147 拷贝"]), sectionText(binding.quick, /^尺码快选$/),
        sectionText(binding.quick, /^cm\/kg$/), null));
    if (binding.trial) result.modules.push(sectionTable(doc, "try_on", "试穿报告", binding.trial,
        findLayer(binding.trial, ["矩形 959 拷贝 4"]), sectionText(binding.trial, /试穿报告/),
        sectionText(binding.trial, /^身高cm\/体重kg$/), null));
    if (reportStage) reportStage("读取独立模特与品牌图位");
    var photos = sectionPhotoData(binding.model, binding.frames, "scenes");
    result.original_images = result.original_images.concat(photos);
    var excluded = [];
    for (i = 0; i < photos.length; i++) excluded.push(photos[i].path);
    var scenes = manifestModule(doc, "scenes", binding.model, sectionSceneRect(binding), excluded, []);
    scenes.slots = [];
    for (i = 0; i < binding.frames.length; i++) {
        var frame = binding.frames[i];
        var slot = {id: "scene_" + (i + 1), path: manifestPath(frame), rect: manifestRect(frame)};
        scenes.slots.push(slot); result.view_slots[slot.id] = slot;
    }
    result.modules.push(scenes);
    photos = sectionPhotoData(binding.brand, [binding.brandFrame], "brand");
    result.original_images = result.original_images.concat(photos);
    excluded = [];
    for (i = 0; i < photos.length; i++) excluded.push(photos[i].path);
    result.modules.push(manifestModule(doc, "brand", binding.brand, sectionBrandRect(binding), excluded, []));
    result.view_slots.brand = {id: "brand", path: manifestPath(binding.brandFrame), rect: manifestRect(binding.brandFrame)};
    result.modules.push(manifestModule(doc, "footer", binding.footer, sectionVisibleRect(binding.footer), [], []));
    for (i = 0; i < result.colors.slots.length; i++) {
        if (result.colors.slots[i].image_path) result.original_images.push({path: result.colors.slots[i].image_path, role: "colors"});
    }
    if (result.colors.generated_image_slots) result.import_warnings = [
        "原稿选色区只有色名和空白区域，已按原有标题、色名与留白位置建立商品图位。"];
    result.modules.sort(function (a, b) { return a.rect[1] - b.rect[1]; });
    return result;
}
